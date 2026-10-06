from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Price

_IKI_BASAMAK = Decimal("0.01")


class PriceNotFoundError(Exception):
    def __init__(self, plan_id: int, months: int):
        self.plan_id = plan_id
        self.months = months
        super().__init__(f"plan_id={plan_id} months={months} için geçerli bir fiyat bulunamadı")


def kdv_hesapla(net: Decimal, vat_rate: Decimal) -> tuple[Decimal, Decimal]:
    """`(vat_amount, total)` döner — `Decimal`/`ROUND_HALF_UP`, 2 basamak
    (bankacılık/faturalama kuralı, bkz. app/services/orders.py::create_order
    aynı gerekçe — `float` ile KESİNLİKLE hesaplanmaz). `GET /api/v1/plans`
    (fiyat gösterimi) ile `create_order` (sipariş snapshot'ı) AYNI formülü
    kullanır — iki yerde ayrı ayrı yazılırsa gösterilen fiyatla gerçekte
    tahsil edilen tutar sessizce ayrışabilirdi."""
    vat_amount = (net * vat_rate / Decimal("100")).quantize(_IKI_BASAMAK, rounding=ROUND_HALF_UP)
    return vat_amount, net + vat_amount


def gecerli_fiyat(db: Session, plan_id: int, months: int, *, when: datetime | None = None) -> Price:
    """`plan_id` × `months` için `when` anında (varsayılan: şimdi) geçerli
    Price'ı döner. İstemci tutar gönderemez — tutar HER ZAMAN buradan gelir."""
    when = when or datetime.now(timezone.utc)
    stmt = (
        select(Price)
        .where(
            Price.plan_id == plan_id,
            Price.months == months,
            Price.valid_from <= when,
            or_(Price.valid_until.is_(None), Price.valid_until >= when),
        )
        .order_by(Price.valid_from.desc())
    )
    price = db.scalars(stmt).first()
    if price is None:
        raise PriceNotFoundError(plan_id, months)
    return price


def gecerli_fiyatlar(db: Session, plan_id: int, *, when: datetime | None = None) -> list[Price]:
    """`GET /api/v1/plans` için — bu plandaki HER `months` değeri için o
    anda geçerli tek fiyatı döner (bkz. `gecerli_fiyat` ile AYNI "çakışan
    aralıklarda en son `valid_from` kazanır" kuralı). Birden çok süre
    seçeneği olabileceği için (ör. 1 ay VE 12 ay) `gecerli_fiyat`'ın tersine
    `months` parametresi ALMAZ, TÜMÜNÜ döner."""
    when = when or datetime.now(timezone.utc)
    stmt = (
        select(Price)
        .where(
            Price.plan_id == plan_id,
            Price.valid_from <= when,
            or_(Price.valid_until.is_(None), Price.valid_until >= when),
        )
        .order_by(Price.months, Price.valid_from.desc())
    )
    en_guncel: dict[int, Price] = {}
    for price in db.scalars(stmt).all():
        en_guncel.setdefault(price.months, price)  # months, valid_from DESC sıralı — ilk görülen en güncel
    return sorted(en_guncel.values(), key=lambda p: p.months)
