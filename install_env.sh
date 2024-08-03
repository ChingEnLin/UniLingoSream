#!/bin/bash

# Install blackhole with brew
brew install blackhole-2ch

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Run main.py
python main.py