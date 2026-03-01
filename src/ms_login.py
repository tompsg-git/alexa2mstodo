"""
Module      : ms_login
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Microsoft Device-Code-Flow Login. Startet den MSAL Device-Code-Flow,
              wartet auf Authentifizierung und speichert das Refresh-Token in
              ms_token.json. Kann direkt als Skript oder als Bibliothek verwendet
              werden (z. B. vom Webserver).
"""

import json
import logging
import os
import sys

import msal

log = logging.getLogger(__name__)

SCOPES = ["Tasks.ReadWrite"]


def run_device_flow(config: dict, config_path: str, on_code=None) -> str:
    """Führt den MSAL Device-Code-Flow durch und speichert das Refresh-Token.

    Args:
        config:      Geladenes config.json als dict.
        config_path: Pfad zur config.json (für relative Token-Datei-Auflösung).
        on_code:     Optionaler Callback(user_code, verification_uri), der aufgerufen
                     wird, sobald der Gerätecode bekannt ist. Fehlt er, wird die
                     Nachricht auf stdout ausgegeben.

    Returns:
        Das Refresh-Token als String.
    """
    client_id = config["ms_client_id"]
    tenant_id = config.get("ms_tenant_id", "consumers")
    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Device flow failed: {flow.get('error_description')}")

    if on_code:
        on_code(
            flow["user_code"],
            flow.get("verification_uri", "https://microsoft.com/devicelogin"),
        )
    else:
        print("\n" + "=" * 60)
        print("Microsoft To Do — Authentifizierung erforderlich")
        print("=" * 60)
        print(flow["message"])
        print("=" * 60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(
            f"Authentifizierung fehlgeschlagen: {result.get('error_description')}"
        )

    refresh_token = result.get("refresh_token")
    if refresh_token:
        _save_refresh_token(config, config_path, refresh_token)
        log.info("MS Login erfolgreich — Refresh-Token gespeichert.")

    return refresh_token


def _save_refresh_token(config: dict, config_path: str, refresh_token: str):
    token_file = config.get("ms_token_file", "ms_token.json")
    config_dir = os.path.dirname(os.path.abspath(config_path))
    token_path = (
        token_file if os.path.isabs(token_file)
        else os.path.join(config_dir, token_file)
    )
    with open(token_path, "w") as f:
        json.dump({"ms_refresh_token": refresh_token}, f, indent=4)
    log.info("Refresh-Token gespeichert: %s", token_path)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
        stream=sys.stdout,
    )
    parser = argparse.ArgumentParser(description="Microsoft To Do Device-Code Login")
    parser.add_argument(
        "--config",
        default=os.environ.get("CONFIG_PATH", "/config/config.json"),
    )
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    run_device_flow(cfg, args.config)
    print("\n Login erfolgreich abgeschlossen!\n")
