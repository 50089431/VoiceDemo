import os
import traceback
import asyncio
import websockets
from openai import AsyncAzureOpenAI
from uuid import uuid4
from realtime import RealtimeClient
from azure_tts import Client as AzureTTSClient
from tools import tools
import re
import logging
import time  # Import the time module

# Import the logger functions
from logger import logger, log_llm_input_output, log_query_search, log_tool_search

# Global variables to store the timestamps
user_stop_time = None
bot_start_time = None

# A dictionary mapping languages to their respective Azure TTS voices
VOICE_MAPPING = {
    "hindi": "hi-IN-KavyaNeural",
    "english": "en-IN-AnanyaNeural",
    "tamil": "ta-IN-PallaviNeural",
    "odia": "or-IN-SubhasiniNeural",
    "bengali": "bn-IN-BashkarNeural",
    "gujarati": "gu-IN-DhwaniNeural",
    "kannada": "kn-IN-SapnaNeural",
    "malayalam": "ml-IN-MidhunNeural",
    "marathi": "mr-IN-AarohiNeural",
    "punjabi": "pa-IN-GurpreetNeural",
    "telugu": "te-IN-MohanNeural",
    "urdu": "ur-IN-AsadNeural"
}

tts_sentence_end = [".", "!", "?", ";", "।", "！", "？", "；", "\n", "।"]

# Custom session management
session = {
    "track_id": str(uuid4()),
    "voice": None,
    "verified_number": None,
    "useAzureVoice": False,
    "useRealtimeTTS": True,
    "Temperature": 0,
    "Language": "english"
}

async def setup_openai_realtime(system_prompt: str, websocket):
    logger.info(f"Setting up OpenAI Realtime with system_prompt: {system_prompt}")
    openai_realtime = RealtimeClient(system_prompt=system_prompt)
    session["track_id"] = str(uuid4())
    voice = VOICE_MAPPING.get(session["Language"])
    session["voice"] = voice
    collected_messages = []

    async def handle_conversation_updated(event):
        global user_stop_time, bot_start_time
        try:
            item = event.get("item")
            delta = event.get("delta")
            if delta:
                if 'audio' in delta:
                    logger.info("Audio received.")
                    audio = delta['audio']
                    if not session.get("useAzureVoice"):
                        bot_start_time = time.time()
                        if user_stop_time is not None:
                            time_difference = bot_start_time - user_stop_time
                            logger.info(f"Time between user stop and bot start: {time_difference}s")
                        await websocket.send(audio)
                if 'transcript' in delta:
                    if session.get("useAzureVoice"):
                        chunk_message = delta['transcript']
                        collected_messages.append(chunk_message)
                        if chunk_message in tts_sentence_end:
                            sent_transcript = ''.join(collected_messages).strip()
                            collected_messages.clear()
                            chunk = await AzureTTSClient.text_to_speech_realtime(text=sent_transcript, voice=voice)
                            await websocket.send(chunk)
        except Exception as e:
            logger.error(f"Error in handle_conversation_updated: {e}")

    async def handle_conversation_interrupt(event):
        global user_stop_time
        try:
            logger.info("Conversation interrupted.")
            user_stop_time = time.time()
            collected_messages.clear()
            await websocket.send("Audio interrupt")
        except Exception as e:
            logger.error(f"Error in handle_conversation_interrupt: {e}")

    openai_realtime.on('conversation.updated', handle_conversation_updated)
    openai_realtime.on('conversation.interrupted', handle_conversation_interrupt)

    session["openai_realtime"] = openai_realtime
    await asyncio.gather(*[openai_realtime.add_tool(tool_def, tool_handler) for tool_def, tool_handler in tools])
    logger.info("OpenAI Realtime setup complete.")

async def websocket_handler(websocket, path):  # Added 'path' argument
    logger.info("Connection open")
    async for message in websocket:
        if message == "start":
            system_prompt = """Your system prompt here"""
            await setup_openai_realtime(system_prompt, websocket)  # Pass websocket to function
        else:
            logger.info(f"Received message: {message}")

async def main():
    server = await websockets.serve(websocket_handler, "localhost", 8765)
    logger.info("WebSocket server started on ws://localhost:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())