"""
Alexa Shopping List API wrapper.

Uses Amazon's internal REST API (the same endpoints the Alexa website uses).
Handles login with optional TOTP MFA via pyotp.

Required config keys:
    amazon_url          - e.g. "amazon.de" or "amazon.com"
    amazon_username     - Amazon account email
    amazon_password     - Amazon account password
    amazon_mfa_secret   - (optional) TOTP secret for 2FA
"""

import json
import logging
import time
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
    """Represents one item on the Alexa shopping list."""

    def __init__(self, item_id: str, value: str, status: str = "active", version: int = 1):
        self.id = item_id
        self.value = value
        self.status = status       # "active" | "completed"
        self.version = version

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    def __repr__(self):
        return f"AlexaItem({self.value!r}, {self.status})"


class AlexaAPI:
    """Thin wrapper around Amazon's Alexa list REST API."""

    def __init__(self, config: dict):
        self.amazon_url = config["amazon_url"].rstrip("/")
        self.username = config["amazon_username"]
        self.password = config["amazon_password"]
        self.mfa_secret = config.get("amazon_mfa_secret", "")

        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._logged_in = False

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def _sign_in(self):
        """Perform Amazon web login and populate session cookies."""
        log.info("Alexa: logging in to %s", self.amazon_url)
        base = f"https://www.{self.amazon_url}"
        signin_url = f"{base}/ap/signin"

        # Step 1: fetch the sign-in page to grab hidden fields
        r = self.session.get(
            signin_url,
            params={"openid.ns": "http://specs.openid.net/auth/2.0",
                    "openid.mode": "checkid_setup",
                    "openid.return_to": f"{base}/gp/yourstore/home",
                    "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
                    "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select"},
            timeout=30,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form", {"name": "signIn"}) or soup.find("form")
        if not form:
            raise RuntimeError("Could not find Amazon sign-in form")

        action = form.get("action", signin_url)
        fields: dict = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                fields[name] = value

        fields["email"] = self.username
        fields["password"] = self.password
        fields["rememberMe"] = "true"

        # Step 2: POST credentials
        r = self.session.post(action, data=fields, timeout=30, allow_redirects=True)
        r.raise_for_status()

        # Step 3: MFA if needed
        if "auth-mfa" in r.url or "mfa" in r.text.lower():
            if not self.mfa_secret:
                raise RuntimeError("Amazon requires MFA but no amazon_mfa_secret is configured")
            totp = pyotp.TOTP(self.mfa_secret)
            soup2 = BeautifulSoup(r.text, "html.parser")
            form2 = soup2.find("form")
            if not form2:
                raise RuntimeError("Could not find MFA form")
            action2 = form2.get("action", r.url)
            fields2: dict = {}
            for inp in form2.find_all("input"):
                name = inp.get("name")
                val = inp.get("value", "")
                if name:
                    fields2[name] = val
            fields2["otpCode"] = totp.now()
            fields2["rememberDevice"] = ""
            r = self.session.post(action2, data=fields2, timeout=30, allow_redirects=True)
            r.raise_for_status()

        # Verify we have session cookies
        if "session-id" not in self.session.cookies and "session-token" not in self.session.cookies:
            # Try a softer check — look for signin in the URL
            if "signin" in r.url:
                raise RuntimeError("Amazon login failed — check credentials/MFA")

        self._logged_in = True
        log.info("Alexa: login successful")

    def _ensure_logged_in(self):
        if not self._logged_in:
            self._sign_in()

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        self._ensure_logged_in()
        url = f"https://alexa.{self.amazon_url}{path}"
        r = self.session.request(method, url, timeout=30, **kwargs)
        if r.status_code == 401:
            log.warning("Alexa: 401, re-logging in")
            self._logged_in = False
            self._sign_in()
            r = self.session.request(method, url, timeout=30, **kwargs)
        r.raise_for_status()
        return r

    # ------------------------------------------------------------------
    # Shopping List API
    # ------------------------------------------------------------------

    def get_items(self) -> list[AlexaItem]:
        """Return all shopping list items (active + completed)."""
        r = self._api("GET", "/api/todos", params={
            "type": "SHOPPING_ITEM",
            "size": 200,
            "startTime": "",
        })
        data = r.json()
        items = []
        for i in data.get("values", []):
            items.append(AlexaItem(
                item_id=i["itemId"],
                value=i["value"],
                status=i.get("status", "active"),
                version=i.get("version", 1),
            ))
        return items

    def get_active_items(self) -> list[AlexaItem]:
        return [i for i in self.get_items() if not i.completed]

    def add_item(self, value: str) -> AlexaItem:
        """Add a new item to the shopping list."""
        log.info("Alexa: adding '%s'", value)
        r = self._api("POST", "/api/todos", json={
            "type": "SHOPPING_ITEM",
            "value": value,
        })
        data = r.json()
        return AlexaItem(
            item_id=data["itemId"],
            value=data["value"],
            status=data.get("status", "active"),
            version=data.get("version", 1),
        )

    def complete_item(self, item: AlexaItem):
        """Mark an item as completed (crossed off)."""
        log.info("Alexa: completing '%s'", item.value)
        self._api("PUT", f"/api/todos/{item.id}", json={
            "type": "SHOPPING_ITEM",
            "itemId": item.id,
            "value": item.value,
            "status": "completed",
            "version": item.version + 1,
        })
        item.status = "completed"

    def delete_item(self, item: AlexaItem):
        """Delete an item from the shopping list."""
        log.info("Alexa: deleting '%s'", item.value)
        self._api("DELETE", f"/api/todos/{item.id}", params={"type": "SHOPPING_ITEM"})

    def update_item(self, item: AlexaItem, new_value: str):
        """Rename / edit an existing item."""
        log.info("Alexa: updating '%s' → '%s'", item.value, new_value)
        self._api("PUT", f"/api/todos/{item.id}", json={
            "type": "SHOPPING_ITEM",
            "itemId": item.id,
            "value": new_value,
            "status": item.status,
            "version": item.version + 1,
        })
        item.value = new_value
        item.version += 1
