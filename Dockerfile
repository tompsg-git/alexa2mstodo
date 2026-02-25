FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/*.py ./

# Config and state are mounted here
VOLUME ["/config"]

ENV CONFIG_PATH=/config/config.json
ENV SYNC_INTERVAL=30
ENV LOG_LEVEL=INFO

CMD ["python", "-u", "server.py"]
