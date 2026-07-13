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
