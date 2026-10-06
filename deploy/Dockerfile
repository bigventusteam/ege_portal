# EGE Lisans Portalı — üretim imajı (backend + frontend AYNI imajdan/AYNI
# origin'den; mapEGE'nin geo_service/static deseninin AYNISI).
#
# BUILD CONTEXT `ege_portal/` (bu Dockerfile'ın BİR üst dizini) — `ege_lisans`
# bu depoda VENDORLANMIŞTIR (./ege_lisans, bkz. README "ege_lisans vendorlama"),
# kardeş dizin gerekmez; depo tek başına klonlanıp build edilebilir:
#
#   docker build -f deploy/Dockerfile -t ege-portal:latest .
#
# (docker-compose.yml bunu `context: ..` + `dockerfile: deploy/Dockerfile` ile
# zaten doğru ayarlar. `.dockerignore` build bağlamından node_modules, .env,
# veritabanı ve anahtar dosyalarını dışlar.)

# ── Aşama 1: Frontend build ───────────────────────────────────────────────
FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts: build.outDir='../static' → /build/static
RUN npm run build


# ── Aşama 2: Python backend ───────────────────────────────────────────────
FROM python:3.12-slim AS backend

WORKDIR /srv/ege_portal
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY scripts/ ./scripts/
# Vendorlanmış ortak lisans kütüphanesi — uygulama koduyla birlikte imaja girer.
COPY ege_lisans/ ./ege_lisans/

# Build edilmiş frontend (aşama 1'den) — app/main.py bunu <repo kökü>/static
# altında arar (bkz. frontend/vite.config.ts'deki AYNI not).
COPY --from=frontend-builder /build/static ./static

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# non-root — konteyner içindeki bir güvenlik açığı, host'ta (ya da başka
# konteynerlerde) root yetkisi ANLAMINA GELMESİN.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin portal \
 && mkdir -p /data/releases \
 && chown -R portal:portal /srv/ege_portal /data
USER portal

# `PORTAL_RELEASE_DIR`in varsayılanı — docker-compose kalıcı bir volume'e
# bağlar (bkz. docker-compose.yml). Konteyner içi bir SQLite dosyası
# İSTENMEZ (üretimde DATABASE_URL PostgreSQL'e işaret eder) — veritabanı
# ayrı bir servistir, bu imajda DOSYA olarak TUTULMAZ.
ENV PORTAL_RELEASE_DIR=/data/releases

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8002/healthz', timeout=3).status==200 else 1)"

ENTRYPOINT ["/entrypoint.sh"]
