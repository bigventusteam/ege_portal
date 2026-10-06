"""
Testlerde kullanılan sahte istemciler. `FakeBVPayClient` hiçbir zaman ağa
çıkmaz; `FakeImzalayici` gerçek Ed25519 imzalama YAPMAZ, yalnız
`LisansImzalayici` protokolüne uyar (bkz. app/licensing.py, app/bvpay/client.py).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.bvpay.client import BVPayPayment, BVPayRequestError


class FakeBVPayClient:
    def __init__(self) -> None:
        self.payments: dict[str, BVPayPayment] = {}
        self.created_requests: list[dict[str, Any]] = []
        self._sonraki_id = 1

    def kuyruga_ekle(self, payment: BVPayPayment) -> None:
        self.payments[payment.payment_id] = payment

    def get_payment(self, payment_id: str) -> BVPayPayment:
        try:
            return self.payments[payment_id]
        except KeyError as e:
            raise BVPayRequestError(f"bilinmeyen payment_id: {payment_id}") from e

    def create_payment(
        self,
        *,
        amount: Decimal,
        currency: str,
        use_3d: bool,
        card: dict[str, Any] | None,
        customer_email: str,
        return_url: str,
        passthrough: dict[str, Any],
    ) -> BVPayPayment:
        self.created_requests.append(
            {
                "amount": amount,
                "currency": currency,
                "use_3d": use_3d,
                "card": card,
                "customer_email": customer_email,
                "return_url": return_url,
                "passthrough": passthrough,
            }
        )
        payment_id = f"pay_test_{self._sonraki_id}"
        self._sonraki_id += 1
        payment = BVPayPayment(
            payment_id=payment_id,
            order_id=None,
            status="pending_3d",
            success=False,
            amount=Decimal(str(amount)),
            currency=currency,
            passthrough=passthrough,
            raw={},
        )
        self.payments[payment_id] = payment
        return payment


def ornek_odeme(
    *,
    payment_id: str = "pay_test_1",
    status: str = "approved",
    amount: Decimal = Decimal("12000.00"),
    currency: str = "949",
    passthrough: dict[str, Any] | None = None,
) -> BVPayPayment:
    passthrough = passthrough if passthrough is not None else {}
    return BVPayPayment(
        payment_id=payment_id,
        order_id=payment_id,
        status=status,
        success=status in {"approved", "captured"},
        amount=amount,
        currency=currency,
        passthrough=passthrough,
        raw={"payment_id": payment_id, "status": status, "amount": str(amount), "currency": currency},
    )


@dataclass
class FakeImzalayici:
    """`LisansImzalayici` protokolüne uyar — gerçek imza yerine payload'ın
    SHA-256'sını döner, böylece testler "aynı payload aynı imzayı üretir"
    gibi özellikleri de doğrulayabilir."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def imzala(self, payload: dict[str, Any]) -> str:
        self.calls.append(payload)
        kanonik = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return "fake-sig-" + hashlib.sha256(kanonik.encode("utf-8")).hexdigest()[:16]
