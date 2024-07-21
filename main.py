# main.py

import os
import threading
from module.audio_capturer import AudioCapturer
from module.transcriber import TranscriberTranslator
from module.display import DisplayTranslation

# Set up Google Cloud credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'unilingostream-project-4cb5d38e928d.json'

def update_display(capturer, display):
    while True:
        transcribed_text = capturer.get_transcription()
        if transcribed_text:
            display.update_label(transcribed_text)

if __name__ == "__main__":
    transcriber_translator = TranscriberTranslator(source_language="ja-JP", target_language="zh-TW")
    audio_capturer = AudioCapturer(transcriber_translator, channels=1, block_duration=10)
    display_translation = DisplayTranslation()

    audio_capturer.start_stream()

    # Start a thread to update the display with transcriptions
    threading.Thread(target=update_display, args=(audio_capturer, display_translation)).start()

    # Start the Tkinter GUI loop
    display_translation.start_gui()
