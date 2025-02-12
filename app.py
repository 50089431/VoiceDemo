import os
import traceback
import asyncio
from openai import AsyncAzureOpenAI
import chainlit as cl
from chainlit.input_widget import Select, Switch, Slider
from uuid import uuid4
from chainlit.logger import logger
from realtime import RealtimeClient
from azure_tts import Client as AzureTTSClient
from tools import tools


"""A dictionary mapping languages to their respective Azure TTS voices.
When a user selects a language, the corresponding TTS voice is used."""
VOICE_MAPPING = {
    # "hindi": "hi-IN-AnanyaNeural",
    "hindi" : "hi-IN-KavyaNeural",
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

tts_sentence_end = [ ".", "!", "?", ";", "。", "！", "？", "；", "\n", "।"]
async def setup_openai_realtime(system_prompt: str):
    """Instantiate and configure the OpenAI Realtime Client"""
    openai_realtime = RealtimeClient(system_prompt = system_prompt) #Creates an OpenAI Realtime Client instance with a system_prompt.
    cl.user_session.set("track_id", str(uuid4())) #Generates a unique track ID for the session.
    voice = VOICE_MAPPING.get(cl.user_session.get("Language")) #Retrieves the voice selection from cl.user_session.
    collected_messages = []
    
    async def fix_number_recognition(transcript):
        """
        Ensures numbers are fully captured, especially avoiding missing last digits.
        """
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
                    
                    if item["status"] == "in_progress":
                        collected_messages.append(chunk_message)  # save the message

                        if chunk_message in tts_sentence_end: # sentence end found
                            sent_transcript = ''.join(collected_messages).strip()
                            collected_messages.clear()

                            sent_transcript = await fix_number_recognition(sent_transcript)
                            print(f"Bot is planning to speak: {sent_transcript}")
                            chunk = await AzureTTSClient.text_to_speech_realtime(text=sent_transcript, voice = voice)
                            await cl.context.emitter.send_audio_chunk(cl.OutputAudioChunk(mimeType="audio/wav", data=chunk, track=cl.user_session.get("track_id")))
                    
            if 'arguments' in delta:
                arguments = delta['arguments']  # string, function arguments added
                pass
    
    async def handle_item_completed(item):
        """Generate the transcript once an item is completed and populate the chat context."""
        try:
            transcript = item['item']['formatted']['transcript']
            print(f"DEBUG - in handle_item_completed : {transcript}")
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
        cl.user_session.set("track_id", str(uuid4()))
        try:
            collected_messages.clear()
        except Exception as e:
            logger.error(f"Failed to clear collected messages: {e}")    
        await cl.context.emitter.send_audio_interrupt()
        
    async def handle_input_audio_transcription_completed(event):
        item = event.get("item")
        delta = event.get("delta")
        if 'transcript' in delta:
            print(f"DEBUG - in handle_input_audio_transcription_completed : {delta['transcript']}")
            transcript = delta['transcript']
            if transcript != "":
                await cl.Message(author="You", type="user_message", content=transcript).send()
        
    async def handle_error(event):
        logger.error(event)
        
    
    openai_realtime.on('conversation.updated', handle_conversation_updated)
    openai_realtime.on('conversation.item.completed', handle_item_completed)
    openai_realtime.on('conversation.interrupted', handle_conversation_interrupt)
    openai_realtime.on('conversation.item.input_audio_transcription.completed', handle_input_audio_transcription_completed)
    openai_realtime.on('error', handle_error)

    cl.user_session.set("openai_realtime", openai_realtime)
    #cl.user_session.set("tts_client", tts_client)
    coros = [openai_realtime.add_tool(tool_def, tool_handler) for tool_def, tool_handler in tools]
    await asyncio.gather(*coros)
    

@cl.password_auth_callback
def auth_callback(username: str, password: str):
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
    '''Asks the user to select a language, toggle Azure Voice, and set AI temperature.'''
    settings = await cl.ChatSettings([
        Select(
            id="Language",
            label="Choose Language",
            values=list(VOICE_MAPPING.keys()),
            initial_index=0,
        ),
        Switch(id="useAzureVoice", label="Use Azure Voice", initial=False),
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


@cl.on_settings_update
async def setup_agent(settings):
    '''When a user sends a text message, it forwards it to OpenAI for processing.'''

    system_prompt = """
    You are a female intelligent voice assistant for L&T Finance, assisting customers with two-wheeler loans.

    - All numbers are to be spoken in English using India Standard System 
    - All dates are to be spoken in English
    - Avoid complex Hindi words and use commonly spoken english words for better customer engagement.

    Response Flow:
        1. Wait for the customer's question
            Listen carefully to the customer's question before responding. 
        2. If the question is related to Loan-Related Queries:
            - Verify the customer only once per conversation.
            - If the customer is not yet verified, request their agreement number or registered contact number for verification.
            - User will speak a **phone number**. Listen carefully to the number, make sure the number is 10 digits. Listen to the first and last digits properly. 
            - Say - Mein aapka number **phone number (in english digits)** search kr rhi hun.
            - Use the search_data tool to retrieve relevant loan details from the dataset.
            - If the provided details match an entry, share only the specific information requested by the customer.
            - If no matching record is found, politely ask the customer to reconfirm their details. Do not provide any loan-related information in this case.
        3. If the question is a General Query:
            - Do not request verification
            - DO not respond with general knowledge.
            - Invoke the fetch_relevant_documents tool to provide the requested information.
        4. After giving the answer, wait for the customer reply.
        5. If the customer dosesn't reply, ask the customer if they have any further questions to ensure a smooth conversation experience.
    
    Example Conversation 1:
    Customer: Hello?
    Assistant: L&T Finance - Customer Support mein aapka swaagat hai. Mein aapki kaise sahayata kar sakti hun?
    Customer: Mujhe apne EMI payment ke baare me jaana hai. 
    Assistant: Kripya apna mobile number ya agreement number pradan karein.
    Customer: 9823456789
    Assistant: Dhanyavad! Mein aapka number nine eight two three four five six seven eight nine search kr rhi hun.
    Assistant: Aapki last EMI Rs. two thousand eight hundred hai, jo 03 February 2025 ko due thi, and iska payment abhi tk nahi hua hai.

    Example Conversation 2:
    Customer: Hello?
    Assistant:L&T Finance - Customer Support  mein aapka swaagat hai. Mein aapki kaise sahayata kar sakti hun?
    Customer: Kya aap bta sakte hai ki mera EMI payment hua hai ya nahi is mahine ka?
    Assistant: Kripya apna mobile number ya agreement number pradan karein.
    Customer: AG12345
    Assistant: Dhanyavad! Mein aapka number AG12345 search kr rhi hun.
    Assistant: Aapka last EMI payment 3 Febuary ko ho chuka hai.
    Assistant: Kya main aapki koi aur madad kar sakti hoon?

    Example Conversation 3:
    Customer: Hello?
    Assistant: L&T Finance - Customer Support mein aapka swaagat hai. Mein aapki kaise sahayata kar sakti hun?
    Customer: Kya aap bta skte hai ki mera kitna payment abhi bacha hua hai?
    Assistant: Kripya apna mobile number ya agreement number pradan karein.
    Customer: 9876034567
    Assistant: Dhanyavad! Mein aapka number nine eight seven six zero three four five six seven search kr rhi hun.
    Assistant: Aapka total balance abhi Rs twenty thousand hai. 
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
    
@cl.on_message
async def on_message(message: cl.Message):
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.send_user_message_content([{ "type": 'input_text', "text": message.content}])
    else:
        await cl.Message(content="Please activate voice mode before sending messages!").send()

@cl.on_audio_start
async def on_audio_start():
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
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime:            
        if openai_realtime.is_connected():
            await openai_realtime.append_input_audio(chunk.data)
        else:
            logger.info("RealtimeClient is not connected")

@cl.on_audio_end
@cl.on_chat_end
@cl.on_stop
async def on_end():
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.disconnect()