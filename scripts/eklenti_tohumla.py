#!/usr/bin/env python
"""
colEGE "Soru sor" EK ÜRÜNÜ (eklenti) katalog tohumu — idempotent.

Oluşturur (yoksa):
  - ürün  `colege_soru`  ("colEGE Soru Sor"), `requires_product` = `colege`
    (bkz. app/services/eklentiler.py — yalnız aktif colEGE aboneliği olan
    müşteriye satılır, colEGE aktivasyonuna aynı license.json'da eklenir)
  - plan  `colege-soru-yillik` (tek kalem: colege_soru, tier "full")
  - 12 aylık fiyat, KDV HARİÇ NET (KDV %20 varsayılan — mevcut katalog deseni)

`colege` ürünü önceden var olmalı (katalogdaki temel ürün).

######################################################################
#  FİYAT YER TUTUCUDUR. Gerçek fiyat KULLANICI KARARIDIR.             #
#  `--net` verilmezse YER_TUTUCU_NET_FIYAT yazılır ve plan SATIŞA     #
#  KAPALI (is_active=False) oluşturulur — yanlışlıkla yer tutucu      #
#  fiyatla satılmasın. Yalnız yerel/test için                          #
#  `--yer-tutucu-fiyatla-satisa-ac` ile açılabilir.                    #
######################################################################

Kullanım:
    python scripts/eklenti_tohumla.py                       # yer tutucu fiyat, plan KAPALI
    python scripts/eklenti_tohumla.py --net 4800.00         # gerçek fiyat, plan AÇIK
    python scripts/eklenti_tohumla.py --yer-tutucu-fiyatla-satisa-ac   # YALNIZ test
Plan zaten varsa fiyat EKLENMEZ/DEĞİŞTİRİLMEZ (fiyat değişikliği yeni bir
`Price` satırı + `valid_until` ile yapılır, bkz. app/services/pricing.py).
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

from app.models import Plan, PlanItem, Price, Product  # noqa: E402

TEMEL_URUN_KODU = "colege"
EKLENTI_URUN_KODU = "colege_soru"
EKLENTI_URUN_ADI = "colEGE Soru Sor"
EKLENTI_PLAN_KODU = "colege-soru-yillik"
EKLENTI_PLAN_ADI = "colEGE Soru Sor — Yıllık (eklenti)"
EKLENTI_SURE_AY = 12

# !!! YER TUTUCU — GERÇEK FİYAT DEĞİL (kullanıcı kararı bekleniyor) !!!
YER_TUTUCU_NET_FIYAT = Decimal("1000.00")


def colege_soru_tohumla(db: Session, *, net: Decimal | None = None, yer_tutucuyla_ac: bool = False) -> Plan:
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
    if plan is None:
        satista = net is not None or yer_tutucuyla_ac
        plan = Plan(code=EKLENTI_PLAN_KODU, name=EKLENTI_PLAN_ADI, is_active=satista)
        plan.items.append(PlanItem(product=urun))  # tier: varsayılan "full"
        db.add(plan)
        db.flush()
        db.add(Price(plan_id=plan.id, months=EKLENTI_SURE_AY, amount=net if net is not None else YER_TUTUCU_NET_FIYAT))
        db.flush()
    return plan


def main() -> None:
    ap = argparse.ArgumentParser(description="colEGE Soru Sor eklentisini kataloğa ekler (idempotent).")
    ap.add_argument("--net", type=Decimal, help="12 aylık KDV hariç net fiyat (TL). Verilmezse YER TUTUCU + plan kapalı.")
    ap.add_argument("--yer-tutucu-fiyatla-satisa-ac", action="store_true",
                    help="YALNIZ yerel/test: yer tutucu fiyatla planı satışa açar")
    a = ap.parse_args()

    from app.db import SessionLocal

    with SessionLocal() as db:
        plan = colege_soru_tohumla(db, net=a.net, yer_tutucuyla_ac=a.yer_tutucu_fiyatla_satisa_ac)
        db.commit()
        fiyatlar = [f"{p.months} ay: {p.amount}" for p in plan.prices]
        print(f"plan {plan.id}: {plan.code} satışta={plan.is_active} fiyatlar={fiyatlar}")
        if any(p.amount == YER_TUTUCU_NET_FIYAT for p in plan.prices):
            print("UYARI: fiyat YER TUTUCU — gerçek fiyat kullanıcı kararı bekliyor.")


if __name__ == "__main__":
    main()
