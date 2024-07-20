""" Transcribe audio file and translate the text to another language 
"""
import os
import io
import threading
import tkinter as tk
from google.cloud import speech
from google.cloud import translate_v2 as translate

# Set up Google Cloud credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'unilingostream-project-4cb5d38e928d.json'

# Transcribe audio
def transcribe_audio(audio_file_path) -> str:
    """Transcribe the given audio"""
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

    transcription = ""
    for result in response.results:
        transcription += result.alternatives[0].transcript + " "

    return transcription.strip()

# Translate text
def translate_text(text, source_language="en", target_language="zh-TW"):
    """Translate the given text"""
    translate_client = translate.Client()
    result = translate_client.translate(text,
                                        source_language=source_language,
                                        target_language=target_language)
    return result["translatedText"]

# Display translation in a GUI
def display_translation(audio_file_path):
    """Display translation in a GUI"""
    root = tk.Tk()
    root.title("Real-Time Translation")
    label = tk.Label(root, text="start", font=("Helvetica", 16), wraplength=500)
    label.pack(pady=20, padx=20)

    def update_label(new_translation):
        label.config(text=new_translation)

    def transcribe_and_translate():
        while True:
            # Assuming you have a way to capture audio chunks
            transcribed_text = transcribe_audio(audio_file_path)
            translated_text = translate_text(transcribed_text, "ja", "zh-TW")
            update_label(translated_text)

    threading.Thread(target=transcribe_and_translate).start()
    root.mainloop()

def main():
    """Main function"""
    audio_file_path = "ookami.mp3"
    display_translation(audio_file_path)

if __name__ == "__main__":
    main()
