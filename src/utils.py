"""
Module      : utils
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Gemeinsame Hilfsfunktionen für Konfigurationsladung,
              Pfadauflösung und interaktive Listenauswahl.
"""

import json
import logging
import os
import sys

log = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        log.error("Config nicht gefunden: %s", path)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def resolve_path(path: str, config_path: str) -> str:
    """Löst einen relativen Pfad relativ zur config-Datei auf."""
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), path)


def choose_from_list(items: list, label_fn, title: str) -> int:
    """Interaktive Auswahl aus einer Liste. Gibt den Index zurück."""
    print(f"\n{title}")
    for i, item in enumerate(items):
        print(f"  [{i}] {label_fn(item)}")
    choice = input("\nNummer wählen: ").strip()
    try:
        idx = int(choice)
        if 0 <= idx < len(items):
            return idx
    except ValueError:
        pass
    print("Ungültige Auswahl.")
    sys.exit(1)


def choose_alexa_list(config: dict) -> tuple[str, str]:
    """Gibt (listId, listName) zurück."""
    from alexa import AlexaAPI
    alexa = AlexaAPI(config)
    alexa._ensure_logged_in()
    url = f"https://www.{alexa.amazon_url}/alexashoppinglists/api/v2/lists/fetch"
    data = alexa._post(url, {})
    lists = data.get("listInfoList", [])
    if not lists:
        print("Keine Alexa-Listen gefunden.")
        sys.exit(1)
    idx = choose_from_list(
        lists,
        lambda lst: lst.get("listName") or lst.get("listType") or "?",
        "Verfügbare Alexa-Listen:",
    )
    chosen = lists[idx]
    return chosen.get("listId"), chosen.get("listName") or chosen.get("listType")


def choose_todo_list(config: dict, config_path: str) -> tuple[str, str]:
    """Gibt (listId, listName) zurück."""
    from mstodo import MSTodo
    todo = MSTodo(config, config_path=config_path)
    todo.connect()
    data = todo._get("/me/todo/lists")
    lists = data.get("value", [])
    if not lists:
        print("Keine MS-Todo-Listen gefunden.")
        sys.exit(1)
    idx = choose_from_list(lists, lambda lst: lst["displayName"], "Verfügbare MS-Todo-Listen:")
    chosen = lists[idx]
    return chosen["id"], chosen["displayName"]
