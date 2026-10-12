"""
Ek ürünler (eklentiler) — ör. colEGE "Soru sor" özelliği (`colege_soru`).

Bir `Product`'ın `requires_product_id`'si doluysa o ürün bir EKLENTİdir
(bkz. app/models.py::Product). Kurallar (2026-10-12):

1. **Satış:** eklenti içeren bir plan yalnız temel ürünün AKTİF aboneliği
   (status=active VE `current_period_end > şimdi`) olan müşteriye satılır —
   ya da temel ürün AYNI planın içindeyse (paket). `create_order`'da
   zorlanır (`TemelAbonelikGerekliError`, 409).

2. **Aktivasyon:** eklentinin kendi `activation_request` dosyası YOKTUR —
   ürün (colEGE) tek dosya üretir, `product="colege"`. Eklenti, temel
   ürünün çevrimdışı aktivasyonuna eklenir: aynı license.json'da
   `products.colege` VE `products.colege_soru`, ikisi de temel ürünün
   dosyasındaki AYNI `fingerprint.components` ile (colEGE soru kontrolü
   `current_fingerprint(ctx)`'i "colege" ürün adıyla hesaplar — bkz.
   colEGE license_service._soru_lisansi_gecerli_mi). Eklenti aboneliği
   üzerinden aktivasyon reddedilir (`EklentiTekBasinaAktiveEdilemezError`).

3. **Bitiş tarihi:** şema v2'de `expires` ÜRÜN BAŞINA DEĞİL, payload
   düzeyinde TEKTİR (ege_lisans schema_v2.validate_v2 her ürün için
   `payload.expires`'a bakar). Bu yüzden eklenti dahil edildiğinde lisansın
   bitişi = min(temel abonelik bitişi, eklenti aboneliği bitişi):
   - eklenti hiçbir zaman ödenmiş süresinin ötesinde açık kalmaz;
   - temel ürün de hiçbir zaman kendi süresinin ötesine geçmez (eklenti
     temel ürünü aşamaz — colEGE kapalıyken soru özelliği zaten anlamsız);
   - BEDELİ: eklenti temel üründen ÖNCE biterse lisansın tamamı o tarihte
     biter (grace_days boyunca colEGE çalışmaya devam eder). Müşteri aynı
     kurulumun dosyasıyla yeniden aktive eder (YENİLEME, koltuk harcamaz)
     ve eklentisi dolmuşsa yalnız colEGE içeren, colEGE bitişine kadar
     geçerli bir lisans alır. Ürün başına bitiş, ege_lisans şemasına
     `products.<p>.expires` eklenmeden mümkün değil (açık konu).

4. **Koltuk:** eklentinin KENDİ koltuk sayısı vardır (eklenti aboneliğinin
   `seats`'i) — `Activation` satırı eklenti aboneliğinin LicenseKey'i
   altında, eklenti ürünü için, temel kurulumun parmak iziyle yazılır.
   Aynı kurulum (aynı instance_id) yeniden aktive edilirse YENİLEMEdir —
   ne temel üründe ne eklentide yeni koltuk harcanır. Eklentinin koltukları
   doluysa ve bu kurulum onlardan biri değilse temel ürünün aktivasyonu
   REDDEDİLMEZ — lisans eklentisiz üretilir ve `AuditEvent
   ("activation.addon_seat_full")` yazılır (colEGE'nin ikinci makinesi,
   eklentinin tek koltuğu yüzünden kilitlenmemeli).

5. **Makine değişikliği:** personel temel ürünün aktivasyonunu iptal
   edince aynı müşterinin AYNI kurulumdaki (aynı instance_id) eklenti
   aktivasyonları da iptal edilir (eklenti koltuğu da serbest kalır) —
   bkz. app/routers/admin.py::aktivasyonu_iptal_et.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Activation, LicenseKey, Plan, PlanItem, Product, Subscription, SubscriptionStatus


class EklentiHatasi(Exception):
    """Eklenti kurallarıyla ilgili hataların ortak üst sınıfı."""


class TemelAbonelikGerekliError(EklentiHatasi):
    def __init__(self, *, eklenti: str, temel: str):
        self.eklenti = eklenti
        self.temel = temel
        super().__init__(
            f"'{eklenti}' bir eklentidir — satın almak için önce aktif bir '{temel}' aboneliğiniz olmalı"
        )


class EklentiTekBasinaAktiveEdilemezError(EklentiHatasi):
    def __init__(self, *, eklentiler: set[str], temeller: set[str]):
        self.eklentiler = eklentiler
        self.temeller = temeller
        super().__init__(
            f"{sorted(eklentiler)} eklentidir, tek başına aktive edilemez — {sorted(temeller)} aboneliğinizin "
            "çevrimdışı aktivasyonunu (aynı kurulumun activation_request dosyasıyla) yapın; eklenti aynı "
            "license.json'a otomatik eklenir"
        )


def aktif_mi(sub: Subscription, now: datetime) -> bool:
    """app/services/releases.py::entitled_product_ids ile AYNI tanım."""
    return sub.status == SubscriptionStatus.ACTIVE and sub.current_period_end > now


def temel_urunun_aktif_aboneligi_var_mi(db: Session, *, customer_id: int, product_id: int, now: datetime) -> bool:
    sayi = db.scalar(
        select(func.count())
        .select_from(Subscription)
        .join(Plan, Subscription.plan_id == Plan.id)
        .join(PlanItem, PlanItem.plan_id == Plan.id)
        .where(
            Subscription.customer_id == customer_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.current_period_end > now,
            PlanItem.product_id == product_id,
        )
    )
    return bool(sayi)


def siparis_icin_eklenti_kontrolu(db: Session, *, customer_id: int, plan: Plan) -> None:
    """Plan eklenti içeriyorsa temel ürünü ya aynı planda ya da müşterinin
    aktif bir aboneliğinde olmalı; değilse `TemelAbonelikGerekliError`."""
    now = datetime.now(timezone.utc)
    plandaki_urunler = {item.product_id for item in plan.items}
    for item in plan.items:
        urun = item.product
        if not urun.is_addon or urun.requires_product_id in plandaki_urunler:
            continue
        if not temel_urunun_aktif_aboneligi_var_mi(
            db, customer_id=customer_id, product_id=urun.requires_product_id, now=now
        ):
            raise TemelAbonelikGerekliError(eklenti=urun.code, temel=urun.requires_product.code)


@dataclass
class EklentiKalemi:
    """Bir temel aktivasyona eklenecek eklenti: hangi abonelikten (koltuk,
    bitiş), hangi ürün, hangi temel ürünün parmak iziyle."""

    subscription: Subscription
    product: Product
    temel_kod: str


def _bilesenler(activation: Activation) -> dict | None:
    try:
        d = json.loads(activation.fingerprint)
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def eklenti_aktivasyonunu_bul(
    db: Session, *, license_key_id: int, product_id: int, instance_id_hash: str
) -> Activation | None:
    for aday in db.scalars(
        select(Activation).where(
            Activation.license_key_id == license_key_id,
            Activation.product_id == product_id,
            Activation.revoked_at.is_(None),
        )
    ).all():
        b = _bilesenler(aday)
        if b is not None and b.get("instance_id") == instance_id_hash:
            return aday
    return None


def aday_eklenti_abonelikleri(
    db: Session, *, customer_id: int, temel_kodlar: set[str], now: datetime
) -> list[tuple[Subscription, Product]]:
    """Müşterinin, temeli `temel_kodlar`dan biri olan eklenti ürünlerini
    taşıyan AKTİF abonelikleri — (abonelik, eklenti ürünü) çiftleri, en
    geç biten önce (aynı eklenti için birden çok abonelik varsa uzun süreli
    olan tercih edilir)."""
    sonuc: list[tuple[Subscription, Product]] = []
    for sub in db.scalars(
        select(Subscription).where(
            Subscription.customer_id == customer_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.current_period_end > now,
        )
    ).all():
        for item in sub.plan.items:
            urun = item.product
            if urun.is_addon and urun.requires_product.code in temel_kodlar:
                sonuc.append((sub, urun))
    sonuc.sort(key=lambda t: t[0].current_period_end, reverse=True)
    return sonuc


def aktif_eklenti_aktivasyon_sayisi(db: Session, *, license_key_id: int, product_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Activation)
            .where(
                Activation.license_key_id == license_key_id,
                Activation.product_id == product_id,
                Activation.revoked_at.is_(None),
            )
        )
        or 0
    )


def ayni_kurulumdaki_eklenti_aktivasyonlari(db: Session, activation: Activation) -> list[Activation]:
    """`activation` bir TEMEL ürün aktivasyonuysa, aynı müşterinin aynı
    kurulumdaki (aynı instance_id) aktif EKLENTİ aktivasyonları."""
    b = _bilesenler(activation)
    if b is None or "instance_id" not in b:
        return []
    customer_id = activation.license_key.subscription.customer_id
    eklenti_urunleri = db.scalars(select(Product.id).where(Product.requires_product_id == activation.product_id)).all()
    if not eklenti_urunleri:
        return []
    sonuc: list[Activation] = []
    for aday in db.scalars(
        select(Activation)
        .join(LicenseKey, Activation.license_key_id == LicenseKey.id)
        .join(Subscription, LicenseKey.subscription_id == Subscription.id)
        .where(
            Subscription.customer_id == customer_id,
            Activation.product_id.in_(eklenti_urunleri),
            Activation.revoked_at.is_(None),
        )
    ).all():
        ab = _bilesenler(aday)
        if ab is not None and ab.get("instance_id") == b["instance_id"]:
            sonuc.append(aday)
    return sonuc
