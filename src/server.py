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

    if direction == "a2m":
        SyncClass = SynchronizerA2M
    elif direction == "both":
        SyncClass = Synchronizer
    else:
        log.error("Ungültige sync_direction '%s' — erlaubt: both, a2m", direction)
        sys.exit(1)
    sync = SyncClass(config, state_path=os.path.join(os.path.dirname(CONFIG_PATH), "state.json"))

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
