"""
Havale/EFT için personel "ödendi" işaretlemesi (kullanıcı kararı,
2026-10-05) — bvpay entegrasyonu bu akışta hiç devreye GİRMEZ: personel
banka ekstresinden/dekonttan gördüğü bir ödemeyi elle onaylar.

Onaylandıktan SONRAKİ etkiler (abonelik uzatma + lisans üretme)
`app/services/payments.py::apply_payment_effects` ÜZERİNDEN bvpay akışıyla
AYNI fonksiyonu paylaşır — kopya mantık YOK, bvpay davranışı birebir kalır.

## Kontroller (sırayla)

1. `received_at` gelecekte OLAMAZ — saf girdi doğrulaması, DB'ye hiç
   dokunmadan en başta yapılır.
2. Sipariş `SELECT ... FOR UPDATE` ile kilitlenir (PostgreSQL'de eşzamanlı
   iki işaretlemeyi sıraya sokar — bkz. app/services/payments.py'deki AYNI
   desen/gerekçe; SQLite'ta etkisiz).
3. **Görevler ayrılığı:** işaretleyen personelin KENDİ müşteri kaydı
   siparişin müşterisiyle AYNIYSA REDDEDİLİR (`SelfDealingError`) — bir
   personelin kendi kurumuna ait bir siparişi onaylaması çıkar
   çatışmasıdır.
4. Sipariş `PENDING` değilse REDDEDİLİR (`OrderAlreadyPaidError`) — zaten
   bvpay ile ödenmiş bir siparişi de kapsar, bilerek: payment_method'a göre
   ayrım YAPILMAZ, "PENDING değil" tek başına yeterli bir ret sebebidir.
5. `amount`, `order.total`'a (KDV DAHİL) `Decimal` olarak TAM EŞİT olmalı
   (`AmountMismatchError`) — KISMİ ÖDEME YOK.
6. `bank_reference` boş olamaz; sistem genelinde TEKİL olması (aynı dekont
   iki siparişe kullanılamaz) `Payment.bank_reference` UNIQUE kısıtıyla
   (DB seviyesinde, yarışa karşı GERÇEK güvence) zorlanır —
   `DuplicateBankReferenceError` bu ihlalin `IntegrityError`'dan çevrilmiş
   hâlidir.

Reddedilen HER deneme (4-6) `app/services/payments.py::PaymentVerification
Service._audit_basarisiz` ile AYNI desende denetim kaydına yazılır — ayrı,
küçük bir commit ile (ana akışta henüz hiçbir yazma yapılmamış)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditEvent, Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, User
from app.services.payments import apply_payment_effects


class ManualPaymentError(Exception):
    """Tüm elle ödeme işaretleme hatalarının ortak üst sınıfı."""


class OrderNotFoundError(ManualPaymentError):
    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"order_id={order_id} bulunamadı")


class FutureReceivedAtError(ManualPaymentError):
    def __init__(self, received_at: datetime):
        self.received_at = received_at
        super().__init__(f"received_at gelecekte olamaz: {received_at.isoformat()}")


class SelfDealingError(ManualPaymentError):
    def __init__(self, order_id: int, user_id: int):
        self.order_id = order_id
        self.user_id = user_id
        super().__init__(
            f"user_id={user_id} kendi müşterisine ait order_id={order_id} siparişini işaretleyemez "
            "(görevler ayrılığı)"
        )


class OrderAlreadyPaidError(ManualPaymentError):
    def __init__(self, order_id: int, status: OrderStatus):
        self.order_id = order_id
        self.status = status
        super().__init__(f"order_id={order_id} zaten sonuçlanmış (durum={status.value}, PENDING değil)")


class AmountMismatchError(ManualPaymentError):
    def __init__(self, got: Decimal, expected: Decimal):
        self.got = got
        self.expected = expected
        super().__init__(f"tutar uyuşmazlığı: gönderilen={got} sipariş toplamı={expected} (kısmi ödeme yok)")


class BankReferenceRequiredError(ManualPaymentError):
    def __init__(self):
        super().__init__("bank_reference boş olamaz")


class DuplicateBankReferenceError(ManualPaymentError):
    def __init__(self, bank_reference: str):
        self.bank_reference = bank_reference
        super().__init__(f"bank_reference={bank_reference!r} başka bir siparişte zaten kullanılmış")


def _audit_basarisiz(
    db: Session, *, order_id: int, staff_user_id: int, hata: ManualPaymentError, extra: dict | None = None
) -> None:
    """`PaymentVerificationService._audit_basarisiz` ile AYNI desen — ana
    akıştan bağımsız, ayrı küçük bir commit."""
    db.add(
        AuditEvent(
            event_type="payment.mark_paid_rejected",
            entity_type="order",
            entity_id=str(order_id),
            data={"staff_user_id": staff_user_id, "error_type": type(hata).__name__, "error": str(hata), **(extra or {})},
        )
    )
    db.commit()


def mark_order_paid_manually(
    db: Session,
    *,
    order_id: int,
    staff_user: User,
    amount: Decimal,
    bank_reference: str,
    received_at: datetime,
    note: str | None,
) -> Payment:
    bank_reference = bank_reference.strip()

    now = datetime.now(timezone.utc)
    if received_at > now:
        hata = FutureReceivedAtError(received_at)
        _audit_basarisiz(db, order_id=order_id, staff_user_id=staff_user.id, hata=hata)
        raise hata

    order = db.execute(select(Order).where(Order.id == order_id).with_for_update()).scalar_one_or_none()
    if order is None:
        # Var olmayan bir sipariş için denetim kaydı AÇILMAZ — tutulacak bir
        # entity_id (order_id) var ama entity'nin kendisi hiç yok; personel
        # zaten `GET /admin/orders`'tan gelen GERÇEK id'lerle çalışır, bu
        # yol pratikte yalnız elle/hatalı bir URL ile tetiklenir.
        raise OrderNotFoundError(order_id)

    if order.customer_id == staff_user.customer_id:
        hata = SelfDealingError(order_id, staff_user.id)
        _audit_basarisiz(db, order_id=order_id, staff_user_id=staff_user.id, hata=hata)
        raise hata

    if order.status != OrderStatus.PENDING:
        _audit_basarisiz(
            db, order_id=order_id, staff_user_id=staff_user.id,
            hata=OrderAlreadyPaidError(order_id, order.status), extra={"order_status": order.status.value},
        )
        raise OrderAlreadyPaidError(order_id, order.status)

    if amount != order.total:
        _audit_basarisiz(
            db, order_id=order_id, staff_user_id=staff_user.id,
            hata=AmountMismatchError(amount, order.total),
            extra={"amount": str(amount), "order_total": str(order.total)},
        )
        raise AmountMismatchError(amount, order.total)

    if not bank_reference:
        _audit_basarisiz(db, order_id=order_id, staff_user_id=staff_user.id, hata=BankReferenceRequiredError())
        raise BankReferenceRequiredError()

    payment = Payment(
        order_id=order.id,
        bvpay_payment_id=None,
        amount=amount,
        currency=order.currency,
        status=PaymentStatus.CAPTURED,
        payment_method=PaymentMethod.BANK_TRANSFER,
        raw_response={},
        processed_at=now,
        bank_reference=bank_reference,
        marked_by_user_id=staff_user.id,
        note=note,
        received_at=received_at,
    )

    try:
        apply_payment_effects(db, order=order, payment=payment)
        db.add(
            AuditEvent(
                event_type="payment.marked_paid_manual",
                entity_type="order",
                entity_id=str(order.id),
                data={
                    "staff_user_id": staff_user.id,
                    "amount": str(amount),
                    "bank_reference": bank_reference,
                    "received_at": received_at.isoformat(),
                },
            )
        )
        db.commit()
    except IntegrityError as e:
        # `bank_reference` UNIQUE ihlali — eşzamanlı iki istek AYNI dekontu
        # kullanmaya çalıştı (ya da bu dekont başka bir siparişte zaten
        # kullanılmış). Kaybeden taraf olarak geri alıp AYRI bir commit'le
        # denetim kaydı yazıyoruz (bkz. _audit_basarisiz).
        db.rollback()
        hata = DuplicateBankReferenceError(bank_reference)
        _audit_basarisiz(db, order_id=order_id, staff_user_id=staff_user.id, hata=hata)
        raise hata from e

    db.refresh(payment)
    return payment
