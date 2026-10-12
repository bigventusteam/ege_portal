"""
Ek ürünler (eklentiler) — ör. colEGE "Soru sor" özelliği (`colege_soru`).

Bir `Product`'ın `requires_product_id`'si doluysa o ürün bir EKLENTİdir
(bkz. app/models.py::Product). Kurallar (2026-10-12; EŞ-SONLANMA kullanıcı
kararı aynı gün):

1. **Bağlama ve satış:** eklenti aboneliği müşterinin BİR temel
   aboneliğine bağlıdır (`Subscription.base_subscription_id`). Eklenti
   siparişi yalnız temel ürünün AKTİF (status=active VE bitişi bugünden
   sonra) bir aboneliği varken açılabilir. Müşterinin o ürünü taşıyan
   birden çok aktif aboneliği varsa siparişte `base_subscription_id`
   AÇIKÇA seçilmelidir (422); tekse otomatik seçilir. Eklenti koltuğu,
   temel aboneliğin koltuğunu aşamaz. Temel ürün AYNI planın içindeyse
   (paket = "aynı sepet") eklenti tam dönem, normal fiyatla satılır, bağlama
   gerekmez. (`Subscription` müşteri+plan başına tektir — müşteri başına tek
   eklenti aboneliği, tek temel aboneliğe bağlı; başka temele taşımak
   personel işi.)

2. **Eş-sonlanma ve orantılı fiyat:** eklentinin bitişi = bağlandığı temel
   aboneliğin sipariş anındaki bitişi (`Order.addon_period_end`). Ücret:
   `yıllık net × adet × kalan_gün / 365`, kuruşa ROUND_HALF_UP (KDV mevcut
   `kdv_hesapla` deseniyle, toplam nete). `kalan_gün` = takvim günü farkı
   (temel bitiş tarihi − bugün); bugün biten (0 gün) temel aboneliğe eklenti
   SATILMAZ (asgari 1 gün). Ayrı bir asgari TUTAR eşiği konmadı: tutar zaten
   orantılı ve adil; bvpay ertelendi ve havalede işlem başı maliyet yok —
   kart komisyonu netleşince bir eşik (ör. "son 30 günde önce colEGE'yi
   yenileyin") eklenebilir (açık konu). /365 sabittir (artık yılda 366 gün
   kalan bir aboneliğe 366/365 ücret çıkar).

3. **Tek başına yenileme yok:** aktif (iptal edilmemiş, bitişi gelmemiş)
   bir eklenti aboneliği varken yeni eklenti siparişi 409. Temel abonelik
   YENİLENİRKEN (aynı plana yeni sipariş) ona bağlı, iptal edilmemiş her
   eklenti siparişe `OrderAddon` satırı olarak eklenir; ödeme onaylanınca
   eklentinin bitişi temel aboneliğin YENİ bitişine eşitlenir. Satır fiyatı:
   eklenti temel bitişe hizalıysa ve eklenti planında siparişin ay sayısı
   için fiyat varsa o fiyat × eklenti koltuğu; değilse yıllık fiyattan gün
   orantısı (eklentinin bitişinden temel aboneliğin yeni bitişine).

4. **İptal/iade:** personel `POST /api/v1/admin/eklentiler/{id}/iptal` ile
   eklenti aboneliğini iptal eder (status=cancelled, aktif eklenti
   aktivasyonları iptal) — sonraki aktivasyon eklentisiz olur, sonraki
   temel yenileme eklentiyi içermez.

5. **Aktivasyon:** eklentinin kendi `activation_request` dosyası YOKTUR —
   ürün (colEGE) tek dosya üretir, `product="colege"`. Eklenti, BAĞLI olduğu
   temel aboneliğin çevrimdışı aktivasyonuna eklenir: aynı license.json'da
   `products.colege` VE `products.colege_soru`, ikisi de temel ürünün
   dosyasındaki AYNI `fingerprint.components` ile (colEGE soru kontrolü
   `current_fingerprint(ctx)`'i "colege" ürün adıyla hesaplar). Eklenti
   aboneliği üzerinden aktivasyon reddedilir.

6. **Lisans bitişi:** şema v2'de `expires` payload düzeyinde TEKTİR. Eklenti
   dahilse lisans bitişi = min(temel, eklenti) — bu "en erken bitiş" kodu
   güvenlik ağı olarak KALIR; eş-sonlanma ile normal akışta ikisi eşittir.

7. **Koltuk:** eklentinin kendi koltuk sayısı vardır (eklenti aboneliğinin
   `seats`'i). Aynı kurulumun yeniden aktivasyonu ne temel üründe ne
   eklentide koltuk harcar. Eklenti koltukları doluysa temel aktivasyon
   REDDEDİLMEZ — lisans eklentisiz üretilir, `activation.addon_seat_full`.

8. **Makine değişikliği:** personel temel ürünün aktivasyonunu iptal edince
   aynı müşterinin AYNI kurulumdaki eklenti aktivasyonları da iptal edilir.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Activation,
    AuditEvent,
    LicenseKey,
    Order,
    OrderAddon,
    Plan,
    PlanItem,
    Product,
    Subscription,
    SubscriptionStatus,
)
from app.services.pricing import PriceNotFoundError, gecerli_fiyat, orantili_net
from app.services.subscriptions import _add_months

YILLIK_AY = 12


class EklentiHatasi(Exception):
    """Eklenti kurallarıyla ilgili hataların ortak üst sınıfı."""


class TemelAbonelikGerekliError(EklentiHatasi):
    def __init__(self, *, eklenti: str, temel: str):
        self.eklenti = eklenti
        self.temel = temel
        super().__init__(
            f"'{eklenti}' bir eklentidir — satın almak için bugünden sonra biten aktif bir '{temel}' "
            "aboneliğiniz olmalı"
        )


class TemelAbonelikSecimiGerekliError(EklentiHatasi):
    def __init__(self, *, eklenti: str, adaylar: list[int]):
        self.adaylar = adaylar
        super().__init__(
            f"'{eklenti}' birden çok aktif temel aboneliğinize bağlanabilir ({adaylar}) — siparişte "
            "base_subscription_id ile hangisine bağlanacağını seçin"
        )


class GecersizTemelAbonelikError(EklentiHatasi):
    def __init__(self, base_subscription_id: int, neden: str):
        self.base_subscription_id = base_subscription_id
        super().__init__(f"base_subscription_id={base_subscription_id}: {neden}")


class EklentiZatenAktifError(EklentiHatasi):
    def __init__(self, *, eklenti: str, subscription_id: int):
        self.subscription_id = subscription_id
        super().__init__(
            f"'{eklenti}' aboneliğiniz (#{subscription_id}) zaten aktif — eklenti tek başına yenilenmez, "
            "bağlı olduğu temel abonelik yenilenince aynı döneme birlikte yenilenir"
        )


class EklentiKoltukFazlaError(EklentiHatasi):
    def __init__(self, *, adet: int, temel_koltuk: int):
        super().__init__(f"eklenti adedi ({adet}) bağlanacağı temel aboneliğin koltuk sayısını ({temel_koltuk}) aşamaz")


class EklentiTekBasinaAktiveEdilemezError(EklentiHatasi):
    def __init__(self, *, eklentiler: set[str], temeller: set[str]):
        self.eklentiler = eklentiler
        self.temeller = temeller
        super().__init__(
            f"{sorted(eklentiler)} eklentidir, tek başına aktive edilemez — {sorted(temeller)} aboneliğinizin "
            "çevrimdışı aktivasyonunu (aynı kurulumun activation_request dosyasıyla) yapın; eklenti aynı "
            "license.json'a otomatik eklenir"
        )


class EklentiIptalHatasi(EklentiHatasi):
    pass


def aktif_mi(sub: Subscription, now: datetime) -> bool:
    """app/services/releases.py::entitled_product_ids ile AYNI tanım."""
    return sub.status == SubscriptionStatus.ACTIVE and sub.current_period_end > now


def temel_urunun_aktif_aboneligi_var_mi(db: Session, *, customer_id: int, product_id: int, now: datetime) -> bool:
    return bool(_temel_aday_abonelikler(db, customer_id=customer_id, product_id=product_id, now=now))


def _temel_aday_abonelikler(db: Session, *, customer_id: int, product_id: int, now: datetime) -> list[Subscription]:
    """Müşterinin `product_id`'yi taşıyan, AKTİF, bitişi bugünden sonraki
    (en az 1 tam takvim günü kalan) abonelikleri."""
    return [
        sub
        for sub in db.scalars(
            select(Subscription)
            .join(Plan, Subscription.plan_id == Plan.id)
            .join(PlanItem, PlanItem.plan_id == Plan.id)
            .where(
                Subscription.customer_id == customer_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.current_period_end > now,
                PlanItem.product_id == product_id,
            )
            .order_by(Subscription.id)
        ).all()
        if kalan_gun(sub.current_period_end, now) >= 1
    ]


def kalan_gun(bitis: datetime, now: datetime) -> int:
    """Takvim günü farkı (UTC tarih). Bugün biten = 0."""
    return (bitis.date() - now.date()).days


def _plandaki_harici_eklenti(plan: Plan) -> Product | None:
    """Planın taşıdığı, temeli AYNI planda OLMAYAN eklenti ürünü (varsa).
    Temel ürün de plandaysa (paket = aynı sepet) None — normal fiyatlanır."""
    plandaki = {item.product_id for item in plan.items}
    for item in plan.items:
        if item.product.is_addon and item.product.requires_product_id not in plandaki:
            return item.product
    return None


@dataclass
class EklentiSiparisi:
    """Eklenti planı siparişinin hesaplanmış koşulları (bkz. madde 1-2)."""

    base_subscription: Subscription
    period_end: datetime
    days: int
    net: Decimal
    price_vat_rate: Decimal
    currency: str


def eklenti_siparisi_hazirla(
    db: Session, *, customer_id: int, plan: Plan, quantity: int, base_subscription_id: int | None
) -> EklentiSiparisi | None:
    """Plan harici bir eklenti taşımıyorsa None (normal sipariş). Taşıyorsa
    temel aboneliği seçer/doğrular, tek başına yenilemeyi reddeder ve
    orantılı neti hesaplar."""
    urun = _plandaki_harici_eklenti(plan)
    if urun is None:
        return None
    now = datetime.now(timezone.utc)
    adaylar = _temel_aday_abonelikler(db, customer_id=customer_id, product_id=urun.requires_product_id, now=now)

    if base_subscription_id is not None:
        temel = db.get(Subscription, base_subscription_id)
        if temel is None or temel.customer_id != customer_id:
            raise GecersizTemelAbonelikError(base_subscription_id, "abonelik bulunamadı")
        if urun.requires_product_id not in {i.product_id for i in temel.plan.items}:
            raise GecersizTemelAbonelikError(
                base_subscription_id, f"bu abonelik '{urun.requires_product.code}' ürününü taşımıyor")
        if temel not in adaylar:
            raise TemelAbonelikGerekliError(eklenti=urun.code, temel=urun.requires_product.code)
    elif not adaylar:
        raise TemelAbonelikGerekliError(eklenti=urun.code, temel=urun.requires_product.code)
    elif len(adaylar) > 1:
        raise TemelAbonelikSecimiGerekliError(eklenti=urun.code, adaylar=[a.id for a in adaylar])
    else:
        temel = adaylar[0]

    mevcut = db.scalar(
        select(Subscription).where(Subscription.customer_id == customer_id, Subscription.plan_id == plan.id))
    if mevcut is not None and aktif_mi(mevcut, now):
        raise EklentiZatenAktifError(eklenti=urun.code, subscription_id=mevcut.id)

    if quantity > temel.seats:
        raise EklentiKoltukFazlaError(adet=quantity, temel_koltuk=temel.seats)

    yillik = gecerli_fiyat(db, plan.id, YILLIK_AY)
    gun = kalan_gun(temel.current_period_end, now)
    return EklentiSiparisi(
        base_subscription=temel,
        period_end=temel.current_period_end,
        days=gun,
        net=orantili_net(yillik.amount * quantity, gun),
        price_vat_rate=yillik.vat_rate,
        currency=yillik.currency,
    )


@dataclass
class YenilemeEklentisi:
    subscription: Subscription
    net: Decimal
    quantity: int


@dataclass
class YenilemeEklentileri:
    satirlar: list[YenilemeEklentisi] = field(default_factory=list)

    @property
    def toplam_net(self) -> Decimal:
        return sum((s.net for s in self.satirlar), Decimal("0"))


def yenileme_eklentileri(db: Session, *, customer_id: int, plan: Plan, months: int) -> YenilemeEklentileri:
    """Bu sipariş müşterinin VAR OLAN bir aboneliğini yeniliyorsa, o
    aboneliğe bağlı ve iptal edilmemiş eklentilerin yenileme satırları
    (madde 3). Fiyat, ödeme şimdi gelseydi temel aboneliğin alacağı yeni
    bitişe göre hesaplanır (extend_subscription ile AYNI formül)."""
    sonuc = YenilemeEklentileri()
    temel = db.scalar(
        select(Subscription).where(Subscription.customer_id == customer_id, Subscription.plan_id == plan.id))
    if temel is None:
        return sonuc
    now = datetime.now(timezone.utc)
    temel_yeni_bitis = _add_months(max(now, temel.current_period_end), months)
    for eklenti in db.scalars(
        select(Subscription)
        .where(Subscription.base_subscription_id == temel.id, Subscription.status == SubscriptionStatus.ACTIVE)
        .order_by(Subscription.id)
    ).all():
        hizali = eklenti.current_period_end.date() == temel.current_period_end.date()
        net: Decimal | None = None
        if hizali:
            try:
                net = gecerli_fiyat(db, eklenti.plan_id, months).amount * eklenti.seats
            except PriceNotFoundError:
                net = None
        if net is None:
            yillik = gecerli_fiyat(db, eklenti.plan_id, YILLIK_AY)
            baslangic = max(now, eklenti.current_period_end)
            net = orantili_net(yillik.amount * eklenti.seats, max(0, kalan_gun(temel_yeni_bitis, baslangic)))
        sonuc.satirlar.append(YenilemeEklentisi(subscription=eklenti, net=net, quantity=eklenti.seats))
    return sonuc


# ─── Ödeme etkileri (app/services/payments.py::apply_payment_effects) ───────


def eklenti_siparisini_uygula(db: Session, order: Order) -> Subscription:
    """Eklenti planı siparişi ödendi: eklenti aboneliğini aç/yeniden aç,
    temel aboneliğe bağla, bitişini siparişteki hedefe (temel aboneliğin
    sipariş anındaki bitişi) eşitle."""
    sub = db.scalar(
        select(Subscription).where(Subscription.customer_id == order.customer_id, Subscription.plan_id == order.plan_id))
    if sub is None:
        sub = Subscription(customer_id=order.customer_id, plan_id=order.plan_id,
                           current_period_end=order.addon_period_end, seats=order.quantity)
        db.add(sub)
    elif aktif_mi(sub, datetime.now(timezone.utc)) and sub.current_period_end >= order.addon_period_end:
        # İki bekleyen eklenti siparişinin ikisi de ödendi — ikincisi süre
        # eklemez (eş-sonlanma), elle iade gerekir.
        db.add(AuditEvent(event_type="addon.duplicate_payment", entity_type="order", entity_id=str(order.id),
                          data={"subscription_id": sub.id}))
    sub.base_subscription_id = order.base_subscription_id
    sub.current_period_end = order.addon_period_end
    sub.seats = order.quantity
    sub.status = SubscriptionStatus.ACTIVE
    db.flush()
    temel = db.get(Subscription, order.base_subscription_id)
    if temel is not None and temel.current_period_end.date() != sub.current_period_end.date():
        # Sipariş ile ödeme arasında temel abonelik yenilendi/değişti —
        # eklenti ödenen süre kadar açık kalır; personel hizalamalı.
        db.add(AuditEvent(event_type="addon.misaligned", entity_type="subscription", entity_id=str(sub.id),
                          data={"base_subscription_id": temel.id, "order_id": order.id}))
    return sub


def yenileme_eklentilerini_uygula(db: Session, order: Order, temel: Subscription) -> None:
    """Temel abonelik yenileme siparişi ödendi: siparişteki her eklentiyi
    temel aboneliğin YENİ bitişine hizala (madde 3)."""
    for satir in order.addons:
        eklenti = satir.subscription
        if eklenti.status == SubscriptionStatus.CANCELLED:
            db.add(AuditEvent(event_type="addon.renewal_skipped_cancelled", entity_type="order",
                              entity_id=str(order.id), data={"subscription_id": eklenti.id, "net": str(satir.net)}))
            continue
        eklenti.current_period_end = temel.current_period_end
        eklenti.base_subscription_id = temel.id
        eklenti.status = SubscriptionStatus.ACTIVE
    db.flush()


def siparise_yenileme_satirlarini_ekle(order: Order, yenileme: YenilemeEklentileri) -> None:
    for s in yenileme.satirlar:
        order.addons.append(
            OrderAddon(subscription_id=s.subscription.id, plan_id=s.subscription.plan_id, quantity=s.quantity, net=s.net))


# ─── İptal ──────────────────────────────────────────────────────────────────


def eklentiyi_iptal_et(db: Session, sub: Subscription, now: datetime) -> list[Activation]:
    if not (sub.plan.items and all(i.product.is_addon for i in sub.plan.items)):
        raise EklentiIptalHatasi("bu abonelik bir eklenti aboneliği değil")
    if sub.status == SubscriptionStatus.CANCELLED:
        raise EklentiIptalHatasi("eklenti aboneliği zaten iptal edilmiş")
    sub.status = SubscriptionStatus.CANCELLED
    iptal: list[Activation] = []
    for lk in sub.license_keys:
        for a in lk.activations:
            if a.revoked_at is None:
                a.revoked_at = now
                iptal.append(a)
    return iptal


# ─── Aktivasyon yardımcıları ────────────────────────────────────────────────


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
    db: Session, *, customer_id: int, temel_abonelik_id: int, temel_kodlar: set[str], now: datetime
) -> list[tuple[Subscription, Product]]:
    """Aktive edilen temel aboneliğe (`temel_abonelik_id`) eklenecek
    eklentiler: müşterinin AKTİF abonelikleri içinde, temeli `temel_kodlar`dan
    biri olan eklenti ürünü taşıyan VE ya bu temel aboneliğe BAĞLI ya da
    (paket) temel aboneliğin KENDİSİ olanlar. Bağlamasız (eski) eklenti
    abonelikleri de kabul edilir. En geç biten önce."""
    sonuc: list[tuple[Subscription, Product]] = []
    for sub in db.scalars(
        select(Subscription).where(
            Subscription.customer_id == customer_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.current_period_end > now,
        )
    ).all():
        bagli = sub.id == temel_abonelik_id or sub.base_subscription_id in (None, temel_abonelik_id)
        if not bagli:
            continue
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
