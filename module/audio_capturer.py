import collections
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
    # Trailing silence kept after speech so word tails are not clipped. Every second of it
    # is billed, so it is short and configurable; 1.0s used to cost a second per utterance.
    HANGOVER_SEC = 0.4
    # Adaptive gate: the noise floor is the 10th percentile of recent block RMS (the gaps
    # between words). Speech has to beat it by MARGIN, but the gate can never rise above
    # CAP x the configured threshold, or a loud passage would mute the subtitles entirely.
    NOISE_WINDOW_SEC = 10.0
    ADAPTIVE_PERCENTILE = 10
    ADAPTIVE_MARGIN = 2.0
    ADAPTIVE_CAP = 3.0
    DUTY_LOG_SEC = 60.0

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
        self.hangover_sec = config.get("hangover_seconds", self.HANGOVER_SEC)
        self._hangover_blocks = int(self.hangover_sec / self.block_duration_sec)
        self._silent_block_count = self._hangover_blocks  # start gated until first speech

        # Adaptive gate: a fixed threshold never closes over content with music or room
        # tone above it, so the stream (and the bill) runs at 100% duty cycle.
        self.adaptive_gate = config.get("adaptive_gate", True)
        self._rms_window = collections.deque(
            maxlen=max(1, int(self.NOISE_WINDOW_SEC / self.block_duration_sec))
        )
        self._blocks_seen = 0
        self._blocks_sent = 0
        self._duty_log_blocks = max(1, int(self.DUTY_LOG_SEC / self.block_duration_sec))

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

    def _gate_threshold(self):
        """Effective RMS gate: the configured floor, raised toward the measured noise floor.

        Only raises, never lowers, and only once the window has filled - a quiet source
        keeps the configured threshold, a loud one stops being streamed continuously.
        """
        if not self.adaptive_gate or len(self._rms_window) < self._rms_window.maxlen:
            return self.silence_rms_threshold
        floor = float(np.percentile(self._rms_window, self.ADAPTIVE_PERCENTILE))
        return min(
            max(self.silence_rms_threshold, floor * self.ADAPTIVE_MARGIN),
            self.silence_rms_threshold * self.ADAPTIVE_CAP,
        )

    def _log_duty_cycle(self, threshold):
        """Every DUTY_LOG_SEC, report the share of audio actually billed."""
        self._blocks_seen += 1
        if self._blocks_seen < self._duty_log_blocks:
            return
        logger.info(
            "Silence gate: streamed %.0f%% of the last %.0fs (threshold %.0f, configured %d)",
            100.0 * self._blocks_sent / self._blocks_seen, self.DUTY_LOG_SEC,
            threshold, self.silence_rms_threshold
        )
        self._blocks_seen = 0
        self._blocks_sent = 0

    def audio_callback(self, indata, frames, time, status):
        """Callback function called by sounddevice for each block of input audio.

        Drops sustained silence so it is not streamed (and billed) to Gemini.
        """
        if status:
            logger.warning("Audio status warning: %s", status)
        rms = np.sqrt(np.mean(indata.astype(np.float64) ** 2))
        self._rms_window.append(rms)
        threshold = self._gate_threshold()
        self._log_duty_cycle(threshold)
        if rms < threshold:
            self._silent_block_count += 1
            if self._silent_block_count > self._hangover_blocks:
                return
        else:
            self._silent_block_count = 0
        self._blocks_sent += 1
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
