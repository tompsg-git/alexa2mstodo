"""
Module      : server
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Haupteinstiegspunkt. Lädt die Konfiguration, authentifiziert
              beide Dienste, führt einen initialen Sync durch und startet
              danach die periodische Synchronisationsschleife.

Environment variables:
    CONFIG_PATH     Pfad zu config.json  (Standard: /config/config.json)
    SYNC_INTERVAL   Sekunden zwischen Sync-Zyklen  (Standard: 30)
    LOG_LEVEL       Python Logging-Level  (Standard: INFO)
"""

import json
import logging
import os
import sys
import threading
import time

from synchronizer import Synchronizer
from synchronizer_a2m import SynchronizerA2M

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.json")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    stream=sys.stdout,
)
log = logging.getLogger("server")


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        log.error("Config file not found: %s", path)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def _alexa_cookie_valid(path: str) -> bool:
    """True if alexa_cookie.json exists and contains a non-empty cookie string."""
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        cookie_str = data.get("localCookie") or data.get("cookie", "")
        return bool(cookie_str.strip())
    except (json.JSONDecodeError, OSError):
        return False


def _ms_token_valid(path: str, config: dict) -> bool:
    """True if ms_token.json exists with a non-empty refresh token, or config has one."""
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            token = data.get("ms_refresh_token") or ""
            if str(token).strip():
                return True
        except (json.JSONDecodeError, OSError):
            pass
    return bool((config.get("ms_refresh_token") or "").strip())


def _wait_for_credentials(config: dict, config_path: str) -> None:
    """Block until both Alexa cookie and MS token are present and valid.

    Runs before sync.connect() so that no interactive device-code flow is
    triggered while credentials are still missing.
    """
    from utils import resolve_path
    alexa_cookie = resolve_path(
        config.get("alexa_cookie_file", "alexa_cookie.json"), config_path
    )
    ms_token = resolve_path(
        config.get("ms_token_file", "ms_token.json"), config_path
    )
    while True:
        alexa_ok = _alexa_cookie_valid(alexa_cookie)
        ms_ok = _ms_token_valid(ms_token, config)
        if alexa_ok and ms_ok:
            log.info("Credentials valid — proceeding with connect.")
            return
        missing = []
        if not alexa_ok:
            missing.append(f"Alexa cookie ({alexa_cookie})")
        if not ms_ok:
            missing.append(f"MS token ({ms_token})")
        log.info("Waiting for valid credentials: %s", ", ".join(missing))
        time.sleep(10)


def main():
    config = load_config(CONFIG_PATH)

    SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", config.get("sync_interval", 30)))
    direction = os.environ.get("SYNC_DIRECTION", config.get("sync_direction", "both"))
    delete_origin = os.environ.get("DELETE_ORIGIN", str(config.get("delete_origin", False))).lower() == "true"

    # Zurückschreiben damit Synchronizer die Werte aus config liest
    config["sync_interval"] = SYNC_INTERVAL
    config["sync_direction"] = direction
    config["delete_origin"] = delete_origin

    log.info("=" * 40)
    log.info("  alexa2mstodo starting")
    log.info("  Config         : %s", CONFIG_PATH)
    log.info("  Sync direction : %s", direction)
    log.info("  Delete origin  : %s", delete_origin)
    log.info("  Sync interval  : %ds", SYNC_INTERVAL)
    log.info("=" * 40)

    # Expose config path so mstodo.py can write the refresh token back
    os.environ["CONFIG_PATH"] = CONFIG_PATH

    # Webserver
    if config.get("webserver", False):
        port = int(config.get("webserver_port", 8080))
        try:
            from webserver import app as web_app
            t = threading.Thread(
                target=lambda: web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
                daemon=True
            )
            t.start()
            log.info("  Web Interface  : http://0.0.0.0:%d", port)
        except Exception as e:
            log.warning("Webserver konnte nicht gestartet werden: %s", e)

    if direction == "a2m":
        SyncClass = SynchronizerA2M
    elif direction == "both":
        SyncClass = Synchronizer
    else:
        log.error("Ungültige sync_direction '%s' — erlaubt: both, a2m", direction)
        sys.exit(1)
    sync = SyncClass(config, state_path=os.path.join(os.path.dirname(CONFIG_PATH), "state.json"))

    # Wait until both Alexa cookie and MS token are present and valid.
    # This prevents a device-code flow from appearing in the log/shell before
    # the user has authenticated via the web interface.
    _wait_for_credentials(config, CONFIG_PATH)

    # Connect (triggers MS Todo device-code auth on first run)
    try:
        sync.connect()
    except Exception as e:
        log.error("Failed to connect: %s", e)
        sys.exit(2)

    # Initial merge
    state_file = os.path.join(os.path.dirname(CONFIG_PATH), "state.json")
    if not os.path.exists(state_file):
        log.info("No state file found — running initial sync")
        try:
            sync.initial_sync()
        except Exception as e:
            log.error("Initial sync failed: %s", e)
            # Not fatal — we'll try again on the next cycle

    # Main loop
    log.info("Entering sync loop (every %ds). Press Ctrl+C to stop.", SYNC_INTERVAL)
    while True:
        try:
            sync.sync()
        except KeyboardInterrupt:
            log.info("Interrupted by user.")
            break
        except Exception as e:
            log.error("Sync cycle error: %s", e, exc_info=True)
            # Container will restart on crash — but try to keep going
        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
