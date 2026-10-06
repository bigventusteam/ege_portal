from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_release_storage_root
from app.models import AuditEvent, Release, User
from app.routers.auth import get_current_user
from app.schemas import ReleaseResponse
from app.services.releases import PathTraversalError, list_visible_releases, resolve_release_path

router = APIRouter(prefix="/api/v1", tags=["downloads"])


def _release_yanitina_cevir(release: Release) -> ReleaseResponse:
    return ReleaseResponse(
        id=release.id,
        product_code=release.product.code,
        product_name=release.product.name,
        version=release.version,
        package_type=release.package_type.value,
        os=release.os,
        arch=release.arch,
        file_name=release.file_name,
        size_bytes=release.size_bytes,
        sha256=release.sha256,
        signed=release.signed,
        notes=release.notes,
        published_at=release.published_at,
    )


def _indirilebilir_surumu_getir(db: Session, release_id: int, user: User) -> Release:
    """Olmayan, pasif ve (müşteri için) imzasız sürüm AYNI 404'ü döner
    (var-yok ayrımı sızdırmaz). Oturum açmış her müşteri aktif imzalı
    sürümleri indirebilir (bkz. app/services/releases.py, indirme kuralı)."""
    release = db.get(Release, release_id)
    if release is None or not release.is_active:
        raise HTTPException(404, "sürüm bulunamadı")
    if not user.is_staff and not release.signed:
        raise HTTPException(404, "sürüm bulunamadı")
    return release


@router.get("/downloads", response_model=list[ReleaseResponse])
def surumleri_listele(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ReleaseResponse]:
    """Personel (`is_staff`) tüm aktif sürümleri (imzasız dahil) görür.
    Müşteri tüm aktif İMZALI sürümleri görür."""
    releases = list_visible_releases(db, customer_id=user.customer_id, is_staff=user.is_staff)
    return [_release_yanitina_cevir(r) for r in releases]


@router.get("/downloads/{release_id}")
def surumu_indir(
    release_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    depo_koku: Path = Depends(get_release_storage_root),
) -> FileResponse:
    release = _indirilebilir_surumu_getir(db, release_id, user)

    try:
        dosya_yolu = resolve_release_path(depo_koku, release.storage_key)
    except (PathTraversalError, FileNotFoundError) as e:
        # Ham sebep (yol, sembolik bağ ayrıntısı) İSTEMCİYE SIZMAZ — bu,
        # `storage_key` bir şekilde bozulmuş/kurcalanmış olsa bile (normal
        # akışta yalnız scripts/surum_yayinla.py yazar) güvenli bir şekilde
        # BAŞARISIZ olur, dosya asla yanlış bir yerden sunulmaz.
        raise HTTPException(500, "sürüm dosyası sunulamadı") from e

    db.add(
        AuditEvent(
            event_type="release.downloaded",
            entity_type="release",
            entity_id=str(release.id),
            data={
                "customer_id": user.customer_id,
                "user_id": user.id,
                "product_code": release.product.code,
                "version": release.version,
                "package_type": release.package_type.value,
            },
        )
    )
    db.commit()

    return FileResponse(
        dosya_yolu,
        filename=release.file_name,
        media_type="application/octet-stream",
        headers={"X-Checksum-SHA256": release.sha256},
    )
