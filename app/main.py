"""
EGE Lisans Portalı — backend çekirdeği (bkz. ege_platform/ege_portal/PLAN.md)
"""
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import startup_checks
from app.config import settings
from app.middleware import OriginDogrulamaMiddleware
from app.routers import activations, admin, auth, downloads, orders, payments, plans, subscriptions, trial

try:
    startup_checks.validate_startup_config()
except startup_checks.StartupConfigError as exc:
    print(f"FATAL: {exc}", file=sys.stderr)
    sys.exit(1)

app = FastAPI(title="EGE Lisans Portalı", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# CORS'tan SONRA eklenir ama Starlette'te middleware yığını LIFO sarılır —
# bu yüzden istek üzerinde Origin kontrolü CORS'un ÖNÜNDE çalışır (CSRF
# savunması, bkz. app/middleware.py docstring'i).
app.add_middleware(OriginDogrulamaMiddleware)

app.include_router(auth.router)
app.include_router(plans.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(activations.router)
app.include_router(subscriptions.router)
app.include_router(trial.router)
app.include_router(admin.router)
app.include_router(downloads.router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# ─── Frontend statik dosyaları (SPA) ──────────────────────────────────────────
# `frontend/vite.config.ts`'in `build.outDir`'ı buraya (`<repo kökü>/static`)
# yazar (bkz. deploy/Dockerfile'daki çok aşamalı build — mapEGE'nin AYNI
# deseni, kopyalanmadı). Yerel geliştirmede (frontend `npm run dev` ile ayrı
# çalışır, Vite proxy'si backend'e gider) bu klasör YOKTUR — aşağıdaki
# bloklar o zaman sessizce ATLANIR, `uvicorn app.main:app` yine de açılır.
_static_dir = Path(__file__).resolve().parent.parent / "static"
_index_html = _static_dir / "index.html"

if _index_html.is_file():
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    # index.html HİÇBİR ZAMAN önbelleğe alınmamalı — dosya adı sabit olduğu
    # için tarayıcı onu önbellekten sunarsa yeni sürümün hash'li asset'lerini
    # (assets/ altında, uzun süre önbelleklenebilir) hiç görmez.
    _INDEX_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}
    _API_ONEKLERI = ("api/", "healthz", "assets/")

    @app.get("/")
    async def spa_root() -> FileResponse:
        return FileResponse(_index_html, headers=_INDEX_HEADERS)

    @app.get("/{full_path:path}")
    async def spa_catch_all(full_path: str) -> FileResponse:
        """React Router istemci tarafında yönlendirir; sunucu bilinmeyen
        yolları `index.html` ile karşılar. API önekleriyle başlayan ya da
        bir dosya uzantısı taşıyan (`favicon.ico` gibi, burada elde
        YOK) eşleşmeyen yollar 404 döner — hatalı bir API çağrısı sessizce
        HTML almamalı."""
        last_segment = full_path.rsplit("/", 1)[-1]
        if full_path.startswith(_API_ONEKLERI) or "." in last_segment:
            raise HTTPException(status_code=404, detail="bulunamadı")
        return FileResponse(_index_html, headers=_INDEX_HEADERS)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8002, reload=False)
