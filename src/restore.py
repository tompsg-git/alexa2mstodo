"""
alexa2mstodo — Restore

Usage:
    python3 restore.py [--config PATH] [--dir DIR]

1. Auswahl der Backup-Datei
2. Auswahl: Alexa oder MS Todo
3. Auswahl der Zielliste
4. Restore (nur fehlende Items)
"""

import glob
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from alexa import AlexaAPI
from mstodo import MSTodo
from utils import load_config, choose_from_list, choose_alexa_list, choose_todo_list

log = logging.getLogger(__name__)


def choose_backup_file(backup_dir: str) -> str:
    files = sorted(glob.glob(os.path.join(backup_dir, "backup_*.json")), reverse=True)
    if not files:
        print(f"Keine Backup-Dateien gefunden in: {backup_dir}")
        sys.exit(1)
    idx = choose_from_list(files, os.path.basename, "Verfügbare Backup-Dateien:")
    return files[idx]


def choose_target() -> str:
    options = ["Alexa", "MS Todo"]
    idx = choose_from_list(options, lambda x: x, "Ziel:")
    return ["alexa", "todo"][idx]


def restore_alexa(config: dict, list_id: str, items: list):
    alexa = AlexaAPI(config)
    alexa._list_id = list_id
    existing = {i.value.lower() for i in alexa.get_active_items()}
    added = 0
    for item in items:
        if item["value"].lower() not in existing:
            alexa.add_item(item["value"])
            added += 1
    print(f"Alexa-Restore: {added} Items hinzugefügt, {len(items) - added} bereits vorhanden.")


def restore_todo(config: dict, config_path: str, list_id: str, items: list):
    todo = MSTodo(config, config_path=config_path)
    todo.connect()
    todo._list_id = list_id
    existing = {i.value.lower() for i in todo.get_items()}
    added = 0
    for item in items:
        if item["value"].lower() not in existing:
            todo.add_item(item["value"])
            added += 1
    print(f"Todo-Restore: {added} Items hinzugefügt, {len(items) - added} bereits vorhanden.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="alexa2mstodo Restore")
    parser.add_argument("--config", default=os.environ.get("CONFIG_PATH", "/config/config.json"))
    parser.add_argument("--dir", default=".", help="Backup-Verzeichnis")
    args = parser.parse_args()

    os.environ["CONFIG_PATH"] = args.config
    config = load_config(args.config)

    backup_file = choose_backup_file(args.dir)
    with open(backup_file) as f:
        items = json.load(f)
    print(f"Backup geladen: {os.path.basename(backup_file)} ({len(items)} Items)")

    target = choose_target()

    if target == "alexa":
        list_id, list_name = choose_alexa_list(config)
        restore_alexa(config, list_id, items)
    else:
        list_id, list_name = choose_todo_list(config, args.config)
        restore_todo(config, args.config, list_id, items)
