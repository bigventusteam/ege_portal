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
