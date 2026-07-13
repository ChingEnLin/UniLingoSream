# UniLingoStream Improvement Spec

Date: 2026-07-13
Scope: full-application review — correctness, cost, latency, UI/UX, entrypoint, tooling.
Ordered by priority. Each item states the problem, evidence, and the smallest fix.

## P0 — Correctness bugs

### 1. Subtitles never clear from the screen
`clear_subtitle_timeout_loop` (module/transcriber.py:171) sets `latest_translation = ""` after the timeout, but `poll_transcription` (main.py:59-61) only calls `display.update_label(text)` when `text` is truthy. The empty string is never rendered, so the last subtitle stays on screen forever. The whole timeout feature is dead on screen.

Fix: track the last rendered text in the poll and always push changes, including "":

```python
if text != last_rendered:
    display.update_label(text)
```

This also stops re-rendering the identical string every 50 ms.

### 2. Stale audio flood after reconnect
During reconnect backoff (up to 60 s), `send_audio_loop` is cancelled, but `audio_callback` keeps pushing 100 ms chunks into the unbounded `asyncio.Queue`. On reconnect, the entire backlog is blasted to Gemini: minutes-old audio gets translated (stale subtitles), input tokens are paid for content the user already missed, and memory grows without bound while disconnected.

Fix: drain the queue at the top of each `connect_and_run` iteration, and construct the queue with a `maxsize` (e.g. 50 chunks = 5 s) so `_safe_put`'s existing `QueueFull` drop path actually engages.

### 3. Silent fallback to microphone
`_find_device_index` (module/audio_capturer.py:50-61) falls back to the system default input when "BlackHole 2ch" is missing — on a Mac that is the microphone. The app then translates room audio while the user believes it is translating the stream. A log warning is the only signal, and most users launch without watching the terminal.

Fix: surface it — set the initial overlay text to something like "WARNING: BlackHole not found, capturing microphone" (or refuse to start with a clear message). The capturer needs a way to report this to the display; a simple attribute checked in `main.py` suffices.

### 4. CI matrix includes Python 3.8, which google-genai does not support
`google-genai` requires Python >= 3.9, so the 3.8 leg of `.github/workflows/python-package.yml` fails at `pip install`. README also still advertises 3.8.

Fix: drop 3.8 from the matrix, add 3.11/3.12, update README prerequisites.

## P1 — Cost and latency

### 5. Requesting AUDIO response modality that is never played
`get_connect_config` (module/transcriber.py:70-76) asks for `response_modalities=[AUDIO]` and reads only `output_transcription`. The generated speech audio is received, paid for at output-audio token rates (the expensive side: $21/1M vs $3.50/1M input), and discarded. It also adds latency, since the transcription text trails the audio synthesis.

Fix: try `response_modalities=[TEXT]` with the same `translation_config`. If the live-translate preview model mandates AUDIO output, document that constraint in a comment; otherwise this is the single biggest cost and latency win in the app.

### 6. VAD exists but is not wired in — silence is streamed 24/7
`module/audio_processer.py` (RMS energy gate) is imported by nothing except its test. Every 100 ms block, including hours of silence or paused video, is streamed to Gemini and billed as input tokens. README falsely claims VAD "filters silence before sending."

Fix: gate in `AudioCapturer.audio_callback` — compute RMS on `indata`, drop blocks below threshold, with a short hangover (keep sending ~1 s after last speech so word tails are not clipped). Note the current `energy_threshold=0.1` was tuned for float audio; int16 input needs rescaling or a new threshold. Alternatively, check whether Gemini Live's server-side VAD already makes silence near-free — if so, delete the module and fix the README instead. Either way, resolve the code/doc mismatch.

### 7. `source_language` config is dead
`config.json` declares `source_language: ja-JP` but `get_connect_config` only sets the target. Either pass it to the session (better recognition accuracy, fewer wrong-language hallucinations) or delete the key.

## P2 — UX

### 8. No way to quit the app
`overrideredirect(True)` removes the title bar and close button. There is no hotkey, menu, or tray icon — the only exits are Ctrl+C in the terminal or force quit.

Fix: bind Escape and a right-click context menu (Quit, optionally Pause) on the label. A Pause toggle that stops sending audio doubles as a cost control.

### 9. No status feedback for failure states
An invalid API key or network outage shows "Reconnecting..." forever with no detail. The initial "Waiting for translation..." also persists indefinitely during silence, indistinguishable from a broken pipeline.

Fix: reuse the existing subtitle channel for status: "Listening..." once connected, "Reconnecting (auth error)..." with the exception class on failure. One line in `connect_and_run`'s except block.

### 10. Overlay steals clicks over the video
The drag bindings make the whole bar an opaque click target sitting on top of the content being watched. Tkinter on macOS cannot do true click-through, so full transparency to clicks is out of scope — but dragging is already configurable (`draggable`), and that limitation should be documented. If click-through becomes important, that is the trigger to move off Tkinter (see item 16).

### 11. Long translations clip
Fixed `window_height: 90` with font size 24 fits roughly one wrapped CJK line plus padding; longer sentences clip vertically. Fix: after `update_label`, measure `label.winfo_reqheight()` and grow/shrink the window geometry within a max (e.g. 3 lines), keeping the bottom edge anchored.

### 12. Dragged position is not remembered
Users who move the bar re-drag it every session. Fix: on drag end (`<ButtonRelease-1>`), write the offset back to `config.json` (or a small state file).

## P3 — Entrypoint and developer experience

### 13. No CLI arguments
Changing language pair means editing `config.json`. Add argparse overrides: `--source`, `--target`, `--device`, `--list-devices` (prints `sd.query_devices()` and exits — currently users must guess device names). Config file stays the source of defaults.

### 14. `install_env.sh` gaps
It never creates `.env` (the app exits immediately at the key check on first run) and unconditionally launches the app at the end. Fix: `cp -n .env.example .env` plus a message to fill in the key; only run the app if the key is set.

### 15. Dependency hygiene
- `scipy` is imported by nothing — remove from requirements.txt.
- Nothing is version-pinned; `google-genai` is a fast-moving SDK against a preview model. Pin at least `google-genai` to a known-good version.

### 16. Platform ceiling (note, not a task)
Tkinter caps this app: no click-through, no native-fullscreen overlay (already documented in README), 90s-looking rendering. The upgrade path when those hurt is a small pyobjc `NSPanel` (non-activating, click-through, joins all Spaces) or a web overlay for OBS use. Not worth it until item 10/fullscreen becomes a real complaint.

### 17. Housekeeping
- CLAUDE.md describes the old Google Cloud Speech-to-Text architecture (ring buffer, translate_v2, hardcoded creds JSON). It is now wrong in almost every section and will mislead future work. Rewrite for the Gemini Live pipeline.
- Logging is inconsistent: `audio_capturer` uses `getLogger(__name__)`, others use `getLogger('root')`. Pick `__name__` everywhere; the root logger config propagates anyway.
- Cost tracking logs per-response; add a single session summary (total tokens, cost) on shutdown.

## Suggested order of work

1. P0 items 1-3 (small diffs, real bugs) plus a regression test for the subtitle-clear bug.
2. Item 5 (TEXT modality experiment) — biggest cost/latency lever, needs one measured session to validate.
3. Item 6 (VAD wiring or deletion) — second cost lever.
4. P2 quick wins: 8, 9 (a few lines each).
5. Everything else opportunistically.
