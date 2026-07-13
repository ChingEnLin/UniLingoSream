# Temporal Pause Subtitles Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the piling-up subtitle issue by using time-based pause detection to split sentences and clear the display on silence, removing dependencies on the API's `turn_complete` signal.

**Architecture:** We will compare the timestamp of incoming chunks against the previous chunk's timestamp. If the gap exceeds a configurable `sentence_pause_seconds` (default: 1.5s), we clear the buffer and start a new sentence. Additionally, the `clear_subtitle_timeout_loop` will clear the display and reset the turn status after `subtitle_timeout_seconds` (default: 4.0s) of absolute silence.

**Tech Stack:** Python 3.8+, `asyncio`.

---

### Task 1: Configuration Schema Updates

**Files:**
- Modify: `config.json`
- Modify: `module/transcriber.py`

- [ ] **Step 1: Update config.json**
  Add the `sentence_pause_seconds` parameter under `api`:
  ```json
  {
    "api": {
      "model": "gemini-3.5-live-translate-preview",
      "source_language": "ja-JP",
      "target_language": "zh-TW",
      "subtitle_timeout_seconds": 4.0,
      "sentence_pause_seconds": 1.5
    },
    ...
  }
  ```

- [ ] **Step 2: Update default fallback configurations in transcriber.py**
  Handle the new pause threshold configuration and defaults in `TranscriberTranslator.__init__`:
  ```python
  # Default fallback configuration dict:
  "subtitle_timeout_seconds": 4.0,
  "sentence_pause_seconds": 1.5
  
  # Constructor kwargs / parsing:
  if "sentence_pause_seconds" in kwargs:
      self.api_config["sentence_pause_seconds"] = kwargs["sentence_pause_seconds"]
  
  self.pause_threshold = self.api_config.get("sentence_pause_seconds", 1.5)
  ```

---

### Task 2: Implement Temporal Pause Detection

**Files:**
- Modify: `module/transcriber.py`

- [ ] **Step 1: Re-implement receive_translation_loop**
  Use temporal gaps between chunks instead of `turn_complete` to mark sentence boundaries:
  ```python
      async def receive_translation_loop(self):
          """ Listens for incoming translated text from the WebSocket """
          try:
              async for response in self.session.receive():
                  if response.server_content:
                      content = response.server_content
                      
                      # Handle incoming text transcription chunks
                      if content.output_transcription:
                          text = content.output_transcription.text
                          if text:
                              current_time = asyncio.get_event_loop().time()
                              
                              # If there was a pause of more than sentence_pause_seconds, start a new turn
                              if self.last_activity_time > 0:
                                  pause_duration = current_time - self.last_activity_time
                                  if pause_duration > self.pause_threshold:
                                      self.is_new_turn = True
                              
                              if self.is_new_turn:
                                  self.current_turn_translation = ""
                                  self.is_new_turn = False
                              
                              self.current_turn_translation += text
                              self.latest_translation = self.current_turn_translation.strip()
                              self.last_activity_time = current_time
                              logger.info("Translation: %s", self.latest_translation)
          except asyncio.CancelledError:
              pass
          except Exception as e:
              logger.error("Error receiving from Live session: %s", e)
              raise e
  ```

- [ ] **Step 2: Re-implement clear_subtitle_timeout_loop**
  Remove the `self.is_new_turn` gating so it clears subtitles on absolute silence and flags the next chunk for a new turn:
  ```python
      async def clear_subtitle_timeout_loop(self):
          """ Clears the subtitle overlay if no new translation activity occurs after a timeout """
          try:
              while True:
                  await asyncio.sleep(0.5)
                  if self.latest_translation and self.last_activity_time:
                      elapsed = asyncio.get_event_loop().time() - self.last_activity_time
                      if elapsed > self.timeout_seconds:
                          logger.info("Subtitle timeout reached. Clearing subtitle overlay.")
                          self.latest_translation = ""
                          self.is_new_turn = True
          except asyncio.CancelledError:
              pass
  ```

---

### Task 3: Update and Verify Unit Tests

**Files:**
- Modify: `tests/test_transcriber.py`

- [ ] **Step 1: Rewrite unit tests**
  Update `test_receive_translation_loop` and the timeout loops in `tests/test_transcriber.py` to match the time-based pause splitting:
  - Mock `asyncio.get_event_loop().time()` or sleep between yields to simulate temporal gaps.
  - Verify that a gap of >1.5s resets the sentence buffer.
  - Verify that absolute silence of >4.0s clears the text.

- [ ] **Step 2: Run all unit tests**
  Run: `pytest -v`
  Expected: All 32 tests pass.
