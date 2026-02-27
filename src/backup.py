"""
alexa2mstodo — Backup

Usage:
    python3 backup.py [--config PATH] [--dir DIR]

1. Auswahl: Alexa oder MS Todo
2. Auswahl der verfügbaren Listen
3. Backup in JSON-Datei
"""

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

from alexa import AlexaAPI
from mstodo import MSTodo


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        print(f"Config nicht gefunden: {path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def choose_source() -> str:
    print("\nQuelle:")
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
    """Gibt (listId, listName) zurück."""
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
    """Gibt (listId, listName) zurück."""
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


def backup_alexa(config: dict, list_id: str, list_name: str, backup_dir: str):
    alexa = AlexaAPI(config)
    alexa._ensure_logged_in()
    alexa._list_id = list_id
    items = alexa.get_active_items()
    today = date.today().isoformat()
    safe_name = list_name.replace(" ", "_").lower()
    backup_file = os.path.join(backup_dir, f"backup_alexa_{safe_name}_{today}.json")
    os.makedirs(backup_dir, exist_ok=True)
    with open(backup_file, "w") as f:
        json.dump([{"value": i.value, "status": i.status} for i in items], f, indent=2, ensure_ascii=False)
    print(f"Alexa-Backup gespeichert: {backup_file} ({len(items)} Items)")


def backup_todo(config: dict, list_id: str, list_name: str, backup_dir: str, config_path: str):
    todo = MSTodo(config, config_path=config_path)
    todo.connect()
    todo._list_id = list_id
    items = todo.get_items()
    today = date.today().isoformat()
    safe_name = list_name.replace(" ", "_").lower()
    backup_file = os.path.join(backup_dir, f"backup_todo_{safe_name}_{today}.json")
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
    elif source == "todo":
        list_id, list_name = choose_todo_list(config, args.config)
        backup_todo(config, list_id, list_name, args.dir, args.config)
