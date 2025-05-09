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

def calculate_energy(frame_data):
    '''
    Converts audio byte data to a NumPy array (assumes 16-bit PCM format).
    Computes audio energy (sum of squared amplitudes).
    Used to detect silence in speech synthesis.
    '''
    # Convert the byte data to a numpy array for easier processing (assuming 16-bit PCM)
    data = np.frombuffer(frame_data, dtype=np.int16)
    # Calculate the energy as the sum of squares of the samples
    energy = np.sum(data**2) / len(data)
    return energy

class AioStream:
    '''
    Handles real-time audio streaming asynchronously.
    Implements an async iterator (__aiter__ and __anext__).
    Stores audio chunks in an async queue (_queue).
    write_data(data): Adds audio data to the queue.
    end_of_stream(): Signals end-of-stream.
    read(): Reads from the queue asynchronously.
'''
    def __init__(self):
        self._queue = asyncio.Queue()

    def write_data(self, data: bytes):
        self._queue.put_nowait(data)

    def end_of_stream(self):
        self._queue.put_nowait(None)

    async def read(self) -> bytes:
        chunk = await self._queue.get()
        if chunk is None:
            raise StopAsyncIteration
        return chunk

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self):
        return await self.read()

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

    def configure(self, voice: str):

        '''
        Configures the Azure Speech Service for a specific voice.
        Sets the Azure Speech API endpoint and authentication using environment variables.
        Defines the audio format (16kHz 16-bit Mono PCM).
        '''

        logger.info(f"Configuring voice: {voice}")
        self.voice = voice

        self.speech_config = speechsdk.SpeechConfig(
            endpoint=f"wss://{os.environ['AZURE_SPEECH_REGION']}.tts.speech.microsoft.com/cognitiveservices/websocket/v2",
            subscription=os.environ["AZURE_SPEECH_KEY"]
        )
        self.speech_config.speech_synthesis_voice_name = voice
        self.speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm)
        self.speech_synthesizers = [speechsdk.SpeechSynthesizer(speech_config=self.speech_config, audio_config=None) for _ in range(self.synthesis_pool_size)]
        for s in self.speech_synthesizers:
            s.synthesis_started.connect(lambda evt: logger.info(f"Synthesis started: {evt.result.reason}"))
            s.synthesis_completed.connect(lambda evt: logger.info(f"Synthesis completed: {evt.result.reason}"))
            s.synthesis_canceled.connect(lambda evt: logger.error(f"Synthesis canceled: {evt.result.reason}"))

    def text_to_speech(self, voice: str, speed: str = "medium") -> Tuple[speechsdk.SpeechSynthesisRequest.InputStream, AioStream]:
        '''
        Converts text into speech audio stream.
        Uses asynchronous processing for real-time synthesis.
        Returns an audio stream that can be played in real time.
        '''
        logger.info(f"Entering text_to_speech with voice: {voice} and speed: {speed}")
        self.configure(voice)
        synthesis_request = speechsdk.SpeechSynthesisRequest(
            input_type=speechsdk.SpeechSynthesisRequestInputType.TextStream)
        self._counter = (self._counter + 1) % len(self.speech_synthesizers)
        current_synthesizer = self.speech_synthesizers[self._counter]

        result = current_synthesizer.start_speaking(synthesis_request)
        stream = speechsdk.AudioDataStream(result)
        aio_stream = AioStream()
        logger.info("Configured synthesizer and started speaking")

        async def read_from_data_stream():
            logger.info("Entering read_from_data_stream")
            leading_silence_skipped = False
            silence_detection_frames_size = int(50 * 16000 * 2 / 1000)  # 50 ms
            loop = asyncio.get_running_loop()
            while True:
                if not leading_silence_skipped:
                    if stream.position >= 3 * silence_detection_frames_size:
                        leading_silence_skipped = True
                        continue
                    frame_data = bytes(silence_detection_frames_size)
                    lenx = await loop.run_in_executor(None, stream.read_data, frame_data)
                    if lenx == 0:
                        if stream.status != speechsdk.StreamStatus.AllData:
                            logger.error(f"Speech synthesis failed: {stream.status}, details: {stream.cancellation_details.error_details}")
                        break
                    energy = await loop.run_in_executor(None, calculate_energy, frame_data)
                    
                    if energy < 500: # Skips leading silence to improve response speed.
                        logger.info("Silence detected, skipping")
                        continue
                    leading_silence_skipped = True
                    stream.position = stream.position - silence_detection_frames_size
                chunk = bytes(1600*2)
                read = await loop.run_in_executor(None, stream.read_data, chunk)
                if read == 0:
                    break
                logger.info(f"Read audio chunk of size {len(chunk)}")
                aio_stream.write_data(chunk[:read])
            if stream.status != speechsdk.StreamStatus.AllData:
                logger.error(f"Speech synthesis failed: {stream.status}, details: {stream.cancellation_details.error_details}")
            aio_stream.end_of_stream()

        asyncio.create_task(read_from_data_stream())
        return synthesis_request.input_stream, aio_stream
        
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
        
        
        input, output = client.text_to_speech(voice)

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
                await asyncio.sleep(0.2)  # Small delay to ensure full processing
            
            await asyncio.sleep(0.4)  # Extra delay before closing (if needed)
            input.close()
        
        await asyncio.gather(read_output(), put_input())
        logger.info("TTS client finished")

    asyncio.run(main())