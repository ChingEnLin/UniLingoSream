""" This module is responsible for capturing audio from the microphone and
transcribing it using the transcriber_translator module. """

import io
import queue
import threading
import logging
from scipy.io.wavfile import write
import sounddevice as sd

logger = logging.getLogger('root')

class AudioCapturer: # pylint: disable=too-many-instance-attributes
    """ Captures audio from the microphone and transcribes it
    using the provided transcriber_translator. """
    def __init__(self, transcriber_translator, sample_rate=16000, channels=1, block_duration=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_duration = block_duration
        self.block_size = int(sample_rate * block_duration)
        self.q = queue.Queue()
        self.transcriber_translator = transcriber_translator
        self.transcribed_text = ""
        self.stream = sd.InputStream(callback=self.audio_callback,
                                     channels=self.channels,
                                     samplerate=self.sample_rate,
                                     blocksize=self.block_size)

    def audio_callback(self, indata, frames, time, status):
        """ This callback function is called by the sounddevice stream
        whenever new audio data is available. """
        if status:
            logger.warning("Audio callback - frames: %s, time: %s, status: %s, indata: %s",
                    frames, time, status, indata.shape)
        self.q.put(indata.copy())

    def start_stream(self):
        """ Starts the audio stream and a separate thread for transcribing the audio. """
        self.stream.start()
        threading.Thread(target=self.transcribe_audio_from_stream).start()

    def transcribe_audio_from_stream(self):
        """ Continuously transcribes audio data from the queue. """
        while True:
            audio_data = self.q.get()
            audio_bytes = self._convert_to_wav_bytes(audio_data)
            self.transcribed_text = self.transcriber_translator.transcribe_and_translate(
                audio_bytes)

    def _convert_to_wav_bytes(self, audio_data):
        """ Converts audio data to WAV format. """
        bytes_wav = bytes()
        byte_io = io.BytesIO(bytes_wav)
        write(byte_io, self.sample_rate, audio_data)
        return byte_io.read()

    def get_transcription(self):
        """ Returns the transcribed text. """
        return self.transcribed_text
