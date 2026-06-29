FROM python:3.11-slim

# Install system dependencies needed for text extraction and process management
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy project files
COPY . .

# Expose the default internal port
EXPOSE 8080

# Run supervisor to spin up all 3 processes concurrently
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
