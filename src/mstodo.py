"""
Microsoft To Do integration via Microsoft Graph API.

Authentication uses MSAL with a Device Code Flow for the first login,
then stores the refresh token in config.json for subsequent runs.

Required config keys:
    ms_client_id     - Azure App Registration client ID (public client)
    ms_tenant_id     - "consumers" for personal accounts, or your tenant GUID
    ms_list_name     - Name of the To Do list to sync (will be created if absent)
    ms_refresh_token - (auto-written after first login)
"""

import json
import logging
import os
import time
from typing import Optional

import msal
import requests

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Tasks.ReadWrite"]


class MSTodoItem:
    """Represents a single task in Microsoft To Do."""

    def __init__(self, task_id: str, title: str, completed: bool = False, importance: str = "normal"):
        self.id = task_id
        self.value = title
        self.completed = completed
        self.importance = importance

    def __repr__(self):
        status = "✓" if self.completed else " "
        return f"[{status}] {self.value} ({self.id})"


class MSTodo:
    """Wrapper around the Microsoft Graph To Do API."""

    def __init__(self, config: dict, config_path: str = "config.json"):
        self.config = config
        self.config_path = config_path
        self.client_id = config["ms_client_id"]
        self.tenant_id = config.get("ms_tenant_id", "consumers")
        self.list_name = config["ms_list_name"]
        self._list_id: Optional[str] = None
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self._app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=authority,
        )

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _save_refresh_token(self, refresh_token: str):
        self.config["ms_refresh_token"] = refresh_token
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
            log.debug("Refresh token saved to %s", self.config_path)
        except OSError as e:
            log.warning("Could not save refresh token: %s", e)

    def _acquire_token(self) -> str:
        """Return a valid access token, refreshing or doing device-code flow as needed."""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        # 1) Try refresh token from config
        refresh_token = self.config.get("ms_refresh_token")
        if refresh_token:
            result = self._app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
            if "access_token" in result:
                self._access_token = result["access_token"]
                self._token_expiry = time.time() + result.get("expires_in", 3600)
                if "refresh_token" in result:
                    self._save_refresh_token(result["refresh_token"])
                return self._access_token
            log.warning("Refresh token invalid (%s), falling back to device code flow.",
                        result.get("error_description", "unknown"))

        # 2) Try cached accounts
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                self._token_expiry = time.time() + result.get("expires_in", 3600)
                return self._access_token

        # 3) Device code flow (interactive, first run)
        flow = self._app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Device flow failed: {flow.get('error_description')}")

        print("\n" + "=" * 60)
        print("Microsoft To Do — First-time authentication required")
        print("=" * 60)
        print(flow["message"])
        print("=" * 60 + "\n")

        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"Authentication failed: {result.get('error_description')}")

        self._access_token = result["access_token"]
        self._token_expiry = time.time() + result.get("expires_in", 3600)
        if "refresh_token" in result:
            self._save_refresh_token(result["refresh_token"])

        return self._access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._acquire_token()}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        r = requests.get(f"{GRAPH_BASE}{path}", headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = requests.post(f"{GRAPH_BASE}{path}", headers=self._headers(), json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, body: dict) -> dict:
        r = requests.patch(f"{GRAPH_BASE}{path}", headers=self._headers(), json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str):
        r = requests.delete(f"{GRAPH_BASE}{path}", headers=self._headers(), timeout=30)
        r.raise_for_status()

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _get_list_id(self) -> str:
        """Return the ID of the configured To Do list, creating it if needed."""
        if self._list_id:
            return self._list_id

        data = self._get("/me/todo/lists")

        # Immer alle Listen ausgeben
        log.info("=" * 40)
        log.info("ToDo: verfügbare Listen:")
        for lst in data.get("value", []):
            log.info("  MS Todo Liste: '%s'", lst["displayName"])

        for lst in data.get("value", []):
            if lst["displayName"].lower() == self.list_name.lower():
                self._list_id = lst["id"]
                log.info("MS Todo: using list '%s' (id=%s)", self.list_name, self._list_id)
                return self._list_id

        # Create the list
        log.info("List '%s' not found, creating it.", self.list_name)
        result = self._post("/me/todo/lists", {"displayName": self.list_name})
        self._list_id = result["id"]
        log.info("Created MS To Do list '%s' (id=%s)", self.list_name, self._list_id)
        return self._list_id

    # ------------------------------------------------------------------
    # Public API (mirrors anylist.py interface)
    # ------------------------------------------------------------------

    def connect(self):
        """Authenticate and resolve the list ID. Call once at startup."""
        log.info("Connecting to Microsoft To Do...")
        self._acquire_token()
        self._get_list_id()
        log.info("Connected. List: '%s'", self.list_name)

    def get_items(self) -> list[MSTodoItem]:
        """Return all *incomplete* tasks in the list."""
        lid = self._get_list_id()
        items = []
        url = f"/me/todo/lists/{lid}/tasks"
        params = {"$filter": "status ne 'completed'", "$top": 200}

        while url:
            data = self._get(url, params=params)
            for t in data.get("value", []):
                items.append(MSTodoItem(
                    task_id=t["id"],
                    title=t["title"],
                    completed=(t.get("status") == "completed"),
                    importance=t.get("importance", "normal"),
                ))
            url = data.get("@odata.nextLink", "").replace(GRAPH_BASE, "") or None
            params = None  # nextLink already contains query params

        log.debug("MS Todo: fetched %d active items", len(items))
        return items

    def add_item(self, title: str) -> MSTodoItem:
        """Add a new task and return it."""
        lid = self._get_list_id()
        log.info("MS Todo: adding '%s'", title)
        t = self._post(f"/me/todo/lists/{lid}/tasks", {"title": title})
        return MSTodoItem(task_id=t["id"], title=t["title"])

    def complete_item(self, item: MSTodoItem):
        """Mark a task as completed."""
        lid = self._get_list_id()
        log.info("MS Todo: completing '%s'", item.value)
        self._patch(
            f"/me/todo/lists/{lid}/tasks/{item.id}",
            {"status": "completed"},
        )
        item.completed = True

    def delete_item(self, item: MSTodoItem):
        """Permanently delete a task."""
        lid = self._get_list_id()
        log.info("MS Todo: deleting '%s'", item.value)
        self._delete(f"/me/todo/lists/{lid}/tasks/{item.id}")

    def update_item_title(self, item: MSTodoItem, new_title: str):
        """Rename a task."""
        lid = self._get_list_id()
        log.info("MS Todo: renaming '%s' → '%s'", item.value, new_title)
        self._patch(f"/me/todo/lists/{lid}/tasks/{item.id}", {"title": new_title})
        item.value = new_title
