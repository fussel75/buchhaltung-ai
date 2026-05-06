# VPS Deployment

Zielsystem:

- Hostinger VPS
- Ubuntu 24.04
- Cloudflare Access vor `buha.fristd-bau.net`
- Cloudflare Tunnel:
  - `buha.fristd-bau.net` -> `127.0.0.1:5173`
  - `buha.fristd-bau.net/api/*` -> `127.0.0.1:8000`

## 1. System vorbereiten

```bash
apt update
apt install -y git docker.io docker-compose-plugin openssl
systemctl enable --now docker
```

## 2. Repository klonen

```bash
mkdir -p /docker
cd /docker
git clone https://github.com/fussel75/buchhaltung-ai.git
cd /docker/buchhaltung-ai
```

## 3. Sichere ENV-Datei erstellen

```bash
cp .env.example .env
POSTGRES_PASSWORD_VALUE="$(openssl rand -base64 36 | tr -d '\n')"
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASSWORD_VALUE}/" .env
sed -i "s#^DATABASE_URL=.*#DATABASE_URL=postgresql://buchhaltung:${POSTGRES_PASSWORD_VALUE}@db:5432/buchhaltung_ai#" .env
sed -i "s#^WEB_API_BASE_URL=.*#WEB_API_BASE_URL=/api#" .env
sed -i "s#^WEB_ALLOWED_HOSTS=.*#WEB_ALLOWED_HOSTS=buha.fristd-bau.net#" .env
chmod 600 .env
```

## 4. Container starten

```bash
docker compose up --build -d
docker compose ps
```

## 5. Lokal auf dem VPS pruefen

```bash
curl http://127.0.0.1:8000/api/health
curl -I http://127.0.0.1:5173
```

## 6. Cloudflare testen

Im Browser:

1. `https://buha.fristd-bau.net` oeffnen.
2. Cloudflare Access Login per E-Mail/Magic-Link abschliessen.
3. Upload-Seite laden.
4. Testbeleg hochladen.

## Updates

```bash
cd /docker/buchhaltung-ai
git pull
docker compose up --build -d
docker compose ps
```
