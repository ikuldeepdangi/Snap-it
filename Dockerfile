FROM python:3.13-slim

# Prevent interactive prompts during apt execution
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies securely and clear cache instantly
RUN apt-get update && apt-get install -y -qq --no-install-recommends \
    supervisor \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install requirements matching your Python 3.13 environment
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy structural codebase
COPY . .

# Expose internal standard port mapping
EXPOSE 8080

# Run supervisor to spin up web, bot, and background loops simultaneously
CMD ["supervisord", "-c", "/app/supervisord.conf"]
