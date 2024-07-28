""" Module for processing audio data. """
import logging
import numpy as np

logger = logging.getLogger('root')

class AudioProcessor: # pylint: disable=too-few-public-methods
    """ Class for processing audio data. """
    def __init__(self, sample_rate=16000, energy_threshold=0.1):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold

    def detect_speech(self, audio_data):
        """
        Detects if there is speech in the given audio data.

        Parameters:
        - audio_data: np.ndarray, audio data segment to analyze

        Returns:
        - bool: True if speech is detected, otherwise False
        """
        # Compute the RMS energy of the audio segment
        rms_energy = np.sqrt(np.mean(audio_data**2))
        logger.info("RMS energy: %s", rms_energy)

        # Compare the energy to the threshold
        return rms_energy > self.energy_threshold
