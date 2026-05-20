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

Produktiv laeuft die App hinter dem Cloudflare Tunnel, die Anmeldung macht die App selbst:

- `buha.fristd-bau.net` -> `127.0.0.1:5173`
- `buha.fristd-bau.net/api/*` -> `127.0.0.1:8000`

Die Compose-Ports binden deshalb nur auf `127.0.0.1`. Das Frontend nutzt relative API-Calls nach `/api/...`.
Der erlaubte Vite-Host wird ueber `WEB_ALLOWED_HOSTS` in `.env` gesetzt.

Siehe [docs/deploy-vps.md](docs/deploy-vps.md) fuer die VPS-Schritte.

## App-Login

Die API nutzt serverseitige Cookie-Sessions. Beim Start wird automatisch ein Admin angelegt,
wenn noch kein User existiert und diese Variablen gesetzt sind:

- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`
- `SESSION_COOKIE_SECURE` (`false` lokal per HTTP, `true` produktiv per HTTPS)

Alle `/api/*`-Routen sind geschuetzt, ausser `/api/health`, `/api/auth/login` und `/api/auth/logout`.
Das Session-Cookie ist HTTP-only, SameSite=Lax und wird bei Aktivitaet verlaengert.

## Erster MVP-Flow

1. Mandant auswaehlen.
2. Beleg per Upload/Drag & Drop hochladen.
3. Original unveraendert speichern.
4. Hash bilden und Duplikat pro Mandant pruefen.
5. Beleg persistent in PostgreSQL speichern und in der Review-Queue anzeigen.
6. Extraktion pruefen und Buchungsvorschlag erzeugen.
7. Vorschlagszeilen korrigieren: Beschreibung, Zuordnung, Kostenart, Netto, USt und Brutto.
8. Beleg final freigeben; danach sind die Vorschlagszeilen gesperrt.

## Aktueller API-Schnitt

- `GET /api/health`
- `POST /api/documents/upload` mit `tenant_id` und `file`
- `GET /api/documents?tenant_id=demo-mandant`
- `GET /api/documents/{document_id}/file?disposition=inline|attachment`
- `POST /api/documents/export` fuer Auswahl-ZIP
- `GET /api/documents/export/month?tenant_id=...&year=2026&month=5`
- `POST /api/documents/{document_id}/extract`
- `POST /api/documents/{document_id}/review`
- `PATCH /api/documents/{document_id}/booking-suggestions/{suggestion_id}`
- `POST /api/documents/{document_id}/approve`

Uploads werden unter `STORAGE_ROOT` abgelegt und mit Metadaten in PostgreSQL gespeichert.
Die Review-Queue liest die persistierten Belege je Mandant.
Die Extraktion ist aktuell ein austauschbarer Mock-Adapter, der erste Rechnungsfelder erzeugt
und Audit-Events fuer Upload, Dublette, Start und Abschluss schreibt.
Der Review-Schritt schreibt Buchungsvorschlaege in `document_booking_suggestions`;
bei Aufteilungen werden die Netto- und Steuerwerte anteilig je Zuordnung verteilt.
Die Vorschlagszeilen sind vor der finalen Freigabe editierbar und werden bei finaler Freigabe auf `approved` gesetzt.

Die Extraktionsreihenfolge ist:

1. Eingebettete E-Rechnungsdaten lesen, z.B. `xrechnung.xml`, ZUGFeRD/Factur-X.
2. Fehlende Kontextdaten aus dem PDF-Text ergaenzen, z.B. Bauvorhaben aus Lieferanschrift.
3. Wenn keine strukturierten Daten vorhanden sind, PDF-Textregeln verwenden.
4. OCR erst als spaeterer Fallback fuer nicht textlesbare Scans.

## Mandanten-Stammdaten

Admin-Benutzer koennen in der App einfache Stammdaten pflegen:

- Benutzer mit Rolle `admin` oder `user`.
- Mandantenprofil mit Branche und fachlicher Bezeichnung fuer Zuordnungscodes.
- Zuordnungseinheiten pro Mandant, z.B. Bauvorhaben, Kostenobjekt, Fahrzeug, Abo/Vertrag oder Bereich.
  Bei Bauvorhaben kann zusaetzlich die Projektnummer gespeichert werden, z.B. `25-00008` neben dem Code `Wewe20`.
- Lieferantenregeln mit Erkennungstext, korrektem Firmennamen, unserer Kunden-Nr., Standard-Kostenart und optionaler Standard-Zuordnung.

Die Extraktion nutzt diese Stammdaten vor Heuristiken. Ein Bauvorhaben ist damit nur eine moegliche Zuordnungsart;
andere Mandanten koennen dieselbe Logik fuer andere Kosten- oder Umsatzobjekte verwenden.

Branchenprofile fuer den MVP:

- Baubranche: Zuordnung heisst `Bauvorhaben`, Kuerzel `BV`.
- Sportstudio: Zuordnung heisst `Standort`, z.B. fuer Kostenstellen je Studio.
- Container/Transport: Zuordnung heisst `Bauvorhaben / Stellplatz`, weil Container sowohl auf Baustellen als auch an anderen Stellplaetzen stehen koennen.

## Tests und Sicherheitschecks

Aktuelle lokale Checks:

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m unittest discover -s tests

cd ..\web
npm run build
npm audit --omit=dev
```

Die Tests decken aktuell die Buchungsvorschlagslogik fuer Splits, Gutschriften und Eingabevalidierung ab.
API-Routen fuer Dateien und Buchungszeilen loesen Daten serverseitig ueber IDs auf; freie Dateipfade werden nicht vom Frontend akzeptiert.
