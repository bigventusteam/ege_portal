"""
İndirme merkezi (PLAN.md §5.4/F5) — hak (entitlement) hesaplama ve depolama
yolu çözümleme.

## İndirme kuralı (2026-10-06 kararı)

Oturum açmış HER kayıtlı müşteri tüm aktif, İMZALI sürümleri görür ve
indirir — abonelik ya da portal denemesi gerekmez. Gerekçe: kurulumun kendisi
lisanssız 7 gün denemeyle başlar (ürün içi kilit asıl kapıdır); portal deneme
aktivasyonu ise kurulmuş üründen gelen bir activation_request istediği için
eski kural yeni müşteriyi ne indirebilir ne deneyebilir hâlde bırakıyordu.
Kayıt zorunlu kalır ve her indirme `AuditEvent("release.downloaded")` yazar.

## Hak hesabı (`entitled_product_ids`) — indirme yolunda KULLANILMIYOR

Raporlama/ileride kademe kısıtı için duruyor. Bir müşteri bir ÜRÜNE hak
sahibidir, eğer:
  - o ürünü içeren bir Plan'a bağlı, DURUMU `active` VE süresi dolmamış
    (`current_period_end > şimdi`) bir `Subscription`'ı varsa (bkz.
    `app/services/offline_activation.py::create_offline_license`'daki AYNI
    "süresi dolmuş" kontrolü — `status` alanı hiçbir yerde otomatik
    `expired`e çevrilmiyor, asıl kontrol her zaman `current_period_end`),
    VEYA
  - o ürün için aktif (süresi dolmamış), İPTAL EDİLMEMİŞ bir `TrialLicense`
    aktivasyonu (`TrialActivation.revoked_at IS NULL`) varsa.

İmzasız (`signed=False`) sürümleri yalnız üretici personeli (`User.is_staff`)
görür/indirebilir (bkz.
`list_visible_releases`/`get_downloadable_release`, çağıran
`app/routers/downloads.py`'de karar verir, burası yalnız SORGULAR).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Plan, PlanItem, Release, Subscription, SubscriptionStatus, TrialActivation, TrialLicense

__all__ = ["PathTraversalError", "entitled_product_ids", "has_product_access", "list_visible_releases", "resolve_release_path"]


class PathTraversalError(Exception):
    """`storage_key` kök dizin dışına çıkıyor ya da sembolik bağ içeriyor."""


def resolve_release_path(root: Path, storage_key: str) -> Path:
    """`root` (PORTAL_RELEASE_DIR) ALTINDA, `storage_key`'in gösterdiği
    dosyanın MUTLAK yolunu döner. Üç bağımsız kontrol — biri eksik olsa
    diğeri yine de yakalasın diye (savunma derinliği):
      1. `storage_key` mutlak bir yol OLAMAZ, `..` bileşeni İÇEREMEZ.
      2. Çözümlenmiş (sembolik bağlar izlenmiş) nihai yol `root`'un
         GERÇEKTEN altında olmalı (`Path.resolve()` + `relative_to`).
      3. `root` ile dosya arasındaki HİÇBİR ara bileşen (dosyanın kendisi
         dahil) sembolik bağ OLAMAZ — (2) yalnız NİHAİ hedefin root
         altında kaldığını doğrular, ama bir sembolik bağ yine de root
         altındaki BAŞKA bir müşterinin dosyasına ya da beklenmeyen bir
         yere işaret edebilir; "hiç sembolik bağ yok" daha güçlü bir
         garanti.
    """
    if not storage_key or not storage_key.strip():
        raise PathTraversalError("boş storage_key")

    parca = PurePosixPath(storage_key.replace("\\", "/"))
    if parca.is_absolute():
        raise PathTraversalError(f"mutlak yol reddedildi: {storage_key!r}")
    if ".." in parca.parts or "." in parca.parts:
        raise PathTraversalError(f"geçersiz yol bileşeni: {storage_key!r}")

    kok = root.resolve()
    hedef = (kok / storage_key).resolve()
    try:
        hedef.relative_to(kok)
    except ValueError as e:
        raise PathTraversalError(f"kök dizin dışına çıkıyor: {storage_key!r}") from e

    gezinilen = kok
    for bilesen in parca.parts:
        gezinilen = gezinilen / bilesen
        if gezinilen.is_symlink():
            raise PathTraversalError(f"sembolik bağ reddedildi: {storage_key!r}")

    if not hedef.is_file():
        raise FileNotFoundError(f"depoda dosya yok: {storage_key!r}")

    return hedef


def entitled_product_ids(db: Session, customer_id: int, *, when: datetime | None = None) -> set[int]:
    """Müşterinin indirme hakkı olan `Product.id` kümesi (bkz. modül
    docstring'i — aktif abonelik VEYA aktif deneme)."""
    when = when or datetime.now(timezone.utc)

    abonelik_urunleri = db.scalars(
        select(PlanItem.product_id)
        .join(Plan, PlanItem.plan_id == Plan.id)
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(
            Subscription.customer_id == customer_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.current_period_end > when,
        )
    ).all()

    deneme_urunleri = db.scalars(
        select(TrialActivation.product_id)
        .join(TrialLicense, TrialActivation.trial_license_id == TrialLicense.id)
        .where(
            TrialLicense.customer_id == customer_id,
            TrialLicense.expires_at > when,
            TrialActivation.revoked_at.is_(None),
        )
    ).all()

    return set(abonelik_urunleri) | set(deneme_urunleri)


def has_product_access(db: Session, customer_id: int, product_id: int, *, when: datetime | None = None) -> bool:
    return product_id in entitled_product_ids(db, customer_id, when=when)


def list_visible_releases(db: Session, *, customer_id: int, is_staff: bool) -> list[Release]:
    """`GET /api/v1/downloads` için. Personel TÜM aktif sürümleri görür
    (imzasız dahil — test/QA amaçlı). Müşteri tüm aktif İMZALI sürümleri
    görür (bkz. modül docstring'i, indirme kuralı). `customer_id` imza
    uyumluluğu için duruyor."""
    stmt = select(Release).where(Release.is_active.is_(True)).order_by(Release.published_at.desc())
    if not is_staff:
        stmt = stmt.where(Release.signed.is_(True))
    return list(db.scalars(stmt).all())
