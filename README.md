# UniLingoStream

UniLingoStream is a real-time translation tool designed to break down language barriers while watching video streams on your computer. It captures audio output from your system, transcribes the spoken language, translates it using AI, and displays the translated text on your screen.

## Features

- Real-time audio capture from your system
- Transcription of spoken language using Google Cloud Speech-to-Text API
- Translation of transcribed text using Google Cloud Translation API
- On-screen display of translated text

## Prerequisites

- Python 3.7 or higher
- Google Cloud account with Speech-to-Text and Translation APIs enabled
- macOS with BlackHole installed for audio capture

## Setup

### 1. Install Dependencies

First, ensure you have `pip` installed, then install the required Python packages:

```bash
pip install -r requirements.txt
```

### 2. Google Cloud Setup

#### a. Enable APIs

- Go to the [Google Cloud Console](https://console.cloud.google.com/).
- Enable the "Speech-to-Text API" and "Cloud Translation API".

#### b. Create Service Account

- Navigate to the IAM & Admin > Service accounts page.
- Click "Create Service Account".
- Follow the prompts to create a new service account and download the JSON key file.

### 3. Computer Sound Input And Output Configuration

To ensure that UniLingoStream captures the audio output of your computer correctly, you need to configure your system's audio settings. Follow these steps:

### macOS Configuration

1. **Install BlackHole**

   If you haven't installed BlackHole yet, follow the [BlackHole installation guide](https://github.com/ExistentialAudio/BlackHole#installation).

2. **Set Up Audio MIDI Setup**

   - Open `Audio MIDI Setup` from the `Applications > Utilities` folder.
   - Click the `+` button in the bottom left corner and select `Create Multi-Output Device`.
   - In the Multi-Output Device, check the boxes for your primary audio output (e.g., built-in speakers or external headphones) and `BlackHole 16ch`.

3. **Configure Sound Settings**

   - Open `System Preferences` and go to `Sound`.
   - In the `Output` tab, select the Multi-Output Device you just created.
   - In the `Input` tab, select `BlackHole 16ch` as the input device.

### 4. Clone the Repository

```bash
git clone https://github.com/ChingEnLin/UniLingoSream
cd UniLingoSream
```

## Usage

### Running the Application

Ensure your system's audio output is routed through BlackHole, then run the main application:

```bash
python main.py
```

The application will start capturing audio, transcribing, translating, and displaying the translated text on your screen.

## Project Structure

- `audio_capturer.py`: Handles real-time audio capturing.
- `transcriber.py`: Manages transcription and translation of audio.
- `display.py`: Manages the display of translated text using Tkinter.
- `main.py`: Main script to initialize and run the application.

## Contributing

Contributions are welcome! Please submit a pull request or open an issue to discuss improvements or bug fixes.

## License

This project is licensed under the MIT License.
```

This `README.md` file provides detailed instructions on setting up, running, and understanding the project. It also outlines the structure of the project and provides an overview of the main components. This should help new users get started with your project and understand its functionality.