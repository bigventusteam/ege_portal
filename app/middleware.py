"""
CSRF savunması — oturum HttpOnly bir çerezle taşınıyor (bkz. app/routers/
auth.py) ve durum değiştiren (POST/PUT/PATCH/DELETE) uçlar var. Çerez artık
`SameSite=Strict` (frontend'in kendisi de AYNI origin'den sunulur, bkz.
deploy/) — bu TEK BAŞINA yeterli olurdu, ama ikinci, bağımsız bir katman:
HER durum değiştiren istek `Origin` (yoksa `Referer`'den türetilen origin)
başlığının `ALLOWED_ORIGINS`'te OLDUĞUNU doğrular; yoksa/eşleşmiyorsa 403.

`/api/v1/webhooks/bvpay` MUAFTIR — bvpay sunucudan sunucuya POST eder,
tarayıcı değildir, Origin/Referer hiç taşımaz; asıl doğrulama zaten GERİ
bir `GET` ile bvpay'e sorularak yapılır (bkz. app/services/payments.py
docstring'i) — webhook gövdesine/başlığına hiç güvenilmiyor olması bu
istisnayı güvenli kılar.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MUAF_YOLLAR = {"/api/v1/webhooks/bvpay"}


def _istek_origini(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin
    referer = request.headers.get("referer")
    if not referer:
        return None
    parcalar = urlsplit(referer)
    if not parcalar.scheme or not parcalar.netloc:
        return None
    return f"{parcalar.scheme}://{parcalar.netloc}"


class OriginDogrulamaMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in _UNSAFE_METHODS and request.url.path not in _MUAF_YOLLAR:
            origin = _istek_origini(request)
            if origin is None or origin not in settings.allowed_origins:
                return JSONResponse({"detail": "izin verilmeyen origin"}, status_code=403)
        return await call_next(request)
