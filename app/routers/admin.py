"""
Yönetici (üretici) uçları — PLAN.md §8 madde 7: deneme süresini yalnız
üretici değiştirebilir, müşteri değiştiremez. Hepsi `require_staff`
arkasında (bkz. app/routers/auth.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activation, AuditEvent, Customer, Order, OrderStatus, Release, User
from app.routers.auth import require_staff
from app.schemas import (
    AdminOrderResponse,
    CustomerTrialOverrideRequest,
    DeactivateReleaseRequest,
    MarkOrderPaidRequest,
    MarkOrderPaidResponse,
    RevokeActivationRequest,
    TrialCampaignCreateRequest,
    TrialCampaignResponse,
    TrialGrantCreateRequest,
    TrialGrantResponse,
    TrialSettingsResponse,
    TrialSettingsUpdateRequest,
)
from app.services import trial as trial_service
from app.services.manual_payments import (
    AmountMismatchError,
    BankReferenceRequiredError,
    DuplicateBankReferenceError,
    FutureReceivedAtError,
    ManualPaymentError,
    OrderAlreadyPaidError,
    OrderNotFoundError,
    SelfDealingError,
    mark_order_paid_manually,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _musteri_getir(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "müşteri bulunamadı")
    return customer


@router.get("/trial-settings", response_model=TrialSettingsResponse)
def deneme_ayarlarini_getir(db: Session = Depends(get_db), _: User = Depends(require_staff)) -> TrialSettingsResponse:
    return TrialSettingsResponse.model_validate(trial_service.get_or_create_trial_settings(db))


@router.put("/trial-settings", response_model=TrialSettingsResponse)
def deneme_ayarlarini_guncelle(
    body: TrialSettingsUpdateRequest, db: Session = Depends(get_db), admin: User = Depends(require_staff)
) -> TrialSettingsResponse:
    try:
        settings_row = trial_service.update_trial_settings(db, default_days=body.default_days, updated_by=admin)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return TrialSettingsResponse.model_validate(settings_row)


@router.get("/trial-campaigns", response_model=list[TrialCampaignResponse])
def deneme_kampanyalarini_listele(
    db: Session = Depends(get_db), _: User = Depends(require_staff)
) -> list[TrialCampaignResponse]:
    return [TrialCampaignResponse.model_validate(c) for c in trial_service.list_trial_campaigns(db)]


@router.post("/trial-campaigns", response_model=TrialCampaignResponse, status_code=201)
def deneme_kampanyasi_olustur(
    body: TrialCampaignCreateRequest, db: Session = Depends(get_db), admin: User = Depends(require_staff)
) -> TrialCampaignResponse:
    try:
        campaign = trial_service.create_trial_campaign(
            db, name=body.name, days=body.days, starts_at=body.starts_at, ends_at=body.ends_at, created_by=admin
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return TrialCampaignResponse.model_validate(campaign)


@router.patch("/customers/{customer_id}/trial-override")
def musteri_deneme_override_ayarla(
    customer_id: int,
    body: CustomerTrialOverrideRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_staff),
) -> dict:
    customer = _musteri_getir(db, customer_id)
    try:
        trial_service.set_customer_trial_override(db, customer=customer, days=body.days, updated_by=admin)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"customer_id": customer.id, "trial_days_override": customer.trial_days_override}


@router.post("/customers/{customer_id}/trial-grants", response_model=TrialGrantResponse, status_code=201)
def musteriye_deneme_ek_suresi_ver(
    customer_id: int,
    body: TrialGrantCreateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_staff),
) -> TrialGrantResponse:
    customer = _musteri_getir(db, customer_id)
    try:
        grant = trial_service.create_trial_grant(
            db, customer=customer, extra_days=body.extra_days, reason=body.reason, granted_by=admin
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return TrialGrantResponse.model_validate(grant)


# ─── Bekleyen siparişler / havale-EFT elle işaretleme (2026-10-05) ───────────


@router.get("/orders", response_model=list[AdminOrderResponse])
def siparisleri_listele(
    status: str = "pending", db: Session = Depends(get_db), _: User = Depends(require_staff)
) -> list[AdminOrderResponse]:
    """Yalnız personel (`is_staff`). `status` varsayılan `pending` —
    havale/EFT işaretleme akışının tek ihtiyacı bu, ama ileride başka bir
    durumu görmek istenirse diye serbest bırakıldı (geçersiz bir değer 422)."""
    try:
        durum = OrderStatus(status)
    except ValueError as e:
        gecerli = ", ".join(s.value for s in OrderStatus)
        raise HTTPException(422, f"geçersiz status: {status!r} (geçerli değerler: {gecerli})") from e

    orders = db.scalars(
        select(Order).where(Order.status == durum).order_by(Order.created_at.asc())
    ).all()
    return [
        AdminOrderResponse(
            id=o.id,
            customer_id=o.customer_id,
            customer_name=o.customer.name,
            plan_id=o.plan_id,
            plan_name=o.plan.name,
            months=o.months,
            net=o.net,
            vat_rate=o.vat_rate,
            vat_amount=o.vat_amount,
            total=o.total,
            currency=o.currency,
            status=o.status.value,
            created_at=o.created_at,
        )
        for o in orders
    ]


_MANUAL_PAYMENT_HTTP_STATUS: dict[type[ManualPaymentError], int] = {
    OrderNotFoundError: 404,
    SelfDealingError: 403,
    OrderAlreadyPaidError: 409,
    AmountMismatchError: 422,
    BankReferenceRequiredError: 422,
    FutureReceivedAtError: 422,
    DuplicateBankReferenceError: 409,
}


@router.post("/orders/{order_id}/mark-paid", response_model=MarkOrderPaidResponse)
def siparisi_odendi_isaretle(
    order_id: int,
    body: MarkOrderPaidRequest,
    db: Session = Depends(get_db),
    staff: User = Depends(require_staff),
) -> MarkOrderPaidResponse:
    """Havale/EFT ile gelen bir ödemeyi personel ELLE onaylar (kullanıcı
    kararı, 2026-10-05 — bvpay entegrasyonu banka bilgilerini beklerken).
    Kontroller ve sıraları için bkz. app/services/manual_payments.py modül
    docstring'i. Başarıda abonelik uzatılır + lisans üretilir — bvpay
    akışıyla AYNI `apply_payment_effects` üzerinden (kopya mantık yok)."""
    try:
        payment = mark_order_paid_manually(
            db,
            order_id=order_id,
            staff_user=staff,
            amount=body.amount,
            bank_reference=body.bank_reference,
            received_at=body.received_at,
            note=body.note,
        )
    except ManualPaymentError as e:
        status_code = _MANUAL_PAYMENT_HTTP_STATUS.get(type(e), 422)
        raise HTTPException(status_code, str(e)) from e

    return MarkOrderPaidResponse(
        payment_id=payment.id,
        order_id=payment.order_id,
        order_status=OrderStatus.PAID.value,
        amount=payment.amount,
        bank_reference=payment.bank_reference,
        received_at=payment.received_at,
        marked_by_user_id=payment.marked_by_user_id,
    )


# ─── Makine değişikliği — aktivasyon iptali (2026-10-05, "lisans birimi makine") ──


@router.post("/activations/{activation_id}/revoke")
def aktivasyonu_iptal_et(
    activation_id: int,
    body: RevokeActivationRequest,
    db: Session = Depends(get_db),
    staff: User = Depends(require_staff),
) -> dict:
    """Müşteri makine değiştirdiğinde (eski donanım bozuldu/elden çıktı vb.)
    personel eski aktivasyonu BURADAN iptal eder — koltuk serbest kalır,
    müşteri yeni makinede çevrimdışı aktivasyon yapabilir hâle gelir (bkz.
    app/services/offline_activation.py `_aktif_aktivasyon_sayisi`, artık
    bu satırı SAYMAZ). `reason` ZORUNLU ve `AuditEvent`e yazılır — bu,
    müşterinin elindeki bir lisansı GEÇERSİZLEŞTİREN bir eylemdir, kim/neden
    izi kalmalı."""
    activation = db.get(Activation, activation_id)
    if activation is None:
        raise HTTPException(404, "aktivasyon bulunamadı")
    if activation.revoked_at is not None:
        raise HTTPException(409, "aktivasyon zaten iptal edilmiş")

    now = datetime.now(timezone.utc)
    activation.revoked_at = now

    db.add(
        AuditEvent(
            event_type="activation.revoked_by_staff",
            entity_type="activation",
            entity_id=str(activation.id),
            data={
                "staff_user_id": staff.id,
                "reason": body.reason,
                "product_id": activation.product_id,
                "license_key_id": activation.license_key_id,
            },
        )
    )
    db.commit()

    return {"activation_id": activation.id, "revoked_at": now.isoformat()}

# ─── İndirme merkezi — sürümü yayından kaldırma ──────────────────────────────


@router.post("/releases/{release_id}/deactivate")
def surumu_yayindan_kaldir(
    release_id: int,
    body: DeactivateReleaseRequest,
    db: Session = Depends(get_db),
    staff: User = Depends(require_staff),
) -> dict:
    """Yanlış/geri çekilen bir sürümü SİLMEDEN gizler (`is_active=False`):
    müşteri listesinden düşer, indirme 404 döner; satır ve geçmiş indirme
    kayıtları kalır. Gerekçe AuditEvent'e yazılır."""
    release = db.get(Release, release_id)
    if release is None:
        raise HTTPException(404, "sürüm bulunamadı")
    if not release.is_active:
        raise HTTPException(409, "sürüm zaten yayından kaldırılmış")

    release.is_active = False
    db.add(
        AuditEvent(
            event_type="release.deactivated",
            entity_type="release",
            entity_id=str(release.id),
            data={
                "staff_user_id": staff.id,
                "reason": body.reason,
                "product_code": release.product.code,
                "version": release.version,
                "package_type": release.package_type.value,
            },
        )
    )
    db.commit()

    return {"release_id": release.id, "is_active": False}
