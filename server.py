# '''
# This script:
# - Exposes an API endpoint (/start_session) to initialize the conversation.
# - Uses WebSockets to interact with GPT-4o Realtime.
# - Streams audio or text responses from GPT-4o back to the client.

# '''
# import asyncio
# import json
# import logging
# import re
# from uuid import uuid4

# from fastapi import FastAPI, WebSocket
# from realtime import RealtimeClient
# from azure_tts import Client as AzureTTSClient

# # --- Logging Setup ---
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("server")

# # --- Constants ---
# SYSTEM_PROMPT = """
# You are a female intelligent voice assistant for L&T Finance, assisting customers with two-wheeler loans.

# - Speak all numbers and dates in English using the India Standard System.
# - Use simple Hindi and commonly spoken English words for better customer engagement.

# Response Flow:
#     1. Greet the customer and ask how you can help.
#     2. Wait for the customer's question. Do not ask a question yourself.
#     3. For Loan-Related Queries:
#         - Verify the customer once per loan using their agreement number or registered contact number.
#         - User will speak a **phone number**. Listen carefully to the number, DO NOT MAKE YOUR OWN DIGITS. DO NOT MISS ANY DIGIT.
#           MAKE SURE THE NUMBER IS 10 DIGITS. Listen to the first and last digits properly.
#         - Say - Mein aapka number **phone number (in english digits)** search kr rhi hun.
#         - If the customer says that number is incorrect, wait for the customer to provide the correct number.
#         - Use the search_data tool to retrieve relevant loan details from the dataset.
#         - If the provided details match an entry, share only the specific information requested by the customer.
#         - If no matching record is found, politely ask the customer to reconfirm their details.
#     4. For General Queries:
#         - Do not request verification.
#         - Invoke the fetch_relevant_documents tool to provide the requested information.
#         - Only provide information that is relevant to the customer's query.
#     5. After giving the answer, wait for the customer reply.
#     6. If the customer doesn't reply, ask if they have any further questions.
#     7. If the customer provides a new phone number or agreement number, update it and fetch information based on the new details.
# """

# VOICE_MAPPING = {
#     "hindi": "hi-IN-KavyaNeural",
#     "english": "en-IN-AnanyaNeural",
#     "tamil": "ta-IN-PallaviNeural",
#     "odia": "or-IN-SubhasiniNeural",
#     "bengali": "bn-IN-BashkarNeural",
#     "gujarati": "gu-IN-DhwaniNeural",
#     "kannada": "kn-IN-SapnaNeural",
#     "malayalam": "ml-IN-MidhunNeural",
#     "marathi": "mr-IN-AarohiNeural",
#     "punjabi": "pa-IN-GurpreetNeural",
#     "telugu": "te-IN-MohanNeural",
#     "urdu": "ur-IN-AsadNeural"
# }

# tts_sentence_end = [".", "!", "?", ";", "।", "！", "？", "；", "\n", "।"]

# # --- Session Management ---
# # We'll store session data per connection (indexed by a unique track_id).
# sessions = {}

# # --- FastAPI App ---
# app = FastAPI()

# @app.get("/")
# async def root():
#     return {"message": "GPT-4o Realtime WebSocket API Running"}

# @app.websocket("/ws")
# async def websocket_endpoint(websocket: WebSocket):
#     await websocket.accept()
#     track_id = str(uuid4())
#     logger.info(f"New connection, track_id: {track_id}")

#     # Default session settings (can be updated via a settings event)
#     session_data = {
#         "track_id": track_id,
#         "openai": None,  # Will hold the RealtimeClient instance
#         "settings": {
#             "Language": "english",
#             "useAzureVoice": False,
#             "useRealtimeTTS": True,
#             "Temperature": 0,
#             "voice": VOICE_MAPPING.get("english")
#         }
#     }
#     sessions[track_id] = session_data

#     try:
#         while True:
#             data = await websocket.receive_text()
#             msg = json.loads(data)
#             event = msg.get("event")

#             # --- Chat Start: Initialize RealtimeClient ---
#             if event == "chat_start":
#                 logger.info(f"Starting chat for session {track_id}")
#                 openai = RealtimeClient(system_prompt=SYSTEM_PROMPT)
#                 session_data["openai"] = openai
#                 await openai.connect()
#                 await openai.wait_for_session_created()
#                 await websocket.send_text(json.dumps({"event": "chat_started", "track_id": track_id}))
            
#             # --- Settings Update ---
#             elif event == "settings_update":
#                 settings = msg.get("settings", {})
#                 session_data["settings"].update(settings)
#                 lang = session_data["settings"].get("Language", "english")
#                 session_data["settings"]["voice"] = VOICE_MAPPING.get(lang)
#                 logger.info(f"Session {track_id} updated settings: {session_data['settings']}")
#                 await websocket.send_text(json.dumps({"event": "settings_updated", "settings": session_data["settings"]}))
            
#             # --- Text Message ---
#             elif event == "message":
#                 user_message = msg.get("message", "")
#                 openai = session_data.get("openai")
#                 if openai and openai.is_connected():
#                     logger.info(f"Session {track_id} received message: {user_message}")
#                     await openai.send_user_message_content([{"type": "input_text", "text": user_message}])
                    
#                     # Wait for the completed response
#                     response = await openai.wait_for_next_assistant_item()
#                     # Defensive handling: if response is empty or not valid JSON
#                     if isinstance(response, str):
#                         if not response.strip():
#                             logger.error("Received empty response from GPT-4o")
#                             await websocket.send_text(json.dumps({"event": "error", "message": "Empty response from GPT-4o"}))
#                             continue
#                         try:
#                             response = json.loads(response)
#                         except Exception as e:
#                             logger.error(f"Error parsing response JSON: {e}. Response: {response}")
#                             await websocket.send_text(json.dumps({"event": "error", "message": "Invalid JSON response from GPT-4o"}))
#                             continue
#                     assistant_response = response.get("item", {}).get("formatted", {}).get("text", "")
#                     if session_data["settings"]["useAzureVoice"]:
#                         chunk = await AzureTTSClient.text_to_speech_realtime(
#                             text=assistant_response,
#                             voice=session_data["settings"]["voice"]
#                         )
#                         await websocket.send_text(json.dumps({"event": "response", "audio": chunk}))
#                     else:
#                         await websocket.send_text(json.dumps({"event": "response", "text": assistant_response}))
#                 else:
#                     await websocket.send_text(json.dumps({"event": "error", "message": "Realtime client not connected"}))
            
#             # --- Audio Start ---
#             elif event == "audio_start":
#                 openai = session_data.get("openai")
#                 if openai:
#                     await openai.connect()
#                     await websocket.send_text(json.dumps({"event": "audio_started"}))
#                 else:
#                     await websocket.send_text(json.dumps({"event": "error", "message": "Realtime client not initialized"}))
            
#             # --- Audio Chunk ---
#             elif event == "audio_chunk":
#                 audio_data = msg.get("audio")
#                 openai = session_data.get("openai")
#                 if openai and openai.is_connected():
#                     # Assume audio_data is in an appropriate format (e.g., base64-encoded)
#                     await openai.append_input_audio(audio_data)
#                 else:
#                     await websocket.send_text(json.dumps({"event": "error", "message": "Realtime client not connected"}))
            
#             # --- Audio End ---
#             elif event == "audio_end":
#                 openai = session_data.get("openai")
#                 if openai and openai.is_connected():
#                     await openai.disconnect()
#                     await websocket.send_text(json.dumps({"event": "audio_ended"}))
#                 else:
#                     await websocket.send_text(json.dumps({"event": "error", "message": "Realtime client not connected"}))
            
#             else:
#                 logger.warning(f"Unknown event received: {event}")
#                 await websocket.send_text(json.dumps({"event": "error", "message": "Unknown event"}))
    
#     except Exception as e:
#         logger.error(f"WebSocket error for session {track_id}: {e}")
#     finally:
#         if track_id in sessions:
#             del sessions[track_id]
#         await websocket.close()

import asyncio
import json
import logging
import base64
from uuid import uuid4
from fastapi import FastAPI, WebSocket
from realtime import RealtimeClient

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# FastAPI app
app = FastAPI()

# Store active sessions
sessions = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    track_id = str(uuid4())
    logger.info(f"New connection, track_id: {track_id}")
    
    # Initialize a new session with GPT-4o
    gpt_client = RealtimeClient(system_prompt="You are a helpful AI assistant.")
    sessions[track_id] = gpt_client
    await gpt_client.connect()
    await gpt_client.wait_for_session_created()
    
    await websocket.send_text(json.dumps({"event": "chat_started", "track_id": track_id}))
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            event = msg.get("event", "")
            
            if event == "audio_chunk":
                audio_data = msg.get("audio", None)
                if audio_data:
                    logger.info("🎤 Received audio chunk from client.")
                    decoded_audio = base64.b64decode(audio_data)
                    await gpt_client.append_input_audio(decoded_audio)
            
            elif event == "audio_end":
                logger.info("🔚 End of user speech detected. Processing response...")
                response = await gpt_client.wait_for_next_assistant_item()
                logger.info(f"📥 Received raw response from GPT-4o: {response}")
                
                assistant_audio = response.get("item", {}).get("formatted", {}).get("audio", None)
                if assistant_audio:
                    logger.info("📤 Sending audio response to client.")
                    await websocket.send_text(json.dumps({"event": "response", "audio": assistant_audio}))
                else:
                    assistant_text = response.get("item", {}).get("formatted", {}).get("text", "")
                    if not assistant_text:
                        assistant_text = response.get("item", {}).get("formatted", {}).get("transcript", "")
                    logger.info(f"📤 Sending response: {assistant_text}")
                    await websocket.send_text(json.dumps({"event": "response", "text": assistant_text}))
    
    except Exception as e:
        logger.error(f"WebSocket error for session {track_id}: {e}")
    
    finally:
        if track_id in sessions:
            await sessions[track_id].disconnect()
            del sessions[track_id]

        try:
            await websocket.close()
        except Exception as e:
            logger.warning(f"Error closing WebSocket: {e}")