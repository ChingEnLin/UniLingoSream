# Subtitle Accumulation and Auto-Clear Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modify the transcription receiver pipeline to accumulate streamed text chunks into a full sentence per turn, and auto-clear the subtitle overlay after a configurable duration of silence.

**Architecture:** We will maintain turn-state variables in `TranscriberTranslator` to accumulate `output_transcription.text` chunks until `turn_complete` is received. An async polling loop task (`clear_subtitle_timeout_loop`) will run concurrently to check for silence and clear the overlay when the timeout threshold is exceeded.

**Tech Stack:** Python 3.8+, `google-genai` SDK, `asyncio`.

---

### Task 1: Configuration Schema Updates

**Files:**
- Modify: `config.json`
- Modify: `module/transcriber.py:10-50`

- [ ] **Step 1: Update config.json**
  Add the `subtitle_timeout_seconds` parameter under `api`:
  ```json
  {
    "api": {
      "model": "gemini-3.5-live-translate-preview",
      "source_language": "ja-JP",
      "target_language": "zh-TW",
      "subtitle_timeout_seconds": 4.0
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

- [ ] **Step 2: Update default fallback config in module/transcriber.py**
  Ensure that `TranscriberTranslator.__init__` handles the fallback:
  ```python
  self.timeout_seconds = self.api_config.get("subtitle_timeout_seconds", 4.0)
  ```

- [ ] **Step 3: Commit/Verify config changes**
  Run: `pytest tests/test_transcriber.py`
  Expected: All existing tests pass.

---

### Task 2: Implement Accumulation & Timeout Loops

**Files:**
- Modify: `module/transcriber.py`

- [ ] **Step 1: Add state variables to TranscriberTranslator.__init__**
  Initialize state properties in `__init__`:
  ```python
  self.current_turn_translation = ""
  self.is_new_turn = True
  self.last_activity_time = 0.0
  self.timeout_seconds = self.api_config.get("subtitle_timeout_seconds", 4.0)
  ```

- [ ] **Step 2: Update receive_translation_loop**
  Accumulate incoming text chunks and detect turn boundaries:
  ```python
      async def receive_translation_loop(self):
          """ Listens for incoming translated text from the WebSocket """
          try:
              async for response in self.session.receive():
                  if response.server_content:
                      content = response.server_content
                      
                      # 1. Handle incoming text transcription chunks
                      if content.output_transcription:
                          text = content.output_transcription.text
                          if text:
                              if self.is_new_turn:
                                  self.current_turn_translation = ""
                                  self.is_new_turn = False
                              
                              self.current_turn_translation += text
                              self.latest_translation = self.current_turn_translation.strip()
                              self.last_activity_time = asyncio.get_event_loop().time()
                              logger.info("Translation: %s", self.latest_translation)
                              
                      # 2. Check if the turn is complete
                      if content.turn_complete:
                          logger.info("Turn complete.")
                          self.is_new_turn = True
                          self.last_activity_time = asyncio.get_event_loop().time()
          except asyncio.CancelledError:
              pass
          except Exception as e:
              logger.error("Error receiving from Live session: %s", e)
              raise e
  ```

- [ ] **Step 3: Add clear_subtitle_timeout_loop**
  Implement the timeout clearing loop:
  ```python
      async def clear_subtitle_timeout_loop(self):
          """ Clears the subtitle overlay if no new translation activity occurs after a turn is complete """
          try:
              while True:
                  await asyncio.sleep(0.5)
                  if self.is_new_turn and self.latest_translation and self.last_activity_time:
                      elapsed = asyncio.get_event_loop().time() - self.last_activity_time
                      if elapsed > self.timeout_seconds:
                          logger.info("Subtitle timeout reached. Clearing subtitle overlay.")
                          self.latest_translation = ""
          except asyncio.CancelledError:
              pass
  ```

- [ ] **Step 4: Execute clear task in connect_and_run**
  Update `connect_and_run` to gather `clear_task` alongside sending/receiving:
  ```python
                      # Start concurrent send, receive, and clear tasks
                      send_task = asyncio.create_task(self.send_audio_loop(audio_queue))
                      receive_task = asyncio.create_task(self.receive_translation_loop())
                      clear_task = asyncio.create_task(self.clear_subtitle_timeout_loop())
                      
                      # Wait for either task to fail/complete
                      done, pending = await asyncio.wait(
                          [send_task, receive_task, clear_task],
                          return_when=asyncio.FIRST_EXCEPTION
                      )
                      
                      # Cancel the other pending tasks
                      reset_task.cancel()
                      for task in pending:
                          task.cancel()
  ```

---

### Task 3: Update Transcriber Unit Tests

**Files:**
- Modify: `tests/test_transcriber.py`

- [ ] **Step 1: Write tests for text accumulation**
  Add unit tests in `tests/test_transcriber.py` to verify that successive text updates append correctly, and that a `turn_complete` signal followed by another chunk resets the buffer.

- [ ] **Step 2: Write tests for timeout clearing**
  Add unit tests checking that the `clear_subtitle_timeout_loop` successfully resets the text after the configured seconds of inactivity.

- [ ] **Step 3: Run the test suite**
  Run: `pytest tests/test_transcriber.py -v`
  Expected: All tests pass.
