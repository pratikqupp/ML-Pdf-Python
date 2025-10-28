  GNU nano 8.3                                                                   Dockerfile                                                                            
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

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install spaCy 3.6.1
RUN pip install --no-cache-dir spacy==3.6.1

# Install the English SpaCy model
RUN pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.6.0/en_core_web_sm-3.6.0.tar.gz

# Copy the rest of your project files
COPY . .

# Make start.sh executable (optional)
RUN chmod +x start.sh  GNU nano 8.3                                                                   Dockerfile                                                                            
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

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install spaCy 3.6.1
RUN pip install --no-cache-dir spacy==3.6.1

# Install the English SpaCy model
RUN pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.6.0/en_core_web_sm-3.6.0.tar.gz

# Copy the rest of your project files
COPY . .

# Make start.sh executable (optional)
RUN chmod +x start.sh