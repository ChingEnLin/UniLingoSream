""" This module is responsible for capturing audio from the microphone and
transcribing it using the transcriber_translator module. """

import io
import queue
import threading
import logging
import numpy as np
from scipy.io.wavfile import write
import sounddevice as sd

logger = logging.getLogger('root')

class AudioCapturer: # pylint: disable=too-many-instance-attributes
    """ Captures audio from the microphone and transcribes it
    using the provided transcriber_translator. """
    def __init__(self, transcriber_translator, # pylint: disable=too-many-arguments
                 sample_rate=16000,
                 channels=1,
                 chunk_duration=1,
                 overlap_duration=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration = chunk_duration
        self.overlap_duration = overlap_duration
        self.chunk_size = int(sample_rate * chunk_duration)
        self.overlap_size = int(sample_rate * overlap_duration)
        self.audio_buffer = np.zeros((0, channels), dtype=np.float32)
        self.q = queue.Queue()
        self.transcriber_translator = transcriber_translator
        self.transcribed_text = ""
        self.stream = sd.InputStream(callback=self.audio_callback,
                                     channels=self.channels,
                                     samplerate=self.sample_rate,
                                     blocksize=self.chunk_size)

    def _convert_to_wav_bytes(self, audio_data):
        """ Converts audio data to WAV format. """
        bytes_wav = bytes()
        byte_io = io.BytesIO(bytes_wav)
        write(byte_io, self.sample_rate, audio_data)
        return byte_io.read()

    def _combine_texts(self, existing_text, new_text):
        if existing_text and existing_text[-1].isalnum() and new_text and new_text[0].isalnum():
            # If last char of existing and first char of new text are both alphanumeric, add a space
            return existing_text + " " + new_text
        # Return only new text if existing text exceeds 20 characters
        if len(existing_text) > 20:
            return new_text
        return existing_text + new_text

    def audio_callback(self, indata, frames, time, status):
        """ This callback function is called by the sounddevice stream
        whenever new audio data is available. """
        if status:
            logger.warning("Audio callback - frames: %s, time: %s, status: %s, indata: %s",
                    frames, time, status, indata.shape)
        self.audio_buffer = np.append(self.audio_buffer, indata, axis=0)

        if len(self.audio_buffer) >= self.chunk_size:
            audio_chunk = self.audio_buffer[:self.chunk_size]
            self.q.put(audio_chunk)
            self.audio_buffer = self.audio_buffer[self.chunk_size - self.overlap_size:]

    def start_stream(self):
        """ Starts the audio stream and a separate thread for transcribing the audio. """
        self.stream.start()
        threading.Thread(target=self.transcribe_audio_from_stream).start()

    def stop_stream(self):
        """ Stops the audio stream."""
        self.stream.stop()
        logging.info("Audio capture stream stopped.")

    def transcribe_audio_from_stream(self):
        """ Continuously transcribes audio data from the queue. """
        while True:
            audio_data = self.q.get()
            audio_bytes = self._convert_to_wav_bytes(audio_data)
            self.transcribed_text = self.transcriber_translator.transcribe_and_translate(
                audio_bytes)

    def get_transcription(self):
        """ Returns the transcribed text. """
        return self.transcribed_text
