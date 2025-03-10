'''This script:

Starts a WebSocket server to communicate with the API.
Handles text and audio responses from GPT-4o.'''

import asyncio
import json
import websockets
import logging
from uuid import uuid4
from realtime import RealtimeClient

logger = logging.getLogger(__name__)

# WebSocket server settings
WEBSOCKET_HOST = "localhost"
WEBSOCKET_PORT = 8765

# Store active GPT-4o sessions
sessions = {}

async def handle_client(websocket):
    try:
        logger.info(f"New WebSocket connection: {websocket.remote_address}")

        async for message in websocket:
            data = json.loads(message)
            track_id = data.get("track_id", str(uuid4()))
            user_message = data.get("message")

            if track_id not in sessions:
                logger.info(f"Initializing new session for {track_id}")
                sessions[track_id] = RealtimeClient(system_prompt="Loan Assistant")

                logger.info("Connecting to GPT-4o...")
                await sessions[track_id].connect()
                await sessions[track_id].wait_for_session_created()
                logger.info("Connected to GPT-4o.")

            gpt_client = sessions[track_id]

            logger.info(f"Sending message to GPT-4o: {user_message}")
            await gpt_client.send_user_message_content([{"type": "input_text", "text": user_message}])

            response = await gpt_client.wait_for_next_completed_item()
            assistant_response = response.get("item", {}).get("formatted", {}).get("text", "")

            logger.info(f"Received response from GPT-4o: {assistant_response}")
            await websocket.send(assistant_response)

    except Exception as e:
        logger.error(f"Error in WebSocket server: {e}")

async def start_server():
    server = await websockets.serve(handle_client, WEBSOCKET_HOST, WEBSOCKET_PORT)
    logger.info(f"WebSocket Server running at ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(start_server())