""" Main script to run the UnilingoStream application """
import os
import threading

from module.audio_capturer import AudioCapturer
from module.transcriber import TranscriberTranslator
from module.display import DisplayTranslation

from module.utility import log # pylint: disable=import-error, no-name-in-module
logger = log.setup_custom_logger('root')

# Set up Google Cloud credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'unilingostream-project-4cb5d38e928d.json'

def update_display(capturer, display):
    """ Updates the display with translated text """
    while True:
        transcribed_text = capturer.get_transcription()
        if transcribed_text:
            display.update_label(transcribed_text)

if __name__ == "__main__":
    transcriber_translator = TranscriberTranslator(source_language="ja-JP",
                                                   target_language="zh-TW",
                                                   audio_channel_count=2)
    audio_capturer = AudioCapturer(transcriber_translator, channels=1, block_duration=10)
    display_translation = DisplayTranslation()

    logger.info("Starting audio capturer...")
    audio_capturer.start_stream()

    # Start a thread to update the display with transcriptions
    threading.Thread(target=update_display, args=(audio_capturer, display_translation)).start()

    # Start the Tkinter GUI loop
    display_translation.start_gui()
