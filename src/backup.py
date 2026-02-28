"""
alexa2mstodo — Backup

Usage:
    python3 backup.py [--config PATH] [--dir DIR]

1. Auswahl: Alexa oder MS Todo
2. Auswahl der verfügbaren Listen
3. Backup in JSON-Datei
"""

import json
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

from alexa import AlexaAPI
from mstodo import MSTodo
from utils import load_config, choose_from_list, choose_alexa_list, choose_todo_list

log = logging.getLogger(__name__)


def choose_source() -> str:
    options = ["Alexa", "MS Todo"]
    idx = choose_from_list(options, lambda x: x, "Quelle:")
    return ["alexa", "todo"][idx]


def backup_alexa(config: dict, list_id: str, list_name: str, backup_dir: str):
    alexa = AlexaAPI(config)
    alexa._list_id = list_id
    items = alexa.get_active_items()
    safe_name = list_name.replace(" ", "_").lower()
    backup_file = os.path.join(backup_dir, f"backup_alexa_{safe_name}_{date.today().isoformat()}.json")
    os.makedirs(backup_dir, exist_ok=True)
    with open(backup_file, "w") as f:
        json.dump([{"value": i.value, "status": i.status} for i in items], f, indent=2, ensure_ascii=False)
    print(f"Alexa-Backup gespeichert: {backup_file} ({len(items)} Items)")


def backup_todo(config: dict, list_id: str, list_name: str, backup_dir: str, config_path: str):
    todo = MSTodo(config, config_path=config_path)
    todo.connect()
    todo._list_id = list_id
    items = todo.get_items()
    safe_name = list_name.replace(" ", "_").lower()
    backup_file = os.path.join(backup_dir, f"backup_todo_{safe_name}_{date.today().isoformat()}.json")
    os.makedirs(backup_dir, exist_ok=True)
    with open(backup_file, "w") as f:
        json.dump([{"value": i.value, "completed": i.completed} for i in items], f, indent=2, ensure_ascii=False)
    print(f"Todo-Backup gespeichert: {backup_file} ({len(items)} Items)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="alexa2mstodo Backup")
    parser.add_argument("--config", default=os.environ.get("CONFIG_PATH", "/config/config.json"))
    parser.add_argument("--dir", default=".", help="Backup-Verzeichnis")
    args = parser.parse_args()

    os.environ["CONFIG_PATH"] = args.config
    config = load_config(args.config)
    source = choose_source()

    if source == "alexa":
        list_id, list_name = choose_alexa_list(config)
        backup_alexa(config, list_id, list_name, args.dir)
    else:
        list_id, list_name = choose_todo_list(config, args.config)
        backup_todo(config, list_id, list_name, args.dir, args.config)
