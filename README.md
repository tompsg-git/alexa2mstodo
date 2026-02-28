# alexa2mstodo

Sync zwischen der **Alexa Einkaufsliste** und **Microsoft To Do** — ohne Selenium, ohne Browser-Automatisierung.

Inspiriert von [alexiri/alexa2anylist](https://github.com/alexiri/alexa2anylist), jedoch mit Microsoft To Do als Ziel statt AnyList.

---

## Schnellstart mit Docker

```bash
mkdir -p ~/alexa2mstodo/config
cd ~/alexa2mstodo
curl -o docker-compose.yml \
  https://raw.githubusercontent.com/tompsg-git/alexa2mstodo/main/docker-compose.yml
docker compose up
```

Beim ersten Start wird `config/config.json` automatisch angelegt. Pflichtfeld eintragen:

```json
"ms_client_id": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
```

Dann neu starten: `docker compose up -d`

---

## Sync-Modi (`sync_direction`)

| Modus | Beschreibung |
|---|---|
| `both` | Bidirektional (Standard) |
| `a2m` | Nur Alexa → MS Todo |

**`both`** — Neue/gelöschte Items werden auf beiden Seiten gespiegelt.

**`a2m`** — Nur Alexa-Items werden nach MS Todo übertragen. Mit `delete_origin: true` werden Items nach dem Sync aus Alexa gelöscht.

---

## Azure App Registration einrichten

1. [portal.azure.com](https://portal.azure.com) → **App-Registrierungen** → **Neue Registrierung**
2. Kontotyp: **Persönliche Microsoft-Konten**
3. **Authentifizierung** → **Öffentliche Clientflows erlauben: Ja**
4. **API-Berechtigungen** → Microsoft Graph → Delegiert → `Tasks.ReadWrite`
5. **Anwendungs-ID (Client-ID)** kopieren → `ms_client_id` in `config.json`

---

## Authentifizierung

### Microsoft To Do

Beim ersten Start erscheint ein Device-Code im Log oder im Webinterface (Tab **Anmeldung**):

```
https://microsoft.com/devicelogin  →  Code: ABCD1234
```

Token wird in `/config/ms_token.json` gespeichert — danach vollautomatisch.

### Amazon / Alexa

**Option 1: Webinterface** → Tab **Anmeldung** → **Proxy starten** → `localhost:8765` im Browser öffnen → bei Amazon einloggen.

**Option 2: Manuell** — Cookie aus ioBroker/FHEM in `/config/alexa_cookie.json` eintragen:

```json
{ "localCookie": "session-id=...; csrf=12345678" }
```

---

## Konfiguration

`config/config.json` (wird beim ersten Start aus der Vorlage angelegt):

```json
{
    "amazon_url": "amazon.de",
    "alexa_list_name": "Einkaufsliste",
    "alexa_cookie_file": "/config/alexa_cookie.json",

    "ms_client_id": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX",
    "ms_tenant_id": "consumers",
    "ms_list_name": "Einkaufsliste",
    "ms_token_file": "/config/ms_token.json",

    "sync_direction": "both",
    "delete_origin": false,
    "sync_interval": 30,

    "webserver": true,
    "webserver_port": 8080
}
```

| Key | Beschreibung |
|---|---|
| `amazon_url` | `amazon.de`, `amazon.com`, `amazon.es` … |
| `alexa_list_name` | Name der Alexa-Liste |
| `alexa_cookie_file` | Pfad zur Cookie-Datei |
| `ms_client_id` | Client-ID der Azure App Registration |
| `ms_tenant_id` | `consumers` für persönliche Konten |
| `ms_list_name` | Name der MS-Todo-Liste |
| `ms_token_file` | Pfad zur Token-Datei |
| `sync_direction` | `both` oder `a2m` |
| `delete_origin` | `true` → nach Sync aus Quelle löschen (nur bei `a2m`) |
| `sync_interval` | Sekunden zwischen Sync-Zyklen |
| `webserver` | `true` aktiviert das Webinterface |
| `webserver_port` | Port des Webinterface (Standard: `8080`) |

---

## docker-compose.yml

```yaml
services:
  alexa2mstodo:
    image: ghcr.io/tompsg-git/alexa2mstodo:latest
    volumes:
      - ./config:/config
      - /etc/localtime:/etc/localtime:ro
    ports:
      - "8080:8080"
    environment:
      - TZ=Europe/Berlin
      - CONFIG_PATH=/config/config.json
      - LOG_LEVEL=INFO
    restart: unless-stopped
```

---

## Umgebungsvariablen

ENV-Variablen haben Vorrang vor `config.json`.

| Variable | Standard | Beschreibung |
|---|---|---|
| `CONFIG_PATH` | `/config/config.json` | Pfad zur Config-Datei |
| `SYNC_INTERVAL` | `30` | Sekunden zwischen Sync-Zyklen |
| `SYNC_DIRECTION` | `both` | `both` oder `a2m` |
| `DELETE_ORIGIN` | `false` | `true` aktiviert delete_origin |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` |

---

## Webinterface

Erreichbar unter `http://localhost:8080` (wenn `webserver: true`).

| Tab | Funktion |
|---|---|
| **Listen** | Alexa und MS Todo nebeneinander, Items bearbeiten |
| **Konfiguration** | Sync-Einstellungen anpassen |
| **Anmeldung** | Amazon Proxy, MS Todo Device Code Flow |

---

## Backup & Restore

```bash
docker compose exec alexa2mstodo python3 /app/src/backup.py --dir /config/backup
docker compose exec alexa2mstodo python3 /app/src/restore.py --dir /config/backup
```

---

## Lokaler Betrieb

```bash
pip install -r requirements.txt
CONFIG_PATH=./config/config.json python3 src/server.py
```

---

## Credits

- [alexiri/alexa2anylist](https://github.com/alexiri/alexa2anylist) — Ursprungsidee
- [ioBroker alexa-remote2](https://github.com/Apollon77/ioBroker.alexa2) — Alexa V2 API
- [Microsoft MSAL](https://github.com/AzureAD/microsoft-authentication-library-for-python)
- [Microsoft Graph To Do API](https://learn.microsoft.com/de-de/graph/api/resources/todo-overview)

## Lizenz

GPL-3.0 — siehe [LICENSE](LICENSE)
