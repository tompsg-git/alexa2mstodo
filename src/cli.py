"""
alexa2mstodo CLI — Backup & Restore

Usage:
    python3 cli.py backup  --source alexa --file config/backup/backup_alexa.json
    python3 cli.py backup  --source todo  --file config/backup/backup_todo.json

    python3 cli.py restore --file config/backup/backup_alexa.json --target alexa
    python3 cli.py restore --file config/backup/backup_todo.json  --target todo
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from alexa import AlexaAPI
from mstodo import MSTodo


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        print(f"Config nicht gefunden: {path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def do_backup(config: dict, source: str, backup_file: str, config_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(backup_file)), exist_ok=True)

    if source == "alexa":
        print("Lese Alexa-Liste...")
        alexa = AlexaAPI(config)
        items = alexa.get_active_items()
        data = [{"value": i.value, "status": i.status, "version": i.version} for i in items]
        with open(backup_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Alexa-Backup: {backup_file} ({len(items)} Items)")

    elif source == "todo":
        print("Lese MS-Todo-Liste...")
        todo = MSTodo(config, config_path=config_path)
        todo.connect()
        items = todo.get_items()
        data = [{"value": i.value, "completed": i.completed} for i in items]
        with open(backup_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Todo-Backup: {backup_file} ({len(items)} Items)")


def do_restore(config: dict, backup_file: str, target: str, config_path: str):
    if not os.path.exists(backup_file):
        print(f"Datei nicht gefunden: {backup_file}")
        sys.exit(1)

    with open(backup_file) as f:
        items = json.load(f)

    print(f"Wiederherstelle {len(items)} Items aus {backup_file} → {target}")
    confirm = input("Fortfahren? Fehlende Items werden hinzugefügt, bestehende bleiben erhalten. [j/N] ").strip().lower()
    if confirm != "j":
        print("Abgebrochen.")
        sys.exit(0)

    if target == "alexa":
        alexa = AlexaAPI(config)
        existing = {i.value.lower() for i in alexa.get_active_items()}
        added = 0
        for item in items:
            if item["value"].lower() not in existing:
                alexa.add_item(item["value"])
                print(f"  + {item['value']}")
                added += 1
        print(f"Fertig: {added} Items hinzugefügt.")

    elif target == "todo":
        todo = MSTodo(config, config_path=config_path)
        todo.connect()
        existing = {i.value.lower() for i in todo.get_items()}
        added = 0
        for item in items:
            if item["value"].lower() not in existing:
                todo.add_item(item["value"])
                print(f"  + {item['value']}")
                added += 1
        print(f"Fertig: {added} Items hinzugefügt.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="alexa2mstodo CLI")
    parser.add_argument("command", choices=["backup", "restore"])
    parser.add_argument("--config", default=os.environ.get("CONFIG_PATH", "/config/config.json"))
    parser.add_argument("--source", choices=["alexa", "todo"], help="Quelle (nur bei backup)")
    parser.add_argument("--file", required=True, help="Backup-Datei")
    parser.add_argument("--target", choices=["alexa", "todo"], help="Ziel (nur bei restore)")
    args = parser.parse_args()

    os.environ["CONFIG_PATH"] = args.config
    config = load_config(args.config)

    if args.command == "backup":
        if not args.source:
            print("--source ist erforderlich für backup (alexa oder todo)")
            sys.exit(1)
        do_backup(config, args.source, args.file, args.config)

    elif args.command == "restore":
        if not args.target:
            print("--target ist erforderlich für restore (alexa oder todo)")
            sys.exit(1)
        do_restore(config, args.file, args.target, args.config)
