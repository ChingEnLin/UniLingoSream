"""Main script to run the UniLingoStream application.

This module initializes the application configurations, environment variables,
sets up the audio capture stream, background async client loop, and starts
the Tkinter GUI subtitle display.
"""

import os
import sys
import json
import atexit
import argparse
import asyncio
import threading
from dotenv import load_dotenv

from module import audio_route
from module.audio_capturer import AudioCapturer
from module.transcriber import TranscriberTranslator
from module.utility import log

logger = log.setup_custom_logger('root')

# Load env variables (GEMINI_API_KEY)
load_dotenv()

# Named constant for polling interval
POLL_INTERVAL_MS = 50

# Bound the capture queue: ~5s of 100ms chunks. AudioCapturer drops frames when full.
AUDIO_QUEUE_MAXSIZE = 50


def run_async_loop(loop, queue, transcriber, capturer):
    """Runs the asyncio event loop to capture audio and handle transcriber stream.

    Args:
        loop: The asyncio event loop.
        queue: The asyncio queue containing raw audio chunks.
        transcriber: The TranscriberTranslator module instance.
        capturer: The AudioCapturer module instance.
    """
    asyncio.set_event_loop(loop)
    
    try:
        # Run the transcriber WebSocket loop with connect/disconnect callbacks for stream warming
        loop.run_until_complete(
            transcriber.connect_and_run(
                queue,
                on_connect=capturer.start_stream,
                on_disconnect=capturer.stop_stream
            )
        )
    except Exception as e:
        logger.error("Error in background async event loop: %s", e)
    finally:
        # Safeguard to ensure capturing is stopped on loop termination
        capturer.stop_stream()
        loop.close()


def poll_transcription(display, transcriber, last_rendered=""):
    """Polls the transcriber buffer and updates the translation overlay.

    Args:
        display: The DisplayTranslation module instance.
        transcriber: The TranscriberTranslator module instance.
        last_rendered: The text currently shown on the overlay.
    """
    text = transcriber.get_transcription()
    if text != last_rendered:
        display.update_label(text)
    # Poll again in POLL_INTERVAL_MS
    display.root.after(POLL_INTERVAL_MS, poll_transcription, display, transcriber, text)


def make_display(backend_override=None, config_path="config.json"):
    """Selects the overlay backend: CLI --backend, else config `ui.backend` (tk | appkit).

    AppKit is imported lazily so non-macOS environments (Linux/CI) never load it.
    """
    backend = backend_override
    if backend is None and os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                backend = json.load(f).get("ui", {}).get("backend")
        except Exception as e:
            logger.warning("Could not read ui.backend from %s: %s. Using tk.", config_path, e)

    if backend == "appkit":
        try:
            from module.display_appkit import DisplayTranslation
            return DisplayTranslation()
        except ImportError as e:
            logger.warning(
                "AppKit backend unavailable (%s); falling back to tk. "
                "Install pyobjc-framework-Cocoa for the native overlay.", e
            )

    from module.display import DisplayTranslation
    return DisplayTranslation()


def parse_args(argv=None):
    """Parses CLI overrides. Unknown args are ignored so test runners' argv doesn't break."""
    parser = argparse.ArgumentParser(description="Real-time translation subtitle overlay")
    parser.add_argument("--target", help="Target language code override, e.g. en-US")
    parser.add_argument("--device", help="Audio input device name substring override")
    parser.add_argument("--backend", choices=["tk", "appkit"], help="Overlay backend override")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    args, _ = parser.parse_known_args(argv)
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        sys.exit(0)

    if not os.getenv("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY not found in env variables or .env file! Please set it.")
        sys.exit(1)

    # Point system output at the Multi-Output Device so audio reaches BlackHole for
    # capture, then restore the previous device on exit. No-op without SwitchAudioSource.
    output_device = json.load(open("config.json", encoding="utf-8")).get(
        "audio", {}
    ).get("output_device", "Multi-Output Device") if os.path.exists("config.json") else "Multi-Output Device"
    _prev_output = audio_route.current_output()
    if audio_route.set_output(output_device) and _prev_output:
        atexit.register(audio_route.set_output, _prev_output)  # tk backend / Ctrl+C
        audio_route.restore_on_terminate(_prev_output)          # appkit Quit (terminate:)

    # Setup asyncio queue and loop
    async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(async_loop)
    audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)

    # Initialize modules
    overrides = {}
    if args.target:
        overrides["target_language"] = args.target
    transcriber_translator = TranscriberTranslator(**overrides)
    audio_capturer = AudioCapturer(async_loop, audio_queue, device_name=args.device)
    display_translation = make_display(args.backend)

    # Surface silent fallback: default input is the microphone, not system audio
    if audio_capturer.device_index is None:
        display_translation.update_label(
            f"WARNING: audio device '{audio_capturer.device_name}' not found - "
            "capturing default input (microphone)"
        )

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
    transcriber_translator.log_session_summary()
