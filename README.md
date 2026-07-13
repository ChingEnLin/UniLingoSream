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

1. Install BlackHole:
   ```bash
   brew install blackhole-2ch
   ```
2. Open Audio MIDI Setup (under Applications > Utilities).
3. Click the + button in the bottom left and select Create Multi-Output Device.
4. In the Multi-Output Device configuration, select both your primary output device (e.g., Headphones or Built-in Speakers) and BlackHole 2ch.
5. Open macOS System Settings -> Sound.
6. Set your Output device to the newly created Multi-Output Device.
7. Set your Input device to BlackHole 2ch.

## Usage

Run the main application:

```bash
python main.py
```

The application will start capturing system audio, streaming it to the Gemini Live API, and showing the translation in a transparent overlay window.

> Note: the overlay floats over normal and maximized windows, but macOS isolates native fullscreen (green-button) apps in their own Space, so the overlay cannot appear over them. Maximize the video window instead of using native fullscreen.

### Configuration

You can customize the application behavior by modifying config.json. The supported parameters are:

- api: Configures the Gemini model, source/target languages, and phrase splitting settings.
- audio: Configures the virtual device name, sample rate, and channels.
- ui: Configures font family, font size, colors, window coordinates, opacity, and window level attributes.

## Project Structure

- main.py: Main entry point. Wires the capturer, transcriber, and display modules, spawning a background thread to poll translations.
- module/audio_capturer.py: Captures real-time audio chunking from the configured audio input device and routes it to an async queue.
- module/audio_processer.py: Performs energy-based Voice Activity Detection (VAD) to filter silence before sending audio.
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