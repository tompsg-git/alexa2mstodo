# alexa2mstodo

Bidirektionaler Sync zwischen der **Alexa Einkaufsliste** und **Microsoft To Do** — ohne Selenium, ohne Browser-Automatisierung.

Inspiriert von [alexiri/alexa2anylist](https://github.com/alexiri/alexa2anylist), jedoch mit Microsoft To Do als Ziel statt AnyList.

---

## Funktionsweise

Jede `SYNC_INTERVAL` Sekunden (Standard: 30 s) vergleicht der Dienst den aktuellen Zustand beider Listen gegen einen gespeicherten Anker-Zustand (`state.json`):

- **Neues Item auf Alexa** → wird in MS To Do angelegt
- **Neues Item in MS To Do** → wird in Alexa angelegt
- **Item von Alexa gelöscht/abgehakt** → wird in MS To Do gelöscht
- **Item aus MS To Do gelöscht** → wird von Alexa gelöscht
- **Konflikt** (beide Seiten geändert) → MS To Do gewinnt

---

## Azure App Registration einrichten

1. Öffne [portal.azure.com](https://portal.azure.com) → **Azure Active Directory** → **App-Registrierungen** → **Neue Registrierung**
2. Name: `alexa2mstodo`, Kontotyp: **Persönliche Microsoft-Konten (z. B. Skype, Xbox)**
3. Weiterleitungs-URI: leer lassen (nicht nötig)
4. Nach dem Erstellen: **Authentifizierung** → **Erweiterte Einstellungen** → **Öffentliche Clientflows erlauben: Ja**
5. **API-Berechtigungen** → **Berechtigung hinzufügen** → Microsoft Graph → Delegiert → `Tasks.ReadWrite` hinzufügen
6. Die **Anwendungs-ID (Client-ID)** aus dem Übersichts-Tab kopieren

---

## Konfiguration

Datei `/data/alexa2mstodo/config.json` anlegen:

```json
{
    "amazon_url": "amazon.de",
    "amazon_username": "deine@email.de",
    "amazon_password": "dein-amazon-passwort",
    "amazon_mfa_secret": "TOTP_SECRET_FALLS_2FA_AKTIV",

    "ms_client_id": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX",
    "ms_tenant_id": "consumers",
    "ms_list_name": "Einkaufsliste"
}
```

| Key | Beschreibung |
|---|---|
| `amazon_url` | `amazon.de`, `amazon.com`, `amazon.es` … |
| `amazon_username` | Amazon-Account-E-Mail |
| `amazon_password` | Amazon-Passwort |
| `amazon_mfa_secret` | TOTP-Geheimnis für 2FA (leer lassen wenn keine 2FA) |
| `ms_client_id` | Client-ID der Azure App Registration (s. o.) |
| `ms_tenant_id` | `consumers` für persönliche Konten, sonst Tenant-GUID |
| `ms_list_name` | Name der To-Do-Liste (wird erstellt falls nicht vorhanden) |

---

## Erster Start (Authentifizierung)

Beim allerersten Start muss die MS-Anmeldung einmalig interaktiv durchgeführt werden:

```bash
docker compose run --rm alexa2mstodo
```

Es erscheint ein Device-Code-Link, z. B.:

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
    build: .
    volumes:
      - /data/alexa2mstodo:/config
      - /etc/localtime:/etc/localtime:ro
    environment:
      - TZ=Europe/Berlin
      - SYNC_INTERVAL=30
    restart: unless-stopped
```

```bash
docker compose up -d
docker compose logs -f
```

`restart: unless-stopped` ist wichtig — falls Amazon die Session invalidiert, crasht der Container und startet neu.

---

## Umgebungsvariablen

| Variable | Standard | Beschreibung |
|---|---|---|
| `CONFIG_PATH` | `/config/config.json` | Pfad zur Config-Datei |
| `SYNC_INTERVAL` | `30` | Sekunden zwischen Sync-Zyklen |
| `LOG_LEVEL` | `INFO` | Python-Log-Level (`DEBUG`, `INFO`, `WARNING`) |

---

## Lokaler Betrieb (ohne Docker)

```bash
pip install -r requirements.txt
CONFIG_PATH=./config.json python server.py
```

---

## Credits

- [alexiri/alexa2anylist](https://github.com/alexiri/alexa2anylist) — Ursprungsidee und Architektur
- [Microsoft MSAL für Python](https://github.com/AzureAD/microsoft-authentication-library-for-python)
- [Microsoft Graph To Do API](https://learn.microsoft.com/de-de/graph/api/resources/todo-overview)

## Lizenz

GPL-3.0 — siehe [LICENSE](LICENSE)
