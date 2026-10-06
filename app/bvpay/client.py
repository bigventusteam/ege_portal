"""
bvpay sanal POS istemcisi.

Sözleşme (EGE lider'den, bvpay projesinin mock/gerçek API'siyle aynı):
  - `GET  {BVPAY_URL}/api/v1/payments/{payment_id}`  (header: `X-API-Key`)
    → {payment_id, order_id, status, success, amount (string), currency
       ("949"), passthrough{...}, ...}
    status ∈ {pending_3d, approved, declined, error, captured, voided, refunded}
  - `POST {BVPAY_URL}/api/v1/payments`
    {amount, currency, use_3d, card, customer_email, return_url, passthrough}

`BVPayClient` bir Protocol'dür — gerçek ağa yalnız `HTTPBVPayClient` çıkar.
Testler `tests/fakes.py::FakeBVPayClient` kullanır, hiçbir zaman bu sınıfı
kullanmaz/import etmez.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import requests


@dataclass(frozen=True)
class BVPayPayment:
    payment_id: str
    order_id: str | None
    status: str
    success: bool
    amount: Decimal
    currency: str
    passthrough: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class BVPayError(Exception):
    """bvpay ile iletişimdeki tüm hataların ortak üst sınıfı."""


class BVPayRequestError(BVPayError):
    """HTTP isteği başarısız oldu ya da yanıt beklenen biçimde değil."""


class BVPayClient(Protocol):
    def get_payment(self, payment_id: str) -> BVPayPayment: ...

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
    ) -> BVPayPayment: ...


def _parse_payment(data: dict[str, Any]) -> BVPayPayment:
    try:
        amount = Decimal(str(data["amount"]))
    except (KeyError, InvalidOperation) as e:
        raise BVPayRequestError(f"bvpay yanıtında geçersiz 'amount': {data.get('amount')!r}") from e

    try:
        return BVPayPayment(
            payment_id=str(data["payment_id"]),
            order_id=str(data["order_id"]) if data.get("order_id") is not None else None,
            status=str(data["status"]),
            success=bool(data.get("success", False)),
            amount=amount,
            currency=str(data.get("currency", "")),
            passthrough=dict(data.get("passthrough") or {}),
            raw=data,
        )
    except KeyError as e:
        raise BVPayRequestError(f"bvpay yanıtında zorunlu alan eksik: {e}") from e


class HTTPBVPayClient:
    """Gerçek bvpay istemcisi. Testlerde KULLANILMAZ."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0, session: requests.Session | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key}

    def get_payment(self, payment_id: str) -> BVPayPayment:
        resp = self._session.get(
            f"{self._base_url}/api/v1/payments/{payment_id}",
            headers=self._headers(),
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise BVPayRequestError(f"bvpay GET /payments/{payment_id} -> HTTP {resp.status_code}")
        return _parse_payment(resp.json())

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
        body = {
            "amount": str(amount),
            "currency": currency,
            "use_3d": use_3d,
            "card": card,
            "customer_email": customer_email,
            "return_url": return_url,
            "passthrough": passthrough,
        }
        resp = self._session.post(
            f"{self._base_url}/api/v1/payments",
            json=body,
            headers=self._headers(),
            timeout=self._timeout,
        )
        if resp.status_code not in (200, 201):
            raise BVPayRequestError(f"bvpay POST /payments -> HTTP {resp.status_code}")
        return _parse_payment(resp.json())
