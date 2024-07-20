import os
import io
from google.cloud import speech

# Set up Google Cloud credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'unilingostream-project-4cb5d38e928d.json'

def transcribe_audio(audio_file_path):
    client = speech.SpeechClient()
    
    with io.open(audio_file_path, "rb") as audio_file:
        content = audio_file.read()
    
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MP3,  # Specify MP3 encoding
        sample_rate_hertz=16000,
        language_code="ja-JP",
    )

    response = client.recognize(config=config, audio=audio)

    for result in response.results:
        print("Transcript: {}".format(result.alternatives[0].transcript))

def main():
    transcribe_audio("ookami.mp3")

if __name__ == "__main__":
    main()
