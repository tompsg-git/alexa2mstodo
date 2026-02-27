"""
alexa2mstodo — Restore

Usage:
    python3 restore.py [--config PATH] [--dir DIR]

1. Auswahl der Backup-Datei
2. Auswahl: Alexa oder MS Todo
3. Auswahl der Zielliste
4. Restore
"""

import json
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(__file__))

from alexa import AlexaAPI
from mstodo import MSTodo


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        print(f"Config nicht gefunden: {path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def choose_backup_file(backup_dir: str) -> str:
    files = sorted(glob.glob(os.path.join(backup_dir, "backup_*.json")), reverse=True)
    if not files:
        print(f"Keine Backup-Dateien gefunden in: {backup_dir}")
        sys.exit(1)
    print("\nVerfügbare Backup-Dateien:")
    for i, f in enumerate(files):
        print(f"  [{i}] {os.path.basename(f)}")
    choice = input("\nNummer wählen: ").strip()
    try:
        return files[int(choice)]
    except (ValueError, IndexError):
        print("Ungültige Auswahl.")
        sys.exit(1)


def choose_target() -> str:
    print("\nZiel:")
    print("  [0] Alexa")
    print("  [1] MS Todo")
    choice = input("\nNummer wählen: ").strip()
    if choice == "0":
        return "alexa"
    elif choice == "1":
        return "todo"
    else:
        print("Ungültige Auswahl.")
        sys.exit(1)


def choose_alexa_list(config: dict) -> tuple[str, str]:
    alexa = AlexaAPI(config)
    alexa._ensure_logged_in()
    url = f"https://www.{alexa.amazon_url}/alexashoppinglists/api/v2/lists/fetch"
    data = alexa._post(url, {})
    lists = data.get("listInfoList", [])
    if not lists:
        print("Keine Alexa-Listen gefunden.")
        sys.exit(1)
    print("\nVerfügbare Alexa-Listen:")
    for i, lst in enumerate(lists):
        name = lst.get("listName") or lst.get("listType") or "?"
        print(f"  [{i}] {name}")
    choice = input("\nNummer wählen: ").strip()
    try:
        chosen = lists[int(choice)]
        return chosen.get("listId"), chosen.get("listName") or chosen.get("listType")
    except (ValueError, IndexError):
        print("Ungültige Auswahl.")
        sys.exit(1)


def choose_todo_list(config: dict, config_path: str) -> tuple[str, str]:
    todo = MSTodo(config, config_path=config_path)
    todo._acquire_token()
    data = todo._get("/me/todo/lists")
    lists = data.get("value", [])
    if not lists:
        print("Keine MS-Todo-Listen gefunden.")
        sys.exit(1)
    print("\nVerfügbare MS-Todo-Listen:")
    for i, lst in enumerate(lists):
        print(f"  [{i}] {lst['displayName']}")
    choice = input("\nNummer wählen: ").strip()
    try:
        chosen = lists[int(choice)]
        return chosen["id"], chosen["displayName"]
    except (ValueError, IndexError):
        print("Ungültige Auswahl.")
        sys.exit(1)


def restore_to_alexa(config: dict, backup_file: str, list_id: str, list_name: str):
    with open(backup_file) as f:
        items = json.load(f)
    print(f"\n{len(items)} Items aus {os.path.basename(backup_file)} → Alexa '{list_name}'")
    confirm = input("Fortfahren? [j/N] ").strip().lower()
    if confirm != "j":
        print("Abgebrochen.")
        sys.exit(0)
    alexa = AlexaAPI(config)
    alexa._ensure_logged_in()
    alexa._list_id = list_id
    existing = {i.value.lower() for i in alexa.get_active_items()}
    added = 0
    for item in items:
        if item["value"].lower() not in existing:
            alexa.add_item(item["value"])
            print(f"  + {item['value']}")
            added += 1
    print(f"Fertig: {added} Items hinzugefügt.")


def restore_to_todo(config: dict, backup_file: str, list_id: str, list_name: str, config_path: str):
    with open(backup_file) as f:
        items = json.load(f)
    print(f"\n{len(items)} Items aus {os.path.basename(backup_file)} → MS Todo '{list_name}'")
    confirm = input("Fortfahren? [j/N] ").strip().lower()
    if confirm != "j":
        print("Abgebrochen.")
        sys.exit(0)
    todo = MSTodo(config, config_path=config_path)
    todo.connect()
    todo._list_id = list_id
    existing = {i.value.lower() for i in todo.get_items()}
    added = 0
    for item in items:
        if item["value"].lower() not in existing:
            todo.add_item(item["value"])
            print(f"  + {item['value']}")
            added += 1
    print(f"Fertig: {added} Items hinzugefügt.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="alexa2mstodo Restore")
    parser.add_argument("--config", default=os.environ.get("CONFIG_PATH", "/config/config.json"))
    parser.add_argument("--dir", default=".", help="Backup-Verzeichnis")
    args = parser.parse_args()

    os.environ["CONFIG_PATH"] = args.config
    config = load_config(args.config)

    backup_file = choose_backup_file(args.dir)
    target = choose_target()

    if target == "alexa":
        list_id, list_name = choose_alexa_list(config)
        restore_to_alexa(config, backup_file, list_id, list_name)
    elif target == "todo":
        list_id, list_name = choose_todo_list(config, args.config)
        restore_to_todo(config, backup_file, list_id, list_name, args.config)
