import asyncio
import json
import base64
import websockets
import sounddevice as sd
import numpy as np
from pydub import AudioSegment
from pydub.playback import play

# WebSocket server URL
WS_URL = "ws://localhost:8000/ws"

# Audio settings
SAMPLE_RATE = 16000  # GPT-4o expects 16kHz audio
CHUNK_DURATION = 0.3  # Duration of each chunk in seconds
SILENCE_THRESHOLD = 100  # Adjust based on mic sensitivity

def encode_audio_to_base64(indata):
    """Encodes the audio chunk (indata) to a base64 string."""
    audio_bytes = indata.tobytes()  # Convert audio data to bytes
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")  # Encode bytes to base64
    return audio_base64

async def send_audio(websocket, loop):
    """ Continuously records and streams audio to the server """
    print("🎤 Speak now...")

    def callback(indata, frames, time, status):
        """ Process real-time audio chunks """
        audio_base64 = encode_audio_to_base64(indata)  # Encode the audio data to base64

        # Run the WebSocket send call in the event loop
        asyncio.run_coroutine_threadsafe(websocket.send(json.dumps({"event": "audio_chunk", "audio": audio_base64})), loop)

    # Start the audio stream
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype=np.int16, callback=callback):
        await asyncio.sleep(10)  # Keep listening for 10 seconds (can be adjusted)
        await websocket.send(json.dumps({"event": "speech_stopped"}))  # Signal end of speech

async def receive_audio(websocket):
    """ Receives and plays audio responses from GPT-4o """
    while True:
        response = await websocket.recv()
        response_data = json.loads(response)

        if "audio" in response_data:
            print("🔊 Playing response...")
            audio_data = base64.b64decode(response_data["audio"])
            
            # Print out some details about the received audio chunk
            print(f"🔊 Received audio chunk: {len(audio_base64)} characters")  # Base64 string length
            print(f"🔊 Audio data first few bytes: {audio_data[:10]}")  # Print the first 10 bytes of raw audio data for debugging
            
            audio = AudioSegment(audio_data, frame_rate=16000, sample_width=2, channels=1)
            play(audio)  # Play assistant's response

async def main():
    """ Manages WebSocket connection and audio streaming """
    async with websockets.connect(WS_URL) as websocket:
        print("✅ Connected to WebSocket server.")
        await websocket.send(json.dumps({"event": "chat_start"}))  # Start session

        # Get the event loop for the main thread
        loop = asyncio.get_event_loop()
        
        # Start bidirectional streaming
        await asyncio.gather(send_audio(websocket, loop), receive_audio(websocket))

asyncio.run(main())
