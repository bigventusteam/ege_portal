from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Customer, Order, OrderStatus, Plan
from app.services.eklentiler import (
    YILLIK_AY,
    eklenti_siparisi_hazirla,
    siparise_yenileme_satirlarini_ekle,
    yenileme_eklentileri,
)
from app.services.pricing import gecerli_fiyat, kdv_hesapla


class PlanNotFoundError(Exception):
    def __init__(self, plan_id: int):
        self.plan_id = plan_id
        super().__init__(f"plan_id={plan_id} bulunamadı ya da aktif değil")


class CustomerNotFoundError(Exception):
    def __init__(self, customer_id: int):
        self.customer_id = customer_id
        super().__init__(f"customer_id={customer_id} bulunamadı")


MAX_QUANTITY = 100


class InvalidQuantityError(Exception):
    def __init__(self, quantity: int):
        self.quantity = quantity
        super().__init__(f"quantity={quantity} geçersiz — 1 ile {MAX_QUANTITY} arasında olmalı")


def create_order(
    db: Session,
    *,
    customer_id: int,
    plan_id: int,
    months: int,
    quantity: int = 1,
    base_subscription_id: int | None = None,
) -> Order:
    """`POST /api/v1/orders` mantığı. Tutar, o anda geçerli Price'tan
    hesaplanıp siparişe SNAPSHOT olarak yazılır (bkz. Order.net docstring).

    `Price.amount` KDV HARİÇ net tutardır (karar 2026-09-28, bkz.
    PLAN.md §8 madde 1) — KDV tutarı burada hesaplanır, uydurma bir
    yuvarlama kuralı DEĞİL: ``Decimal`` ile, ``ROUND_HALF_UP``, 2 basamağa
    (bankacılık/faturalama kuralı — `float` ile KESİNLİKLE hesaplanmaz,
    ikili kayan nokta 99.99 * 0.20 gibi değerlerde sessizce yanlış sonuç
    üretir).

    `quantity` (KARAR 2026-10-05: lisans birimi MAKİNE) — `net` BİRİM
    fiyatın `quantity` İLE ÇARPILMASINDAN SONRAKİ toplam net tutardır, KDV
    bu TOPLAMA uygulanır (adet sonrası kırılım — `kdv_hesapla` TEK yerde
    kalır, burada da `app/routers/plans.py`'de de aynı fonksiyon)."""
    if not (1 <= quantity <= MAX_QUANTITY):
        raise InvalidQuantityError(quantity)

    if db.get(Customer, customer_id) is None:
        raise CustomerNotFoundError(customer_id)

    plan = db.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        raise PlanNotFoundError(plan_id)

    # Eklenti (ör. colege_soru) — EŞ-SONLANMA (bkz. app/services/eklentiler.py):
    # temel aboneliğe bağlanır, bitişi onunkine eşit, ücret kalan güne orantılı.
    eklenti = eklenti_siparisi_hazirla(
        db, customer_id=customer_id, plan=plan, quantity=quantity, base_subscription_id=base_subscription_id
    )
    yenileme = None
    if eklenti is not None:
        months = YILLIK_AY  # fiyat temeli yıllık; gerçek süre addon_period_end/prorated_days
        net = eklenti.net
        vat_rate, currency = eklenti.price_vat_rate, eklenti.currency
    else:
        price = gecerli_fiyat(db, plan_id, months)
        net = price.amount * quantity
        vat_rate, currency = price.vat_rate, price.currency
        # Temel abonelik yenileniyorsa bağlı eklentiler de aynı döneme (madde 3).
        yenileme = yenileme_eklentileri(db, customer_id=customer_id, plan=plan, months=months)
        net += yenileme.toplam_net

    vat_amount, total = kdv_hesapla(net, vat_rate)

    order = Order(
        customer_id=customer_id,
        plan_id=plan_id,
        months=months,
        quantity=quantity,
        net=net,
        currency=currency,
        vat_rate=vat_rate,
        vat_amount=vat_amount,
        total=total,
        status=OrderStatus.PENDING,
    )
    if eklenti is not None:
        order.base_subscription_id = eklenti.base_subscription.id
        order.addon_period_end = eklenti.period_end
        order.prorated_days = eklenti.days
    if yenileme is not None:
        siparise_yenileme_satirlarini_ekle(order, yenileme)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order
