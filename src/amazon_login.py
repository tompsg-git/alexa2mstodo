"""
alexa2mstodo — Amazon Login via Browser-Proxy

Implementiert den gleichen Proxy-Ansatz wie alexa-cookie2:
- Alle Amazon-URLs werden durch den Proxy geleitet
- https://www.amazon.de/... → http://localhost:PORT/www.amazon.de/...
- https://alexa.amazon.de/... → http://localhost:PORT/alexa.amazon.de/...

Usage:
    python3 amazon_login.py [--config PATH] [--port PORT]
"""

import base64
import hashlib
import http.server
import json
import logging
import os
import re
import secrets
import socketserver
import ssl
import sys
import threading
import urllib.parse
import urllib.request
import urllib.error
import gzip
import zlib

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("amazon_login")

LOGIN_DONE = threading.Event()
CAPTURED = {}
PROXY_PORT = 8765
PROXY_HOST = "localhost"


def generate_device_id() -> str:
    buf = secrets.token_bytes(32)
    return buf.hex() + "23413249564c5635564d32573831"


def pkce_pair() -> tuple:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_signin_url(amazon_page: str, device_id: str, code_challenge: str) -> str:
    tld = amazon_page.split(".")[-1]
    handle_map = {"de": "_de", "co.uk": "_uk", "es": "_es", "fr": "_fr", "it": "_it", "com": ""}
    handle = handle_map.get(tld, f"_{tld}")
    base = f"https://www.{amazon_page}"
    params = urllib.parse.urlencode({
        "openid.return_to": f"{base}/ap/maplanding",
        "openid.assoc_handle": f"amzn_dp_project_dee_ios{handle}",
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "pageId": f"amzn_dp_project_dee_ios{handle}",
        "accountStatusPolicy": "P1",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.mode": "checkid_setup",
        "openid.ns.oa2": f"{base}/ap/ext/oauth/2",
        "openid.oa2.client_id": f"device:{device_id}",
        "openid.ns.pape": "http://specs.openid.net/extensions/pape/1.0",
        "openid.oa2.response_type": "code",
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.pape.max_auth_age": "0",
        "openid.oa2.scope": "device_auth_access",
        "openid.oa2.code_challenge_method": "S256",
        "openid.oa2.code_challenge": code_challenge,
        "language": f"de_DE",
    })
    return f"{base}/ap/signin?{params}"


def replace_hosts(data: str, amazon_page: str, port: int, host: str) -> str:
    """URLs in Responses umschreiben — Amazon → Proxy."""
    data = data.replace("&#x2F;", "/")
    data = re.sub(
        rf"https?://www\.{re.escape(amazon_page)}:?[0-9]*/",
        f"http://{host}:{port}/www.{amazon_page}/",
        data
    )
    data = re.sub(
        rf"https?://alexa\.{re.escape(amazon_page)}:?[0-9]*/",
        f"http://{host}:{port}/alexa.{amazon_page}/",
        data
    )
    return data


def replace_hosts_back(data: str, amazon_page: str, port: int, host: str) -> str:
    """URLs in Requests zurückschreiben — Proxy → Amazon."""
    data = re.sub(
        rf"http://{re.escape(host)}:{port}/www\.{re.escape(amazon_page)}/",
        f"https://www.{amazon_page}/",
        data
    )
    data = re.sub(
        rf"http://{re.escape(host)}:{port}/alexa\.{re.escape(amazon_page)}/",
        f"https://alexa.{amazon_page}/",
        data
    )
    return data


class ProxyHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        log.debug(f"Proxy: {format % args}")

    def do_GET(self):
        self._handle("GET", None)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self._handle("POST", body)

    def _handle(self, method: str, body):
        amazon_page = CAPTURED["amazon_page"]
        port = CAPTURED["port"]
        host = CAPTURED["host"]
        path = self.path

        # Startseite → signin URL
        if path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", replace_hosts(CAPTURED["signin_url"], amazon_page, port, host))
            self.end_headers()
            return

        # maplanding → Authorization Code auslesen
        if "/ap/maplanding" in path:
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            auth_code = params.get("openid.oa2.authorization_code", [None])[0]
            if auth_code:
                log.info("Authorization Code erhalten!")
                self._exchange_and_save(auth_code)
            else:
                # Kein Code → trotzdem Cookies sammeln und speichern
                log.info("Maplanding ohne Code — speichere gesammelte Cookies")
                self._save_cookies()
            return

        # URL zurückschreiben: Proxy → Amazon
        if path.startswith(f"/www.{amazon_page}/"):
            target = "https://www." + amazon_page + "/" + path[len(f"/www.{amazon_page}/"):]
        elif path.startswith(f"/alexa.{amazon_page}/"):
            target = "https://alexa." + amazon_page + "/" + path[len(f"/alexa.{amazon_page}/"):]
        elif path.startswith("http"):
            target = path
        else:
            # Unbekannter Pfad
            target = f"https://www.{amazon_page}{path}"
            #self.send_response(404)
            #self.end_headers()
            #return

        # Referer zurückschreiben
        headers = {}
        for k, v in self.headers.items():
            if k.lower() in ("host", "proxy-connection"):
                continue
            if k.lower() == "referer":
                v = replace_hosts_back(v, amazon_page, port, host)
            headers[k] = v

        # Body zurückschreiben (POST-Daten)
        if body and headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            body = replace_hosts_back(body.decode(), amazon_page, port, host).encode()

        headers["Accept-Encoding"] = "gzip, deflate"

        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(target, data=body, headers=headers, method=method)
            opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx))
            with opener.open(req, timeout=30) as resp:
                resp_body = resp.read()

                # Cookies sammeln
                for k, v in resp.headers.items():
                    if k.lower() == "set-cookie":
                        self._collect_cookie(v)

                # Body dekomprimieren falls nötig
                encoding = resp.headers.get("Content-Encoding", "")
                if encoding == "gzip":
                    resp_body = gzip.decompress(resp_body)
                elif encoding == "deflate":
                    resp_body = zlib.decompress(resp_body)

                content_type = resp.headers.get("Content-Type", "")
                is_text = any(t in content_type for t in ["text/", "application/json", "application/javascript"])

                # URLs in Response umschreiben
                if is_text:
                    try:
                        text = resp_body.decode("utf-8", errors="replace")
                        text = replace_hosts(text, amazon_page, port, host)
                        resp_body = text.encode("utf-8")
                    except Exception:
                        pass

                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() in ("transfer-encoding", "content-encoding", "content-length"):
                        continue
                    if k.lower() == "location":
                        v = replace_hosts(v, amazon_page, port, host)
                        log.info("Redirect → %s", v)
                    elif k.lower() == "set-cookie":
                        # Domain entfernen damit Browser Cookie für localhost akzeptiert
                        v = re.sub(r";\s*domain=[^;]+", "", v, flags=re.IGNORECASE)
                        v = re.sub(r";\s*secure", "", v, flags=re.IGNORECASE)
                        v = re.sub(r";\s*samesite=[^;]+", "", v, flags=re.IGNORECASE)
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

        except urllib.error.HTTPError as e:
            log.error("HTTP %d für %s", e.code, target)
            self.send_response(e.code)
            self.end_headers()
        except Exception as e:
            log.error("Proxy error %s: %s", target, e)
            self.send_response(502)
            self.end_headers()

    def _collect_cookie(self, header: str):
        parts = header.split(";")
        if parts and "=" in parts[0]:
            name, value = parts[0].strip().split("=", 1)
            CAPTURED.setdefault("cookies", {})[name.strip()] = value.strip()

    def _exchange_and_save(self, auth_code: str):
        """Authorization Code gegen Tokens tauschen."""
        amazon_page = CAPTURED["amazon_page"]
        device_id = CAPTURED["device_id"]
        code_verifier = CAPTURED["code_verifier"]
        tld = amazon_page.split(".")[-1]

        register_data = json.dumps({
            "auth_data": {
                "client_id": device_id,
                "authorization_code": auth_code,
                "code_verifier": code_verifier,
                "code_algorithm": "SHA-256",
                "client_domain": "DeviceLegacy",
            },
            "registration_data": {
                "domain": "Device",
                "app_version": "2.2.485407",
                "device_type": "A2IVLV5VM2W81",
                "os_version": "15.0",
                "device_serial": device_id[:32],
                "device_model": "iPhone",
                "app_name": "Amazon Alexa",
                "software_version": "1",
            },
            "requested_token_type": ["bearer", "mac_dms", "website_cookies"],
            "requested_extensions": ["device_info", "customer_info"],
            "cookies": {
                "website_cookies": [],
                "domain": f".amazon.{tld}",
            },
        }).encode()

        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                f"https://api.amazon.{tld}/auth/register",
                data=register_data,
                headers={
                    "Content-Type": "application/json",
                    "x-amzn-identity-auth-domain": f"api.amazon.{tld}",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read())
                website_cookies = (data.get("response", {})
                                   .get("success", {})
                                   .get("tokens", {})
                                   .get("website_cookies", []))
                cookies = {c["Name"]: c["Value"] for c in website_cookies}
                CAPTURED.setdefault("cookies", {}).update(cookies)
                log.info("Token-Exchange: %d Cookies erhalten", len(cookies))
        except Exception as e:
            log.error("Token-Exchange fehlgeschlagen: %s — nutze Browser-Cookies", e)

        self._save_cookies()

    def _save_cookies(self):
        config_path = os.environ.get("CONFIG_PATH", "/config/config.json")
        config_dir = os.path.dirname(os.path.abspath(config_path))

        with open(config_path) as f:
            config = json.load(f)

        # cookie_file = os.path.join(config_dir, config.get("alexa_cookie_file", "alexa_cookie.json"))
        cookie_filename = os.path.basename(config.get("alexa_cookie_file", "alexa_cookie.json"))
        cookie_file = os.path.join(config_dir, cookie_filename)
        cookies = CAPTURED.get("cookies", {})
        cookie_string = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        csrf = cookies.get("csrf", cookies.get("csrf-token", ""))

        with open(cookie_file, "w") as f:
            json.dump({"cookie": cookie_string, "csrf-token": csrf}, f, indent=2)

        log.info("✓ Cookies gespeichert: %s (%d Cookies)", cookie_file, len(cookies))

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("""
        <html><body style="font-family:sans-serif;text-align:center;margin-top:100px">
        <h1>&#10003; Login erfolgreich!</h1>
        <p>Cookies wurden gespeichert. Du kannst dieses Fenster schlie&szlig;en.</p>
        </body></html>
        """.encode())

        LOGIN_DONE.set()

class NoRedirect(urllib.request.HTTPErrorProcessor):
    def http_response(self, request, response):
        return response
    https_response = http_response


def run_proxy(port: int):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), ProxyHandler) as httpd:
        while not LOGIN_DONE.is_set():
            httpd.handle_request()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Amazon Login via Browser-Proxy")
    parser.add_argument("--config", default=os.environ.get("CONFIG_PATH", "/config/config.json"))
    parser.add_argument("--port", type=int, default=PROXY_PORT)
    parser.add_argument("--host", default=PROXY_HOST)
    args = parser.parse_args()

    os.environ["CONFIG_PATH"] = args.config

    if not os.path.exists(args.config):
        log.error("Config nicht gefunden: %s", args.config)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    amazon_page = config.get("amazon_url", "amazon.de")
    device_id = generate_device_id()
    code_verifier, code_challenge = pkce_pair()
    signin_url = build_signin_url(amazon_page, device_id, code_challenge)

    CAPTURED.update({
        "amazon_page": amazon_page,
        "device_id": device_id,
        "code_verifier": code_verifier,
        "signin_url": signin_url,
        "port": args.port,
        "host": args.host,
        "cookies": {},
    })

    print("\n" + "=" * 60)
    print("Amazon Login — Browser-Proxy")
    print("=" * 60)
    print(f"\nBitte öffne im Browser:\n")
    print(f"  http://{args.host}:{args.port}/\n")
    print("Logge dich bei Amazon ein (inkl. MFA falls aktiv).")
    print("Die Cookies werden automatisch gespeichert.\n")
    print("=" * 60 + "\n")

    t = threading.Thread(target=run_proxy, args=(args.port,), daemon=True)
    t.start()

    LOGIN_DONE.wait(timeout=300)

    if LOGIN_DONE.is_set():
        print("\n✓ Login erfolgreich abgeschlossen!\n")
    else:
        print("\n✗ Timeout nach 5 Minuten.\n")
        sys.exit(1)
