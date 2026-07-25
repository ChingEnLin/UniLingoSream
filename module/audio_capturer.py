import logging
import sounddevice as sd
import asyncio
import numpy as np

from module.utility.config import load_config

logger = logging.getLogger(__name__)


class AudioCapturer:
    """Captures audio from microphone in raw 16-bit PCM mono format
    and pushes it thread-safely to an asyncio queue.
    """
    BLOCK_DURATION_SEC = 0.05
    HANGOVER_SEC = 1.0

    def __init__(self, loop, audio_queue: asyncio.Queue, config_path="config.json", config=None, device_name=None):
        DEFAULT_CONFIG = {
            "device_name": "BlackHole 2ch",
            "sample_rate": 16000,
            "channels": 1,
            "silence_rms_threshold": 300,
            "block_duration_seconds": 0.05
        }
        if config is None:
            config = load_config(config_path).get("audio", DEFAULT_CONFIG)

        self.loop = loop
        self.audio_queue = audio_queue
        self.sample_rate = config.get("sample_rate", DEFAULT_CONFIG["sample_rate"])
        self.channels = config.get("channels", DEFAULT_CONFIG["channels"])
        self.device_name = device_name or config.get("device_name", DEFAULT_CONFIG["device_name"])
        self.block_duration_sec = config.get("block_duration_seconds", self.BLOCK_DURATION_SEC)

        # Stream in chunk size based on block duration (e.g. 50ms = 800 samples @ 16kHz)
        self.blocksize = int(self.sample_rate * self.block_duration_sec)

        # ponytail: RMS silence gate; threshold is a calibration knob in config.json (int16 units)
        self.silence_rms_threshold = config.get("silence_rms_threshold", DEFAULT_CONFIG["silence_rms_threshold"])
        self._hangover_blocks = int(self.HANGOVER_SEC / self.block_duration_sec)
        self._silent_block_count = self._hangover_blocks  # start gated until first speech

        # Find device index by name
        self.device_index = self._find_device_index(self.device_name)

        # Constructing the stream is the first thing that can fail on a misconfigured
        # machine. Surface it as a message on the overlay instead of a traceback before
        # any window exists; main.py renders self.error.
        self.error = None
        try:
            self.stream = sd.InputStream(
                callback=self.audio_callback,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.blocksize,
                device=self.device_index,
                dtype='int16',  # Raw 16-bit PCM expected by Gemini
            )
        except Exception as e:
            self.stream = None
            self.error = f"could not open audio input '{self.device_name}': {e}"
            logger.error("Could not open audio input stream: %s", e)

    def _find_device_index(self, target_name):
        """Find the index of the audio input device matching target_name.

        Devices with no input channels are skipped: sd.query_devices() lists outputs too,
        and handing an output-only index to InputStream fails at construction.
        """
        try:
            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                if target_name.lower() not in dev["name"].lower():
                    continue
                if dev.get("max_input_channels", 0) < 1:
                    logger.debug("Skipping '%s' at index %d: no input channels", dev["name"], idx)
                    continue
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
        """Callback function called by sounddevice for each block of input audio.

        Drops sustained silence so it is not streamed (and billed) to Gemini.
        """
        if status:
            logger.warning("Audio status warning: %s", status)
        rms = np.sqrt(np.mean(indata.astype(np.float64) ** 2))
        if rms < self.silence_rms_threshold:
            self._silent_block_count += 1
            if self._silent_block_count > self._hangover_blocks:
                return
        else:
            self._silent_block_count = 0
        # Convert captured numpy array to raw bytes
        raw_bytes = indata.tobytes()
        # Thread-safely push raw bytes to the asyncio queue
        self.loop.call_soon_threadsafe(self._safe_put, raw_bytes)

    def start_stream(self):
        """Start the audio stream. No-op if the stream could not be opened."""
        if self.stream is None:
            return
        self.stream.start()
        logger.info("Audio stream started.")

    def stop_stream(self):
        """Stop the audio stream. No-op if the stream could not be opened."""
        if self.stream is None:
            return
        self.stream.stop()
        logger.info("Audio stream stopped.")

    def close_stream(self):
        """Release the PortAudio stream. Safe to call more than once."""
        if self.stream is None:
            return
        self.stream.close()
        self.stream = None
        logger.info("Audio stream closed.")
