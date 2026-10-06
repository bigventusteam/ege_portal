from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IssuedLicense, LicenseKey, Subscription
from app.security import generate_license_key, hash_license_key


def get_or_create_license_key(db: Session, subscription: Subscription) -> tuple[LicenseKey, str | None]:
    """Abonelik için geçerli bir LicenseKey olduğundan emin olur — İMZALI
    BİR BELGE ÜRETMEZ, yalnız insan-okur anahtarı (hash'lenerek saklanan).

    Zaten varsa dokunmadan döner (`raw_key` = None — düz metin hiçbir yerde
    saklanmadığı için tekrar üretilemez). Yeni üretilirse `raw_key` (bir kez
    gösterilecek) ile birlikte döner.

    İMZALI bir `IssuedLicense` ÜRETMEZ — bunu çağıran (ör. app/services/
    offline_activation.py) kendi `IssuedLicense`'ını KENDİSİ yazmalı.
    KARAR (2026-10-06, EGE lider onayı — müşteri testinde "aynı abonelikte
    2 lisans" bulundu): ödeme akışı (app/services/payments.py::
    apply_payment_effects) da YALNIZ bunu çağırır, artık bir placeholder
    `IssuedLicense` ÜRETMEZ. Önceki tasarım (kaldırılan `ensure_license_key`)
    satın alma anında fingerprint/activation henüz bilinmediği için
    `fingerprint: None` ile imzalı bir "online tarzı" belge de üretiyordu —
    ama `ege_lisans` şema v2 ÇAPA ZORUNLULUĞU (bkz. ege_lisans/src/
    ege_lisans/schema_v2.py, "fingerprint_missing_anchor") yüzünden bu
    belge HİÇBİR kurulumda GEÇERLİ olamazdı; yalnız müşteriye kafa
    karıştırıcı, kullanılamaz bir ikinci "lisans" olarak görünüyordu."""
    existing = db.scalars(
        select(LicenseKey).where(
            LicenseKey.subscription_id == subscription.id,
            LicenseKey.revoked_at.is_(None),
        )
    ).first()
    if existing is not None:
        return existing, None

    raw_key = generate_license_key()
    license_key = LicenseKey(
        subscription_id=subscription.id,
        key_hash=hash_license_key(raw_key),
        key_prefix=raw_key.split("-")[0] + "-" + raw_key.split("-")[1],
    )
    db.add(license_key)
    db.flush()
    return license_key, raw_key


def find_issued_license(db: Session, subscription_id: int, license_id: str) -> IssuedLicense | None:
    """Yeniden indirme ucu için (`GET /api/v1/subscriptions/{id}/licenses/
    {license_id}`) — `license_id`, `IssuedLicense.payload["license_id"]`
    içinde durur, ayrı bir kolon DEĞİL; bu yüzden Python tarafında
    eşleştiriliyor. Bir abonelikte tipik olarak tek haneli sayıda
    `IssuedLicense` olur (her çevrimdışı aktivasyon bir tane ekler — ödeme
    artık placeholder bir belge ÜRETMİYOR, bkz. get_or_create_license_key
    docstring'i), bu yüzden SQL'de JSON sorgusu yerine burada filtrelemek
    hem taşınabilir (SQLite/PostgreSQL) hem yeterince hızlı."""
    for issued in db.scalars(select(IssuedLicense).where(IssuedLicense.subscription_id == subscription_id)).all():
        if issued.payload.get("license_id") == license_id:
            return issued
    return None
