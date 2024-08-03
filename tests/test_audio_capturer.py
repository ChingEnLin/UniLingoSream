""" Test cases for the AudioCapturer class """
import unittest
from unittest.mock import MagicMock
from module.audio_capturer import AudioCapturer

class TestAudioCapturer(unittest.TestCase):
    """ Test cases for the AudioCapturer class """

    def setUp(self):
        # Create a mock transcriber_translator object
        self.transcriber_translator = MagicMock()

        # Create an instance of AudioCapturer
        self.audio_capturer = AudioCapturer(self.transcriber_translator)

    def test_convert_to_wav_bytes(self):
        """ Test converting audio data to WAV format """
        audio_data = [0.1, 0.2, 0.3]
        expected_result = b'WAV_BYTES'
        self.audio_capturer._convert_to_wav_bytes = MagicMock(return_value=expected_result)
        result = self.audio_capturer._convert_to_wav_bytes(audio_data)
        self.assertEqual(result, expected_result)

    def test_combine_texts(self):
        """ Test combining existing text and new text """
        existing_text = "Hello"
        new_text = "World"
        expected_result = "Hello World"
        result = self.audio_capturer._combine_texts(existing_text, new_text)
        self.assertEqual(result, expected_result)

    def test_audio_callback(self):
        """ Test audio callback function """
        indata = [[0.1], [0.2], [0.3]]
        frames = 3
        time = 1.0
        status = None
        self.audio_capturer.audio_processor.detect_speech = MagicMock(return_value=True)
        self.audio_capturer.q.put = MagicMock()
        self.audio_capturer.audio_callback(indata, frames, time, status)
        self.assertEqual(len(self.audio_capturer.audio_buffer), 0)

    def test_get_transcription(self):
        """ Test getting the transcribed text """
        expected_result = "Transcribed Text"
        self.audio_capturer.transcribed_text = expected_result
        result = self.audio_capturer.get_transcription()
        self.assertEqual(result, expected_result)

if __name__ == '__main__':
    unittest.main()
