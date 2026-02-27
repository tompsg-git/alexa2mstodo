# alexa2mstodo

Sync zwischen der **Alexa Einkaufsliste** und **Microsoft To Do** — ohne Selenium, ohne Browser-Automatisierung.

Inspiriert von [alexiri/alexa2anylist](https://github.com/alexiri/alexa2anylist), jedoch mit Microsoft To Do als Ziel statt AnyList.

---

## Funktionsweise

Jede `sync_interval` Sekunden (Standard: 30 s) vergleicht der Dienst den aktuellen Zustand beider Listen gegen einen gespeicherten Anker-Zustand (`state.json`).

### Sync-Modi (`sync_direction`)

| Modus | Beschreibung |
|---|---|
| `both` | Bidirektionaler Sync (Standard) |
| `a2m` | Nur Alexa → MS Todo (One-Way) |

#### `both`
- Neues Item auf Alexa → wird in MS Todo angelegt
- Neues Item in MS Todo → wird in Alexa angelegt
- Item von Alexa gelöscht → wird in MS Todo gelöscht
- Item aus MS Todo gelöscht → wird von Alexa gelöscht

#### `a2m`
- Neues Item auf Alexa → wird in MS Todo angelegt
- Mit `delete_origin: true` → Item wird nach dem Sync aus Alexa gelöscht
- Löschungen werden nicht propagiert

---

## Azure App Registration einrichten

1. Öffne [portal.azure.com](https://portal.azure.com) → **Azure Active Directory** → **App-Registrierungen** → **Neue Registrierung**
2. Name: `alexa2mstodo`, Kontotyp: **Persönliche Microsoft-Konten**
3. Nach dem Erstellen: **Authentifizierung** → **Erweiterte Einstellungen** → **Öffentliche Clientflows erlauben: Ja**
4. **API-Berechtigungen** → Microsoft Graph → Delegiert → `Tasks.ReadWrite`
5. Die **Anwendungs-ID (Client-ID)** kopieren

---

## Amazon Cookie einrichten

Die Authentifizierung bei Amazon erfolgt über einen Session-Cookie. Dieser kann auf zwei Wegen beschafft werden:

### Option 1: Browser-Proxy (empfohlen)

```bash
python3 src/amazon_login.py --config config/config.json
```

Browser öffnen: `http://localhost:8765/` → bei Amazon einloggen → Cookie wird automatisch in `alexa_cookie.json` gespeichert.

### Option 2: Manuell aus ioBroker / FHEM

Cookie und CSRF-Token aus der jeweiligen Alexa-Integration entnehmen und in `config/alexa_cookie.json` eintragen:

```json
{
    "cookie": "session-id=...; csrf=12345678",
    "csrf-token": "12345678"
}
```

---

## Konfiguration

`config/config.json`:

```json
{
    "amazon_url": "amazon.de",
    "alexa_list_name": "shop",
    "alexa_cookie_file": "alexa_cookie.json",

    "ms_client_id": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX",
    "ms_tenant_id": "consumers",
    "ms_list_name": "Einkaufsliste",

    "sync_direction": "both",
    "delete_origin": false,
    "sync_interval": 30
}
```

| Key | Beschreibung |
|---|---|
| `amazon_url` | `amazon.de`, `amazon.com`, `amazon.es` … |
| `alexa_list_name` | Name der Alexa-Liste (z. B. `shop`) |
| `alexa_cookie_file` | Pfad zur Cookie-Datei (relativ zur config.json) |
| `ms_client_id` | Client-ID der Azure App Registration |
| `ms_tenant_id` | `consumers` für persönliche Konten |
| `ms_list_name` | Name der MS-Todo-Liste |
| `sync_direction` | `both` oder `a2m` |
| `delete_origin` | `true` → nach Sync aus Quelle löschen (nur bei `a2m`) |
| `sync_interval` | Sekunden zwischen Sync-Zyklen |

---

## Erster Start (MS Todo Authentifizierung)

Beim allerersten Start muss die MS-Anmeldung einmalig interaktiv durchgeführt werden:

```bash
docker compose run --rm alexa2mstodo
```

Es erscheint ein Device-Code-Link:

```
To sign in, use a web browser to open the page https://microsoft.com/devicelogin
and enter the code ABCD1234 to authenticate.
```

Browser öffnen, Code eingeben, mit Microsoft-Konto anmelden. Der Refresh-Token wird automatisch in `config.json` gespeichert — danach läuft alles unbeaufsichtigt.

---

## Betrieb mit Docker Compose

```yaml
services:
  alexa2mstodo:
    image: ghcr.io/tompsg-git/alexa2mstodo:latest
    volumes:
      - ./config:/config
      - /etc/localtime:/etc/localtime:ro
    environment:
      - TZ=Europe/Berlin
      - SYNC_INTERVAL=30
      - SYNC_DIRECTION=both
    restart: unless-stopped
```

```bash
docker compose up -d
docker compose logs -f
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

## Backup & Restore

```bash
# Backup Alexa-Liste
python3 src/backup.py --config config/config.json --dir config/backup

# Backup MS-Todo-Liste
python3 src/backup.py --config config/config.json --dir config/backup

# Restore
python3 src/restore.py --config config/config.json --dir config/backup
```

Beide Skripte zeigen interaktiv die verfügbaren Listen zur Auswahl an.

---

## Lokaler Betrieb (ohne Docker)

```bash
pip install -r requirements.txt
CONFIG_PATH=./config/config.json python3 src/server.py
```

---

## Tests

```bash
python3 src/test_synchronizer.py
```

---

## Credits

- [alexiri/alexa2anylist](https://github.com/alexiri/alexa2anylist) — Ursprungsidee und Architektur
- [ioBroker alexa-remote2](https://github.com/Apollon77/ioBroker.alexa2) — Alexa V2 API Endpunkte
- [Microsoft MSAL für Python](https://github.com/AzureAD/microsoft-authentication-library-for-python)
- [Microsoft Graph To Do API](https://learn.microsoft.com/de-de/graph/api/resources/todo-overview)

## Lizenz

GPL-3.0 — siehe [LICENSE](LICENSE)
