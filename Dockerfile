FROM python:3.12-slim

WORKDIR /app

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Quellcode kopieren
COPY src/ ./src/

# Vorlagen für config
COPY config.json.example ./config.json.example
COPY alexa_cookie.json.example ./alexa_cookie.json.example
COPY ms_token.json.example ./ms_token.json.example

# Entrypoint
COPY entrypoint.sh ./entrypoint.sh

ENV CONFIG_PATH=/config/config.json
ENV LOG_LEVEL=INFO
ENV TZ=Europe/Berlin

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
