# UniLingoStream

UniLingoStream is a real-time translation tool designed to break down language barriers while watching video streams or playing games on your computer. It captures system audio output, streams it to the Gemini Live API, and displays the translated subtitles in a floating, borderless Tkinter window.

## Features

- Real-time system audio capture using PortAudio
- Real-time speech transcription and translation using the Gemini Live API (google-genai SDK)
- Custom floating borderless translation overlay
- Session-accumulated token usage and cost logging

## Prerequisites

- Python 3.9 to 3.12
- Gemini API Key (obtained from Google AI Studio)
- macOS (requires BlackHole installed for capturing system audio) or Linux with PortAudio

## Setup

### 1. Install Dependencies

First, ensure you have the package dependencies installed:

```bash
pip install -r requirements.txt
pip install -r requirements_dev.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory and add your Gemini API Key:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. macOS Audio Routing Configuration

To route system audio so that UniLingoStream can capture it:

1. Install BlackHole and (for automatic output switching) SwitchAudioSource:
   ```bash
   brew install blackhole-2ch switchaudio-osx
   ```
2. Open Audio MIDI Setup (under Applications > Utilities).
3. Click the + button in the bottom left and select Create Multi-Output Device.
4. In the Multi-Output Device configuration, select both your primary output device (e.g., Headphones or Built-in Speakers) and BlackHole 2ch.

That's it for the one-time setup. The Multi-Output Device configuration persists across
reboots. You do **not** need to visit System Settings -> Sound each time: on launch the app
switches your system output to the Multi-Output Device automatically (via SwitchAudioSource)
and restores your previous device on quit. Set the device name under `audio.output_device`
in `config.json` (defaults to `"Multi-Output Device"` — rename if you called yours something
else). If SwitchAudioSource is not installed the app still runs; you just switch output
manually as before.

## Usage

Double-click **`UniLingoStream.command`** in Finder to launch (it activates the venv, runs the
app, and opens a Terminal window for logs). The first launch may need a right-click -> Open to
clear the Gatekeeper warning. Drag it to the Dock or Applications for one-click access.

Or run it directly:

```bash
python main.py
```

The application switches system output to the Multi-Output Device, captures that audio, streams
it to the Gemini Live API, and shows the translation in a transparent overlay window. Quit via
the "UL" menu-bar item (or Ctrl+C); your previous output device is restored on exit.

> Note: the overlay floats over normal and maximized windows, but macOS isolates native fullscreen (green-button) apps in their own Space, so the overlay cannot appear over them. Maximize the video window instead of using native fullscreen.

### Configuration

You can customize the application behavior by modifying config.json. The supported parameters are:

- api: Configures the Gemini model, source/target languages, and phrase splitting settings.
  - context_file: Path to a JSON file holding `{ "context": ..., "glossary": {...} }` (see `contexts/`) that biases the translation. Swap shows without editing config by passing `--context contexts/<show>.json` on the command line. This is the normal way to set both.
  - context / glossary: Optional inline equivalents of the two keys above, if you would rather not keep a separate file. `context_file` overrides them when set, so config.json ships without them.
- audio: Configures the virtual device name, sample rate, and channels.
- ui: Configures font family, font size, colors, window coordinates, opacity, and window level attributes.

## Project Structure

- UniLingoStream.command: Double-clickable Finder launcher (activates the venv and runs main.py).
- main.py: Main entry point. Wires the capturer, transcriber, and display modules, spawning a background thread to poll translations.
- module/audio_route.py: Switches the macOS system output to the Multi-Output Device on launch and restores the previous device on quit (via SwitchAudioSource).
- module/audio_capturer.py: Captures real-time audio from the configured input device, drops sustained silence (RMS gate), and routes speech chunks to an async queue.
- module/transcriber.py: Manages the WebSocket connection to the Gemini Live API, feeds incoming audio, decodes translated text, and logs cumulative token/cost statistics.
- module/display.py: Renders the Tkinter subtitle overlay window, manages transparency, and dragging logic.
- module/utility/log.py: Configures custom logging formatters and handlers.

## Development and Testing

To run tests:

```bash
pytest
```

To run the linter:

```bash
flake8 .
```

## License

This project is licensed under the MIT License.