"""
Alexa Shopping List wrapper using the internal V2 API.

Endpoints discovered from alexa-remote2 (Apollon77):
  GET  /api/household                                           → list all lists
  GET  /alexashoppinglists/api/v2/lists/{listId}/items/fetch   → get items
  POST /alexashoppinglists/api/v2/lists/{listId}/items         → add item
  PUT  /alexashoppinglists/api/v2/lists/{listId}/items/{id}    → update item
  DELETE /alexashoppinglists/api/v2/lists/{listId}/items/{id}  → delete item
"""

import logging
import os
from typing import Optional

import pyotp
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class AlexaItem:
    def __init__(self, item_id: str, value: str, status: str = "active", version: int = 1):
        self.id = item_id
        self.value = value
        self.status = status
        self.version = version

    @property
    def completed(self):
        return self.status == "completed"

    def __repr__(self):
        return f"AlexaItem({self.value!r}, {self.status})"


class AlexaAPI:
    def __init__(self, config: dict):
        self.config = config
        self.amazon_url = config["amazon_url"].rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._logged_in = False
        self._list_id: Optional[str] = None

    def _load_cookies(self):
        import json
        from utils import resolve_path
        config_path = os.environ.get("CONFIG_PATH", "/config/config.json")
        cookie_file = resolve_path(
            self.config.get("alexa_cookie_file", "alexa_cookie.json"),
            config_path
        )
        with open(cookie_file) as f:
            data = json.load(f)

        # Cookie-String in Session laden
        cookie_string = data.get("localCookie") or data.get("cookie", "")
        for part in cookie_string.split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                self.session.cookies.set(name.strip(), value.strip())

        # CSRF-Token als Header setzen
        # csrf = data.get("csrf-token")
        # if csrf:
            # self.session.headers.update({"csrf": csrf})
            # log.info("Alexa: CSRF token loaded from file")

        self._logged_in = True
        log.info("Alexa: cookies loaded from %s", cookie_file)

    def _ensure_logged_in(self):
        if not self._logged_in:
            self._load_cookies()

    def _get(self, url, params=None):
        self._ensure_logged_in()
        r = self.session.get(url, params=params, timeout=30)
        if r.status_code == 401:
            log.warning("Alexa: 401, re-logging in")
            self._logged_in = False
            self._load_cookies()
            r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, url, body):
        self._ensure_logged_in()
        r = self.session.post(url, json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _put(self, url, body):
        self._ensure_logged_in()
        r = self.session.put(url, json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _delete(self, url, params=None):
        self._ensure_logged_in()
        r = self.session.delete(url, params=params, timeout=30)
        r.raise_for_status()

    def _get_list_id(self):
        if self._list_id:
            return self._list_id
        url = f"https://www.{self.amazon_url}/alexashoppinglists/api/v2/lists/fetch"
        data = self._post(url, {})
        lists = data.get("listInfoList", [])

        # Immer alle Listen ausgeben
        log.info("Alexa: verfügbare Listen:")
        for lst in lists:
            name = lst.get("listName") or lst.get("listType") or "?"
            log.info("  - '%s'", name)

        target = self.config.get("alexa_list_name", "shop").lower()
        for lst in lists:
            name = (lst.get("listName") or lst.get("listType") or "").lower()
            ltype = (lst.get("listType") or "").lower()
            if name == target or ltype == target:
                self._list_id = lst.get("listId")
                log.info("Alexa: using list '%s' (id=%s)", name, self._list_id)
                return self._list_id

        if lists:
            self._list_id = lists[0].get("listId")
            log.warning("Alexa: list '%s' not found, using first", target)
            return self._list_id
        raise RuntimeError(f"No Alexa lists found. Response: {data}")

    def get_items(self):
        lid = self._get_list_id()
        url = f"https://www.{self.amazon_url}/alexashoppinglists/api/v2/lists/{lid}/items/fetch"
        data = self._post(url, {"limit": 100})
        log.debug("Alexa items: %s", data)
        items = []
        for i in data.get("itemInfoList", []):
            status = "completed" if i.get("itemStatus") == "COMPLETE" else "active"
            items.append(AlexaItem(
                item_id=i["itemId"],
                value=i.get("itemName", ""),
                status=status,
                version=i.get("version", 1),
            ))
        return items

    def get_active_items(self):
        return [i for i in self.get_items() if not i.completed]

    def add_item(self, value):
        lid = self._get_list_id()
        log.info("Alexa: adding '%s'", value)
        url = f"https://www.{self.amazon_url}/alexashoppinglists/api/v2/lists/{lid}/items"
        data = self._post(url, {"items": [{"itemName": value, "quantity": "1", "itemType": "KEYWORD"}]})
        log.debug("Alexa add response: %s", data)
        items = data.get("itemInfoList", [])
        if items:
            i = items[0]
            return AlexaItem(item_id=i["itemId"], value=i.get("itemName", value), version=i.get("version", 1))
        return AlexaItem(item_id="unknown", value=value)

    def delete_item(self, item):
        lid = self._get_list_id()
        log.info("Alexa: deleting '%s'", item.value)
        url = f"https://www.{self.amazon_url}/alexashoppinglists/api/v2/lists/{lid}/items/{item.id}"
        self._delete(url, params={"version": item.version})

    def complete_item(self, item):
        self.delete_item(item)
        item.status = "completed"

    def update_item(self, item, new_value):
        lid = self._get_list_id()
        log.info("Alexa: updating '%s' -> '%s'", item.value, new_value)
        url = f"https://www.{self.amazon_url}/alexashoppinglists/api/v2/lists/{lid}/items/{item.id}"
        self._put(url, {"value": new_value, "version": item.version, "quantity": "1"})
        item.value = new_value
        item.version += 1
