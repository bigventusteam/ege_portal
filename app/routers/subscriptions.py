from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditEvent, Subscription, User
from app.routers.auth import get_current_user
from app.schemas import (
    LicenseDocumentResponse,
    SubscriptionActivationSummary,
    SubscriptionIssuedLicenseSummary,
    SubscriptionPlanItemSummary,
    SubscriptionResponse,
)
from app.services.licenses import find_issued_license
from app.services.subscriptions import list_customer_subscriptions

router = APIRouter(prefix="/api/v1", tags=["subscriptions"])


def _abonelik_getir(db: Session, subscription_id: int, user: User) -> Subscription:
    """`app/routers/activations.py::_abonelik_getir` ile AYNI desen (sisEGE'deki
    "var olmayan == başkasına ait, ikisi de aynı 404" deseni) — burada da
    kopyalanmadan tekrar yazıldı çünkü iki satırlık bir kontrolü ayrı bir
    modüle çıkarmak bu ölçekte gereksiz dolaylılık olurdu."""
    subscription = db.get(Subscription, subscription_id)
    if subscription is None or subscription.customer_id != user.customer_id:
        raise HTTPException(404, "abonelik bulunamadı")
    return subscription


def _abonelik_yanitina_cevir(subscription: Subscription) -> SubscriptionResponse:
    items = [
        SubscriptionPlanItemSummary(product_code=item.product.code, product_name=item.product.name, tier=item.tier)
        for item in subscription.plan.items
    ]

    activations: list[SubscriptionActivationSummary] = []
    issued_licenses: list[SubscriptionIssuedLicenseSummary] = []
    for license_key in subscription.license_keys:
        for activation in license_key.activations:
            activations.append(
                SubscriptionActivationSummary(
                    product_code=activation.product.code,
                    mode=activation.mode.value,
                    created_at=activation.created_at,
                    last_seen_at=activation.last_seen_at,
                    revoked_at=activation.revoked_at,
                )
            )
        for issued in license_key.issued_licenses:
            issued_licenses.append(
                SubscriptionIssuedLicenseSummary(
                    license_id=issued.payload.get("license_id", ""),
                    issued_at=issued.issued_at,
                    expires_at=issued.expires_at,
                )
            )

    activations.sort(key=lambda a: a.created_at, reverse=True)
    issued_licenses.sort(key=lambda lic: lic.issued_at, reverse=True)

    return SubscriptionResponse(
        id=subscription.id,
        plan_id=subscription.plan_id,
        plan_code=subscription.plan.code,
        plan_name=subscription.plan.name,
        items=items,
        status=subscription.status.value,
        current_period_end=subscription.current_period_end,
        activations=activations,
        issued_licenses=issued_licenses,
    )


@router.get("/subscriptions", response_model=list[SubscriptionResponse])
def abonelikleri_listele(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[SubscriptionResponse]:
    """Oturumdaki kullanıcının KENDİ müşterisine ait abonelikler —
    `customer_id` istekten DEĞİL oturumdan gelir (IDOR yok, bkz.
    app/routers/orders.py'deki aynı desen)."""
    subscriptions = list_customer_subscriptions(db, user.customer_id)
    return [_abonelik_yanitina_cevir(sub) for sub in subscriptions]


@router.get("/subscriptions/{subscription_id}/licenses/{license_id}", response_model=LicenseDocumentResponse)
def lisans_yeniden_indir(
    subscription_id: int, license_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> LicenseDocumentResponse:
    """İmzalı `license.json`'u YENİDEN indirir (müşteri dosyayı kaybettiyse/
    yeni bir makineye kuracaksa) — aynı sahiplik kontrolü + denetim kaydı."""
    subscription = _abonelik_getir(db, subscription_id, user)

    issued = find_issued_license(db, subscription.id, license_id)
    if issued is None:
        raise HTTPException(404, "lisans bulunamadı")

    db.add(
        AuditEvent(
            event_type="license.redownloaded",
            entity_type="issued_license",
            entity_id=str(issued.id),
            data={"subscription_id": subscription.id, "license_id": license_id, "customer_id": user.customer_id},
        )
    )
    db.commit()

    return LicenseDocumentResponse(payload=issued.payload, signature=issued.signature)
