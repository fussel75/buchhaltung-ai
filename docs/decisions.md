# Entscheidungen

## 2026-05-06 MVP-Start

- Betrieb: Hostinger VPS, Ubuntu 24.04, Root-Zugriff.
- Deployment: Docker Compose.
- Backend: Python/FastAPI.
- Frontend: React/Vite.
- Datenbank: PostgreSQL.
- Erster Belegfluss: Upload und Drag & Drop.
- E-Mail-, ERP- und Bank-Connectoren folgen nach dem Upload-MVP.

## 2026-05-06 Cloudflare Access und Tunnel

- Domain: `buha.fristd-bau.net`.
- Cloudflare Access schuetzt die App per E-Mail/Magic-Link.
- Tunnel-Routing:
  - Frontend: `buha.fristd-bau.net` -> `127.0.0.1:5173`.
  - Backend: `buha.fristd-bau.net/api/*` -> `127.0.0.1:8000`.
- Backend liefert API-Routen unter `/api` aus.
- Frontend ruft die API relativ ueber `/api/...` auf.
- Docker Compose bindet Web, API und Datenbank nur an `127.0.0.1`.
- Erlaubte Vite-Hosts werden ueber `WEB_ALLOWED_HOSTS` konfiguriert, nicht hart im Code.
