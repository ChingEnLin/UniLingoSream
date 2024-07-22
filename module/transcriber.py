""" Transcriber module for transcribing and translating audio data """
import logging

from google.cloud import speech # pylint: disable=import-error
from google.cloud import translate_v2 as translate # pylint: disable=import-error

logger = logging.getLogger('root')

class TranscriberTranslator:
    """ Transcriber module for transcribing and translating audio data """
    def __init__(self, source_language="en",
                 target_language="zh-TW",
                 sample_rate=16000,
                 audio_channel_count=1):
        self.sample_rate = sample_rate
        self.audio_channel_count = audio_channel_count
        self.source_language = source_language
        self.target_language = target_language
        self.speech_client = speech.SpeechClient()
        self.translate_client = translate.Client()

    def transcribe_audio(self, audio_data):
        """ Transcribes the audio data """
        audio = speech.RecognitionAudio(content=audio_data)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate,
            audio_channel_count=self.audio_channel_count,
            language_code=self.source_language,
            model="default",
        )
        response = self.speech_client.recognize(config=config, audio=audio)
        transcription = ""
        for result in response.results:
            transcription += result.alternatives[0].transcript + " "
        logger.info("Script: %s", transcription)
        return transcription.strip()

    def translate_text(self, text):
        """ Translates the text """
        result = self.translate_client.translate(text,
                                                 source_language=self.source_language,
                                                 target_language=self.target_language)
        return result["translatedText"]

    def transcribe_and_translate(self, audio_data):
        """ Transcribes and translates the audio data """
        transcription = self.transcribe_audio(audio_data)
        translation = self.translate_text(transcription)
        return translation
