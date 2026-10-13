#!/usr/bin/env python
"""
colEGE "Soru sor" EK ÜRÜNÜ (eklenti) katalog tohumu — idempotent.

Oluşturur (yoksa):
  - ürün  `colege_soru`  ("colEGE Soru Sor"), `requires_product` = `colege`
    (bkz. app/services/eklentiler.py — yalnız aktif colEGE aboneliği olan
    müşteriye satılır, colEGE aktivasyonuna aynı license.json'da eklenir)
  - plan  `colege-soru-yillik` (tek kalem: colege_soru, tier "full")
  - 12 aylık fiyat, KDV HARİÇ NET (KDV %20 varsayılan — mevcut katalog deseni)
    KULLANICI KARARI (2026-10-13): colEGE fiyatına EK ayda 500 TL (KDV hariç)
    -> 12 ay net 6.000,00 TL (KDV dahil 7.200,00 TL). Eklenti temel abonelikle
    aynı gün biter; ücret kalan güne orantılanır (app/services/eklentiler.py).

`colege` ürünü önceden var olmalı (katalogdaki temel ürün).

Kullanım:
    python scripts/eklenti_tohumla.py                 # karar fiyatı (6.000,00 net), plan AÇIK
    python scripts/eklenti_tohumla.py --net 4800.00   # başka net fiyat, plan AÇIK
Plan zaten varsa fiyat EKLENMEZ/DEĞİŞTİRİLMEZ (fiyat değişikliği yeni bir
`Price` satırı + `valid_until` ile yapılır, bkz. app/services/pricing.py).
TEK İSTİSNA: eski sürümün yer tutucu fiyatla (1000,00) KAPALI oluşturduğu,
hiç sipariş almamış plan karar fiyatına çekilir ve satışa açılır.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models import Order, Plan, PlanItem, Price, Product  # noqa: E402

TEMEL_URUN_KODU = "colege"
EKLENTI_URUN_KODU = "colege_soru"
EKLENTI_URUN_ADI = "colEGE Soru Sor"
EKLENTI_PLAN_KODU = "colege-soru-yillik"
EKLENTI_PLAN_ADI = "colEGE Soru Sor — Yıllık (eklenti)"
EKLENTI_SURE_AY = 12

# Kullanıcı kararı 2026-10-13: ayda 500 TL (KDV hariç) x 12.
KARAR_NET_FIYAT = Decimal("6000.00")
# Eski sürümün yer tutucusu — yalnız o kapalı planı tanıyıp düzeltmek için.
ESKI_YER_TUTUCU_NET_FIYAT = Decimal("1000.00")


def colege_soru_tohumla(db: Session, *, net: Decimal | None = None) -> Plan:
    """Idempotent; `db.commit()` ÇAĞIRMAZ (çağıran yapar). Dönen değer plan."""
    temel = db.scalar(select(Product).where(Product.code == TEMEL_URUN_KODU))
    if temel is None:
        raise RuntimeError(f"temel ürün '{TEMEL_URUN_KODU}' katalogda yok — önce onu oluşturun")

    urun = db.scalar(select(Product).where(Product.code == EKLENTI_URUN_KODU))
    if urun is None:
        urun = Product(code=EKLENTI_URUN_KODU, name=EKLENTI_URUN_ADI, requires_product_id=temel.id)
        db.add(urun)
        db.flush()
    elif urun.requires_product_id != temel.id:
        urun.requires_product_id = temel.id

    plan = db.scalar(select(Plan).where(Plan.code == EKLENTI_PLAN_KODU))
    tutar = net if net is not None else KARAR_NET_FIYAT
    if plan is None:
        plan = Plan(code=EKLENTI_PLAN_KODU, name=EKLENTI_PLAN_ADI, is_active=True)
        plan.items.append(PlanItem(product=urun))  # tier: varsayılan "full"
        db.add(plan)
        db.flush()
        db.add(Price(plan_id=plan.id, months=EKLENTI_SURE_AY, amount=tutar))
        db.flush()
    elif (not plan.is_active and [p.amount for p in plan.prices] == [ESKI_YER_TUTUCU_NET_FIYAT]
          and db.scalar(select(Order.id).where(Order.plan_id == plan.id).limit(1)) is None):
        plan.prices[0].amount = tutar
        plan.is_active = True
        db.flush()
    return plan


def main() -> None:
    ap = argparse.ArgumentParser(description="colEGE Soru Sor eklentisini kataloğa ekler (idempotent).")
    ap.add_argument("--net", type=Decimal, help=f"12 aylık KDV hariç net fiyat (TL). Varsayılan {KARAR_NET_FIYAT}.")
    a = ap.parse_args()

    from app.db import SessionLocal

    with SessionLocal() as db:
        plan = colege_soru_tohumla(db, net=a.net)
        db.commit()
        fiyatlar = [f"{p.months} ay: {p.amount}" for p in plan.prices]
        print(f"plan {plan.id}: {plan.code} satışta={plan.is_active} fiyatlar={fiyatlar}")


if __name__ == "__main__":
    main()
