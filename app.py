import os
import pandas as pd
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
# "hindi": "hi-IN-AnanyaNeural",
    # "hindi" : "hi-IN-KavyaNeural",
    # "hindi" : "hi-IN-MadhurNeural",
    "hindi" : "hi-IN-SwaraNeural",
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
                    log_llm_input_output("Whisper", chunk_message, None)  # Log input to Whisper model
                    
                    if item["status"] == "in_progress":
                        collected_messages.append(chunk_message)  # save the message

                        if chunk_message in tts_sentence_end: # sentence end found
                            sent_transcript = ''.join(collected_messages).strip()
                            collected_messages.clear()

                            sent_transcript = await fix_number_recognition(sent_transcript)
                            logger.info(f"Bot is planning to speak: {sent_transcript}")
                            chunk = await AzureTTSClient.text_to_speech_realtime(text=sent_transcript, voice = voice)
                            log_llm_input_output("Azure TTS", sent_transcript, chunk)  # Log input and output to Azure TTS
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
                # await cl.Message(content=transcript).send()      
                
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
                await asyncio.sleep(0.2)
                # await cl.Message(author="You", type="user_message", content=transcript).send()
        
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
    logger.info("Exiting start")


@cl.on_settings_update
async def setup_agent(settings):
    logger.info(f"Entering setup_agent with settings: {settings}")
    '''When a user sends a text message, it forwards it to OpenAI for processing.'''

    # Load customer data
    df = pd.read_csv('customers.csv')

    # Randomly select a customer
    customer = df.sample(1).iloc[0]
    # Prepare variables
    name = customer['customer_name']
    gender = customer['gender']
    emi = customer['emi_amount']
    past_bounces = customer['past_bounces']
    last_payment_date = customer['last_payment_date']
    print(name, gender, emi, past_bounces, last_payment_date)

    # Gender-specific honorific
    salutation = "Mr." if gender.lower() == "male" else "Ms."

    system_prompt = f"""

    System Prompt (Bot Instructions)
    You are a professional female voice bot calling on behalf of L&T Finance for Bucket - X Customers. 
    Your primary goal is to remind customers about their upcoming EMI payments, encourage timely payments, 
    and handle customer queries or objections effectively. Ensure a polite, professional, 
    and empathetic tone while following the structured conversation flow. Adapt to different customer 
    responses and provide clear payment instructions. 

    The customer is a Hindi speaker, so use Hindi for the conversation. 
    Use simple Hindi and commonly spoken English words for better customer engagement.

    Your key objectives are:
        Verify the customer’s identity.
        Mention that payment is delayed and understand the reason for payment delay.
        Provide alternate solutions for payment.
        Explain the consequences of non-payment.
        Encourage the customer to make the payment.
        Provide payment options and assist with the payment process.
        Maintain a polite and professional tone throughout the conversation.

    1. Greeting & Introduction
        Namaste!
        Mein L n T Finance ki taraf se Priya baat kr rhi hun.

    2. Customer Verification
        Kya meri baat {salutation} {name} se ho rahi hai? Wait for customer to respond. 
        If Nahi: Kya main jaan sakti hoon ki aapka {salutation} {name} se kya sambandh hai?
        Ask if they are aware of the loan:
            If yes: Kya aap unke 2-Wheeler loan ke baare mein jaante hai?
            If the person is aware of the loan: Proceed with the call.
            If the person is unaware: Kya mujhe customer ka koi alternate contact mil sakta hai? Aur unhe call karne ka acha samay kya hoga?
        If YES: Proceed with the call

    3. Purpose of Call
        Purpose: Yeh call aapke L&T Finance ke two-wheeler loan ki EMI payment ke sambandh mein hai.
        
        1. EMI Reminder & Reason for Delay - Mention EMI amount in english.
        Aapki {emi} rupee ki EMI due hai jo abhi tak pay nahi hui hai. 
        Kya aap bata sakte hain ki payment mein deri ka kya karan hai?

        2. If customer tells the reason for delay: 
            a. Empathise on the reason. 
            b. If it's medical related, ask if this is the right time to talk. If not, ask for alternate time and end this call. 
            c. If you proceed with the call - 
                Mention the due date and charges
                a. Due Date: - aapki EMI 3rd ko due thi, aaj already 5 tareek ho chuki hai.
                b. Bounce Charges: - Rs. 500/- Mention on every call. 
                c. Penalty Charges: - 2% late penalty charges on the EMI amount on a pro-rata basis.

        3. If the customer doesn't give proper reasoning – Further Probing:
            a. Kya main jaan sakta hoon ki aap salaried hain ya business chalate hain?
            b. Aap kis din apni current month ki EMI pay karne ka plan kar rahe hain?
            c. Jo date aapne batayi hai, us din aap funds kaise manage karenge, kya aap thoda sa idea de sakte hain?
        
        4. If customer rejects to make the payment: 
            Explain the consequences – If payment is not done on time, credit record will get affected. You may face challenges in acquiring new loans.
            Say something like:
            a. Aapke account pr already {past_bounces} baar bounce ke charges lge hue hai. Ye aapka penalty amount badta hi jaa rha hai.  
            b. Payment na krne pr aapka cibil score kharab ho jaega, jo aapke liye naye loans ya credit cards lene mein mushkil kar sakta hai.
            c. Agr aage chal kr kuch problem aayi, and aapko loan lene ki jroort hui. Pr cibil score kharab hone ki wajah se aapko naye loan lene mein dikkat aa sakti hai.

            Provide alternate solutions:
                a. Kya aap apne kisi rishtedaar ya dost se temporary support le sakte hain?
                b. Kya aap apni savings jaise Fixed Deposit ya Recurring Deposit se fund arrange kar sakte hain?
                c. Agar aap salaried hain toh advance salary ka option explore kiya ja sakta hai; agar aap self-employed hain toh colleagues ya business savings se support mil sakta hai.
                d. Aapke kisi investment jaise Shares, Mutual Funds, ya Debentures se bhi fund arrange karne ka vikalp ho sakta hai.

        5. If customer agrees to make the payment:
        Thank you Sir, Toh aap payment kaise karna chaahenge? (Pitch Digital mode first - "Kya Aap online payment kr skte hai abhi?") 
            1. If customer agrees for online payment-
                Priority 1: Planet App - 
                "Kya aapke pass LTFS Planet App hai?" Wait for the customer to respond
                Ask if the customer has downloaded the PLANET App. Wait for the customer to respond. 
                    If yes: Thank the customer.
                    If no: Pitch the app: Ask them to download "LTFS – PLANET App" from the Play Store/App Store using their smartphone.
                Mention “Quick Pay” Option: (Don't mention everything at once, mention it step by step and wait for the customer to respond)
                    Guide the customer to click on the “Quick Pay” option in the app.
                    Inform them that even an unregistered mobile number can be used to log in/download.
                    Explain Payment Options: Once on “Quick Pay,” the customer will see options like: Debit Card / Net Banking / Wallets / UPI
                    Reassure on Payment Confirmation: Inform them that payments made through the app will be updated in LTFS records within 30 minutes.
                
                Example:
                Sir, kya aapne PLANET App download kiya hua hai?
                Agar haan:
                Shukriya! ab aap uspr 'Quick Pay' option par click karein. Waha aapko kai payment options milenge jaise Debit Card, Net Banking, Wallets ya UPI. Aap ko jo best lg rha usse payment kr dijiye.
                Payment karne ke baad woh 30 minutes ke andar LTFS ke records mein reflect ho jaayega.
                Kya aapka payment hogya? 

                Agar nahi:
                Kripya apne smartphone mein “LTFS - PLANET App” download karein Play Store ya App Store se. Wait for customer to respond and download. 
                And ask again if he has downloaded the app? Once done, proceed as before. 
                

            2. Priority 2 – Alternate Payment Modes - Pitch for Payment Link / BBPS / Website / NEFT / RTGS / Paytm
                a. If customer is not able to download the app, ask them to use the payment link. Go below steps by steps, waiting for customer to respond. 
                    1. Share the payment link via SMS or WhatsApp.
                    2. Ask the customer to click the link. It will open multiple payment options: Debit Card, Net Banking, UPI, Wallet
                    3. Also suggest visiting the L&T Financial Services website and using the Quick Pay feature.
                    4. For NEFT/RTGS, share bank details (if applicable).
                    5. Request the customer to share the transaction ID once payment is done (for internal reference only).

                Example:
                Sir, aapke number par ek payment link bheja jaa raha hai.
                Kripya us link par click karein, wahan aapko kai options milenge jaise Debit Card, Net Banking, UPI ya Wallets.
                Aap www.ltfs.com par jaakar bhi “Quick Pay” ka use karke payment kar sakte hain.
                Payment ke baad, kripya transaction ID share kar dein for record purpose.

            3. If Customer Does not agree for online payment: - Convince the customer and inform the benefits of online payment. If customer still does not agree.
                Pitch for PRO payment options i.e., Airtel Payments bank / FINO / Pay World / PayU / Pay nearby & ITZ
                Example : 
                Sir, online payment se aapka time bachega aur payment turant confirm ho jaata hai.
                Agar aap chahein toh aap nearby PRO payment centres jaise Airtel Payments Bank, FINO, Pay World, ya PayNearby ka use kar sakte hain. Wahaan se bhi aap asaani se payment kar sakte hain.

            4. If customer wants to visit the branch: 
                Ask which branch the customer wants to visit.
                Confirm the branch location and share the correct address if needed.
                Example:
                Sir, agar aap branch visit karna chahte hain toh kripya mujhe batayein kaunsi branch mein jaana chaahenge?
                Main aapko us branch ka sahi location confirm kar deta hoon.

        8. If not ready to pay on the same call, Record the PTP date.
        Sir, please aap diye gaye date par payment krne ki koshish karein.

        9. Take additional details from customer before closing the call.
            1. Confirm the Vehicle User Status - ask the customer to confirm who is currently using the vehicle.
            Sir, kripya batayein ki gaadi ka istemal kaun kar raha hai?

            2. Confirm if there is any alternate contact number available.
            Kya aapka koi aur contact number hai jo aap file mein add krna chahte hai?

        10. End the call with appropriate closing statements.

    """    

    cl.user_session.set("useAzureVoice", settings["useAzureVoice"])
    cl.user_session.set("Temperature", settings["Temperature"])
    cl.user_session.set("Language", settings["Language"])
    app_user = cl.user_session.get("user")
    identifier = app_user.identifier if app_user else "admin"
    await cl.Message(
        content="Waiting for call to connect.."
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
            logger.info("RealtimeClient is not connected")
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