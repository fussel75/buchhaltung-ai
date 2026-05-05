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
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Erster MVP-Flow

1. Mandant auswaehlen.
2. Beleg per Upload/Drag & Drop hochladen.
3. Original unveraendert speichern.
4. Hash bilden und Duplikat pruefen.
5. Beleg in Review-Queue anzeigen.
6. OCR/KI/Buchungsvorschlag als naechste Ausbaustufe anbinden.

