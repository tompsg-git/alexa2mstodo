#!/bin/sh
set -e

CONFIG_PATH="${CONFIG_PATH:-/config/config.json}"
CONFIG_DIR=$(dirname "$CONFIG_PATH")

mkdir -p "$CONFIG_DIR"

# Config anlegen falls nicht vorhanden
if [ ! -f "$CONFIG_PATH" ]; then
    echo "Keine config.json gefunden — Vorlage wird kopiert nach $CONFIG_PATH"
    cp /app/config.json.example "$CONFIG_PATH"
fi

# Cookie-Datei anlegen falls nicht vorhanden
COOKIE_FILE="$CONFIG_DIR/alexa_cookie.json"
if [ ! -f "$COOKIE_FILE" ]; then
    cp /app/alexa_cookie.json.example "$COOKIE_FILE"
fi

# Token-Datei anlegen falls nicht vorhanden
TOKEN_FILE="$CONFIG_DIR/ms_token.json"
if [ ! -f "$TOKEN_FILE" ]; then
    cp /app/ms_token.json.example "$TOKEN_FILE"
fi

exec python3 /app/src/server.py "$@"
