# buchhaltung-ai

Modernes, mandantenfaehiges Buchhaltungsprogramm fuer Deutschland mit KI-Automationskern.

## Zielbild

Die App soll laufende Buchhaltung fuer mehrere Mandanten vorbereiten: Belege hochladen, Originale unveraendert speichern, auslesen, Mandant/Monat/Lieferant erkennen, SKR03-Buchungsvorschlaege erzeugen, Rueckfragen markieren und Steuerberater-Exportpakete vorbereiten.

## MVP-Stack

- Backend: FastAPI
- Frontend: React/Vite
- Datenbank: PostgreSQL
- Deployment: Docker Compose
- Betrieb: Ubuntu 24.04 VPS hinter VPN oder geschuetztem Zugriff

## Lokaler Start

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Danach:

- Frontend: http://localhost:5173
- API: http://localhost:8000/api/health
- API Docs: http://localhost:8000/docs

## Cloudflare Tunnel Setup

Produktiv ist der Zugriff ueber Cloudflare Access geplant:

- `buha.fristd-bau.net` -> `127.0.0.1:5173`
- `buha.fristd-bau.net/api/*` -> `127.0.0.1:8000`

Die Compose-Ports binden deshalb nur auf `127.0.0.1`. Das Frontend nutzt relative API-Calls nach `/api/...`.

Siehe [docs/deploy-vps.md](docs/deploy-vps.md) fuer die VPS-Schritte.

## Erster MVP-Flow

1. Mandant auswaehlen.
2. Beleg per Upload/Drag & Drop hochladen.
3. Original unveraendert speichern.
4. Hash bilden und Duplikat pruefen.
5. Beleg in Review-Queue anzeigen.
6. OCR/KI/Buchungsvorschlag als naechste Ausbaustufe anbinden.
