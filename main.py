"""Main script to run the UniLingoStream application.

This module initializes the application configurations, environment variables,
sets up the audio capture stream, background async client loop, and starts
the Tkinter GUI subtitle display.
"""

import os
import sys
import asyncio
import threading
from dotenv import load_dotenv

from module.audio_capturer import AudioCapturer
from module.transcriber import TranscriberTranslator
from module.display import DisplayTranslation
from module.utility import log

logger = log.setup_custom_logger('root')

# Load env variables (GEMINI_API_KEY)
load_dotenv()

# Named constant for polling interval
POLL_INTERVAL_MS = 50


def run_async_loop(loop, queue, transcriber, capturer):
    """Runs the asyncio event loop to capture audio and handle transcriber stream.

    Args:
        loop: The asyncio event loop.
        queue: The asyncio queue containing raw audio chunks.
        transcriber: The TranscriberTranslator module instance.
        capturer: The AudioCapturer module instance.
    """
    asyncio.set_event_loop(loop)
    
    # Start the sounddevice audio input capture stream
    capturer.start_stream()
    
    try:
        # Run the transcriber WebSocket loop
        loop.run_until_complete(transcriber.connect_and_run(queue))
    except Exception as e:
        logger.error("Error in background async event loop: %s", e)
    finally:
        capturer.stop_stream()
        loop.close()


def poll_transcription(display, transcriber):
    """Polls the transcriber buffer and updates the translation overlay.

    Args:
        display: The DisplayTranslation module instance.
        transcriber: The TranscriberTranslator module instance.
    """
    text = transcriber.get_transcription()
    if text:
        display.update_label(text)
    # Poll again in POLL_INTERVAL_MS
    display.root.after(POLL_INTERVAL_MS, poll_transcription, display, transcriber)


if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY not found in env variables or .env file! Please set it.")
        sys.exit(1)
        
    # Setup asyncio queue and loop
    async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(async_loop)
    audio_queue = asyncio.Queue()
    
    # Initialize modules
    transcriber_translator = TranscriberTranslator()
    audio_capturer = AudioCapturer(async_loop, audio_queue)
    display_translation = DisplayTranslation()

    # Start background thread for asyncio loop
    t = threading.Thread(
        target=run_async_loop, 
        args=(async_loop, audio_queue, transcriber_translator, audio_capturer),
        daemon=True
    )
    t.start()

    # Start polling for translations in Tkinter
    display_translation.root.after(POLL_INTERVAL_MS, poll_transcription, display_translation, transcriber_translator)

    # Start Tkinter GUI loop
    logger.info("Starting subtitle display overlay...")
    display_translation.start_gui()
