# Gemini Live Translate Spec

Date: 2026-07-12
Status: Approved

## Overview
This specification details the transition of the UniLingoStream application to use the Google Gemini Live API (`gemini-3.5-live-translate-preview`). The goal remains the same: capture system audio (spoken Japanese), translate in real-time, and show Traditional Chinese subtitles via a borderless, transparent screen overlay.

---

## 1. Architecture and Data Flow

### 1.1 API and Real-Time Stream
* **Model ID**: `gemini-3.5-live-translate-preview`
* **SDK**: `google-genai` Python SDK
* **Connection**: Stateful bidirectional WebSocket managed by `asyncio` (`client.aio.live.connect`).
* **Format**: Raw 16-bit PCM little-endian mono audio at 16kHz. Audio is sent in ~100ms chunks to optimize latency.
* **Translation Configuration**:
  ```python
  config = types.LiveConnectConfig(
      response_modalities=[types.Modality.AUDIO],
      translation_config=types.TranslationConfig(
          target_language_code="zh-TW",
      ),
      output_audio_transcription=types.AudioTranscriptionConfig()
  )
  ```

### 1.2 Data Flow Pipeline
1. **Audio Capture**: `sounddevice.InputStream` callback captures system audio from the BlackHole device and pushes raw bytes into an `asyncio.Queue`.
2. **Send Loop**: An async task continuously pulls audio chunks from the queue and sends them to Gemini via `session.send_realtime_input()`.
3. **Receive Loop**: An async task listens to `session.receive()`. When a message contains `output_transcription.text`, it extracts the translation and writes it to a shared string buffer.
4. **UI Polling**: Tkinter runs on the main thread and uses `root.after()` to poll the shared buffer every 50ms to refresh the overlay text.

---

## 2. Components and Configuration

### 2.1 File Structure
* `main.py`: Entrypoint. Initializes environment variables, config, asyncio event loop, audio capture, and starts the Tkinter event loop.
* `config.json`: Configuration file for the GUI overlay, target languages, and audio device preferences.
* `module/audio_capturer.py`: Manages the sounddevice capture stream, searching for the device specified in the config.
* `module/transcriber.py`: Manages the Gemini client connection, handles async send/receive loops, and updates the text buffer.
* `module/display.py`: Implements the borderless transparent Tkinter subtitle overlay window.

### 2.2 Configuration Schema (`config.json`)
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
    "font_size": 26,
    "text_color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 0.55,
    "window_height": 90,
    "window_width_percent": 75,
    "bottom_margin": 100,
    "always_on_top": true,
    "draggable": true
  }
}
```

### 2.3 Subtitle UI Window Customization
* **Borderless Floating**: Handled via `overrideredirect(True)` to strip standard macOS window decorations.
* **Opacity**: Handled via `-alpha` attribute on the Tkinter root.
* **Positioning**: Center-bottom calculated using the screen's dimensions.
* **Draggability**: Mouse click and drag events bound to reposition the overlay anywhere on the screen.

---

## 3. Error Handling and Verification

### 3.1 Error Handling & Connection Resilience
* **WebSocket Drops**: Auto-reconnection with exponential backoff. Subtitle overlay shows "Connecting..." status message.
* **Audio Device Missing**: Fallback to system default input device, outputting a list of active audio devices to the terminal.
* **API Key Check**: Fail-fast validation check on `GEMINI_API_KEY` environment variable.

### 3.2 Verification and Testing Plan
* **Mock File Stream**: Test script feeding a pre-recorded WAV file to the Gemini Live session to verify translations.
* **UI Verification**: Interactive check on window dimensions, borderless state, transparency, always-on-top behavior, and dragging.
* **Unit Tests**: Updated pytest assertions verifying configuration loading and transcription text parsing.
