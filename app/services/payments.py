"""
Ödeme doğrulama ve işleme (PLAN.md §5.1, adım 3-4).

Webhook gövdesine GÜVENİLMEZ — yalnız "şu payment_id'yi kontrol et" sinyali
olarak kullanılır. Gerçek doğru bvpay'den her seferinde taze `GET` ile
okunur ve şu sırayla kontrol edilir:
  1. status ∈ {approved, captured}  (declined/error/pending_3d reddedilir;
     refunded/voided ayrı, daha açıklayıcı bir hata olarak reddedilir)
  2. currency == "949"
  3. amount == order.total            (Decimal ile, string/float karşılaştırma YOK)
  4. passthrough.order_id == order.id (başka bir siparişin ödemesi kabul edilmez)
  5. payment_id daha önce işlenmemiş  (idempotency)
  6. sipariş hâlâ PENDING             (aynı siparişe İKİNCİ bir ödeme, ya da
     zaten CANCELLED/FAILED bir siparişe gelen onaylı ödeme reddedilir —
     bkz. OrderAlreadyPaid)

Hepsi başarılıysa tek transaction'da: Order → paid, abonelik uzatılır,
LicenseKey yoksa üretilir.

Eşzamanlılık: `Order` satırı `SELECT ... FOR UPDATE` ile kilitlenerek okunur
(PostgreSQL'de aynı siparişe eşzamanlı doğrulamaları sıraya sokar; SQLite'ta
etkisizdir — sürücü FOR UPDATE'i desteklemez). Ek güvence olarak commit
sırasında `bvpay_payment_id` UNIQUE kısıtının tetiklediği IntegrityError
yakalanır: rollback edilip kayıt yeniden okunur, kazanan taraf idempotent
biçimde döndürülür (bkz. tests/test_payment_concurrency.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bvpay import BVPayClient, BVPayPayment
from app.models import AuditEvent, Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, Subscription
from app.services.licenses import get_or_create_license_key
from app.services.subscriptions import extend_subscription

EXPECTED_CURRENCY = "949"
APPROVED_STATUSES = {"approved", "captured"}
REFUND_LIKE_STATUSES = {"refunded", "voided"}


class PaymentVerificationError(Exception):
    """Tüm doğrulama hatalarının ortak üst sınıfı."""


class OrderNotFoundError(PaymentVerificationError):
    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"order_id={order_id} bulunamadı")


class PaymentNotApproved(PaymentVerificationError):
    def __init__(self, status: str):
        self.status = status
        super().__init__(f"bvpay ödeme durumu onaylı değil: {status!r}")


class PaymentRefundedOrVoided(PaymentNotApproved):
    def __init__(self, status: str):
        super().__init__(status)
        self.args = (f"ödeme iade edilmiş/iptal edilmiş, kabul edilmiyor: {status!r}",)


class CurrencyMismatch(PaymentVerificationError):
    def __init__(self, got: str):
        self.got = got
        super().__init__(f"beklenmeyen para birimi: {got!r} (beklenen {EXPECTED_CURRENCY!r})")


class AmountMismatch(PaymentVerificationError):
    def __init__(self, got: Decimal, expected: Decimal):
        self.got = got
        self.expected = expected
        super().__init__(f"tutar uyuşmazlığı: bvpay={got} sipariş={expected}")


class PassthroughMismatch(PaymentVerificationError):
    def __init__(self, got: object, expected: int):
        self.got = got
        self.expected = expected
        super().__init__(f"passthrough.order_id uyuşmazlığı: bvpay={got!r} beklenen={expected}")


class OrderAlreadyPaid(PaymentVerificationError):
    """Sipariş PENDING değilken (zaten paid, ya da cancelled/failed) gelen,
    aksi halde geçerli görünen bir ödeme. Abonelik UZATILMAZ. Ödeme yine de
    bir `Payment` satırı olarak (processed_at=None) kaydedilir ki elle iade
    edilebilsin — bkz. app/services/payments.py::_kaydet_yinelenen_odeme."""

    def __init__(self, order_id: int, payment_id: str):
        self.order_id = order_id
        self.payment_id = payment_id
        super().__init__(
            f"order_id={order_id} zaten sonuçlanmış (PENDING değil); "
            f"payment_id={payment_id} reddedildi, elle iade gerekebilir"
        )


def apply_payment_effects(db: Session, *, order: Order, payment: Payment) -> Subscription:
    """Bir ödeme onaylandıktan SONRAKİ ortak etkiler — bvpay
    (`PaymentVerificationService.verify_and_process`) VE elle havale/EFT
    işaretleme (`app/services/manual_payments.py::mark_order_paid_manually`)
    AYNI fonksiyonu çağırır; kopya mantık yazılmazsa bvpay davranışı
    (abonelik uzatma + lisans üretme sırası/şekli) birebir kalır (EGE
    lider'in isteği, 2026-10-05).

    `Payment` satırını eklemek, commit etmek VE olası `IntegrityError`'ı
    yakalamak ÇAĞIRANIN sorumluluğundadır — idempotency/eşzamanlılık hata
    sınıfları çağıranlar arasında FARKLI (bvpay_payment_id'ye karşı
    bank_reference UNIQUE ihlali), bu yüzden burada SARILMAZ.

    KARAR (2026-10-06, EGE lider onayı): ödemede YALNIZ `LicenseKey`
    (insan-okur anahtar) garantilenir — imzalı bir `IssuedLicense` ÜRETİLMEZ,
    bu yüzden fonksiyon bir imzalayıcıya hiç İHTİYAÇ DUYMUYOR (eskiden
    `imzalayici` parametresi vardı — KALDIRILDI, bkz. app/services/
    licenses.py::get_or_create_license_key docstring'i, gerekçe orada).
    O belge yalnız GERÇEK bir çevrimdışı aktivasyonda (app/services/
    offline_activation.py, kendi imzalayıcısıyla) oluşur."""
    db.add(payment)
    order.status = OrderStatus.PAID
    subscription = extend_subscription(
        db, customer_id=order.customer_id, plan_id=order.plan_id, months=order.months, quantity=order.quantity
    )
    get_or_create_license_key(db, subscription)
    return subscription


class PaymentVerificationService:
    def __init__(self, db: Session, bvpay: BVPayClient):
        self._db = db
        self._bvpay = bvpay

    def verify_and_process(self, order_id: int, payment_id: str) -> Payment:
        db = self._db

        order = db.execute(select(Order).where(Order.id == order_id).with_for_update()).scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(order_id)

        existing = db.scalars(select(Payment).where(Payment.bvpay_payment_id == payment_id)).first()
        if existing is not None:
            if existing.processed_at is not None:
                return existing  # aynı ödeme daha önce başarıyla işlendi — idempotent no-op
            # Daha önce "yinelenen ödeme" olarak işaretlenmiş (processed_at=None,
            # bkz. _kaydet_yinelenen_odeme) — tekrar bvpay'e sormaya/AuditEvent
            # tekrarlamaya gerek yok, aynı reddi tekrar bildir.
            raise OrderAlreadyPaid(order.id, payment_id)

        remote = self._bvpay.get_payment(payment_id)

        try:
            self._dogrula(remote, order)
        except PaymentVerificationError as hata:
            self._audit_basarisiz(order_id=order_id, payment_id=payment_id, hata=hata, remote_status=remote.status)
            raise

        if order.status != OrderStatus.PENDING:
            self._kaydet_yinelenen_odeme(order, payment_id, remote)
            raise OrderAlreadyPaid(order.id, payment_id)

        now = datetime.now(timezone.utc)
        payment = Payment(
            order_id=order.id,
            bvpay_payment_id=payment_id,
            amount=remote.amount,
            currency=remote.currency,
            status=PaymentStatus(remote.status),
            payment_method=PaymentMethod.BVPAY,
            raw_response=remote.raw,
            processed_at=now,
        )

        try:
            # NOT: `extend_subscription`/`get_or_create_license_key` (apply_payment_
            # effects içinde) kendi içinde `db.flush()` çağırır — bu, üstteki
            # `payment` insert'ini de (autoflush kapalı olsa bile) HEMEN
            # gönderir. UNIQUE ihlali bu yüzden nihai `db.commit()`'ten ÖNCE,
            # bu flush'lardan birinde de patlayabilir — try bloğu bu yüzden
            # `apply_payment_effects`'ten `db.commit()`'e kadar HER ŞEYİ
            # sarmalı, yalnız commit'i değil.
            apply_payment_effects(db, order=order, payment=payment)

            db.add(
                AuditEvent(
                    event_type="payment.verified",
                    entity_type="order",
                    entity_id=str(order.id),
                    data={"payment_id": payment_id, "status": remote.status, "amount": str(remote.amount)},
                )
            )

            db.commit()
        except IntegrityError:
            # Eşzamanlı bir doğrulama (webhook + mutabakat görevi gibi) aynı
            # payment_id'yi bizden önce commit etti — bvpay_payment_id UNIQUE
            # kısıtı bizim insert'imizi reddetti. Kaybeden taraf olarak kendi
            # yazdıklarımızı geri alıp kazananın sonucunu idempotent döneriz.
            db.rollback()
            kazanan = db.scalars(select(Payment).where(Payment.bvpay_payment_id == payment_id)).first()
            if kazanan is not None and kazanan.processed_at is not None:
                return kazanan
            raise  # beklenmedik bir bütünlük hatası — sessizce yutma

        db.refresh(payment)
        return payment

    def _dogrula(self, remote: BVPayPayment, order: Order) -> None:
        if remote.status in REFUND_LIKE_STATUSES:
            raise PaymentRefundedOrVoided(remote.status)
        if remote.status not in APPROVED_STATUSES:
            raise PaymentNotApproved(remote.status)

        if remote.currency != EXPECTED_CURRENCY:
            raise CurrencyMismatch(remote.currency)

        if remote.amount != order.total:
            raise AmountMismatch(remote.amount, order.total)

        passthrough_order_id = remote.passthrough.get("order_id")
        if passthrough_order_id is None or str(passthrough_order_id) != str(order.id):
            raise PassthroughMismatch(passthrough_order_id, order.id)

    def _audit_basarisiz(
        self, *, order_id: int, payment_id: str, hata: PaymentVerificationError, remote_status: str | None
    ) -> None:
        """Bu noktaya kadar başka hiçbir yazma yapılmadı (yalnız SELECT'ler) —
        yine de ana akıştan bağımsız, ayrı küçük bir commit ile yazılır.
        Ham bvpay yanıtı ve kart bilgisi KAYDEDİLMEZ, yalnız durum/hata özeti."""
        self._db.add(
            AuditEvent(
                event_type="payment.verification_failed",
                entity_type="order",
                entity_id=str(order_id),
                data={
                    "payment_id": payment_id,
                    "error_type": type(hata).__name__,
                    "error": str(hata),
                    "remote_status": remote_status,
                },
            )
        )
        self._db.commit()

    def _kaydet_yinelenen_odeme(self, order: Order, payment_id: str, remote: BVPayPayment) -> None:
        """Order PENDING değilken gelen, aksi halde geçerli görünen bir ödeme.
        `processed_at=None` bırakılır — bu "elle iade gerekiyor" işaretidir
        (bkz. idempotency kontrolündeki processed_at is None dalı)."""
        self._db.add(
            Payment(
                order_id=order.id,
                bvpay_payment_id=payment_id,
                amount=remote.amount,
                currency=remote.currency,
                status=PaymentStatus(remote.status),
                payment_method=PaymentMethod.BVPAY,
                raw_response=remote.raw,
                processed_at=None,
            )
        )
        self._db.add(
            AuditEvent(
                event_type="payment.duplicate_for_order",
                entity_type="order",
                entity_id=str(order.id),
                data={"payment_id": payment_id, "order_status": order.status.value, "amount": str(remote.amount)},
            )
        )
        self._db.commit()
