"""
alexa2mstodo — main entry point.

Reads config.json, authenticates both services, performs an initial sync,
then polls every SYNC_INTERVAL seconds.

Environment variables:
    CONFIG_PATH     Path to config.json  (default: /config/config.json)
    SYNC_INTERVAL   Seconds between sync cycles  (default: 30)
    LOG_LEVEL       Python logging level  (default: INFO)
"""

import json
import logging
import os
import sys
import time

from synchronizer import Synchronizer

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


def main():
    log.info("alexa2mstodo starting")
    log.info("Config: %s", CONFIG_PATH)
    config = load_config(CONFIG_PATH)
    SYNC_INTERVAL = int(config.get("sync_interval", os.environ.get("SYNC_INTERVAL", "30")))
    log.info("Sync interval: %ds", SYNC_INTERVAL)

    # Expose config path so mstodo.py can write the refresh token back
    os.environ["CONFIG_PATH"] = CONFIG_PATH

    sync = Synchronizer(config, state_path=os.path.join(os.path.dirname(CONFIG_PATH), "state.json"))

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
