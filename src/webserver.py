"""
Module      : webserver
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Flask-basiertes Webinterface mit REST API für Listenanzeige,
              Item-CRUD, Konfigurationsverwaltung und OAuth-Login-Flows
              für Amazon und Microsoft.
"""

import json
import logging
import os
import subprocess
import sys
import threading

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(__file__))

from alexa import AlexaAPI
from mstodo import MSTodo
from utils import load_config as _load_config

log = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "./config/config.json")
app = Flask(__name__, static_folder="web", static_url_path="")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    return _load_config(CONFIG_PATH)


def save_config(data: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


_alexa = None
_todo = None


def get_alexa() -> AlexaAPI:
    global _alexa
    if _alexa is None:
        _alexa = AlexaAPI(load_config())
    return _alexa


def get_todo() -> MSTodo:
    global _todo
    if _todo is None:
        config = load_config()
        _todo = MSTodo(config, config_path=CONFIG_PATH)
        _todo.connect()
    return _todo


def load_state() -> dict:
    state_path = os.path.join(os.path.dirname(CONFIG_PATH), "state.json")
    if os.path.exists(state_path):
        with open(state_path) as f:
            return json.load(f)
    return {"items": []}


# ---------------------------------------------------------------------------
# Static UI
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# API — Listen
# ---------------------------------------------------------------------------

@app.route("/api/alexa/items", methods=["GET"])
def alexa_items():
    try:
        alexa = get_alexa()
        items = alexa.get_active_items()
        return jsonify([{"id": i.id, "value": i.value} for i in items])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/alexa/items", methods=["POST"])
def alexa_add_item():
    value = request.json.get("value", "").strip()
    if not value:
        return jsonify({"error": "value required"}), 400
    try:
        alexa = get_alexa()
        item = alexa.add_item(value)
        return jsonify({"id": item.id, "value": item.value})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/alexa/items/<item_id>", methods=["DELETE"])
def alexa_delete_item(item_id):
    try:
        alexa = get_alexa()
        items = alexa.get_active_items()
        item = next((i for i in items if i.id == item_id), None)
        if not item:
            return jsonify({"error": "not found"}), 404
        alexa.delete_item(item)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/todo/items", methods=["GET"])
def todo_items():
    try:
        todo = get_todo()
        items = todo.get_items()
        return jsonify([{"id": i.id, "value": i.value, "completed": i.completed} for i in items])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/todo/items", methods=["POST"])
def todo_add_item():
    value = request.json.get("value", "").strip()
    if not value:
        return jsonify({"error": "value required"}), 400
    try:
        todo = get_todo()
        item = todo.add_item(value)
        return jsonify({"id": item.id, "value": item.value})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/todo/items/<item_id>", methods=["DELETE"])
def todo_delete_item(item_id):
    try:
        todo = get_todo()
        items = todo.get_items()
        item = next((i for i in items if i.id == item_id), None)
        if not item:
            return jsonify({"error": "not found"}), 404
        todo.delete_item(item)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API — State
# ---------------------------------------------------------------------------

@app.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(load_state())


@app.route("/api/state/mtime", methods=["GET"])
def state_mtime():
    state_path = os.path.join(os.path.dirname(CONFIG_PATH), "state.json")
    if os.path.exists(state_path):
        return jsonify({"mtime": os.path.getmtime(state_path)})
    return jsonify({"mtime": 0})


# ---------------------------------------------------------------------------
# API — Config
# ---------------------------------------------------------------------------

@app.route("/api/config", methods=["GET"])
def get_config():
    try:
        config = load_config()
        # Sensitive Felder nicht zurückgeben
        safe = {k: v for k, v in config.items()
                if k not in ("ms_refresh_token", "amazon_password", "amazon_mfa_secret")}
        return jsonify(safe)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def update_config():
    try:
        config = load_config()
        allowed = (
            "sync_direction", "delete_origin", "sync_interval",
            "alexa_list_name", "ms_list_name",
            "webserver", "webserver_port", "amazon_url",
        )
        for key in allowed:
            if key in request.json:
                config[key] = request.json[key]
        save_config(config)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API — Alexa Listen
# ---------------------------------------------------------------------------

@app.route("/api/alexa/lists", methods=["GET"])
def alexa_lists():
    try:
        alexa = get_alexa()
        alexa._ensure_logged_in()
        url = f"https://www.{alexa.amazon_url}/alexashoppinglists/api/v2/lists/fetch"
        data = alexa._post(url, {})
        lists = [
            {"id": l.get("listId"), "name": l.get("listName") or l.get("listType")}
            for l in data.get("listInfoList", [])
        ]
        return jsonify(lists)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API — MS Todo Listen
# ---------------------------------------------------------------------------

@app.route("/api/todo/lists", methods=["GET"])
def todo_lists():
    try:
        todo = get_todo()
        data = todo._get("/me/todo/lists")
        lists = [{"id": l["id"], "name": l["displayName"]} for l in data.get("value", [])]
        return jsonify(lists)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API — Amazon Login (startet amazon_login.py)
# ---------------------------------------------------------------------------

proxy_process = None
proxy_lock = threading.Lock()


@app.route("/api/login/amazon/start", methods=["POST"])
def amazon_login_start():
    global proxy_process
    with proxy_lock:
        if proxy_process and proxy_process.poll() is None:
            return jsonify({"ok": True, "running": True})
        script = os.path.join(os.path.dirname(__file__), "amazon_login.py")
        proxy_process = subprocess.Popen(
            [sys.executable, script, "--config", CONFIG_PATH, "--port", "8765"],
        )
        return jsonify({"ok": True, "running": True, "url": "http://localhost:8765/"})


@app.route("/api/login/amazon/stop", methods=["POST"])
def amazon_login_stop():
    global proxy_process
    with proxy_lock:
        if proxy_process and proxy_process.poll() is None:
            proxy_process.terminate()
        return jsonify({"ok": True})


@app.route("/api/login/amazon/status", methods=["GET"])
def amazon_login_status():
    cookie_file = os.path.join(
        os.path.dirname(CONFIG_PATH),
        load_config().get("alexa_cookie_file", "alexa_cookie.json")
    )
    connected = os.path.exists(cookie_file)
    running = proxy_process is not None and proxy_process.poll() is None
    return jsonify({"connected": connected, "proxy_running": running})


# ---------------------------------------------------------------------------
# API — Microsoft Login
# ---------------------------------------------------------------------------

ms_login_state = {"running": False, "user_code": None, "verification_uri": None, "error": None}
ms_login_lock = threading.Lock()


def _run_ms_device_flow():
    global ms_login_state
    try:
        todo = get_todo()
        flow = todo._app.initiate_device_flow(scopes=["Tasks.ReadWrite"])
        if "user_code" not in flow:
            with ms_login_lock:
                ms_login_state["error"] = flow.get("error_description", "Device flow failed")
                ms_login_state["running"] = False
            return
        with ms_login_lock:
            ms_login_state["user_code"] = flow["user_code"]
            ms_login_state["verification_uri"] = flow.get("verification_uri", "https://microsoft.com/devicelogin")
        result = todo._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            with ms_login_lock:
                ms_login_state["error"] = result.get("error_description", "Auth failed")
        elif "refresh_token" in result:
            todo._save_refresh_token(result["refresh_token"])
    except Exception as e:
        with ms_login_lock:
            ms_login_state["error"] = str(e)
    finally:
        with ms_login_lock:
            ms_login_state["running"] = False
            ms_login_state["user_code"] = None
            ms_login_state["verification_uri"] = None


@app.route("/api/login/microsoft/start", methods=["POST"])
def ms_login_start():
    global ms_login_state
    with ms_login_lock:
        if ms_login_state["running"]:
            return jsonify({"ok": True, "already_running": True})
        ms_login_state = {"running": True, "user_code": None, "verification_uri": None, "error": None}
    t = threading.Thread(target=_run_ms_device_flow, daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/login/microsoft/status", methods=["GET"])
def ms_login_status():
    try:
        config = load_config()
        token_file = config.get("ms_token_file", "ms_token.json")
        config_dir = os.path.dirname(os.path.abspath(CONFIG_PATH))
        token_path = token_file if os.path.isabs(token_file) else os.path.join(config_dir, token_file)
        connected = os.path.exists(token_path) or bool(config.get("ms_refresh_token"))
        with ms_login_lock:
            state = dict(ms_login_state)
        return jsonify({"connected": connected, **state})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="alexa2mstodo Web Interface")
    parser.add_argument("--config", default=os.environ.get("CONFIG_PATH", "./config/config.json"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    CONFIG_PATH = args.config
    os.environ["CONFIG_PATH"] = CONFIG_PATH

    log.info("Web Interface: http://%s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False)
