#!/bin/bash
echo "Starting deployment..."

# Ensure spaCy model installed
python3 -m spacy download en_core_web_sm || true

echo "Starting mail_fetcher.py..."

# Run your script
python3 mail_fetcher.py
