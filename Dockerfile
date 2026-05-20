FROM python:3.11-slim

WORKDIR /app

COPY worker.py .

# Install GitHub CLI and requests library for Telegram
RUN apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/* && \
    pip install requests --no-cache-dir

CMD ["python", "worker.py"]
