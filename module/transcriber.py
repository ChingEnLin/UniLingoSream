# transcriber_translator.py

from google.cloud import speech
from google.cloud import translate_v2 as translate

class TranscriberTranslator:
    def __init__(self, source_language="en", target_language="zh-TW", sample_rate=16000):
        self.sample_rate = sample_rate
        self.source_language = source_language
        self.target_language = target_language
        self.speech_client = speech.SpeechClient()
        self.translate_client = translate.Client()

    def transcribe_audio(self, audio_data):
        audio = speech.RecognitionAudio(content=audio_data)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate,
            language_code=self.source_language,
            model="default",
        )
        response = self.speech_client.recognize(config=config, audio=audio)
        transcription = ""
        for result in response.results:
            transcription += result.alternatives[0].transcript + " "
        print(f"Transcription: {transcription}", transcription)
        return transcription.strip()

    def translate_text(self, text):
        result = self.translate_client.translate(text, source_language=self.source_language, target_language=self.target_language)
        return result["translatedText"]

    def transcribe_and_translate(self, audio_data):
        transcription = self.transcribe_audio(audio_data)
        translation = self.translate_text(transcription)
        return translation
