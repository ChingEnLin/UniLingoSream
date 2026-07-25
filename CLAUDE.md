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
  from the Tk event loop, logs a token/cost summary on exit (registered with both `atexit` and
  `mac_terminate.on_terminate`, since the two quit paths are different).
- `module/audio_route.py` - switches the macOS default output to the Multi-Output Device on launch
  (`audio.output_device` in config.json) and restores the previous device on quit, via the
  `SwitchAudioSource` CLI. No-op if SwitchAudioSource is absent.
- `module/audio_capturer.py` - `AudioCapturer`: `sd.InputStream` callback pushes int16 PCM chunks
  of `audio.block_duration_seconds` (50 ms default) into a bounded asyncio queue; RMS silence gate
  with 1 s hangover drops silence so it is not streamed (and billed). Only devices with input
  channels are eligible; a stream that fails to open is reported via `.error`, not raised.
- `module/transcriber.py` - `TranscriberTranslator`: Gemini Live WebSocket (send/receive/clear
  tasks), reconnect loop with exponential backoff that drains stale audio first, sentence
  splitting on punctuation/pauses, token/cost accounting.
- `module/utility/config.py` - `load_config(path)`: the only place config.json is read. Returns the
  parsed dict or `{}`; callers merge it over their own defaults.
- `module/utility/mac_terminate.py` - `on_terminate(fn)`: runs `fn` on
  `NSApplicationWillTerminateNotification`. The AppKit Quit menu calls `terminate:`, which exits at
  the C level and skips `atexit`, so anything that must run on quit registers both ways (audio
  restore and the token/cost summary do). No-op without AppKit.
- `module/display.py` - `DisplayTranslation`: borderless always-on-top subtitle bar; draggable
  (position persisted to config.json), auto-grows for long lines, right-click menu / Escape to quit.
- `module/utility/log.py` - `setup_custom_logger('root')` configures the root logger; modules use
  `logging.getLogger(__name__)`.

## Gotchas
- macOS-oriented. Needs BlackHole routed via a Multi-Output Device to capture system output (see
  README). If BlackHole is missing the capturer falls back to the default input (microphone) and
  shows a warning on the overlay. PortAudio (`libportaudio2`) required on Linux/CI.
- `UniLingoStream.command` is a double-clickable Finder launcher (activates venv, runs main.py).
  Automatic output switching needs `switchaudio-osx` (`brew install switchaudio-osx`); without it
  the app runs but you route audio manually.
- `GEMINI_API_KEY` comes from `.env` (see `.env.example`); the app exits at startup without it.
- All tuning lives in `config.json`: model, target language, subtitle timeouts, silence RMS
  threshold, UI fonts/colors/geometry. CLI flags override target language and device.
- macOS native fullscreen (green button) apps live in their own Space; the overlay cannot appear
  over them - maximize the window instead. Do not re-attempt a Tkinter fullscreen overlay; it
  segfaults (see commit 44bb097).
- Default branch for CI is `dev`, not `main`.
