# Improvement Spec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement docs/superpowers/specs/2026-07-13-improvement-spec.md — fix the three P0 bugs, cut Gemini cost (TEXT modality, VAD gate), and close the UX/entrypoint gaps.

**Architecture:** Real-time translation overlay. `main.py` wires three modules: `AudioCapturer` (sounddevice callback pushes 100 ms int16 PCM chunks into an asyncio queue), `TranscriberTranslator` (Gemini Live WebSocket via `google-genai`, reconnect loop, exposes `get_transcription()`), `DisplayTranslation` (borderless Tkinter subtitle bar, polled every 50 ms from the Tk event loop). All changes are edits to these four files plus tests, config, CI, and docs.

**Tech Stack:** Python 3.9-3.12, google-genai 2.11.0 (Gemini Live API), sounddevice, numpy, Tkinter, unittest (under pytest), flake8.

## Global Constraints

- Tests are `unittest`-style classes in `tests/`, run with `pytest`. Follow the existing mock patterns (patch `google.genai.Client`, `sounddevice.InputStream`, `module.display.tk.Label`, `builtins.open`).
- Lint gates (CI): `flake8 . --select=E9,F63,F7,F82` must be clean; keep lines <= 127 chars.
- Verified SDK facts (google-genai 2.11.0): `types.TranslationConfig` has ONLY `echo_target_language` and `target_language_code` (no source language field). `types.Modality.TEXT` exists. `LiveServerContent` has `model_turn`, `output_transcription`, `turn_complete` among its fields.
- `logging.getLogger('root')` aliases the real root logger (verified) — the existing handler setup reaches `__name__` loggers too.
- No emojis in markdown files or documentation.
- Work on the `dev` branch (CI runs on push/PR to `dev` only). Commit after every task.
- After each task, run the full suite: `pytest` — expect all tests passing before commit.

---

### Task 1: Fix subtitles never clearing (P0 bug 1)

`poll_transcription` only pushes truthy text to the label, so the timeout loop's `latest_translation = ""` never reaches the screen. Track the last rendered text and push every change, including "".

**Files:**
- Modify: `main.py:52-63` (`poll_transcription`)
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `poll_transcription(display, transcriber, last_rendered="")` — third positional arg threads the last rendered string through the Tk `after` reschedule chain. The startup call in `main.py` stays two-arg (default applies).

- [ ] **Step 1: Update the enshrined-bug test and add the two new tests**

In `tests/test_main.py`, replace `test_poll_transcription_with_text` and `test_poll_transcription_no_text` with:

```python
    def test_poll_transcription_with_text(self):
        """ Test poll_transcription updates label when transcription changed """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = "Hello"

        poll_transcription(mock_display, mock_transcriber)

        mock_display.update_label.assert_called_once_with("Hello")
        mock_display.root.after.assert_called_once_with(
            POLL_INTERVAL_MS, poll_transcription, mock_display, mock_transcriber, "Hello"
        )

    def test_poll_transcription_no_text(self):
        """ Test poll_transcription does not re-render when nothing changed """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = ""

        poll_transcription(mock_display, mock_transcriber)

        mock_display.update_label.assert_not_called()
        mock_display.root.after.assert_called_once_with(
            POLL_INTERVAL_MS, poll_transcription, mock_display, mock_transcriber, ""
        )

    def test_poll_transcription_clears_label(self):
        """ Timeout-cleared translation ("") must reach the screen """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = ""

        poll_transcription(mock_display, mock_transcriber, last_rendered="Hello")

        mock_display.update_label.assert_called_once_with("")

    def test_poll_transcription_skips_identical_text(self):
        """ Unchanged text must not be re-rendered every 50ms """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = "Hello"

        poll_transcription(mock_display, mock_transcriber, last_rendered="Hello")

        mock_display.update_label.assert_not_called()
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `pytest tests/test_main.py -v`
Expected: `test_poll_transcription_clears_label` FAILS (update_label not called), `test_poll_transcription_with_text` FAILS (after called without the third arg). The other two pass by accident.

- [ ] **Step 3: Implement**

In `main.py`, replace `poll_transcription`:

```python
def poll_transcription(display, transcriber, last_rendered=""):
    """Polls the transcriber buffer and updates the translation overlay.

    Args:
        display: The DisplayTranslation module instance.
        transcriber: The TranscriberTranslator module instance.
        last_rendered: The text currently shown on the overlay.
    """
    text = transcriber.get_transcription()
    if text != last_rendered:
        display.update_label(text)
    # Poll again in POLL_INTERVAL_MS
    display.root.after(POLL_INTERVAL_MS, poll_transcription, display, transcriber, text)
```

The startup call at `main.py:90` needs no change — the `last_rendered=""` default keeps the initial "Waiting for translation..." label until the first real update.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_main.py -v` then `pytest`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "fix: push cleared subtitles to the overlay (timeout clear never rendered)"
```

---

### Task 2: Bound the audio queue and drain stale audio on reconnect (P0 bug 2)

During reconnect backoff nothing consumes the unbounded queue; on reconnect minutes of stale audio get streamed to Gemini. Bound the queue (the capturer's `_safe_put` already drops on `QueueFull`) and drain it before each connect.

**Files:**
- Modify: `main.py:74` (queue construction), `module/transcriber.py:185-196` (`connect_and_run`)
- Test: `tests/test_transcriber.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `main.AUDIO_QUEUE_MAXSIZE = 50` module constant; `connect_and_run` drains `audio_queue` at the top of every reconnect iteration.

- [ ] **Step 1: Write the failing tests**

In `tests/test_transcriber.py`, add inside `TestTranscriberTranslator`:

```python
    async def test_connect_and_run_drains_stale_queue(self):
        """ Audio buffered while disconnected must be dropped, not streamed on reconnect """
        translator = TranscriberTranslator(config_path="dummy.json")
        queue = asyncio.Queue()
        for _ in range(3):
            queue.put_nowait(b'stale')

        # First connect attempt raises; patched sleep aborts the retry loop.
        translator.client.aio.live.connect = MagicMock(side_effect=RuntimeError("boom"))

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await translator.connect_and_run(queue)

        self.assertTrue(queue.empty())
```

In `tests/test_main.py`, inside `test_main_execution_success` after the existing assertions, add:

```python
        from main import AUDIO_QUEUE_MAXSIZE
        mock_queue_class.assert_called_once_with(maxsize=AUDIO_QUEUE_MAXSIZE)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_transcriber.py::TestTranscriberTranslator::test_connect_and_run_drains_stale_queue tests/test_main.py -v`
Expected: drain test FAILS (`queue.empty()` is False); main test FAILS (Queue called with no args).

- [ ] **Step 3: Implement**

In `main.py`, below `POLL_INTERVAL_MS`:

```python
# Bound the capture queue: ~5s of 100ms chunks. AudioCapturer drops frames when full.
AUDIO_QUEUE_MAXSIZE = 50
```

and change line 74 to:

```python
    audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
```

In `module/transcriber.py`, at the top of the `while True:` in `connect_and_run` (before the `try:`):

```python
        while True:
            # Drop audio buffered while disconnected; translating it would show stale subtitles
            while not audio_queue.empty():
                audio_queue.get_nowait()
                audio_queue.task_done()
            try:
```

- [ ] **Step 4: Run tests**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add main.py module/transcriber.py tests/test_transcriber.py tests/test_main.py
git commit -m "fix: bound audio queue and drain stale audio before reconnecting"
```

---

### Task 3: Warn on the overlay when falling back to the microphone (P0 bug 3)

When the configured device (BlackHole) is missing, the capturer silently uses the default input — the microphone. Surface that on the overlay at startup.

**Files:**
- Modify: `module/audio_capturer.py:33-39`, `main.py` (after module init, before thread start)
- Test: `tests/test_audio_capturer.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `AudioCapturer.device_name` (str, the configured target name) and the existing `AudioCapturer.device_index` (`None` means fallback). `main.py` checks `device_index is None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_audio_capturer.py`:

```python
    def test_device_name_attribute(self):
        """ The configured device name is exposed for warning messages """
        self.assertEqual(self.audio_capturer.device_name, "BlackHole 2ch")
```

In `tests/test_main.py` add a new test (same decorator stack as `test_main_execution_success`):

```python
    @patch('module.transcriber.TranscriberTranslator')
    @patch('module.audio_capturer.AudioCapturer')
    @patch('module.display.DisplayTranslation')
    @patch('threading.Thread')
    @patch('asyncio.new_event_loop')
    @patch('asyncio.Queue')
    @patch('os.getenv')
    def test_main_warns_on_device_fallback(
        self, mock_getenv, mock_queue_class, mock_new_loop,
        mock_thread_class, mock_display_class, mock_capturer_class, mock_transcriber_class
    ):
        """ Missing BlackHole must produce a visible overlay warning """
        mock_getenv.return_value = "fake-api-key"
        mock_new_loop.return_value = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_capturer_class.return_value.device_index = None
        mock_capturer_class.return_value.device_name = "BlackHole 2ch"

        import runpy
        runpy.run_path("main.py", run_name="__main__")

        warning = mock_display_class.return_value.update_label.call_args[0][0]
        self.assertIn("WARNING", warning)
        self.assertIn("BlackHole 2ch", warning)
```

Also in `test_main_execution_success`, add after the existing assertions (guards against warning on the happy path — the mocked `device_index` is a truthy MagicMock, not None):

```python
        mock_display_class.return_value.update_label.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_audio_capturer.py tests/test_main.py -v`
Expected: `test_device_name_attribute` FAILS (AttributeError), `test_main_warns_on_device_fallback` FAILS (update_label not called).

- [ ] **Step 3: Implement**

In `module/audio_capturer.py`, replace line 33:

```python
        self.device_name = config.get("device_name", DEFAULT_CONFIG["device_name"])
```

and line 39:

```python
        self.device_index = self._find_device_index(self.device_name)
```

In `main.py`, after the three module initializations (after line 79):

```python
    # Surface silent fallback: default input is the microphone, not system audio
    if audio_capturer.device_index is None:
        display_translation.update_label(
            f"WARNING: audio device '{audio_capturer.device_name}' not found - capturing default input (microphone)"
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add module/audio_capturer.py main.py tests/test_audio_capturer.py tests/test_main.py
git commit -m "fix: warn on overlay when configured audio device is missing"
```

---

### Task 4: Toolchain hygiene — CI matrix, README Python floor, dependency prune/pin (P0 bug 4 + spec item 15)

`google-genai` requires Python >= 3.9, so the CI 3.8 leg fails at install. `scipy` is imported by nothing (verified by grep). Pin `google-genai` (fast-moving SDK against a preview model).

**Files:**
- Modify: `.github/workflows/python-package.yml:20`, `README.md` (Prerequisites), `requirements.txt`

**Interfaces:** none (config only).

- [ ] **Step 1: Edit the CI matrix**

In `.github/workflows/python-package.yml` change:

```yaml
        python-version: ["3.9", "3.10", "3.11", "3.12"]
```

- [ ] **Step 2: Edit README prerequisites**

Change the line `- Python 3.8 to 3.10` to:

```markdown
- Python 3.9 to 3.12
```

- [ ] **Step 3: Rewrite requirements.txt**

```
google-genai==2.11.0
python-dotenv
numpy
sounddevice
```

(scipy removed — no module imports it; numpy stays, Task 6 uses it in the capturer.)

- [ ] **Step 4: Verify locally**

Run: `pip install -r requirements.txt && pytest && flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`
Expected: install succeeds, ALL tests pass, flake8 clean.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/python-package.yml README.md requirements.txt
git commit -m "chore: drop py3.8 (google-genai needs 3.9+), add 3.11/3.12, prune scipy, pin google-genai"
```

---

### Task 5: TEXT response modality — stop paying for discarded audio (P1 item 5)

The session requests `Modality.AUDIO` and reads only the transcription; the synthesized speech is billed at output rates and thrown away, and the transcription trails the audio synthesis (latency). Switch to `Modality.TEXT`, with a text extractor that also keeps the old `output_transcription` path working as a fallback.

**Files:**
- Modify: `module/transcriber.py` (`get_connect_config`, `receive_translation_loop`, new `_extract_text`)
- Test: `tests/test_transcriber.py`

**Interfaces:**
- Produces: `TranscriberTranslator._extract_text(content) -> str | None` (staticmethod) — returns joined text from `content.model_turn.parts` (TEXT modality) or `content.output_transcription.text` (AUDIO modality fallback), else `None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_transcriber.py`:

```python
    def test_get_connect_config_text_modality(self):
        """ Session must request TEXT output, not billed-and-discarded AUDIO """
        translator = TranscriberTranslator(config_path="dummy.json")
        config = translator.get_connect_config()
        self.assertEqual(config.response_modalities, [types.Modality.TEXT])

    def test_extract_text_from_model_turn(self):
        """ TEXT modality: text arrives in model_turn parts """
        content = MagicMock()
        part1 = MagicMock()
        part1.text = "Ni"
        part2 = MagicMock()
        part2.text = "Hao"
        content.model_turn.parts = [part1, part2]
        self.assertEqual(TranscriberTranslator._extract_text(content), "NiHao")

    def test_extract_text_falls_back_to_output_transcription(self):
        """ AUDIO modality fallback: text arrives via output_transcription """
        content = MagicMock()
        content.model_turn = None
        content.output_transcription.text = "hello"
        self.assertEqual(TranscriberTranslator._extract_text(content), "hello")

    def test_extract_text_none(self):
        """ No text in the message """
        content = MagicMock()
        content.model_turn = None
        content.output_transcription = None
        self.assertIsNone(TranscriberTranslator._extract_text(content))
```

- [ ] **Step 2: Update existing receive-loop test mocks**

The existing `test_receive_translation_loop`, `test_receive_translation_loop_temporal_pause`, and `test_receive_translation_loop_punctuation_split` build `MagicMock()` server_content objects whose `model_turn` attribute is a truthy MagicMock — the new extractor would take the wrong branch. Add to EVERY mocked `server_content` in those tests:

```python
        mock_response_N.server_content.model_turn = None
```

(one line per mock response that has non-None `server_content`).

Also update the old modality assertion: in `test_get_connect_config`, change

```python
        self.assertEqual(config.response_modalities, [types.Modality.AUDIO])
```

to

```python
        self.assertEqual(config.response_modalities, [types.Modality.TEXT])
```

(then delete the now-duplicate `test_get_connect_config_text_modality` OR keep only one of the two — keep `test_get_connect_config` with the TEXT assertion and do not add the duplicate from Step 1).

- [ ] **Step 3: Run tests to verify the new ones fail**

Run: `pytest tests/test_transcriber.py -v`
Expected: `_extract_text` tests FAIL (AttributeError: no `_extract_text`), modality assertion FAILS (AUDIO != TEXT).

- [ ] **Step 4: Implement**

In `module/transcriber.py`, replace `get_connect_config`:

```python
    def get_connect_config(self):
        """ Generates LiveConnectConfig for the Gemini session """
        # TEXT modality: we never play the synthesized audio, so don't pay output-audio rates for it
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.TEXT],
            translation_config=types.TranslationConfig(
                target_language_code=self.api_config.get("target_language", "zh-TW")
            )
        )
```

Add the extractor:

```python
    @staticmethod
    def _extract_text(content):
        """ Pulls translated text from a server message.

        TEXT modality delivers it via model_turn parts; AUDIO modality via output_transcription.
        """
        if content.model_turn and content.model_turn.parts:
            return "".join(part.text for part in content.model_turn.parts if part.text)
        if content.output_transcription:
            return content.output_transcription.text
        return None
```

In `receive_translation_loop`, replace the block

```python
                    # 1. Handle incoming text transcription chunks
                    if content.output_transcription:
                        text = content.output_transcription.text
                        if text:
```

with

```python
                    # 1. Handle incoming translated text chunks
                    text = self._extract_text(content)
                    if text:
```

and dedent the body under it by one level (it was nested two conditions deep, now one).

- [ ] **Step 5: Run tests**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 6: Manual verification (required before commit)**

Run: `python main.py` against a Japanese audio source for ~1 minute.

- If subtitles appear: check the `Session Accumulated` log lines — candidates (output) token counts should be far lower than an equivalent pre-change run (no audio tokens). Done.
- If the connection fails with an error mentioning `response_modalities` (the preview model may mandate AUDIO): revert only the modality — in `get_connect_config`, set `response_modalities=[types.Modality.AUDIO]` and re-add `output_audio_transcription=types.AudioTranscriptionConfig()` to the LiveConnectConfig, restore the AUDIO assertion in `test_get_connect_config`, and add a comment `# Preview model mandates AUDIO modality; transcription is the only usable output` — keep `_extract_text` either way.

- [ ] **Step 7: Commit**

```bash
git add module/transcriber.py tests/test_transcriber.py
git commit -m "feat: request TEXT modality; extract text from model_turn with transcription fallback"
```

(If Step 6 forced the revert, commit message: `refactor: extract translation text via _extract_text; preview model mandates AUDIO modality`.)

---

### Task 6: RMS silence gate in the capturer; delete the orphaned VAD module (P1 item 6)

Silence currently streams to Gemini 24/7 and is billed. Gate in `audio_callback`: drop blocks below an RMS threshold once silence has lasted past a hangover window (so word tails are not clipped). `module/audio_processer.py` is dead code (float-scaled, imported by nothing) — delete it.

**Files:**
- Modify: `module/audio_capturer.py`, `config.json` (audio section)
- Delete: `module/audio_processer.py`, `tests/test_audio_processer.py`
- Modify: `README.md` (Features bullet + Project Structure bullet)
- Test: `tests/test_audio_capturer.py`

**Interfaces:**
- Produces: `AudioCapturer._hangover_blocks` (int), `AudioCapturer._silent_block_count` (int, starts AT `_hangover_blocks` so nothing streams before first speech), config key `audio.silence_rms_threshold` (int16 RMS units, default 300).

- [ ] **Step 1: Write the failing tests**

In `tests/test_audio_capturer.py`:

```python
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
```

If an existing `audio_callback` test in this file feeds low-amplitude fixture data, change its fixture to `np.full((1600, 1), 1000, dtype=np.int16)` so it clears the gate.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_audio_capturer.py -v`
Expected: both new tests FAIL (callback currently streams everything unconditionally).

- [ ] **Step 3: Implement**

In `module/audio_capturer.py`:

Add import at the top:

```python
import numpy as np
```

Add to `DEFAULT_CONFIG` in `__init__`:

```python
            "silence_rms_threshold": 300
```

Add after the `self.blocksize` line, add a class constant next to `BLOCK_DURATION_SEC`:

```python
    HANGOVER_SEC = 1.0
```

and in `__init__` (after `self.blocksize = ...`):

```python
        # ponytail: RMS silence gate; threshold is a calibration knob in config.json (int16 units)
        self.silence_rms_threshold = config.get("silence_rms_threshold", DEFAULT_CONFIG["silence_rms_threshold"])
        self._hangover_blocks = int(self.HANGOVER_SEC / self.BLOCK_DURATION_SEC)
        self._silent_block_count = self._hangover_blocks  # start gated until first speech
```

Replace `audio_callback`:

```python
    def audio_callback(self, indata, frames, time, status):
        """Callback function called by sounddevice for each block of input audio.

        Drops sustained silence so it is not streamed (and billed) to Gemini.
        """
        if status:
            logger.warning("Audio status warning: %s", status)
        rms = np.sqrt(np.mean(indata.astype(np.float64) ** 2))
        if rms < self.silence_rms_threshold:
            self._silent_block_count += 1
            if self._silent_block_count > self._hangover_blocks:
                return
        else:
            self._silent_block_count = 0
        # Convert captured numpy array to raw bytes
        raw_bytes = indata.tobytes()
        # Thread-safely push raw bytes to the asyncio queue
        self.loop.call_soon_threadsafe(self._safe_put, raw_bytes)
```

Add to `config.json` `audio` section:

```json
    "silence_rms_threshold": 300
```

- [ ] **Step 4: Delete the dead module and its test**

```bash
git rm module/audio_processer.py tests/test_audio_processer.py
```

In `README.md`: delete the line `- module/audio_processer.py: Performs energy-based Voice Activity Detection (VAD) to filter silence before sending audio.` from Project Structure, and change the capturer bullet to mention the gate:

```markdown
- module/audio_capturer.py: Captures real-time audio from the configured input device, drops sustained silence (RMS gate), and routes speech chunks to an async queue.
```

- [ ] **Step 5: Run tests**

Run: `pytest && flake8 . --count --select=E9,F63,F7,F82`
Expected: ALL PASS, flake8 clean.

- [ ] **Step 6: Manual calibration check**

Run: `python main.py` with a quiet system and then speech/video. Verify in logs that no `send_realtime_input` traffic happens during silence (no token growth in `Session Accumulated` lines) and that speech is not clipped at sentence starts. If speech onset is clipped, lower `silence_rms_threshold` in `config.json` (try 150).

- [ ] **Step 7: Commit**

```bash
git add module/audio_capturer.py config.json tests/test_audio_capturer.py README.md
git commit -m "feat: RMS silence gate in capturer; remove orphaned VAD module"
```

---

### Task 7: Remove the dead source_language config key (P1 item 7)

Verified: `types.TranslationConfig` has no source-language field in google-genai 2.11.0, so the key cannot be wired. Delete it.

**Files:**
- Modify: `config.json` (api section), `module/transcriber.py` (default config + kwargs block)

**Interfaces:** none removed that anything consumes (grep confirms only definition sites).

- [ ] **Step 1: Remove the key**

- `config.json`: delete the line `"source_language": "ja-JP",`
- `module/transcriber.py`: delete `"source_language": "ja-JP",` from the fallback config dict, and delete the two-line kwargs block:

```python
        if "source_language" in kwargs:
            self.api_config["source_language"] = kwargs["source_language"]
```

- [ ] **Step 2: Verify nothing references it**

Run: `grep -rn source_language --include="*.py" --include="*.json" . | grep -v venv`
Expected: no output.

- [ ] **Step 3: Run tests and commit**

Run: `pytest`
Expected: ALL PASS

```bash
git add config.json module/transcriber.py
git commit -m "chore: remove dead source_language config (SDK TranslationConfig has no source field)"
```

---

### Task 8: Quit controls — Escape key and right-click menu (P2 item 8)

The borderless window has no close button; the only exits are Ctrl+C or force quit.

**Files:**
- Modify: `module/display.py` (`__init__`, new `show_menu`)
- Test: `tests/test_display.py`

**Interfaces:**
- Produces: `DisplayTranslation.show_menu(event)`, `DisplayTranslation.menu` (tk.Menu with a Quit entry).

- [ ] **Step 1: Update test setup and write the failing test**

In `tests/test_display.py` `setUp`, after the Label patch block, add a Menu patch (tk.Menu would otherwise need a real Tk root):

```python
        self.menu_patcher = patch('module.display.tk.Menu')
        self.mock_menu_class = self.menu_patcher.start()
        self.mock_menu_instance = MagicMock()
        self.mock_menu_class.return_value = self.mock_menu_instance
```

and in `tearDown`:

```python
        self.menu_patcher.stop()
```

Add tests:

```python
    def test_quit_bindings(self):
        """ Escape and right-click must be bound so the borderless window can be closed """
        root_bindings = [c.args[0] for c in self.mock_root.bind.call_args_list]
        self.assertIn("<Escape>", root_bindings)
        self.assertIn("<Button-2>", root_bindings)
        self.assertIn("<Button-3>", root_bindings)
        self.mock_menu_instance.add_command.assert_called_once_with(
            label="Quit", command=self.mock_root.destroy
        )

    def test_show_menu(self):
        """ Right-click pops the context menu at the pointer """
        event = MagicMock()
        event.x_root = 100
        event.y_root = 200
        self.display.show_menu(event)
        self.mock_menu_instance.tk_popup.assert_called_once_with(100, 200)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_display.py -v`
Expected: both new tests FAIL.

- [ ] **Step 3: Implement**

In `module/display.py` `__init__`, after the draggability block:

```python
        # Quit controls: borderless windows have no close button
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Quit", command=self.root.destroy)
        self.root.bind("<Escape>", lambda event: self.root.destroy())
        for widget in (self.root, self.label):
            widget.bind("<Button-2>", self.show_menu)  # macOS aqua right-click
            widget.bind("<Button-3>", self.show_menu)
```

Add the method:

```python
    def show_menu(self, event):
        """ Shows the right-click context menu at the pointer. """
        self.menu.tk_popup(event.x_root, event.y_root)
```

- [ ] **Step 4: Run tests**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 5: Manual verification**

Run: `python main.py`. Right-click the subtitle bar → Quit must close the app. Also try Escape (may not fire on macOS: `overrideredirect` windows often cannot take keyboard focus — the menu is the reliable path; if Escape does nothing, that is acceptable, leave the binding).

- [ ] **Step 6: Commit**

```bash
git add module/display.py tests/test_display.py
git commit -m "feat: quit via right-click menu and Escape on the overlay"
```

---

### Task 9: Status feedback on the overlay (P2 item 9)

A bad API key currently shows "Reconnecting..." forever with no detail; a fresh connection shows the stale "Waiting for translation..." text.

**Files:**
- Modify: `module/transcriber.py` (`connect_and_run`)
- Test: `tests/test_transcriber.py`

**Interfaces:**
- Produces: `latest_translation` is set to `"Listening..."` on successful connect and `"Reconnecting (<ExceptionName>)..."` on failure. These flow through the existing `get_transcription()` -> overlay path.

- [ ] **Step 1: Write the failing test**

```python
    async def test_connection_error_shows_exception_on_overlay(self):
        """ Connection failures must surface the exception class, not a bare Reconnecting """
        translator = TranscriberTranslator(config_path="dummy.json")
        translator.client.aio.live.connect = MagicMock(side_effect=ValueError("bad key"))

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await translator.connect_and_run(asyncio.Queue())

        self.assertIn("Reconnecting", translator.latest_translation)
        self.assertIn("ValueError", translator.latest_translation)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transcriber.py -v -k exception_on_overlay`
Expected: FAIL ("ValueError" not in "Reconnecting...").

- [ ] **Step 3: Implement**

In `connect_and_run`, after `logger.info("Connected to Gemini Live successfully.")`:

```python
                    self.latest_translation = "Listening..."
```

and in the except block, replace `self.latest_translation = "Reconnecting..."` with:

```python
                self.latest_translation = f"Reconnecting ({type(e).__name__})..."
```

- [ ] **Step 4: Run tests**

Run: `pytest`
Expected: ALL PASS (the drain test from Task 2 still passes; it does not assert on latest_translation).

- [ ] **Step 5: Commit**

```bash
git add module/transcriber.py tests/test_transcriber.py
git commit -m "feat: show Listening/Reconnecting status with error class on the overlay"
```

---

### Task 10: Auto-grow the subtitle window for long lines (P2 item 11)

Fixed 90 px height clips anything past one wrapped line. Grow up to 3x base height, bottom edge anchored.

**Files:**
- Modify: `module/display.py` (`update_label`)
- Test: `tests/test_display.py`

**Interfaces:**
- Consumes: `update_label(text)` is only called on text changes (Task 1), so per-update geometry work is cheap.

- [ ] **Step 1: Give the setUp mocks concrete geometry values**

In `tests/test_display.py` `setUp`, after creating `self.display`, add (prevents MagicMock arithmetic noise in every update_label test):

```python
        self.mock_root.winfo_height.return_value = 90
        self.mock_root.winfo_width.return_value = 1536
        self.mock_root.winfo_x.return_value = 192
        self.mock_root.winfo_y.return_value = 890
        self.mock_label_instance.winfo_reqheight.return_value = 70
        self.mock_root.geometry.reset_mock()
```

- [ ] **Step 2: Write the failing tests**

```python
    def test_update_label_grows_window_for_long_text(self):
        """ Window grows (bottom-anchored) when the label needs more height """
        self.mock_label_instance.winfo_reqheight.return_value = 160
        self.display.update_label("a very long translation that wraps to several lines")
        self.mock_root.geometry.assert_called_with("1536x180+192+800")

    def test_update_label_keeps_base_height_for_short_text(self):
        """ Short text keeps the configured base height: no resize call """
        self.mock_label_instance.winfo_reqheight.return_value = 70
        self.display.update_label("short")
        self.mock_root.geometry.assert_not_called()
```

Height math for the first test: needed = 160 + 20 = 180; clamp to [90, 270] -> 180; y = 890 + 90 - 180 = 800.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_display.py -v`
Expected: grow test FAILS (geometry not called from update_label).

- [ ] **Step 4: Implement**

Replace `update_label` in `module/display.py`:

```python
    def update_label(self, text):
        """ Updates the label and resizes the window to fit, bottom edge anchored. """
        self.label.config(text=text)
        self.root.update_idletasks()
        needed = self.label.winfo_reqheight() + 20
        base = self.config["window_height"]
        height = max(base, min(needed, base * 3))
        if height != self.root.winfo_height():
            y = self.root.winfo_y() + self.root.winfo_height() - height
            self.root.geometry(f"{self.root.winfo_width()}x{height}+{self.root.winfo_x()}+{y}")
```

- [ ] **Step 5: Run tests**

Run: `pytest`
Expected: ALL PASS (existing `test_update_label` still passes: label.config call unchanged; short-text path calls no geometry).

- [ ] **Step 6: Commit**

```bash
git add module/display.py tests/test_display.py
git commit -m "feat: auto-grow subtitle window up to 3x base height for long lines"
```

---

### Task 11: Persist the dragged overlay position (P2 item 12)

**Files:**
- Modify: `module/display.py` (`__init__`, new `end_drag`)
- Test: `tests/test_display.py`

**Interfaces:**
- Produces: config keys `ui.window_x` / `ui.window_y` (written on drag release, honored at startup); `DisplayTranslation.config_path` attribute.

- [ ] **Step 1: Write the failing tests**

```python
    def test_end_drag_persists_position(self):
        """ Releasing a drag writes window_x/window_y back to config.json """
        import json as jsonlib
        from unittest.mock import mock_open
        self.mock_root.winfo_x.return_value = 300
        self.mock_root.winfo_y.return_value = 500
        m = mock_open(read_data='{"ui": {}}')
        with patch("module.display.open", m):
            self.display.end_drag(MagicMock())
        written = "".join(call.args[0] for call in m().write.call_args_list)
        data = jsonlib.loads(written)
        self.assertEqual(data["ui"]["window_x"], 300)
        self.assertEqual(data["ui"]["window_y"], 500)

    def test_saved_position_used_at_startup(self):
        """ A persisted position overrides the computed centered position """
        display = DisplayTranslation(root=self.mock_root, config={"window_x": 10, "window_y": 20})
        geometry_arg = self.mock_root.geometry.call_args_list[0].args[0]
        self.assertTrue(geometry_arg.endswith("+10+20"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_display.py -v`
Expected: both FAIL (`end_drag` missing; startup ignores window_x/window_y).

- [ ] **Step 3: Implement**

In `module/display.py` `__init__`:

Store the path (first line of `__init__` body):

```python
        self.config_path = config_path
```

Replace the coordinate computation:

```python
        x = self.config.get("window_x")
        y = self.config.get("window_y")
        if x is None or y is None:
            x = (screen_width - width) // 2
            y = screen_height - height - self.config["bottom_margin"]
```

In the draggability block, add the release binding alongside the existing two:

```python
                widget.bind("<ButtonRelease-1>", self.end_drag)
```

Add the method:

```python
    def end_drag(self, event):
        """ Persists the dragged window position to the config file. """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("ui", {})["window_x"] = self.root.winfo_x()
            data["ui"]["window_y"] = self.root.winfo_y()
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Could not persist window position: %s", e)
```

- [ ] **Step 4: Run tests**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add module/display.py tests/test_display.py
git commit -m "feat: remember dragged overlay position across sessions"
```

---

### Task 12: CLI arguments — target language, device override, list-devices (P3 item 13)

No `--source` flag: the SDK has no source-language field (Task 7). Uses `parse_known_args` so `runpy`-based tests under pytest are unaffected by pytest's argv.

**Files:**
- Modify: `main.py` (new `parse_args`, `__main__` block), `module/audio_capturer.py` (`device_name` kwarg)
- Test: `tests/test_main.py`, `tests/test_audio_capturer.py`

**Interfaces:**
- Produces: `main.parse_args(argv=None) -> argparse.Namespace` with `.target`, `.device`, `.list_devices`; `AudioCapturer.__init__(..., device_name=None)` keyword override that beats the config file.

- [ ] **Step 1: Write the failing tests**

In `tests/test_main.py` (import `parse_args` alongside the existing imports from `main`):

```python
    def test_parse_args_defaults(self):
        """ No flags: no overrides """
        args = parse_args([])
        self.assertIsNone(args.target)
        self.assertIsNone(args.device)
        self.assertFalse(args.list_devices)

    def test_parse_args_overrides(self):
        """ Flags parse into overrides; unknown args are ignored (pytest compatibility) """
        args = parse_args(["--target", "en-US", "--device", "Loopback", "--list-devices", "ignored-positional"])
        self.assertEqual(args.target, "en-US")
        self.assertEqual(args.device, "Loopback")
        self.assertTrue(args.list_devices)
```

In `tests/test_audio_capturer.py`:

```python
    def test_device_name_kwarg_overrides_config(self):
        """ An explicit device_name beats the config file value """
        with patch('builtins.open', mock_open(read_data=self.mock_config)):
            capturer = AudioCapturer(self.loop, self.audio_queue, device_name="Built-in Microphone")
        self.assertEqual(capturer.device_name, "Built-in Microphone")
        self.assertEqual(capturer.device_index, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py tests/test_audio_capturer.py -v`
Expected: FAIL (`parse_args` import error; `device_name` unexpected kwarg).

- [ ] **Step 3: Implement**

In `main.py`, add `import argparse` and:

```python
def parse_args(argv=None):
    """Parses CLI overrides. Unknown args are ignored so test runners' argv doesn't break."""
    parser = argparse.ArgumentParser(description="Real-time translation subtitle overlay")
    parser.add_argument("--target", help="Target language code override, e.g. en-US")
    parser.add_argument("--device", help="Audio input device name substring override")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    args, _ = parser.parse_known_args(argv)
    return args
```

In the `__main__` block, first lines:

```python
    args = parse_args()
    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        sys.exit(0)
```

Replace the module initializations:

```python
    overrides = {}
    if args.target:
        overrides["target_language"] = args.target
    transcriber_translator = TranscriberTranslator(**overrides)
    audio_capturer = AudioCapturer(async_loop, audio_queue, device_name=args.device)
    display_translation = DisplayTranslation()
```

In `module/audio_capturer.py`, change the signature:

```python
    def __init__(self, loop, audio_queue: asyncio.Queue, config_path="config.json", config=None, device_name=None):
```

and change the Task 3 device-name line to honor the override:

```python
        self.device_name = device_name or config.get("device_name", DEFAULT_CONFIG["device_name"])
```

- [ ] **Step 4: Run tests**

Run: `pytest`
Expected: ALL PASS (existing runpy tests unaffected: `parse_known_args` swallows pytest's argv; `args.list_devices` is False, `args.target`/`args.device` are None so behavior is unchanged).

- [ ] **Step 5: Verify the new entrypoint manually**

Run: `python main.py --list-devices`
Expected: device table printed, immediate exit, no window.

- [ ] **Step 6: Commit**

```bash
git add main.py module/audio_capturer.py tests/test_main.py tests/test_audio_capturer.py
git commit -m "feat: CLI overrides --target/--device and --list-devices"
```

---

### Task 13: Fix install_env.sh first-run flow (P3 item 14)

The script never creates `.env`, so the app it launches at the end exits immediately at the API-key check.

**Files:**
- Modify: `install_env.sh`

- [ ] **Step 1: Rewrite the script**

```bash
#!/bin/bash
set -e

# Install blackhole with brew
brew install blackhole-2ch

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# First run: create .env and stop so the user can add their API key
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env - set GEMINI_API_KEY in it, then run:"
    echo "  source venv/bin/activate && python main.py"
    exit 0
fi

# Run main.py
python main.py
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n install_env.sh`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add install_env.sh
git commit -m "fix: install_env.sh creates .env and stops for API key on first run"
```

---

### Task 14: Session cost summary on exit + logger naming (P3 item 17, part 1)

Pricing constants are currently inline in the receive loop; extract them, add a shutdown summary, and standardize on `getLogger(__name__)` (safe: `getLogger('root')` aliases the real root logger — verified — so `__name__` loggers propagate to the same handler).

**Files:**
- Modify: `module/transcriber.py`, `module/display.py` (logger line only), `main.py` (after `start_gui()`)
- Test: `tests/test_transcriber.py`

**Interfaces:**
- Produces: `TranscriberTranslator.PROMPT_TOKEN_COST = 0.0000035`, `TranscriberTranslator.OUTPUT_TOKEN_COST = 0.000021` (class attrs), `TranscriberTranslator.log_session_summary()`.

- [ ] **Step 1: Write the failing test**

```python
    def test_log_session_summary(self):
        """ Shutdown summary logs accumulated tokens and cost """
        translator = TranscriberTranslator(config_path="dummy.json")
        translator.accumulated_prompt_tokens = 1000000
        translator.accumulated_candidates_tokens = 1000000
        with patch('module.transcriber.logger.info') as mock_info:
            translator.log_session_summary()
            mock_info.assert_called_once()
            logged = mock_info.call_args[0][0] % tuple(mock_info.call_args[0][1:])
        self.assertIn("1000000", logged)
        self.assertIn("24.50", logged)  # 3.50 input + 21.00 output per 1M tokens
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transcriber.py -v -k session_summary`
Expected: FAIL (AttributeError: no `log_session_summary`).

- [ ] **Step 3: Implement**

In `module/transcriber.py`, add class attributes right below the class docstring:

```python
    # Gemini 3.5 Live pricing per token: $3.50/1M input, $21.00/1M output
    PROMPT_TOKEN_COST = 0.0000035
    OUTPUT_TOKEN_COST = 0.000021
```

In `receive_translation_loop`, replace the inline cost line:

```python
                        estimated_cost = (
                            self.accumulated_prompt_tokens * self.PROMPT_TOKEN_COST
                            + self.accumulated_candidates_tokens * self.OUTPUT_TOKEN_COST
                        )
```

(and delete the old `# Gemini 3.5 Live pricing` comment there).

Add the method:

```python
    def log_session_summary(self):
        """ Logs total token usage and estimated cost for the whole session. """
        cost = (
            self.accumulated_prompt_tokens * self.PROMPT_TOKEN_COST
            + self.accumulated_candidates_tokens * self.OUTPUT_TOKEN_COST
        )
        logger.info(
            "Session summary - prompt tokens: %d, output tokens: %d, estimated cost: $%.2f",
            self.accumulated_prompt_tokens,
            self.accumulated_candidates_tokens,
            cost
        )
```

Logger naming: in `module/transcriber.py` and `module/display.py`, change `logging.getLogger('root')` to `logging.getLogger(__name__)`.

In `main.py`, after `display_translation.start_gui()` (runs when the window closes):

```python
    display_translation.start_gui()
    transcriber_translator.log_session_summary()
```

- [ ] **Step 4: Run tests**

Run: `pytest`
Expected: ALL PASS. If `test_main_execution_success` asserts nothing after `start_gui`, it still passes (the transcriber is a mock).

- [ ] **Step 5: Commit**

```bash
git add module/transcriber.py module/display.py main.py tests/test_transcriber.py
git commit -m "feat: session cost summary on exit; extract pricing constants; logger naming"
```

---

### Task 15: Rewrite CLAUDE.md for the Gemini architecture (P3 item 17, part 2)

CLAUDE.md still describes the removed Google Cloud Speech/Translate pipeline (ring buffer, translate_v2, hardcoded creds JSON) and misleads every future session. Rewrite it to describe the final state after Tasks 1-14. Do this task LAST.

**Files:**
- Modify: `CLAUDE.md` (currently untracked — this task also adds it to git)

- [ ] **Step 1: Replace CLAUDE.md content**

```markdown
# CLAUDE.md - UniLingoStream

Real-time translation overlay: captures system audio, streams it to the Gemini Live API
(transcription + translation in one WebSocket), displays subtitles in a borderless Tkinter window.

## Tech stack
- Python 3.9-3.12 (CI matrix)
- `sounddevice` (PortAudio) for capture, `numpy` for the RMS silence gate
- `google-genai` (pinned) - Gemini Live API, model and languages in `config.json`
- Tkinter for the on-screen display
- pytest (unittest-style tests) + flake8

## Run / build / test
```bash
pip install -r requirements.txt   # plus requirements_dev.txt for pytest/flake8
python main.py                    # runs the app; --target/--device/--list-devices overrides
pytest                            # tests in tests/
./install_env.sh                  # brew install blackhole-2ch, venv, deps; creates .env on first run
```
Lint (matches CI): `flake8 . --select=E9,F63,F7,F82` for hard errors; `flake8 . --max-line-length=127` for warnings.
CI (`.github/workflows`) runs on push/PR to `dev` only.

## Architecture
- `main.py` - parses CLI args, wires the three components, starts a daemon thread running the
  asyncio loop (`connect_and_run`), polls `get_transcription()` into the display every 50 ms
  from the Tk event loop, logs a token/cost summary on exit.
- `module/audio_capturer.py` - `AudioCapturer`: `sd.InputStream` callback pushes 100 ms int16 PCM
  chunks into a bounded asyncio queue; RMS silence gate with 1 s hangover drops silence so it is
  not streamed (and billed).
- `module/transcriber.py` - `TranscriberTranslator`: Gemini Live WebSocket (send/receive/clear
  tasks), reconnect loop with exponential backoff that drains stale audio first, sentence
  splitting on punctuation/pauses, token/cost accounting.
- `module/display.py` - `DisplayTranslation`: borderless always-on-top subtitle bar; draggable
  (position persisted to config.json), auto-grows for long lines, right-click menu / Escape to quit.
- `module/utility/log.py` - `setup_custom_logger('root')` configures the root logger; modules use
  `logging.getLogger(__name__)`.

## Gotchas
- macOS-oriented. Needs BlackHole routed via a Multi-Output Device to capture system output (see
  README). If BlackHole is missing the capturer falls back to the default input (microphone) and
  shows a warning on the overlay. PortAudio (`libportaudio2`) required on Linux/CI.
- `GEMINI_API_KEY` comes from `.env` (see `.env.example`); the app exits at startup without it.
- All tuning lives in `config.json`: model, target language, subtitle timeouts, silence RMS
  threshold, UI fonts/colors/geometry. CLI flags override target language and device.
- macOS native fullscreen (green button) apps live in their own Space; the overlay cannot appear
  over them - maximize the window instead. Do not re-attempt a Tkinter fullscreen overlay; it
  segfaults (see commit 44bb097).
- Default branch for CI is `dev`, not `main`.
```

- [ ] **Step 2: Sanity-check claims against the code**

Run: `grep -n "getLogger" module/*.py main.py && grep -n "maxsize" main.py && grep -n "silence_rms_threshold" config.json`
Expected: output matches the claims above (adjust CLAUDE.md if a task was skipped or reverted, e.g. Task 5's modality outcome does not affect this file).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: rewrite CLAUDE.md for the Gemini Live architecture"
```

---

## Deferred (explicitly out of scope)

- Pause toggle on the context menu (spec item 8 "optionally") — add when someone asks.
- Click-through overlay / native `NSPanel` rewrite (spec items 10, 16) — Tkinter cannot do it; trigger is a real user complaint about intercepted clicks or fullscreen.
- Packaging/pyproject entry point (spec item 15 note) — repo is run-from-checkout; add when distribution matters.
