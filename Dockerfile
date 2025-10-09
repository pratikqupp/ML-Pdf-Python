# 1. Use Python 3.10 (same as your local)
FROM python:3.10-slim

# 2. Set working directory
WORKDIR /app

# 3. Copy project files
COPY . .

# 4. Install system dependencies if needed
RUN apt-get update && \
    apt-get install -y build-essential libffi-dev tesseract-ocr poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# 5. Upgrade pip & install dependencies
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# 6. Run mail_fetcher.py as main process
CMD ["python", "mail_fetcher.py"]
