from __future__ import annotations

import calendar
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Subscription, SubscriptionStatus


def list_customer_subscriptions(db: Session, customer_id: int) -> list[Subscription]:
    """`GET /api/v1/subscriptions` için — yalnız BU müşterinin abonelikleri
    (çağıran IDOR kontrolünü `customer_id`'yi oturumdan alarak yapar, bkz.
    app/routers/subscriptions.py)."""
    return list(
        db.scalars(
            select(Subscription)
            .where(Subscription.customer_id == customer_id)
            .order_by(Subscription.created_at.desc())
        ).all()
    )


def _add_months(dt: datetime, months: int) -> datetime:
    """Ay ekler; hedef ayda gün yoksa (ör. 31 Ocak + 1 ay) o ayın son gününe
    sabitler (31 Ocak + 1 ay = 28/29 Şubat, 31 Mart değil)."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def extend_subscription(db: Session, *, customer_id: int, plan_id: int, months: int, quantity: int = 1) -> Subscription:
    """`period_end = max(bugün, mevcut_bitiş) + sipariş_süresi` (PLAN.md §5.1.4).

    Abonelik süresi dolmuşsa bugünden, hâlâ aktifse mevcut bitiş tarihinden
    uzatılır — böylece erken yenileme kalan süreyi silmez.

    `quantity` (lisans birimi MAKİNE, karar 2026-10-05) YALNIZ aboneliğin
    İLK AÇILIŞINDA `seats`e yazılır — bir UZATMA (aynı aboneliğe yeni
    sipariş) `seats`i DEĞİŞTİRMEZ (adet artırımı bu turda ayrı bir sipariş
    tipi değil, bkz. app/models.py::Subscription.seats)."""
    now = datetime.now(timezone.utc)

    sub = db.scalars(
        select(Subscription).where(Subscription.customer_id == customer_id, Subscription.plan_id == plan_id)
    ).first()

    if sub is None:
        sub = Subscription(
            customer_id=customer_id,
            plan_id=plan_id,
            current_period_end=now,
            seats=quantity,
            status=SubscriptionStatus.ACTIVE,
        )
        db.add(sub)
        db.flush()

    base = max(now, sub.current_period_end)
    sub.current_period_end = _add_months(base, months)
    sub.status = SubscriptionStatus.ACTIVE
    db.flush()
    return sub
