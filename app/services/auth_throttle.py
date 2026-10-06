"""
Giriş/kayıt brute-force hız sınırlaması (PLAN.md §6, 2026-10-05 canlıya
hazırlık görevi). Depolama: DB tablosu (`LoginAttempt`) — Redis'e BİLEREK
gerek yok, bkz. o modelin docstring'i (tek VE çok süreçli dağıtımda aynı
şekilde doğru çalışır).

Kayan pencere ("sliding window"): son `WINDOW_MINUTES` içindeki başarısız
deneme sayısı eşiği AŞARSA reddedilir. Ayrı bir "locked_until" alanına
gerek YOK — saldırgan denemeye devam ettikçe pencere kendiliğinden "dolu"
kalır (kilidi fiilen UZATIR), dururlarsa `WINDOW_MINUTES` sonra kendiliğinden
açılır. E-posta VE IP ayrı ayrı sayılır — biri aşılınca diğeri etkilenmeden
TEK BAŞINA yeter (bkz. LoginAttempt docstring'i).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LoginAttempt

LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_FAILURES = 5

REGISTER_WINDOW_MINUTES = 15
REGISTER_MAX_ATTEMPTS = 5


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _pencere_sayisi(db: Session, *, kind: str, alan, deger: str, pencere_dakika: int, yalniz_basarisiz: bool) -> int:
    esik = datetime.now(timezone.utc) - timedelta(minutes=pencere_dakika)
    kosullar = [LoginAttempt.kind == kind, alan == deger, LoginAttempt.created_at > esik]
    if yalniz_basarisiz:
        kosullar.append(LoginAttempt.success.is_(False))
    return db.scalar(select(func.count()).select_from(LoginAttempt).where(*kosullar)) or 0


def login_kilitli_mi(db: Session, *, email: str, ip_address: str) -> bool:
    email = _normalize_email(email)
    e_sayisi = _pencere_sayisi(
        db, kind="login", alan=LoginAttempt.email, deger=email,
        pencere_dakika=LOGIN_WINDOW_MINUTES, yalniz_basarisiz=True,
    )
    if e_sayisi >= LOGIN_MAX_FAILURES:
        return True
    ip_sayisi = _pencere_sayisi(
        db, kind="login", alan=LoginAttempt.ip_address, deger=ip_address,
        pencere_dakika=LOGIN_WINDOW_MINUTES, yalniz_basarisiz=True,
    )
    return ip_sayisi >= LOGIN_MAX_FAILURES


def login_denemesi_kaydet(db: Session, *, email: str, ip_address: str, success: bool) -> None:
    db.add(LoginAttempt(email=_normalize_email(email), ip_address=ip_address, kind="login", success=success))
    db.commit()


def register_hiz_asildi_mi(db: Session, *, ip_address: str) -> bool:
    """Kayıtta başarılı/başarısız FARK ETMEZ — her DENEME sayılır (bir
    botun art arda farklı e-postalarla hesap açması da, aynı e-postayı
    tekrar tekrar denemesi de aynı IP sınırına takılır)."""
    return (
        _pencere_sayisi(
            db, kind="register", alan=LoginAttempt.ip_address, deger=ip_address,
            pencere_dakika=REGISTER_WINDOW_MINUTES, yalniz_basarisiz=False,
        )
        >= REGISTER_MAX_ATTEMPTS
    )


def register_denemesi_kaydet(db: Session, *, email: str, ip_address: str, success: bool) -> None:
    db.add(LoginAttempt(email=_normalize_email(email), ip_address=ip_address, kind="register", success=success))
    db.commit()
