# Gemini Live Translate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the UniLingoStream application to use the Gemini Live API (`gemini-3.5-live-translate-preview`) for real-time translation of spoken Japanese system audio to Traditional Chinese text subtitles.

**Architecture:** We will set up a persistent, async WebSocket connection using the `google-genai` SDK. Raw PCM audio chunks (16kHz, 16-bit mono) will be captured from the system's loopback audio device and queued asynchronously to the Gemini Live session. The translation transcription will be polled by a customized, transparent, borderless Tkinter window.

**Tech Stack:** Python 3.8+, `google-genai` SDK, `asyncio`, `sounddevice`, `numpy`, `python-dotenv`, `Tkinter`.

---

### Task 1: Dependencies and Configuration

**Files:**
- Create: `config.json`
- Create: `.env.example`
- Modify: `requirements.txt`

- [ ] **Step 1: Write the config file**
  Create the default `config.json` in the project root:
  ```json
  {
    "api": {
      "model": "gemini-3.5-live-translate-preview",
      "source_language": "ja-JP",
      "target_language": "zh-TW"
    },
    "audio": {
      "device_name": "BlackHole 2ch",
      "sample_rate": 16000,
      "channels": 1
    },
    "ui": {
      "font_family": "Helvetica",
      "font_size": 24,
      "text_color": "#FFFFFF",
      "bg_color": "#000000",
      "bg_opacity": 0.6,
      "window_height": 90,
      "window_width_percent": 80,
      "bottom_margin": 100,
      "always_on_top": true,
      "draggable": true
    }
  }
  ```

- [ ] **Step 2: Create the example environment file**
  Create `.env.example` to document the environment key:
  ```bash
  GEMINI_API_KEY=your_google_ai_studio_api_key_here
  ```

- [ ] **Step 3: Modify requirements.txt**
  Update the requirements to use the new standard SDK and dotenv library:
  ```text
  google-genai
  python-dotenv
  numpy
  scipy
  sounddevice
  ```

- [ ] **Step 4: Verify installation**
  Run the environment setup or manual installation:
  Run: `pip install -r requirements.txt`
  Expected: Installation finishes successfully.

---

### Task 2: Advanced Transparent & Draggable UI (Tkinter)

**Files:**
- Modify: `module/display.py`

- [ ] **Step 1: Re-implement DisplayTranslation**
  Update `module/display.py` to support borderless, transparent, draggable overlays:
  ```python
  import tkinter as tk
  import json
  import os

  class DisplayTranslation:
      def __init__(self, config_path="config.json"):
          # Load config
          with open(config_path, "r", encoding="utf-8") as f:
              self.config = json.load(f)["ui"]
          
          self.root = tk.Tk()
          self.root.title("UniLingoStream Subtitles")
          
          # Borderless overlay
          self.root.overrideredirect(True)
          self.root.attributes("-alpha", self.config["bg_opacity"])
          self.root.wm_attributes("-topmost", self.config["always_on_top"])
          self.root.configure(bg=self.config["bg_color"])
          
          # Sizing and coordinates
          screen_width = self.root.winfo_screenwidth()
          screen_height = self.root.winfo_screenheight()
          
          width = int(screen_width * self.config["window_width_percent"] / 100)
          height = self.config["window_height"]
          x = (screen_width - width) // 2
          y = screen_height - height - self.config["bottom_margin"]
          
          self.root.geometry(f"{width}x{height}+{x}+{y}")
          
          # Subtitle Text Label
          self.label = tk.Label(
              self.root,
              text="Waiting for translation...",
              font=(self.config["font_family"], self.config["font_size"]),
              fg=self.config["text_color"],
              bg=self.config["bg_color"],
              wraplength=width - 40,
              justify="center"
          )
          self.label.pack(expand=True, fill="both", pady=10, padx=20)
          
          # Draggability binding
          if self.config["draggable"]:
              self.root.bind("<Button-1>", self.start_drag)
              self.root.bind("<B1-Motion>", self.drag)
          
          self._drag_data = {"x": 0, "y": 0}

      def start_drag(self, event):
          self._drag_data["x"] = event.x
          self._drag_data["y"] = event.y

      def drag(self, event):
          x = self.root.winfo_x() - self._drag_data["x"] + event.x
          y = self.root.winfo_y() - self._drag_data["y"] + event.y
          self.root.geometry(f"+{x}+{y}")

      def update_label(self, text):
          self.label.config(text=text)

      def start_gui(self):
          self.root.mainloop()
  ```

- [ ] **Step 2: Run verification test**
  Add a simple main execution inside `module/display.py` for direct manual testing. Run the script:
  Run: `python module/display.py`
  Expected: A borderless, semi-transparent black rectangle floats on screen displaying "Waiting for translation..." and can be dragged around by clicking and dragging. Remove the main execution code block after verification.

---

### Task 3: Implement Gemini WebSocket Client

**Files:**
- Modify: `module/transcriber.py`

- [ ] **Step 1: Rewrite transcriber.py**
  Replace the GCP Speech/Translate clients with the `google-genai` async Live client:
  ```python
  import asyncio
  import logging
  import json
  from google import genai
  from google.genai import types

  logger = logging.getLogger('root')

  class TranscriberTranslator:
      def __init__(self, config_path="config.json"):
          with open(config_path, "r", encoding="utf-8") as f:
              self.full_config = json.load(f)
          self.api_config = self.full_config["api"]
          self.audio_config = self.full_config["audio"]
          
          self.client = genai.Client()
          self.model_id = self.api_config["model"]
          self.latest_translation = ""
          
          self.session = None

      def get_connect_config(self):
          return types.LiveConnectConfig(
              response_modalities=[types.Modality.AUDIO],
              translation_config=types.TranslationConfig(
                  target_language_code=self.api_config["target_language"]
              ),
              output_audio_transcription=types.AudioTranscriptionConfig()
          )

      async def send_audio_loop(self, audio_queue: asyncio.Queue):
          """ Pulls audio chunks from the queue and streams to Gemini Live API """
          try:
              while True:
                  chunk = await audio_queue.get()
                  if self.session:
                      await self.session.send_realtime_input(
                          audio=types.Blob(
                              data=chunk,
                              mime_type=f"audio/pcm;rate={self.audio_config['sample_rate']}"
                          )
                      )
                  audio_queue.task_done()
          except asyncio.CancelledError:
              pass

      async def receive_translation_loop(self):
          """ Listens for incoming translated text from the WebSocket """
          try:
              async for response in self.session.receive():
                  if response.server_content:
                      content = response.server_content
                      if content.output_transcription:
                          text = content.output_transcription.text
                          if text.strip():
                              self.latest_translation = text.strip()
                              logger.info("Translation: %s", self.latest_translation)
          except asyncio.CancelledError:
              pass
          except Exception as e:
              logger.error("Error receiving from Live session: %s", e)

      async def connect_and_run(self, audio_queue: asyncio.Queue):
          """ Establishes connection and handles reconnect loops """
          connect_config = self.get_connect_config()
          while True:
              try:
                  logger.info("Connecting to Gemini Live API...")
                  async with self.client.aio.live.connect(
                      model=self.model_id, 
                      config=connect_config
                  ) as session:
                      self.session = session
                      logger.info("Connected to Gemini Live successfully.")
                      
                      # Start concurrent send and receive tasks
                      send_task = asyncio.create_task(self.send_audio_loop(audio_queue))
                      receive_task = asyncio.create_task(self.receive_translation_loop())
                      
                      await asyncio.gather(send_task, receive_task)
              except Exception as e:
                  logger.error("Session disconnect or connection error: %s. Reconnecting in 3s...", e)
                  self.latest_translation = "Reconnecting..."
                  await asyncio.sleep(3)

      def get_transcription(self):
          return self.latest_translation
  ```

---

### Task 4: Connect AudioCapturer Callback to Async Queue

**Files:**
- Modify: `module/audio_capturer.py`

- [ ] **Step 1: Simplify audio_capturer.py for raw streaming**
  Since Gemini handles the VAD internally and expects continuous streaming input, we stream chunks directly:
  ```python
  import queue
  import logging
  import numpy as np
  import sounddevice as sd
  import json
  import asyncio

  logger = logging.getLogger('root')

  class AudioCapturer:
      def __init__(self, loop, audio_queue: asyncio.Queue, config_path="config.json"):
          with open(config_path, "r", encoding="utf-8") as f:
              config = json.load(f)["audio"]
              
          self.loop = loop
          self.audio_queue = audio_queue
          self.sample_rate = config["sample_rate"]
          self.channels = config["channels"]
          
          # Let's stream in ~100ms chunks (1600 samples @ 16kHz)
          self.blocksize = int(self.sample_rate * 0.1)
          
          # Find device index by name
          self.device_index = self._find_device_index(config["device_name"])
          
          self.stream = sd.InputStream(
              callback=self.audio_callback,
              channels=self.channels,
              samplerate=self.sample_rate,
              blocksize=self.blocksize,
              device=self.device_index,
              dtype='int16' # Raw 16-bit PCM expected by Gemini
          )

      def _find_device_index(self, target_name):
          devices = sd.query_devices()
          for idx, dev in enumerate(devices):
              if target_name.lower() in dev["name"].lower():
                  logger.info("Found target audio device %s at index %d", dev["name"], idx)
                  return idx
          logger.warning("Target device '%s' not found. Using system default input.", target_name)
          return None

      def audio_callback(self, indata, frames, time, status):
          if status:
              logger.warning("Audio status warning: %s", status)
          # Convert captured numpy array to raw bytes
          raw_bytes = indata.tobytes()
          # Thread-safely push raw bytes to the asyncio queue
          self.loop.call_soon_threadsafe(self.audio_queue.put_nowait, raw_bytes)

      def start_stream(self):
          self.stream.start()
          logger.info("Audio stream started.")

      def stop_stream(self):
          self.stream.stop()
          logger.info("Audio stream stopped.")
  ```

---

### Task 5: Main Integration

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Implement main loop integration**
  Re-wire `main.py` to run the asyncio event loop in a background thread while Tkinter runs on the main thread:
  ```python
  import os
  import asyncio
  import threading
  import logging
  from dotenv import load_dotenv

  from module.audio_capturer import AudioCapturer
  from module.transcriber import TranscriberTranslator
  from module.display import DisplayTranslation
  from module.utility import log

  logger = log.setup_custom_logger('root')

  # Load env variables (GEMINI_API_KEY)
  load_dotenv()

  def run_async_loop(loop, queue, transcriber, capturer):
      asyncio.set_event_loop(loop)
      
      # Start the sounddevice audio input capture stream
      capturer.start_stream()
      
      # Run the transcriber WebSocket loop
      loop.run_until_complete(transcriber.connect_and_run(queue))

  def poll_transcription(display, transcriber):
      text = transcriber.get_transcription()
      if text:
          display.update_label(text)
      # Poll again in 50ms
      display.root.after(50, poll_transcription, display, transcriber)

  if __name__ == "__main__":
      if not os.getenv("GEMINI_API_KEY"):
          logger.error("GEMINI_API_KEY not found in env variables or .env file! Please set it.")
          exit(1)
          
      # Setup asyncio queue and loop
      async_loop = asyncio.new_event_loop()
      audio_queue = asyncio.Queue()
      
      # Initialize modules
      transcriber_translator = TranscriberTranslator()
      audio_capturer = AudioCapturer(async_loop, audio_queue)
      display_translation = DisplayTranslation()

      # Start background thread for asyncio loop
      t = threading.Thread(
          target=run_async_loop, 
          args=(async_loop, audio_queue, transcriber_translator, audio_capturer),
          daemon=True
      )
      t.start()

      # Start polling for translations in Tkinter
      display_translation.root.after(50, poll_transcription, display_translation, transcriber_translator)

      # Start Tkinter GUI loop
      logger.info("Starting subtitle display overlay...")
      display_translation.start_gui()
  ```
