# EGE Lisans Portalı — üretim imajı (backend + frontend AYNI imajdan/AYNI
# origin'den; mapEGE'nin geo_service/static deseninin AYNISI).
#
# BUILD CONTEXT `ege_platform/` (bu Dockerfile'ın İKİ üst dizini) OLMALI —
# `requirements.txt`'teki `-e ../ege_lisans` (editable yol bağımlılığı,
# vendorlanmadı — bkz. ege_portal/README.md "ege_lisans vendorlanmadı"
# kararı) kardeş bir `ege_lisans/` dizini gerektirir, bu Dockerfile tek
# başına `ege_portal/` içinden build EDİLEMEZ:
#
#   docker build -f ege_portal/deploy/Dockerfile -t ege-portal:latest ege_platform/
#
# (docker-compose.yml bunu zaten `context: ../..` ile doğru ayarlar.)

# ── Aşama 1: Frontend build ───────────────────────────────────────────────
FROM node:22-alpine AS frontend-builder
WORKDIR /build/ege_portal/frontend
COPY ege_portal/frontend/package*.json ./
RUN npm ci
COPY ege_portal/frontend/ ./
# vite.config.ts: build.outDir='../static' → /build/ege_portal/static
RUN npm run build


# ── Aşama 2: Python backend ───────────────────────────────────────────────
FROM python:3.12-slim AS backend

# Kardeş ege_lisans (editable yol bağımlılığı, bkz. üstteki build context notu).
COPY ege_lisans/ /srv/ege_lisans/

WORKDIR /srv/ege_portal
COPY ege_portal/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY ege_portal/app/ ./app/
COPY ege_portal/alembic/ ./alembic/
COPY ege_portal/alembic.ini ./
COPY ege_portal/scripts/ ./scripts/

# Build edilmiş frontend (aşama 1'den) — app/main.py bunu <repo kökü>/static
# altında arar (bkz. frontend/vite.config.ts'deki AYNI not).
COPY --from=frontend-builder /build/ege_portal/static ./static

COPY ege_portal/deploy/entrypoint.sh /entrypoint.sh
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
