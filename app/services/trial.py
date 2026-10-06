"""
Deneme (trial) lisansı — PLAN.md §8 madde 7.

Karar (kullanıcı, 2026-09-26): lisanssız kurulum ürüne GÖMÜLÜ 7 gün çalışır
(worker_1, ürün tarafı) — bu portal tarafını ilgilendirmez. Portal tarafı,
ÜRETİCİNİN (yalnız üretici — müşteri DEĞİL) süreyi genel olarak ve müşteri
bazında (kampanyalar) değiştirebildiği, imzalı bir deneme lisansı
(`license_type: "trial"`) üreten kısım.

## Süre çözümleme önceliği

müşteri override (`Customer.trial_days_override`) > aktif kampanya
(`TrialCampaign`, tarih aralığı) > genel varsayılan (`TrialSettings`,
DB'de — env'DE DEĞİL, çünkü üretici çalışma zamanında değiştirebilmeli).
Birden çok kampanya aynı anda geçerliyse EN SON OLUŞTURULAN kazanır (bkz.
`find_active_campaign`) — basit, öngörülebilir; kampanyaların kesişmemesi
operasyonel bir beklenti, DB seviyesinde zorlanmıyor.

Yöneticinin elle verdiği ek süre(ler) (`TrialGrant.extra_days`) bu
önceliğin SONUNA eklenir. **Birikmeli:** tüketilmemiş (`consumed_at` boş)
TÜM grant'ların `extra_days`'i TOPLANIR ve bir deneme lisansı üretilince
HEPSİ birlikte tüketilir (bkz. `find_usable_grants`) — bir yöneticinin
verdiği hiçbir süre "askıda" kalmaz. Herhangi bir tüketilmemiş grant varsa
aynı müşteri+ürün için "ikinci deneme yok" kuralı (yalnız BU müşteri için,
çapraz-müşteri instance_id kontrolünü DEĞİL) bir kez atlanır.

## `license_type`

`ege_lisans.signing.build_v2_payload`'a doğrudan `license_type="trial"`
veriliyor (worker_1 bunu ekledi — önceki turda henüz yokken payload'a
manuel eklenen bir sarmalayıcı kullanılıyordu, artık gerek kalmadı).
`validate_license` sonucu da `license_type` alanını döner ve `ege_lisans`
artık v2 lisanslarda `instance_id` çapasını KENDİSİ de zorunlu kılıyor
(`"fingerprint_missing_anchor"`) — bu, portalın kendi
`app/services/activation_request.py` kontrolüyle aynı açığı kapatan,
kütüphane tarafında BAĞIMSIZ bir ikinci katman (savunma derinliği).

## Çapraz-müşteri `instance_id` çarpışması: deneme REDDEDER, abonelik yalnız İŞARETLER

Bilerek farklı: deneme öncesinde müşteriyle henüz gerçek bir ödeme
ilişkisi/kanıtı yok, bu yüzden aynı kurulumun başka bir müşteride deneme
aldığı görülünce burada doğrudan 409 ile reddediyoruz
(`InstanceIdAlreadyTrialedError`) + `AuditEvent`. Abonelik çevrimdışı
aktivasyonunda (`app/services/offline_activation.py`) müşteri ZATEN ÖDEMİŞ
— orada yanlış pozitifle meşru bir ödeyen müşteriyi kilitleme riski daha
ağır bastığı için yalnız `AuditEvent` yazılır, istek reddedilmez. İki farklı
risk dengesi, iki farklı davranış — EGE lider'in onayladığı kasıtlı bir
tutarsızlık (bkz. ege_portal/README.md "Deneme (trial) lisansı" bölümü).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

from ege_lisans.signing import build_v2_payload
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.licensing import LisansImzalayici
from app.models import (
    TAM_SURUM_TIER,
    AuditEvent,
    Customer,
    Product,
    TrialActivation,
    TrialCampaign,
    TrialGrant,
    TrialLicense,
    TrialSettings,
    User,
)
from app.services.activation_request import InvalidActivationRequestError, parse_activation_request

TRIAL_TIER = TAM_SURUM_TIER  # kademe yok — deneme de tam sürüm (PLAN.md §8)
TRIAL_GRACE_DAYS = 0

__all__ = [
    "DuplicateTrialError",
    "InstanceIdAlreadyTrialedError",
    "InvalidActivationRequestError",
    "NoActivationFilesError",
    "TrialActivationError",
    "UnknownProductError",
    "create_trial_grant",
    "create_trial_campaign",
    "create_trial_license",
    "get_or_create_trial_settings",
    "list_trial_campaigns",
    "resolve_trial_days",
    "set_customer_trial_override",
    "update_trial_settings",
]


class TrialActivationError(Exception):
    """Tüm deneme-lisansı-üretme hatalarının ortak üst sınıfı."""


class NoActivationFilesError(TrialActivationError):
    def __init__(self):
        super().__init__("en az bir activation_request dosyası gerekli")


class UnknownProductError(TrialActivationError):
    def __init__(self, codes: set[str]):
        self.codes = codes
        super().__init__(f"katalogda olmayan ürün(ler): {sorted(codes)}")


class DuplicateTrialError(TrialActivationError):
    def __init__(self, product_code: str):
        self.product_code = product_code
        super().__init__(f"'{product_code}' için bu müşteriye zaten bir deneme lisansı verilmiş")


class InstanceIdAlreadyTrialedError(TrialActivationError):
    def __init__(self, product_code: str):
        self.product_code = product_code
        super().__init__(f"'{product_code}': bu kurulum (instance_id) başka bir müşteride deneme almış")


# ─── Ayarlar (yönetici) ──────────────────────────────────────────────────────


def get_or_create_trial_settings(db: Session) -> TrialSettings:
    settings_row = db.get(TrialSettings, 1)
    if settings_row is None:
        settings_row = TrialSettings(id=1, default_days=7)
        db.add(settings_row)
        db.flush()
    return settings_row


def update_trial_settings(db: Session, *, default_days: int, updated_by: User) -> TrialSettings:
    if default_days < 1:
        raise ValueError("default_days en az 1 olmalı")

    settings_row = get_or_create_trial_settings(db)
    onceki = settings_row.default_days
    settings_row.default_days = default_days
    settings_row.updated_by_user_id = updated_by.id

    db.add(
        AuditEvent(
            event_type="trial.settings_updated",
            entity_type="trial_settings",
            entity_id="1",
            data={"previous_default_days": onceki, "default_days": default_days, "updated_by": updated_by.id},
        )
    )
    db.commit()
    db.refresh(settings_row)
    return settings_row


def list_trial_campaigns(db: Session) -> list[TrialCampaign]:
    return list(db.scalars(select(TrialCampaign).order_by(TrialCampaign.starts_at.desc())).all())


def create_trial_campaign(
    db: Session, *, name: str, days: int, starts_at: datetime, ends_at: datetime, created_by: User
) -> TrialCampaign:
    if days < 1:
        raise ValueError("days en az 1 olmalı")
    if ends_at <= starts_at:
        raise ValueError("ends_at, starts_at'tan sonra olmalı")

    campaign = TrialCampaign(
        name=name, days=days, starts_at=starts_at, ends_at=ends_at, created_by_user_id=created_by.id
    )
    db.add(campaign)
    db.flush()

    db.add(
        AuditEvent(
            event_type="trial.campaign_created",
            entity_type="trial_campaign",
            entity_id=str(campaign.id),
            data={
                "name": name,
                "days": days,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "created_by": created_by.id,
            },
        )
    )
    db.commit()
    db.refresh(campaign)
    return campaign


def set_customer_trial_override(db: Session, *, customer: Customer, days: int | None, updated_by: User) -> Customer:
    if days is not None and days < 1:
        raise ValueError("days en az 1 olmalı (None = override'ı kaldır)")

    onceki = customer.trial_days_override
    customer.trial_days_override = days

    db.add(
        AuditEvent(
            event_type="trial.customer_override_set",
            entity_type="customer",
            entity_id=str(customer.id),
            data={"previous_days": onceki, "days": days, "updated_by": updated_by.id},
        )
    )
    db.commit()
    db.refresh(customer)
    return customer


def create_trial_grant(db: Session, *, customer: Customer, extra_days: int, reason: str | None, granted_by: User) -> TrialGrant:
    if extra_days < 1:
        raise ValueError("extra_days en az 1 olmalı")

    grant = TrialGrant(
        customer_id=customer.id, extra_days=extra_days, reason=reason, granted_by_user_id=granted_by.id
    )
    db.add(grant)
    db.flush()

    db.add(
        AuditEvent(
            event_type="trial.grant_created",
            entity_type="trial_grant",
            entity_id=str(grant.id),
            data={
                "customer_id": customer.id,
                "extra_days": extra_days,
                "reason": reason,
                "granted_by": granted_by.id,
            },
        )
    )
    db.commit()
    db.refresh(grant)
    return grant


# ─── Süre çözümleme ──────────────────────────────────────────────────────────


def find_active_campaign(db: Session, when: datetime) -> TrialCampaign | None:
    return db.scalars(
        select(TrialCampaign)
        .where(TrialCampaign.starts_at <= when, TrialCampaign.ends_at >= when)
        .order_by(TrialCampaign.created_at.desc())
    ).first()


def find_usable_grants(db: Session, customer_id: int) -> list[TrialGrant]:
    """Tüketilmemiş (`consumed_at` boş) TÜM grant'lar — birikmeli olarak
    kullanılır (bkz. modül docstring'i)."""
    return list(
        db.scalars(
            select(TrialGrant)
            .where(TrialGrant.customer_id == customer_id, TrialGrant.consumed_at.is_(None))
            .order_by(TrialGrant.created_at.asc())
        ).all()
    )


def resolve_trial_days(db: Session, customer: Customer, *, when: datetime | None = None) -> tuple[int, dict]:
    """`(gün, kaynak_bilgisi)` döner — `kaynak_bilgisi` AuditEvent'e ve
    yönetici arayüzüne konulmak üzere. Öncelik: müşteri override > aktif
    kampanya > genel varsayılan (bkz. modül docstring'i)."""
    when = when or datetime.now(timezone.utc)

    if customer.trial_days_override is not None:
        return customer.trial_days_override, {"source": "customer_override"}

    kampanya = find_active_campaign(db, when)
    if kampanya is not None:
        return kampanya.days, {"source": "campaign", "campaign_id": kampanya.id, "campaign_name": kampanya.name}

    genel = get_or_create_trial_settings(db)
    return genel.default_days, {"source": "general"}


# ─── Deneme lisansı üretimi ──────────────────────────────────────────────────


def create_trial_license(
    db: Session, *, customer: Customer, activation_files: list[tuple[str, bytes]], imzalayici: LisansImzalayici
) -> dict:
    """`activation_files`: `[(dosya_adı, ham_bayt), ...]` — abonelik
    çevrimdışı aktivasyonundakiyle AYNI `activation_request` doğrulaması
    (bkz. app/services/activation_request.py, ORTAK/kopyalanmadı). Dönen
    değer imzalı `{"payload": ..., "signature": ...}`."""
    if not activation_files:
        raise NoActivationFilesError()

    istekler: dict[str, dict] = {}
    for filename, raw in activation_files:
        data = parse_activation_request(filename, raw)
        product = data["product"]
        if product in istekler:
            raise InvalidActivationRequestError(filename, f"'{product}' için birden fazla dosya yüklendi")
        istekler[product] = data

    urunler = {
        p.code: p for p in db.scalars(select(Product).where(Product.code.in_(istekler))).all()
    }
    bilinmeyen = set(istekler) - set(urunler)
    if bilinmeyen:
        raise UnknownProductError(bilinmeyen)

    grants = find_usable_grants(db, customer.id)

    # Kontroller — hiçbir yazma yapılmadan ÖNCE, kısmi/tutarsız bir durum
    # oluşmasın diye (bir ürün için 409 dönerken başka bir ürün için Activation
    # satırı yazılmış olmasın).
    for code, product in urunler.items():
        instance_id_hash = istekler[code]["fingerprint"]["components"]["instance_id"]

        if not grants and _musterinin_bu_urun_icin_denemesi_var_mi(db, customer.id, product.id):
            raise DuplicateTrialError(code)

        if _instance_id_baska_musteride_kullanilmis_mi(db, product.id, instance_id_hash, customer.id):
            db.add(
                AuditEvent(
                    event_type="trial.instance_id_collision",
                    entity_type="customer",
                    entity_id=str(customer.id),
                    data={"product": code, "instance_id_hash": instance_id_hash},
                )
            )
            db.commit()
            raise InstanceIdAlreadyTrialedError(code)

    gun, kaynak = resolve_trial_days(db, customer)
    gun += sum(g.extra_days for g in grants)
    bitis_tarihi = date.today() + timedelta(days=gun)
    now = datetime.now(timezone.utc)
    expires_at = datetime.combine(bitis_tarihi, datetime.min.time(), tzinfo=timezone.utc) + timedelta(
        hours=23, minutes=59, seconds=59
    )

    products_payload = {
        code: {"tier": TRIAL_TIER, "fingerprint_components": istekler[code]["fingerprint"]["components"]}
        for code in urunler
    }

    payload = build_v2_payload(
        license_id=f"lic_trial_{uuid.uuid4().hex[:16]}",
        subscription_id=f"trial_{uuid.uuid4().hex[:16]}",
        customer={"id": f"cus_{customer.id}", "name": customer.name, "email": customer.email},
        products=products_payload,
        issued=date.today().isoformat(),
        expires=bitis_tarihi.isoformat(),
        grace_days=TRIAL_GRACE_DAYS,
        activation={"id": f"act_trial_{uuid.uuid4().hex[:16]}", "mode": "trial"},
        license_type="trial",
    )
    signature = imzalayici.imzala(payload)

    trial_license = TrialLicense(
        customer_id=customer.id, payload=payload, signature=signature, issued_at=now, expires_at=expires_at
    )
    db.add(trial_license)
    db.flush()

    for code, product in urunler.items():
        components = istekler[code]["fingerprint"]["components"]
        db.add(
            TrialActivation(
                trial_license_id=trial_license.id,
                product_id=product.id,
                instance_id_hash=components["instance_id"],
                fingerprint=json.dumps(components, sort_keys=True),
            )
        )

    for g in grants:
        g.consumed_at = now

    db.add(
        AuditEvent(
            event_type="trial.issued",
            entity_type="trial_license",
            entity_id=str(trial_license.id),
            data={
                "customer_id": customer.id,
                "products": sorted(urunler),
                "days": gun,
                "days_source": kaynak,
                "grant_ids": [g.id for g in grants],
            },
        )
    )
    db.commit()

    return {"payload": payload, "signature": signature}


def _musterinin_bu_urun_icin_denemesi_var_mi(db: Session, customer_id: int, product_id: int) -> bool:
    return (
        db.scalars(
            select(TrialActivation)
            .join(TrialLicense, TrialActivation.trial_license_id == TrialLicense.id)
            .where(
                TrialLicense.customer_id == customer_id,
                TrialActivation.product_id == product_id,
                TrialActivation.revoked_at.is_(None),
            )
        ).first()
        is not None
    )


def _instance_id_baska_musteride_kullanilmis_mi(
    db: Session, product_id: int, instance_id_hash: str, customer_id: int
) -> bool:
    return (
        db.scalars(
            select(TrialActivation)
            .join(TrialLicense, TrialActivation.trial_license_id == TrialLicense.id)
            .where(
                TrialActivation.product_id == product_id,
                TrialActivation.instance_id_hash == instance_id_hash,
                TrialActivation.revoked_at.is_(None),
                TrialLicense.customer_id != customer_id,
            )
        ).first()
        is not None
    )
