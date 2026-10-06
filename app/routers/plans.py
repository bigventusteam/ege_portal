from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Plan
from app.schemas import PlanItemResponse, PlanPriceResponse, PlanResponse
from app.services.pricing import gecerli_fiyatlar, kdv_hesapla

router = APIRouter(prefix="/api/v1", tags=["plans"])


@router.get("/plans", response_model=list[PlanResponse])
def planlari_listele(db: Session = Depends(get_db)) -> list[PlanResponse]:
    """Oturumsuz da erişilebilir — frontend'in satın alma akışı (ürünler ve
    fiyatlar sayfası) giriş yapmadan önce de gösterilir. Yalnız `is_active`
    planlar döner; her plan için o anda geçerli TÜM fiyat seçenekleri (ör.
    1 ay VE 12 ay) ve KDV kırılımı (`app/services/pricing.py::kdv_hesapla`
    — `Order` oluşturulurken kullanılanla AYNI formül) birlikte gelir."""
    plans = db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.id)).all()

    sonuc: list[PlanResponse] = []
    for plan in plans:
        items = [
            PlanItemResponse(product_code=item.product.code, product_name=item.product.name, tier=item.tier)
            for item in plan.items
        ]
        prices = []
        for price in gecerli_fiyatlar(db, plan.id):
            vat_amount, total = kdv_hesapla(price.amount, price.vat_rate)
            prices.append(
                PlanPriceResponse(
                    months=price.months,
                    net=price.amount,
                    vat_rate=price.vat_rate,
                    vat_amount=vat_amount,
                    total=total,
                    currency=price.currency,
                )
            )
        sonuc.append(PlanResponse(id=plan.id, code=plan.code, name=plan.name, items=items, prices=prices))
    return sonuc
