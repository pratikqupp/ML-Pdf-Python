# 1. Base image with Python 3.10
FROM python:3.10-slim

# 2. Working directory
WORKDIR /app

# 3. Copy project files
COPY . .

# 4. Install system dependencies
RUN apt-get update && \
    apt-get install -y build-essential libffi-dev tesseract-ocr poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# 5. Upgrade pip
RUN pip install --upgrade pip setuptools wheel

# 6. Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 7. Install Flask (agar requirements me nahi hai)
RUN pip install flask

# 8. Expose port for Render
EXPOSE 10000

# 9. Start both the mail_fetcher and a Flask server
CMD ["sh", "-c", "python mail_fetcher.py & python server.py"]
