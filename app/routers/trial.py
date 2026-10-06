from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_imzalayici
from app.licensing import LisansImzalayici
from app.models import User
from app.routers.auth import get_current_user
from app.services.activation_request import InvalidActivationRequestError
from app.services.trial import (
    DuplicateTrialError,
    InstanceIdAlreadyTrialedError,
    NoActivationFilesError,
    TrialActivationError,
    UnknownProductError,
    create_trial_license,
    find_usable_grants,
    resolve_trial_days,
)

router = APIRouter(prefix="/api/v1", tags=["trial"])


@router.post("/trial-activation")
async def deneme_lisansi_uret(
    files: list[UploadFile],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    imzalayici: LisansImzalayici = Depends(get_imzalayici),
) -> dict:
    """Oturumdaki kullanıcının kurumu için, yüklenen `activation_request`
    dosyalarındaki HER ürün için (abonelik gerektirmeden) imzalı bir deneme
    `license.json` üretir. Doğrulama abonelik çevrimdışı aktivasyonuyla
    AYNIDIR (bkz. app/services/activation_request.py). Bkz.
    app/services/trial.py modül docstring'i (süre önceliği, tekrar deneme
    yasağı, `license_type` geçiş planı)."""
    activation_files = [(f.filename or "activation_request.json", await f.read()) for f in files]

    try:
        return create_trial_license(db, customer=user.customer, activation_files=activation_files, imzalayici=imzalayici)
    except NoActivationFilesError as e:
        raise HTTPException(422, str(e)) from e
    except UnknownProductError as e:
        raise HTTPException(422, str(e)) from e
    except InvalidActivationRequestError as e:
        raise HTTPException(422, str(e)) from e
    except (DuplicateTrialError, InstanceIdAlreadyTrialedError) as e:
        raise HTTPException(409, str(e)) from e
    except TrialActivationError as e:  # beklenmeyen ama sınıf-ailesinden bir hata — yine 422
        raise HTTPException(422, str(e)) from e


@router.get("/trial-settings")
def gecerli_deneme_suresi(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Bu müşteri şimdi deneme başlatsa alacağı gün sayısı: müşteri override >
    aktif kampanya > genel varsayılan, artı tüketilmemiş ek süreler
    (`create_trial_license` ile AYNI hesap). Yalnız sonuç döner — hangi
    kaynaktan geldiği, kampanya adı/kimliği ve genel ayar sızdırılmaz."""
    gun, _kaynak = resolve_trial_days(db, user.customer)
    gun += sum(g.extra_days for g in find_usable_grants(db, user.customer_id))
    return {"days": gun}
