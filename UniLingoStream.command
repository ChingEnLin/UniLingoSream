#!/bin/bash
# Double-click this file in Finder to launch the app.
# It switches system audio to the Multi-Output Device (via main.py), starts capture,
# and shows the subtitle overlay. Close the overlay to quit; audio is restored on exit.
cd "$(dirname "$0")"
source venv/bin/activate
exec python main.py "$@"
