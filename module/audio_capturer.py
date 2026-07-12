import logging
import sounddevice as sd
import json
import asyncio

logger = logging.getLogger(__name__)

class AudioCapturer:
    """Captures audio from microphone in raw 16-bit PCM mono format
    and pushes it thread-safely to an asyncio queue.
    """
    BLOCK_DURATION_SEC = 0.1

    def __init__(self, loop, audio_queue: asyncio.Queue, config_path="config.json", config=None):
        DEFAULT_CONFIG = {
            "device_name": "BlackHole 2ch",
            "sample_rate": 16000,
            "channels": 1
        }
        if config is None:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    config = data.get("audio", DEFAULT_CONFIG)
            except Exception as e:
                logger.warning("Failed to load config from %s: %s. Using default audio config.", config_path, e)
                config = DEFAULT_CONFIG

        self.loop = loop
        self.audio_queue = audio_queue
        self.sample_rate = config.get("sample_rate", DEFAULT_CONFIG["sample_rate"])
        self.channels = config.get("channels", DEFAULT_CONFIG["channels"])
        device_name = config.get("device_name", DEFAULT_CONFIG["device_name"])
        
        # Stream in ~100ms chunks (1600 samples @ 16kHz)
        self.blocksize = int(self.sample_rate * self.BLOCK_DURATION_SEC)
        
        # Find device index by name
        self.device_index = self._find_device_index(device_name)
        
        self.stream = sd.InputStream(
            callback=self.audio_callback,
            channels=self.channels,
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            device=self.device_index,
            dtype='int16' # Raw 16-bit PCM expected by Gemini
        )

    def _find_device_index(self, target_name):
        """Find the index of the audio input device matching target_name."""
        try:
            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                if target_name.lower() in dev["name"].lower():
                    logger.info("Found target audio device %s at index %d", dev["name"], idx)
                    return idx
        except Exception as e:
            logger.warning("Error querying audio devices: %s", e)
        logger.warning("Target device '%s' not found. Using system default input.", target_name)
        return None

    def _safe_put(self, raw_bytes):
        """Thread-safe helper to put audio data in the queue, handling QueueFull."""
        try:
            self.audio_queue.put_nowait(raw_bytes)
        except asyncio.QueueFull:
            logger.warning("Audio queue is full, dropping frame.")

    def audio_callback(self, indata, frames, time, status):
        """Callback function called by sounddevice for each block of input audio."""
        if status:
            logger.warning("Audio status warning: %s", status)
        # Convert captured numpy array to raw bytes
        raw_bytes = indata.tobytes()
        # Thread-safely push raw bytes to the asyncio queue
        self.loop.call_soon_threadsafe(self._safe_put, raw_bytes)

    def start_stream(self):
        """Start the audio stream."""
        self.stream.start()
        logger.info("Audio stream started.")

    def stop_stream(self):
        """Stop the audio stream."""
        self.stream.stop()
        logger.info("Audio stream stopped.")
