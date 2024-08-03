""" Test cases for the AudioProcessor class """
import unittest
import numpy as np
from module.audio_processer import AudioProcessor

class TestAudioProcesser(unittest.TestCase):
    """ Test cases for the AudioProcesser class """

    def setUp(self):
        # Create an instance of AudioProcessor
        self.audio_processer = AudioProcessor()

    def test_detect_speech(self):
        """ Test detecting speech in audio data """
        audio_data = np.array([0.1, 0.2, 0.3])
        expected_result = True
        self.audio_processer.energy_threshold = 0.2
        result = self.audio_processer.detect_speech(audio_data)
        self.assertEqual(result, expected_result)

        audio_data = np.array([0.01, 0.02, 0.03])
        expected_result = False
        self.audio_processer.energy_threshold = 0.1
        result = self.audio_processer.detect_speech(audio_data)
        self.assertEqual(result, expected_result)

if __name__ == '__main__':
    unittest.main()