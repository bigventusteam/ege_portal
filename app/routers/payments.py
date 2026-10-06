from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.bvpay import BVPayClient
from app.db import get_db
from app.deps import get_bvpay_client
from app.schemas import BVPayWebhookPayload
from app.services.payments import PaymentVerificationError, PaymentVerificationService

router = APIRouter(prefix="/api/v1", tags=["payments"])
logger = logging.getLogger(__name__)


@router.post("/webhooks/bvpay", status_code=202)
def bvpay_webhook(
    body: BVPayWebhookPayload,
    db: Session = Depends(get_db),
    bvpay: BVPayClient = Depends(get_bvpay_client),
) -> dict:
    """`payment.result` webhook'u. Gövde İMZASIZ geldiği için yalnız hangi
    payment_id/order_id'nin kontrol edileceğini söyleyen bir TETİKLEYİCİ
    olarak kullanılır; asıl doğrulama servis içinde ayrı bir GET ile yapılır
    (bkz. app/services/payments.py docstring'i).

    Her zaman 202 döner: bvpay'in webhook'u tekrar denemesi burada bir şey
    değiştirmez (doğrulama zaten idempotent), hata durumunu 4xx/5xx ile
    bvpay'e yansıtmanın bir faydası yok — yalnız loglanır."""
    order_id = body.order_id
    if order_id is None and body.passthrough:
        order_id = body.passthrough.get("order_id")

    if order_id is None:
        logger.warning("bvpay webhook: order_id çözümlenemedi (payment_id=%s)", body.payment_id)
        return {"received": True, "processed": False}

    service = PaymentVerificationService(db, bvpay)
    try:
        service.verify_and_process(order_id=int(order_id), payment_id=body.payment_id)
    except PaymentVerificationError:
        logger.exception("bvpay webhook doğrulaması başarısız (order_id=%s, payment_id=%s)", order_id, body.payment_id)
        return {"received": True, "processed": False}

    return {"received": True, "processed": True}
