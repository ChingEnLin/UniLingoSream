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