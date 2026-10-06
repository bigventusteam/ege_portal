#!/usr/bin/env bash
# Konteyner girişi — şema migration'ı HER ZAMAN uygulamadan ÖNCE çalışır
# (ADR-0025/mapEGE'deki aynı "stop-the-world" gerekçe: eski ve yeni şemanın
# aynı anda farklı yorumlanması riskini ortadan kaldırır). Migration
# başarısız olursa süreç BAŞLAMAZ (set -e) — yarım bir şemayla ayağa
# kalkmak, hiç kalkmamaktan daha kötüdür.
set -euo pipefail

echo "[entrypoint] şema migration'ı uygulanıyor…"
alembic upgrade head

echo "[entrypoint] uygulama başlatılıyor…"
exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers "${WORKERS:-2}"
