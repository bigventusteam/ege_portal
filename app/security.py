"""
Parola hash'leme, lisans anahtarı üretimi/hash'i.

Parolalar bcrypt ile saklanır (sisEGE'nin auth.py'sindeki aynı yaklaşım —
bkz. app/routers/auth.py docstring'i).
"""
from __future__ import annotations

import hashlib
import secrets

import bcrypt

# bcrypt YALNIZ ilk 72 BAYTI (UTF-8) kullanır — bu kütüphane (bcrypt 4.x)
# bunu SESSİZCE yapar, hata vermez (elle doğrulandı: 100 baytlık bir parola
# ile üretilen hash, ilk 72 bayt aynıyken SONRASI farklı olan başka bir
# parolayla da `checkpw` TRUE döner). Kullanıcı 72 bayttan uzun bir parola
# girip "güvenli, uzun bir parola seçtim" sanabilir — oysa 73. bayttan
# sonrası doğrulamada hiç ÖNEMLİ DEĞİLDİR. Sessizce kesmek yerine AÇIKÇA
# reddediyoruz (bkz. validate_password_policy).
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 72


class PasswordPolicyError(ValueError):
    pass


def validate_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"parola en az {MIN_PASSWORD_LENGTH} karakter olmalı")
    boyut = len(password.encode("utf-8"))
    if boyut > MAX_PASSWORD_BYTES:
        raise PasswordPolicyError(
            f"parola en çok {MAX_PASSWORD_BYTES} bayt olabilir (bcrypt sınırı — şu an {boyut} bayt)"
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


# Var olup olmadığı BİLİNMEYEN bir e-posta için de giriş denemesi AYNI
# sürede sonuçlanmalı (zamanlama ile kullanıcı numarası çıkarılmasın,
# "user enumeration") — bcrypt kasıtlı YAVAŞ olduğu için e-posta hiç yoksa
# `verify_password`'u hiç ÇAĞIRMAMAK, var olan bir e-postaya göre BELİRGİN
# derecede hızlı yanıt üretirdi. Sabit bir ÖNCEDEN HESAPLANMIŞ (import
# anında, her süreçte bir kez) sahte hash'e karşı HER ZAMAN bir `checkpw`
# çalıştırılır (bkz. app/routers/auth.py::giris_yap).
_SAHTE_PAROLA_HASH = hash_password("bu-hic-kullanilmayacak-sahte-bir-parola")


def verify_password_or_dummy(password: str, password_hash: str | None) -> bool:
    """`password_hash` `None` ise (e-posta bulunamadı) sahte hash'e karşı
    doğrular — sonuç HER ZAMAN `False`, ama çalışma SÜRESİ gerçek bir
    e-posta/yanlış parola denemesiyle aynı büyüklükte kalır."""
    hedef = password_hash if password_hash is not None else _SAHTE_PAROLA_HASH
    sonuc = verify_password(password, hedef)
    return sonuc if password_hash is not None else False


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def generate_license_key() -> str:
    """İnsan-okur, kolayca kopyalanabilir bir anahtar: EGE-XXXX-XXXX-XXXX-XXXX."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # karışabilecek 0/O, 1/I yok
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return "EGE-" + "-".join(groups)


def hash_license_key(raw_key: str) -> str:
    """Lisans anahtarı bizim ürettiğimiz yüksek entropili bir sırdır (kullanıcı
    parolası değil) — burada yavaş bir KDF'e gerek yok, düz SHA-256 yeterli."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
