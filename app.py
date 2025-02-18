import os
import traceback
import asyncio
from openai import AsyncAzureOpenAI
import chainlit as cl
from chainlit.input_widget import Select, Switch, Slider
from uuid import uuid4
from realtime import RealtimeClient
from azure_tts import Client as AzureTTSClient
from tools import tools
import re
import logging
import os
from logger import logger, log_llm_input_output, log_query_search, log_tool_search  # Import the logger functions

"""A dictionary mapping languages to their respective Azure TTS voices.
When a user selects a language, the corresponding TTS voice is used."""
VOICE_MAPPING = {
    "hindi 1": "hi-IN-AnanyaNeural",
    "hindi 2" : "hi-IN-KavyaNeural",
    "hindi 3" : "hi-IN-SwaraNeural",
    "hindi 4" : "hi-IN-MadhurNeural",
    "hindi 5" : "hi-IN-RehaanNeural",
    "hindi 6" : "hi-IN-KunalNeural",
    "english": "en-IN-AnanyaNeural",
    # "tamil": "ta-IN-PallaviNeural",
    # "odia": "or-IN-SubhasiniNeural",
    # "bengali": "bn-IN-BashkarNeural",
    # "gujarati": "gu-IN-DhwaniNeural",
    # "kannada": "kn-IN-SapnaNeural",
    # "malayalam": "ml-IN-MidhunNeural",
    # "marathi": "mr-IN-AarohiNeural",
    # "punjabi": "pa-IN-GurpreetNeural",
    # "telugu": "te-IN-MohanNeural",
    # "urdu": "ur-IN-AsadNeural"
}

tts_sentence_end = [ ".", "!", "?", ";", "।", "！", "？", "；", "\n", "।"]
async def setup_openai_realtime(system_prompt: str):
    """Instantiate and configure the OpenAI Realtime Client"""
    logger.info(f"Entering setup_openai_realtime with system_prompt: {system_prompt}")
    openai_realtime = RealtimeClient(system_prompt = system_prompt) #Creates an OpenAI Realtime Client instance with a system_prompt.
    cl.user_session.set("track_id", str(uuid4())) #Generates a unique track ID for the session.
    voice = VOICE_MAPPING.get(cl.user_session.get("Language")) #Retrieves the voice selection from cl.user_session.
    cl.user_session.set("voice", voice)  # Store the voice in the session
    collected_messages = []
    logger.info(f"Configured OpenAI Realtime Client with voice: {voice}")
    
    async def fix_number_recognition(transcript):
        """
        Ensures numbers are fully captured, especially avoiding missing last digits.
        """
        logger.info(f"Entering fix_number_recognition with transcript: {transcript}")
        # Check if the last part of transcript contains a number and is possibly incomplete
        
        number_match = re.search(r"(\d[\d\s]*)$", transcript)  # Match trailing numbers
        if number_match:
            last_number = number_match.group(1).strip()
            if last_number and last_number[-1].isdigit():
                await asyncio.sleep(0.5)  # Small delay to ensure full capture
                return transcript  # No fix needed
            
            # Possible incomplete number, wait for the next update before finalizing
            return transcript + " (waiting for last digit...)"
        
        return transcript


    async def handle_conversation_updated(event):
        '''
        Listens for live updates from OpenAI's real-time model.
        If audio is received, it sends the voice output to the user.
        If transcription text is received:
            Stores it in collected_messages.
            When a sentence-ending character (".", "?", "।") is detected:
                Converts text to speech using Azure TTS.
                Sends audio output to the user.
        '''
        # logger.info(f"Entering handle_conversation_updated with event: {event}")
        item = event.get("item")
        delta = event.get("delta")
        
        """Currently used to stream audio back to the client."""
        if delta:
            # Only one of the following will be populated for any given event
            if 'audio' in delta:
                audio = delta['audio']  # Int16Array, audio added
                if not cl.user_session.get("useAzureVoice"):
                    await cl.context.emitter.send_audio_chunk(
                        cl.OutputAudioChunk(mimeType="pcm16", data=audio, track=cl.user_session.get("track_id")))
            
            if 'transcript' in delta:
                if cl.user_session.get("useAzureVoice"):
                    chunk_message = delta['transcript']
                    logger.info(f"Received transcript: {chunk_message}")
                    
                    if item["status"] == "in_progress":
                        collected_messages.append(chunk_message)  # save the message

                        if chunk_message in tts_sentence_end: # sentence end found
                            sent_transcript = ''.join(collected_messages).strip()
                            collected_messages.clear()

                            logger.info(f"Bot is planning to speak: {sent_transcript}") 
                            chunk = await AzureTTSClient.text_to_speech_realtime(text=sent_transcript, voice=voice)
                            logger.info(f"Audio chunk length: {len(chunk)}")
                            await cl.context.emitter.send_audio_chunk(cl.OutputAudioChunk(mimeType="audio/wav", data=chunk, track=cl.user_session.get("track_id")))
                    
            if 'arguments' in delta:
                arguments = delta['arguments']  # string, function arguments added
                logger.info(f"Received arguments: {arguments}")
    
    async def handle_item_completed(item):
        """Generate the transcript once an item is completed and populate the chat context."""
        # logger.info(f"Entering handle_item_completed with item: {item}")
        try:
            transcript = item['item']['formatted']['transcript']
            logger.info(f"Completed transcript: {transcript}")
            if transcript.strip() != "":
                await asyncio.sleep(0.2)  # Small delay to ensure last word is captured
                await cl.Message(content=transcript).send()      
                
        except Exception as e:
            logger.error(f"Failed to generate transcript: {e}")
            logger.error(traceback.format_exc())
    
    async def handle_conversation_interrupt(event):
        """If the conversation interrupts, it:
            Clears collected messages.
            Sends an audio stop signal to cancel playback.
            Used to cancel the client previous audio playback."""
        logger.info(f"Entering handle_conversation_interrupt with event content: {event.get('content')}")
        cl.user_session.set("track_id", str(uuid4()))
        try:
            collected_messages.clear()
        except Exception as e:
            logger.error(f"Failed to clear collected messages: {e}")    
        await cl.context.emitter.send_audio_interrupt()
        
    async def handle_input_audio_transcription_completed(event):
        logger.info(f"Entering handle_input_audio_transcription_completed with event content: {event.get('content')}")
        item = event.get("item")
        delta = event.get("delta")
        if 'transcript' in delta:
            transcript = delta['transcript']
            logger.info(f"Input audio transcription completed: {transcript}")
            if transcript != "":
                await asyncio.sleep(0.2)  # Wait for 2 seconds to ensure complete transcript is captured
                await cl.Message(author="You", type="user_message", content=transcript).send()
        
    async def handle_error(event):
        logger.error(f"Error event: {event}")
        
    openai_realtime.on('conversation.updated', handle_conversation_updated)
    openai_realtime.on('conversation.item.completed', handle_item_completed)
    openai_realtime.on('conversation.interrupted', handle_conversation_interrupt)
    openai_realtime.on('conversation.item.input_audio_transcription.completed', handle_input_audio_transcription_completed)
    openai_realtime.on('error', handle_error)

    cl.user_session.set("openai_realtime", openai_realtime)
    #cl.user_session.set("tts_client", tts_client)
    coros = [openai_realtime.add_tool(tool_def, tool_handler) for tool_def, tool_handler in tools]
    await asyncio.gather(*coros)
    logger.info("Exiting setup_openai_realtime")
    

@cl.password_auth_callback
def auth_callback(username: str, password: str):
    logger.info(f"Entering auth_callback with username: {username}")
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    if (username, password) == ("raj", "pass123"):
        return cl.User(
            identifier="raj", metadata={"role": "admin", "provider": "credentials"}
        )
    else:
        return None

@cl.on_chat_start
async def start():
    logger.info("Entering start")
    '''Asks the user to select a language, toggle Azure Voice, and set AI temperature.'''

    # Reset the verified number at the beginning of a new chat session
    # cl.user_session.set("verified_number", None)

    settings = await cl.ChatSettings([
        Select(
            id="Language",
            label="Choose Language",
            values=list(VOICE_MAPPING.keys()),
            initial_index=0,
        ),
        Switch(id="useAzureVoice", label="Use Azure Voice", initial=False),
        # Switch(id="useRealtimeTTS", label="Use Real-time TTS", initial=True),
        Slider(
            id="Temperature",
            label="Temperature",
            initial=0,
            min=0,
            max=2,
            step=0.1,
        )
    ]).send()

    #Calls setup_agent(settings) to configure the AI.
    await setup_agent(settings)
    logger.info("Exiting start")


@cl.on_settings_update
async def setup_agent(settings):
    logger.info(f"Entering setup_agent with settings: {settings}")
    '''When a user sends a text message, it forwards it to OpenAI for processing.'''

    system_prompt = """
    You are a female intelligent voice assistant for L and T Finance, assisting customers with two-wheeler loans.

    - Speak all numbers and dates in English using the India Standard System.
    - Use simple Hindi and commonly spoken English words for better customer engagement.

    Response Flow:
        1. Greet the customer and ask how you can help.
        2. Wait for the customer's question. Do not ask a question yourself. 
        3. For Loan-Related Queries:
            - Verify the customer once per loan using their agreement number or registered contact number.
            - User will speak a **phone number**. Listen carefully to the number, DO NOT MAKE YOUR OWN DIGITS. DO NOT MISS ANY DIGIT.
              MAKE SURE THE NUMBER IS 10 DIGITS. Listen to the first and last digits properly. 
            - Say - Mein aapka number **phone number (in english digits)** search kr rhi hun.
            - If the customer says that number is incorrect, wait for the customer to provide the correct number.
            - Use the search_data tool to retrieve relevant loan details from the dataset.
            - If the provided details match an entry, share only the specific information requested by the customer.
            - If no matching record is found, politely ask the customer to reconfirm their details. Do not provide any loan-related information in this case.
        4. For General Queries:
            - Do not request verification
            - Invoke the fetch_relevant_documents tool to provide the requested information.
            - DO not respond with general knowledge. Only provide information that is relevant to the customer's query.
        5. After giving the answer, wait for the customer reply.
        6. If the customer dosesn't reply, ask the customer if they have any further questions to ensure a smooth conversation experience.
        7. If the customer provides a new phone number or agreement number, update it and fetch information based on the new details.
        8. While cheking this new number, speak the new phone number in English digits.

    These are the possible conversation flows. Do not use these exact details in actual conversation.
    Example Conversation 1:
    Customer: Hello?
    Assistant: L and T Finance - Customer Support mein aapka swaagat hai. Mein aapki kaise sahayata kar sakti hun?
    Customer: Mujhe apne EMI payment ke baare me jaana hai. 
    Assistant: Kripya apna mobile number ya agreement number pradan karein.
    Customer: 9823456789
    Assistant: Dhanyavad! Mein aapka number nine eight two three four five six seven eight nine search kr rhi hun.
    Assistant: Aapki last EMI Rupees two thousand eight hundred hai, jo 03 February 2025 ko due thi, and iska payment abhi tk nahi hua hai.

    Example Conversation 2:
    Customer: Hello?
    Assistant:L and T Finance - Customer Support  mein aapka swaagat hai. Mein aapki kaise sahayata kar sakti hun?
    Customer: Kya aap bta sakte hai ki mera EMI payment hua hai ya nahi is mahine ka?
    Assistant: Kripya apna mobile number ya agreement number pradan karein.
    Customer: AG12345
    Assistant: Dhanyavad! Mein aapka number AG12345 search kr rhi hun.
    Assistant: Aapka last EMI payment 3 Febuary ko ho chuka hai.
    Assistant: Kya main aapki koi aur madad kar sakti hoon?

    Example Conversation 3:
    Customer: Hello?
    Assistant: L and T Finance - Customer Support mein aapka swaagat hai. Mein aapki kaise sahayata kar sakti hun?
    Customer: Kya aap bta skte hai ki mera kitna payment abhi bacha hua hai?
    Assistant: Kripya apna mobile number ya agreement number pradan karein.
    Customer: 9876034567
    Assistant: Dhanyavad! Mein aapka number nine eight seven six zero three four five six seven search kr rhi hun.
    Assistant: Aapka total balance abhi Rupees twenty thousand hai. 
    Customer: Okay
    Assistant: Kya main aapki koi aur sahayta kar sakti hoon?
    """    

    cl.user_session.set("useAzureVoice", settings["useAzureVoice"])
    cl.user_session.set("Temperature", settings["Temperature"])
    cl.user_session.set("Language", settings["Language"])
    app_user = cl.user_session.get("user")
    identifier = app_user.identifier if app_user else "admin"
    await cl.Message(
        content="Hi, Welcome to LoanAssist. How can I help you?"
    ).send()

    system_prompt = system_prompt.replace("<customer_language>", settings["Language"])

    await setup_openai_realtime(system_prompt=system_prompt)
    logger.info("Exiting setup_agent")
    
@cl.on_message
async def on_message(message: cl.Message):
    logger.info(f"Entering on_message with message: {message.content}")
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        log_llm_input_output("GPT-4o", message.content, None)  # Log input to GPT-4o model
        await openai_realtime.send_user_message_content([{ "type": 'input_text', "text": message.content}])
    else:
        await cl.Message(content="Please activate voice mode before sending messages!").send()
    logger.info("Exiting on_message")

@cl.on_audio_start
async def on_audio_start():
    logger.info("Entering on_audio_start")
    try:
        openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
        # TODO: might want to recreate items to restore context
        # openai_realtime.create_conversation_item(item)
        await openai_realtime.connect()
        logger.info("Connected to OpenAI realtime")
        return True
    except Exception as e:
        await cl.ErrorMessage(content=f"Failed to connect to OpenAI realtime: {e}").send()
        return False

@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    # logger.info(f"Entering on_audio_chunk with chunk of size: {len(chunk.data)}")
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime:            
        if openai_realtime.is_connected():
            await openai_realtime.append_input_audio(chunk.data)
        else:
            pass
            # logger.info("RealtimeClient is not connected")
    # logger.info("Exiting on_audio_chunk")

@cl.on_audio_end
@cl.on_chat_end
@cl.on_stop
async def on_end():
    logger.info("Entering on_end")
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.disconnect()
    logger.info("Exiting on_end")



if __name__ == "__main__":
    async def main():
        logger.info("Starting the TTS client")
        client = AzureTTSClient()
        logger.info("Client initialized")
        
        voice = "hi-IN-KavyaNeural"  # Replace this with the desired voice
          
        input, output = client.text_to_speech(voice)
        logger.info(f"Checking input going to tts under azure_tts.py - {input}")

        async def read_output():
            audio = b''
            async for chunk in output:
                logger.info(f"Received audio chunk of size {len(chunk)}")
                audio += chunk
            with open("output.wav", "wb") as f:
                f.write(b'RIFF')
                f.write((36 + len(audio)).to_bytes(4, 'little'))
                f.write(b'WAVE')
                f.write(b'fmt ')
                f.write((16).to_bytes(4, 'little'))
                f.write((1).to_bytes(2, 'little'))
                f.write((1).to_bytes(2, 'little'))
                f.write((24000).to_bytes(4, 'little'))
                f.write((48000).to_bytes(4, 'little'))
                f.write((2).to_bytes(2, 'little'))
                f.write((16).to_bytes(2, 'little'))
                f.write(b'data')
                f.write((len(audio)).to_bytes(4, 'little'))
                f.write(audio)

        async def put_input():
            text_list = [
                "Hello,",
                "world!",
                "आपकी अगली EMI 3500 रूपये है।",  # Example with numbers
                "My name is Manoranjan",
                "आपका बकाया 25000 रूपये है।",  # Another example
                "How can I help you today?"
            ]

            for text in text_list:
                input.write(text)  # Send processed text to TTS
                # await asyncio.sleep(0.2)  # Small delay to ensure full processing
            
            # await asyncio.sleep(0.4)  # Extra delay before closing (if needed)
            input.close()
        
        await asyncio.gather(read_output(), put_input())
        logger.info("TTS client finished")

    asyncio.run(main())
    