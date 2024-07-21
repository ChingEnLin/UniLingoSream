# audio_capturer.py

# from scipy.io.wavfile import write
import queue
import threading
import sounddevice as sd

class AudioCapturer:
    def __init__(self, transcriber_translator, sample_rate=16000, channels=1, block_duration=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_duration = block_duration
        self.block_size = int(sample_rate * block_duration)
        self.q = queue.Queue()
        self.transcriber_translator = transcriber_translator
        self.transcribed_text = ""
        self.stream = sd.InputStream(callback=self.audio_callback, channels=self.channels, samplerate=self.sample_rate, blocksize=self.block_size)

    def audio_callback(self, indata, frames, time, status):
        if status:
            print(status)
        self.q.put(indata.copy())
        # print(f"Audio callback - frames: {frames}, time: {time}, status: {status}, indata: {indata.shape}")

    def start_stream(self):
        self.stream.start()
        threading.Thread(target=self.transcribe_audio_from_stream).start()

    def transcribe_audio_from_stream(self):
        while True:
            audio_data = self.q.get()
            # output audio data to a WAV file
            # write("output.wav", self.sample_rate, audio_data)
            audio_bytes = audio_data.tobytes()
            self.transcribed_text = self.transcriber_translator.transcribe_and_translate(audio_bytes)

    def get_transcription(self):
        return self.transcribed_text
