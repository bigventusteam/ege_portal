#!/usr/bin/env python
"""
Üretici (EGE) personeli oluşturur ya da var olan bir kullanıcıyı personel
yapar (`User.is_staff = True`). Bilerek bir API ucu DEĞİL, bir CLI betiği —
personel hesapları self-servis hiçbir uçtan oluşturulamaz/yükseltilemez
(bkz. app/routers/auth.py docstring'i, "rol karışıklığı" düzeltmesi:
`is_staff`, müşteri kurumu içi `role`'den TAMAMEN BAĞIMSIZ bir platform
yetkisidir).

Parola argv'DEN ALINMAZ (kabuk geçmişinde, `ps`/görev yöneticisinde açıkça
görünür) — bir terminalde `getpass` ile sorulur; terminal yoksa (ör. CI/
betikten çağrılırsa) stdin'in İLK satırından okunur.

Kullanım:
    python scripts/personel_olustur.py --email admin@bigventus.com
        # e-posta hiçbir kullanıcıda yoksa: yeni bir personel hesabı açar
        # (parola sorulur), ortak bir "EGE Portal Personeli" müşterisi
        # altında (bkz. _personel_musterisini_bul_ya_da_olustur — Users
        # tablosunun customer_id'si NOT NULL olduğu için personelin de bir
        # Customer'a bağlı olması gerekiyor; bu yalnız iç muhasebe amaçlı,
        # gerçek bir müşteri değil).
        # e-posta zaten bir kullanıcıdaysa: yalnız is_staff=True yapar,
        # parola SORULMAZ/değiştirilmez.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows konsolunda Türkçe karakterler için (bkz. colEGE'deki aynı desen)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Customer, User  # noqa: E402
from app.security import PasswordPolicyError, hash_password, validate_password_policy  # noqa: E402

_PERSONEL_MUSTERI_ADI = "EGE Portal Personeli"
_PERSONEL_MUSTERI_EPOSTA = "personel@ege-portal.internal"


def _parola_oku() -> str:
    if sys.stdin.isatty():
        parola = getpass.getpass("Parola: ")
        tekrar = getpass.getpass("Parola (tekrar): ")
        if parola != tekrar:
            print("HATA: parolalar eşleşmiyor.", file=sys.stderr)
            sys.exit(1)
    else:
        parola = sys.stdin.readline().rstrip("\n")
    try:
        validate_password_policy(parola)
    except PasswordPolicyError as e:
        print(f"HATA: {e}", file=sys.stderr)
        sys.exit(1)
    return parola


def _personel_musterisini_bul_ya_da_olustur(db: Session) -> Customer:
    musteri = db.scalars(select(Customer).where(Customer.email == _PERSONEL_MUSTERI_EPOSTA)).first()
    if musteri is None:
        musteri = Customer(name=_PERSONEL_MUSTERI_ADI, email=_PERSONEL_MUSTERI_EPOSTA)
        db.add(musteri)
        db.flush()
    return musteri


def main() -> None:
    parser = argparse.ArgumentParser(description="Üretici personeli oluşturur/yükseltir (is_staff=True).")
    parser.add_argument("--email", required=True, help="Personel hesabının e-postası")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.scalars(select(User).where(User.email == args.email)).first()

        if user is not None:
            if user.is_staff:
                print(f"'{args.email}' zaten personel.")
                return
            user.is_staff = True
            db.commit()
            print(f"'{args.email}' personel yapıldı (mevcut hesap yükseltildi, parola değiştirilmedi).")
            return

        parola = _parola_oku()
        musteri = _personel_musterisini_bul_ya_da_olustur(db)
        user = User(customer_id=musteri.id, email=args.email, password_hash=hash_password(parola), is_staff=True)
        db.add(user)
        db.commit()
        print(f"'{args.email}' yeni personel hesabı olarak oluşturuldu.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
