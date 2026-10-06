from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_imzalayici
from app.licensing import LisansImzalayici
from app.models import Subscription, User
from app.routers.auth import get_current_user
from app.services.offline_activation import (
    InvalidActivationRequestError,
    ProductMismatchError,
    SeatLimitExceededError,
    SubscriptionNotActiveError,
    create_offline_license,
)

router = APIRouter(prefix="/api/v1", tags=["activations"])


def _abonelik_getir(db: Session, subscription_id: int, user: User) -> Subscription:
    subscription = db.get(Subscription, subscription_id)
    # Var olmayan bir abonelik İLE başkasının aboneliği aynı 404'ü döner —
    # sisEGE'deki aynı desen (bkz. auth.py::get_workspace_context): hangisi
    # olduğunu istemciye sızdırmaz.
    if subscription is None or subscription.customer_id != user.customer_id:
        raise HTTPException(404, "abonelik bulunamadı")
    return subscription


@router.post("/subscriptions/{subscription_id}/offline-activation")
async def cevrimdisi_aktivasyon(
    subscription_id: int,
    files: list[UploadFile],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    imzalayici: LisansImzalayici = Depends(get_imzalayici),
) -> dict:
    """Abonelikteki HER ürün için bir `activation_request` JSON dosyası
    (`ege_lisans.context.activation_request` çıktısı) bekler; tek bir imzalı
    şema v2 `license.json` döner. Bkz. app/services/offline_activation.py."""
    subscription = _abonelik_getir(db, subscription_id, user)

    activation_files = [(f.filename or "activation_request.json", await f.read()) for f in files]

    try:
        return create_offline_license(
            db, subscription=subscription, activation_files=activation_files, imzalayici=imzalayici
        )
    except (SubscriptionNotActiveError, SeatLimitExceededError) as e:
        raise HTTPException(409, str(e)) from e
    except (InvalidActivationRequestError, ProductMismatchError) as e:
        raise HTTPException(422, str(e)) from e
