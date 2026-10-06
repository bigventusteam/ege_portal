"""
Kimlik doğrulama.

Yaklaşım sisEGE'nin `auth.py`'sindeki ile aynı (kopyalanmadı, ayrı yazıldı):
oturum token'ı hem `Authorization: Bearer` header'ından hem de HttpOnly bir
çerezden okunabilir — tarayıcı tabanlı bir arayüz çerezi otomatik gönderir,
script/API istemcileri bearer kullanır. sisEGE PyJWT kullanıyor; burada
zaten bağımlılık olan `itsdangerous` (imzalı + süresi kontrol edilebilir
token) yeterli, ayrı bir JWT kütüphanesi eklemedim.

E-posta doğrulama yok (F2/F6 kapsamı). Brute-force hız sınırlaması VAR
(2026-10-05 canlıya hazırlık görevi, bkz. app/services/auth_throttle.py) —
e-posta VE IP başına ayrı pencereler, kilitliyken de yanlış parolayla AYNI
genel hata (kilitli/yanlış ayrımı sızdırılmaz), bilinmeyen e-postada da
gerçek bir bcrypt karşılaştırması çalışır (zamanlama eşitlemesi, bkz.
app/security.py::verify_password_or_dummy).

`User.role` (owner/admin/member) müşteri KURUMU İÇİNDEKİ roldür — bir
müşteri kendi ekibini yönetebilsin diye. `User.is_staff` bundan TAMAMEN
BAĞIMSIZ, üretici (EGE) personeli mi sorusu. İlk taslakta `require_admin`,
deneme ayarları gibi platform-genel uçları `role == ADMIN`'e bağlamıştı —
EGE lider'in incelemesinde yakalandı: bir müşteri kendi ekibine (kendi
kurumu içinde) "admin" rolü verdiğinde bu kullanıcı yanlışlıkla TÜM
platformun deneme ayarlarına erişebiliyordu. Artık `require_staff`,
yalnız `is_staff`'a bakıyor; `role` hiç karışmıyor. `is_staff` self-servis
hiçbir uçtan set edilemez — bkz. `scripts/personel_olustur.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Customer, User
from app.net import client_ip
from app.security import PasswordPolicyError, hash_password, validate_password_policy, verify_password_or_dummy
from app.services import auth_throttle

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_COOKIE_NAME = "ege_portal_session"
_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7 gün
_UNAUTHORIZED = HTTPException(status_code=401, detail="oturum gerekli", headers={"WWW-Authenticate": "Bearer"})


def _serializer() -> URLSafeTimedSerializer:
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY tanımlı değil — token imzalanamaz")
    return URLSafeTimedSerializer(settings.secret_key, salt="ege-portal-auth")


def issue_session_token(user_id: int) -> str:
    return _serializer().dumps({"user_id": user_id})


def decode_session_token(token: str) -> dict:
    try:
        return _serializer().loads(token, max_age=_TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired) as e:
        raise _UNAUTHORIZED from e


class RegisterRequest(BaseModel):
    customer_name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _parola_politikasi(cls, v: str) -> str:
        try:
            validate_password_policy(v)
        except PasswordPolicyError as e:
            raise ValueError(str(e)) from e
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    user_id: int
    customer_id: int
    # Frontend'in "Personel" sayfalarını göstermek için SINYALİ — gerçek
    # yetki her zaman backend'de `require_staff` ile kontrol edilir, burada
    # taşınması TEK BAŞINA hiçbir uca erişim VERMEZ (bkz. app/routers/
    # admin.py, 2026-10-05 havale/EFT işaretleme görevi).
    is_staff: bool


def _giris_yanitla(response: Response, user: User) -> TokenResponse:
    token = issue_session_token(user.id)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=_TOKEN_MAX_AGE_SECONDS,
        httponly=True,
        # "strict" — frontend ARTIK aynı origin'den sunuluyor (bkz. deploy/),
        # çapraz-site bir bağlantı/form ASLA bu çerezi taşımaz (CSRF
        # savunmasının birinci katmanı; ikincisi app/middleware.py'deki
        # Origin doğrulaması — bkz. o dosyanın docstring'i).
        samesite="strict",
        secure=settings.cookie_secure,
    )
    return TokenResponse(access_token=token, user_id=user.id, customer_id=user.customer_id, is_staff=user.is_staff)


@router.post("/register", response_model=TokenResponse, status_code=201)
def kayit_ol(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    ip = client_ip(request)
    if auth_throttle.register_hiz_asildi_mi(db, ip_address=ip):
        raise HTTPException(429, "çok fazla kayıt denemesi — lütfen biraz sonra tekrar deneyin")

    if db.query(User).filter_by(email=body.email).first() is not None:
        auth_throttle.register_denemesi_kaydet(db, email=body.email, ip_address=ip, success=False)
        raise HTTPException(409, "bu e-posta zaten kayıtlı")

    customer = Customer(name=body.customer_name, email=body.email)
    db.add(customer)
    db.flush()

    user = User(customer_id=customer.id, email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    auth_throttle.register_denemesi_kaydet(db, email=body.email, ip_address=ip, success=True)
    return _giris_yanitla(response, user)


@router.post("/login", response_model=TokenResponse)
def giris_yap(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    ip = client_ip(request)
    # Kilitliyken de AYNI genel hata döner — "kilitli" ile "yanlış parola"
    # ayrımı sızdırılmaz (bkz. modül docstring'i). Reddedilen deneme de
    # kaydedilir: saldırgan denemeye devam ettikçe pencere "dolu" kalır.
    if auth_throttle.login_kilitli_mi(db, email=body.email, ip_address=ip):
        auth_throttle.login_denemesi_kaydet(db, email=body.email, ip_address=ip, success=False)
        raise HTTPException(401, "e-posta veya parola yanlış")

    user = db.query(User).filter_by(email=body.email).first()
    # `verify_password_or_dummy` kullanıcı YOKSA bile (password_hash=None)
    # bir bcrypt karşılaştırması ÇALIŞTIRIR (sahte hash'e karşı) — bilinmeyen
    # bir e-postada yanıt süresi, var olan bir e-postadaki yanlış parola
    # denemesiyle AYNI büyüklükte kalır (bkz. app/security.py).
    sifre_dogru = verify_password_or_dummy(body.password, user.password_hash if user else None)
    basarili = user is not None and user.is_active and sifre_dogru

    auth_throttle.login_denemesi_kaydet(db, email=body.email, ip_address=ip, success=basarili)
    if not basarili:
        raise HTTPException(401, "e-posta veya parola yanlış")

    return _giris_yanitla(response, user)


@router.post("/logout", status_code=204)
def cikis_yap(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


def get_current_user(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    """Önce `Authorization: Bearer`, yoksa oturum çerezi. İkisi de yoksa 401.

    `POST /api/v1/orders` gibi uçlar `customer_id`'yi artık BURADAN alır —
    eskiden query parametresiydi, bu da herkesin başkasının customer_id'siyle
    sipariş açabilmesine (IDOR) izin veriyordu."""
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("bearer "):].strip()
    elif session_cookie:
        token = session_cookie

    if not token:
        raise _UNAUTHORIZED

    data = decode_session_token(token)
    user = db.get(User, data.get("user_id"))
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    """Deneme süresi ayarları gibi ÜRETİCİ-yalnız (platform genelinde,
    müşteri kurumundan bağımsız) uçlar için (bkz. app/routers/admin.py) —
    PLAN.md §8 madde 7: "Süreyi yalnız ÜRETİCİ değiştirir... Müşteri
    değiştiremez." `User.role` (müşteri kurumu içi) İLE KARIŞTIRILMASIN —
    bkz. modül docstring'i ve app/models.py::User.is_staff."""
    if not user.is_staff:
        raise HTTPException(403, "bu işlem için üretici (personel) yetkisi gerekli")
    return user


class MeResponse(BaseModel):
    user_id: int
    customer_id: int
    customer_name: str
    email: str
    is_staff: bool


@router.get("/me", response_model=MeResponse)
def ben(user: User = Depends(get_current_user)) -> MeResponse:
    """Oturum çerezinin (ya da bearer token'ın) kime ait olduğu. Arayüz sayfa
    yenilendiğinde "oturum açık mı" bilgisini localStorage'dan değil buradan
    kurar; geçersiz/süresi dolmuş oturumda 401."""
    return MeResponse(
        user_id=user.id,
        customer_id=user.customer_id,
        customer_name=user.customer.name,
        email=user.email,
        is_staff=user.is_staff,
    )
