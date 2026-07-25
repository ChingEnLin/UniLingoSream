""" Test cases for the AudioCapturer class """
import unittest
from unittest.mock import MagicMock, patch, mock_open
import numpy as np
import asyncio
from module.audio_capturer import AudioCapturer


class TestAudioCapturer(unittest.TestCase):
    """ Test cases for the AudioCapturer class """

    def setUp(self):
        self.loop = MagicMock()
        self.audio_queue = MagicMock()

        self.mock_config = '{"audio": {"device_name": "BlackHole 2ch", "sample_rate": 16000, "channels": 1}}'

        # Patch sd.query_devices and sd.InputStream to avoid actual hardware queries
        self.patcher_query = patch('sounddevice.query_devices')
        self.mock_query = self.patcher_query.start()
        self.mock_query.return_value = [
            {'name': 'Built-in Microphone', 'index': 0, 'max_input_channels': 1},
            {'name': 'BlackHole 2ch', 'index': 1, 'max_input_channels': 2}
        ]

        self.patcher_stream = patch('sounddevice.InputStream')
        self.mock_stream = self.patcher_stream.start()

        with patch('builtins.open', mock_open(read_data=self.mock_config)):
            self.audio_capturer = AudioCapturer(self.loop, self.audio_queue)

    def tearDown(self):
        self.patcher_query.stop()
        self.patcher_stream.stop()

    def test_init(self):
        """ Test initialization and device selection """
        self.assertEqual(self.audio_capturer.sample_rate, 16000)
        self.assertEqual(self.audio_capturer.channels, 1)
        self.assertEqual(self.audio_capturer.device_index, 1)
        self.mock_stream.assert_called_once()

    def test_init_direct_config(self):
        """ Test initialization when passing a config dictionary directly """
        direct_config = {"device_name": "Built-in Microphone", "sample_rate": 8000, "channels": 2}
        with patch('builtins.open') as mock_file:
            capturer = AudioCapturer(self.loop, self.audio_queue, config=direct_config)
            mock_file.assert_not_called()
            self.assertEqual(capturer.sample_rate, 8000)
            self.assertEqual(capturer.channels, 2)
            self.assertEqual(capturer.device_index, 0)

    def test_init_missing_config_file_fallback(self):
        """ Test fallback behavior when the config file is missing """
        with patch('builtins.open', side_effect=FileNotFoundError):
            with patch('module.utility.config.logger.info') as mock_info:
                capturer = AudioCapturer(self.loop, self.audio_queue, config_path="nonexistent.json")
                mock_info.assert_called()
                # Check default config is applied: sample_rate=16000, channels=1
                self.assertEqual(capturer.sample_rate, 16000)
                self.assertEqual(capturer.channels, 1)
                self.assertEqual(capturer.device_index, 1)  # BlackHole 2ch index is 1

    def test_init_corrupt_config_file_fallback(self):
        """ Test fallback behavior when the config file is corrupt json """
        corrupt_config = '{"audio": {corrupt_json: true}}'
        with patch('builtins.open', mock_open(read_data=corrupt_config)):
            with patch('module.utility.config.logger.warning') as mock_warn:
                capturer = AudioCapturer(self.loop, self.audio_queue)
                mock_warn.assert_called()
                self.assertEqual(capturer.sample_rate, 16000)
                self.assertEqual(capturer.channels, 1)

    def test_device_name_attribute(self):
        """ The configured device name is exposed for warning messages """
        self.assertEqual(self.audio_capturer.device_name, "BlackHole 2ch")

    def test_find_device_index_fallback(self):
        """ Test fallback when device is not found """
        self.mock_query.return_value = [
            {'name': 'Built-in Microphone', 'index': 0, 'max_input_channels': 1}
        ]
        with patch('builtins.open', mock_open(read_data=self.mock_config)):
            capturer = AudioCapturer(self.loop, self.audio_queue)
            self.assertIsNone(capturer.device_index)

    def test_find_device_index_skips_output_only_device(self):
        """ An output-only name match must be skipped: InputStream would reject the index """
        self.mock_query.return_value = [
            {'name': 'BlackHole 2ch (multi-out)', 'index': 0, 'max_input_channels': 0},
            {'name': 'BlackHole 2ch', 'index': 1, 'max_input_channels': 2},
        ]
        with patch('builtins.open', mock_open(read_data=self.mock_config)):
            capturer = AudioCapturer(self.loop, self.audio_queue)
        self.assertEqual(capturer.device_index, 1)

    def test_stream_open_failure_is_reported_not_raised(self):
        """ A failing InputStream must surface as .error, not a traceback before the UI exists """
        self.patcher_stream.stop()
        try:
            with patch('sounddevice.InputStream', side_effect=OSError("Invalid number of channels")):
                with patch('builtins.open', mock_open(read_data=self.mock_config)):
                    capturer = AudioCapturer(self.loop, self.audio_queue)
            self.assertIsNone(capturer.stream)
            self.assertIn("Invalid number of channels", capturer.error)
            capturer.start_stream()  # must not raise
            capturer.stop_stream()
            capturer.close_stream()
        finally:
            self.mock_stream = self.patcher_stream.start()

    def test_find_device_index_exception(self):
        """ Test fallback on Exception during querying """
        self.mock_query.side_effect = Exception("Sounddevice error")
        with patch('builtins.open', mock_open(read_data=self.mock_config)):
            capturer = AudioCapturer(self.loop, self.audio_queue)
            self.assertIsNone(capturer.device_index)

    def test_audio_callback(self):
        """ Test audio callback thread-safe queue pushing """
        # Loud block clears the silence gate so it is streamed
        indata = np.full((1600, 1), 1000, dtype=np.int16)
        frames = 1600
        time = MagicMock()
        status = None

        self.audio_capturer.audio_callback(indata, frames, time, status)

        # Check that loop.call_soon_threadsafe is called with self.audio_capturer._safe_put and raw bytes
        self.loop.call_soon_threadsafe.assert_called_once_with(
            self.audio_capturer._safe_put,
            indata.tobytes()
        )

    def test_callback_drops_silence_before_speech(self):
        """ Silence before any speech must not be streamed """
        silent = np.zeros((1600, 1), dtype=np.int16)
        self.audio_capturer.audio_callback(silent, 1600, None, None)
        self.loop.call_soon_threadsafe.assert_not_called()

    def test_callback_streams_speech_and_hangover(self):
        """ Speech streams; trailing silence streams for the hangover window then stops """
        loud = np.full((1600, 1), 1000, dtype=np.int16)
        silent = np.zeros((1600, 1), dtype=np.int16)

        self.audio_capturer.audio_callback(loud, 1600, None, None)
        self.assertEqual(self.loop.call_soon_threadsafe.call_count, 1)

        # Silence within the hangover window still streams (protects word tails)
        self.audio_capturer.audio_callback(silent, 1600, None, None)
        self.assertEqual(self.loop.call_soon_threadsafe.call_count, 2)

        # Exhaust the hangover; further silence is dropped
        for _ in range(self.audio_capturer._hangover_blocks):
            self.audio_capturer.audio_callback(silent, 1600, None, None)
        count_after_hangover = self.loop.call_soon_threadsafe.call_count
        self.audio_capturer.audio_callback(silent, 1600, None, None)
        self.assertEqual(self.loop.call_soon_threadsafe.call_count, count_after_hangover)

    def test_safe_put_success(self):
        """ Test _safe_put successfully puts data in the queue """
        raw_bytes = b'\x01\x02'
        self.audio_capturer._safe_put(raw_bytes)
        self.audio_queue.put_nowait.assert_called_once_with(raw_bytes)

    def test_safe_put_queue_full(self):
        """ Test _safe_put handles asyncio.QueueFull exception gracefully """
        raw_bytes = b'\x01\x02'
        self.audio_queue.put_nowait.side_effect = asyncio.QueueFull()

        with patch('module.audio_capturer.logger.warning') as mock_warn:
            self.audio_capturer._safe_put(raw_bytes)
            mock_warn.assert_called_with("Audio queue is full, dropping frame.")

    def test_audio_callback_with_status(self):
        """ Test audio callback handles status warning """
        indata = np.array([[10]], dtype=np.int16)
        frames = 1
        time = MagicMock()
        status = "input overflow"

        with patch('module.audio_capturer.logger.warning') as mock_warn:
            self.audio_capturer.audio_callback(indata, frames, time, status)
            mock_warn.assert_called_with("Audio status warning: %s", status)

    def test_start_stop_stream(self):
        """ Test start and stop stream calls """
        stream = self.audio_capturer.stream
        self.audio_capturer.start_stream()
        stream.start.assert_called_once()

        self.audio_capturer.stop_stream()
        stream.stop.assert_called_once()

        self.audio_capturer.close_stream()
        stream.close.assert_called_once()
        self.assertIsNone(self.audio_capturer.stream)
        self.audio_capturer.close_stream()  # idempotent
        stream.close.assert_called_once()

    def test_device_name_kwarg_overrides_config(self):
        """ An explicit device_name beats the config file value """
        with patch('builtins.open', mock_open(read_data=self.mock_config)):
            capturer = AudioCapturer(self.loop, self.audio_queue, device_name="Built-in Microphone")
        self.assertEqual(capturer.device_name, "Built-in Microphone")
        self.assertEqual(capturer.device_index, 0)


if __name__ == '__main__':
    unittest.main()
