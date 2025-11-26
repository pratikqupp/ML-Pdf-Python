# Use Python 3.10 slim image
FROM python:3.10-slim

# Set working directory inside container
WORKDIR /app

# Install system dependencies required for some Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for Docker cache efficiency
COPY requirements.txt .

# Install Python dependencies (includes playwright now)
RUN pip install --no-cache-dir -r requirements.txt

# Install spaCy 3.6.1 over the pinned 3.5.3 (your original logic)
RUN pip install --no-cache-dir spacy==3.6.1

# Install the English SpaCy model
RUN pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.6.0/en_core_web_sm-3.6.0.tar.gz

# Install Playwright browsers (Chromium + all Linux deps)
RUN python -m playwright install --with-deps chromium

# Copy the rest of your project files
COPY . .

# Make start.sh executable (if you use it)
RUN chmod +x start.sh

# If you have a start.sh that runs your mail loop, use this:
# CMD ["./start.sh"]

# Or, if your main script is named mailscript.py, do:
# CMD ["python", "mailscript.py"]
