# 1. Base image with Python 3.10 (matches your local)
FROM python:3.10-slim

# 2. Set working directory
WORKDIR /app

# 3. Copy project files
COPY . .

# 4. Install system dependencies required for C extensions
RUN apt-get update && \
    apt-get install -y build-essential libffi-dev tesseract-ocr poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# 5. Upgrade pip & setuptools
RUN pip install --upgrade pip setuptools wheel

# 6. Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 7. Default command to start your script
CMD ["python", "mail_fetcher.py"]
