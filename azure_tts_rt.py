# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE.md file in the project root for full license information.
'''
This script is designed for Text-to-Speech (TTS) synthesis using Azure Cognitive Services Speech SD

What This Code Does:
1. Loads Environment Variables:
    Uses dotenv to load AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.

2. Handles Audio Streaming:
    AioStream class manages an asynchronous audio data queue.
    calculate_energy() function detects silence in the audio.

3. Azure Speech Synthesis Setup:
    The Client class initializes Azure Speech SDK and configures the TTS system.
    It creates multiple instances of SpeechSynthesizer for parallel processing.

4. Text-to-Speech (TTS) Processing:
    The text_to_speech() function takes input text and converts it to speech.
    Uses SSML (Speech Synthesis Markup Language) for fine-tuned speech synthesis.
    Processes silence removal and energy detection for better output.
    The generated speech is written to a WAV file (output.wav).

'''
import asyncio # for asynchronous processing
import logging
import os
from typing import AsyncIterator, Tuple
import traceback
import azure.cognitiveservices.speech as speechsdk # Text-to-Speech
import numpy as np
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
load_dotenv()
from logger import logger  # Import the logger
import re

class Client:
    '''
    Manages speech synthesis using Azure Cognitive Services.
    synthesis_pool_size: Defines the number of concurrent speech synthesis requests.
    '''
    def __init__(self, synthesis_pool_size: int = 2):
        if synthesis_pool_size < 1:
            raise ValueError("synthesis_pool_size must be at least 1")
        self.synthesis_pool_size = synthesis_pool_size
        self._counter = 0
        self.voice = None

    @classmethod
    async def text_to_speech_realtime(self, text: str, voice: str, speed: str = "medium"):
        
        '''Processes text-to-speech in real-time using Azure Cognitive Services.'''
        # Azure Speech Service Configuration
        text = re.sub(r'\d+', lambda x: ' '.join(x.group()), text)
        
        logger.info("In text_to_speech_realtime - %s" % text)

        speech_config = speechsdk.SpeechConfig(subscription=os.environ['AZURE_SPEECH_KEY'], region=os.environ['AZURE_SPEECH_REGION'])
        speech_config.speech_synthesis_voice_name = voice
        speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm)
        speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        
        # Synthesize speech
        # ssml = f'<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="hi-IN"><voice name="{voice}">{text}</voice></speak>'
        
        # ssml = f'<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="hi-IN"><voice name="{voice}"><mstts:express-as type="digits">{text}</mstts:express-as></voice></speak>'
        
        def convert_to_ssml(text, voice):
            # Function to wrap detected numbers in <say-as interpret-as="digits">
            def wrap_digits(match):
                return f'<say-as interpret-as="digits">{match.group().strip()}</say-as>'
            
            # Replace all numbers in text while keeping normal text unchanged
            processed_text = re.sub(r'\d+', wrap_digits, text)
            print(f'In text_to_speech_realtime - {processed_text}')
            # Final SSML output
            ssml = f'''
            <speak xmlns="http://www.w3.org/2001/10/synthesis"
                xmlns:mstts="http://www.w3.org/2001/mstts"
                version="1.0" xml:lang="{voice.split('-')[0]}-{voice.split('-')[1]}">
                <voice name="{voice}">
                    {processed_text}
                </voice>
            </speak>
            '''
            
            return ssml

        ssml = convert_to_ssml(text, voice)
        print(f'In text_to_speech_realtime ssml - {ssml}')

        # Converts the generated speech into audio data (result.audio_data).
        result = speech_synthesizer.speak_ssml_async(ssml).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print("Speech synthesized successfully.")
            audio_data = result.audio_data
            return audio_data
        else:
            print("Failed to synthesize speech:", result.reason)

if __name__ == "__main__":
    async def main():

        logger.info("Starting the TTS client")
        client = Client()
        logger.info("Client initialized")
        
        voice = "hi-IN-KavyaNeural"  # Replace this with the desired voice
          
        input, output = client.text_to_speech_realtime(voice)

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
                
            ]

            for text in text_list:
                input.write("ndjdjdklsjdkl")  # Send processed text to TTS
                await asyncio.sleep(0.2)  # Small delay to ensure full processing
            
            await asyncio.sleep(0.4)  # Extra delay before closing (if needed)
            input.close()
        
        await asyncio.gather(read_output(), put_input())
        logger.info("TTS client finished")

    asyncio.run(main())