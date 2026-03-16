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
from utils import get_list_pairs, resolve_path

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


def _apply_env_overrides(config: dict) -> dict:
    """Überschreibt ausgewählte Config-Werte mit Umgebungsvariablen."""
    if "SYNC_INTERVAL" in os.environ:
        config["sync_interval"] = int(os.environ["SYNC_INTERVAL"])
    if "SYNC_DIRECTION" in os.environ:
        config["sync_direction"] = os.environ["SYNC_DIRECTION"]
    if "DELETE_ORIGIN" in os.environ:
        config["delete_origin"] = os.environ["DELETE_ORIGIN"].lower() == "true"
    return config


def _make_sync(config: dict, pair: dict, config_dir: str, multi: bool):
    """Erstellt einen Synchronizer für ein Listen-Paar."""
    dir_pair = pair["sync_direction"]
    SyncClass = SynchronizerA2M if dir_pair == "a2m" else Synchronizer
    pair_config = {
        **config,
        "alexa_list_name": pair["alexa"],
        "ms_list_name": pair["ms"],
        "sync_direction": dir_pair,
        "delete_origin": pair["delete_origin"],
        "sync_interval": pair["sync_interval"],
    }
    if multi:
        safe = pair["alexa"].lower().replace(" ", "_")
        state_path = os.path.join(config_dir, f"state_{safe}.json")
    else:
        state_path = os.path.join(config_dir, "state.json")
    return SyncClass(pair_config, state_path=state_path)


def _connect_and_init(sync) -> bool:
    """Verbindet einen Synchronizer und führt ggf. Initial-Sync durch.
    Gibt True bei Erfolg zurück."""
    alexa_name = sync.config["alexa_list_name"]
    ms_name = sync.config["ms_list_name"]
    try:
        sync.connect()
    except Exception as e:
        log.error("Failed to connect ('%s' ↔ '%s'): %s", alexa_name, ms_name, e)
        return False
    if not os.path.exists(sync.state_path):
        log.info("No state file for '%s' — running initial sync", alexa_name)
        try:
            sync.initial_sync()
        except Exception as e:
            log.error("Initial sync failed for '%s': %s", alexa_name, e)
    return True


def main():
    config = load_config(CONFIG_PATH)
    _apply_env_overrides(config)

    log.info("=" * 40)
    log.info("  alexa2mstodo starting")
    log.info("  Config         : %s", CONFIG_PATH)
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

    config_dir = os.path.dirname(os.path.abspath(CONFIG_PATH))

    _wait_for_credentials(config, CONFIG_PATH)

    # Initiale Paare aufbauen und verbinden
    pairs = get_list_pairs(config)
    multi = "lists" in config
    syncs: list = []
    last_sync: list = []

    for pair in pairs:
        sync = _make_sync(config, pair, config_dir, multi)
        if _connect_and_init(sync):
            log.info("  Paar: '%s' ↔ '%s' [%s, %ds]",
                     pair["alexa"], pair["ms"], pair["sync_direction"], pair["sync_interval"])
            syncs.append(sync)
            last_sync.append(0.0)
        else:
            sys.exit(2)

    # Main loop — per-pair interval tracking + Config-Hot-Reload
    log.info("Entering sync loop. Press Ctrl+C to stop.")
    while True:
        # Config neu lesen und auf Änderungen prüfen
        try:
            fresh_config = load_config(CONFIG_PATH)
            _apply_env_overrides(fresh_config)
            fresh_pairs = get_list_pairs(fresh_config)
            fresh_multi = "lists" in fresh_config
        except Exception as e:
            log.warning("Config reload failed: %s", e)
            fresh_pairs = pairs
            fresh_config = config
            fresh_multi = multi

        if fresh_pairs != pairs:
            log.info("Konfiguration geändert — Liste der Paare wird aktualisiert")
            old_last = {(pairs[i]["alexa"], pairs[i]["ms"]): last_sync[i]
                        for i in range(len(pairs))}
            new_syncs, new_last = [], []
            for pair in fresh_pairs:
                key = (pair["alexa"], pair["ms"])
                sync = _make_sync(fresh_config, pair, config_dir, fresh_multi)
                if key in old_last:
                    # Bestehendes Paar — last_sync-Zeit übernehmen
                    new_syncs.append(sync)
                    new_last.append(old_last[key])
                else:
                    # Neues Paar — verbinden und sofort in den Loop aufnehmen
                    log.info("Neues Paar: '%s' ↔ '%s'", pair["alexa"], pair["ms"])
                    if _connect_and_init(sync):
                        new_syncs.append(sync)
                        new_last.append(0.0)
            pairs, syncs, last_sync = fresh_pairs, new_syncs, new_last
            config, multi = fresh_config, fresh_multi

        now = time.time()
        sync_intervals = [p["sync_interval"] for p in pairs]
        for i, sync in enumerate(syncs):
            if now - last_sync[i] >= sync_intervals[i]:
                try:
                    sync.sync()
                except KeyboardInterrupt:
                    log.info("Interrupted by user.")
                    sys.exit(0)
                except Exception as e:
                    log.error("Sync cycle error ('%s'): %s",
                              sync.config["alexa_list_name"], e, exc_info=True)
                last_sync[i] = time.time()
        time.sleep(1)


if __name__ == "__main__":
    main()
