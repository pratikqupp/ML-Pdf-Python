#!/bin/bash
# install spaCy model if not already present
python3 -m spacy download en_core_web_sm || true
echo "Starting mail_fetcher.py..."
# run main script
python3 mail_fetcher.py
