#!/usr/bin/env python
"""
EGE ÜRETİM lisans imza anahtarlarını üretir — PORTAL SUNUCUSUNDA, bir kez
çalıştırılır (karar 2026-10-10; runbook: deploy/OKUBENI.md "Üretim anahtarı").

Ne yapar:
- İki Ed25519 çifti üretir: BİRİNCİL (portal bununla imzalar) ve YEDEK
  (kasada bekler; birincil kaybolur/sızarsa devreye girer).
- Her özel anahtarı AYRI bir parolayla şifreli PKCS8 PEM'e yazar
  (BestAvailableEncryption). Dosyalar `O_EXCL` ile açılır — var olan bir
  dosyanın ÜZERİNE ASLA YAZILMAZ. İzin: POSIX'te 0600 (sahibi çalıştıran
  kullanıcı); Windows'ta ACL yalnız çalıştıran kullanıcıya tam yetki
  (kalıtım kapatılır, `icacls`).
- Parolalar ETKİLEŞİMLİ sorulur (getpass, iki kez) — argümandan/env'den
  ALINMAZ. Asgari 16 karakter; birincil ve yedek parolaları farklı olmalı.
- Yazılan her dosyayı parolasıyla geri yükleyip bir imza/doğrulama turu
  yapar (bozuk yedek kalmasın).
- Açık anahtarları (gizli DEĞİL) hex, kısa parmak izi ve ürünlerin
  `PUBLIC_KEYS` satırına yapıştırılacak biçimde yazdırır. Özel anahtar ve
  parola ASLA yazdırılmaz.

Yalnız `cryptography` gerektirir (portal imajında var; host'ta
`pip install cryptography` yeterli).

Kullanım:
    python scripts/uretim_anahtari_olustur.py --cikti-dizini /root/ege_anahtar_uretim
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ASGARI_PAROLA_UZUNLUGU = 16
ANAHTARLAR = ("birincil", "yedek")


class AracHatasi(Exception):
    pass


def parmak_izi(acik_anahtar_hex: str) -> str:
    """app/licensing.py::acik_anahtar_parmak_izi ile AYNI hesap."""
    return "sha256:" + hashlib.sha256(bytes.fromhex(acik_anahtar_hex)).hexdigest()[:16]


def dosya_adi(onek: str, kimlik: str) -> str:
    return f"{onek}_{kimlik}.pem"


def parola_sor(kimlik: str, girdi=getpass.getpass) -> bytes:
    for _deneme in range(3):
        p1 = girdi(f"{kimlik.upper()} anahtar parolası (en az {ASGARI_PAROLA_UZUNLUGU} karakter): ")
        if len(p1) < ASGARI_PAROLA_UZUNLUGU:
            print(f"  Parola çok kısa (en az {ASGARI_PAROLA_UZUNLUGU} karakter). Tekrar deneyin.", file=sys.stderr)
            continue
        p2 = girdi(f"{kimlik.upper()} anahtar parolası (tekrar): ")
        if p1 != p2:
            print("  Parolalar eşleşmiyor. Tekrar deneyin.", file=sys.stderr)
            continue
        return p1.encode("utf-8")
    raise AracHatasi(f"{kimlik} parolası 3 denemede alınamadı — hiçbir dosya yazılmadı.")


def _windows_acl_kisitla(yol: Path) -> None:
    kullanici = os.environ.get("USERNAME") or getpass.getuser()
    alan = os.environ.get("USERDOMAIN")
    hesap = f"{alan}\\{kullanici}" if alan else kullanici
    sonuc = subprocess.run(
        ["icacls", str(yol), "/inheritance:r", "/grant:r", f"{hesap}:(F)"],
        capture_output=True, text=True,
    )
    if sonuc.returncode != 0:
        raise AracHatasi(f"icacls ile erişim kısıtlanamadı: {yol} ({sonuc.stderr.strip() or sonuc.stdout.strip()})")


def gizli_dosya_yaz(yol: Path, icerik: bytes) -> None:
    """Dosyayı YALNIZ yoksa oluşturur (O_EXCL), içerik yazılmadan ÖNCE
    erişimi kısıtlar."""
    bayrak = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(yol, bayrak, 0o600)
    except FileExistsError:
        raise AracHatasi(f"Dosya zaten var, üzerine YAZILMAZ: {yol}") from None
    try:
        if os.name == "nt":
            os.close(fd)
            fd = -1
            _windows_acl_kisitla(yol)
            with open(yol, "r+b") as f:
                f.write(icerik)
                f.flush()
                os.fsync(f.fileno())
        else:
            os.fchmod(fd, 0o600)
            os.write(fd, icerik)
            os.fsync(fd)
    except BaseException:
        if fd >= 0:
            os.close(fd)
            fd = -1
        try:
            yol.unlink()
        except OSError:
            pass
        raise
    finally:
        if fd >= 0:
            os.close(fd)


def anahtar_uret_ve_yaz(yol: Path, parola: bytes) -> str:
    anahtar = Ed25519PrivateKey.generate()
    pem = anahtar.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(parola),
    )
    gizli_dosya_yaz(yol, pem)
    acik = anahtar.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    # Geri yükleme + imza turu: dosya gerçekten bu parolayla açılıyor mu?
    geri = serialization.load_pem_private_key(yol.read_bytes(), password=parola)
    ornek = b"ege-lisans-uretim-anahtari-oz-sinama"
    anahtar.public_key().verify(geri.sign(ornek), ornek)
    return acik.hex()


def main(argv: list[str] | None = None, *, girdi=getpass.getpass) -> int:
    ayr = argparse.ArgumentParser(description="EGE üretim lisans imza anahtarlarını (birincil + yedek) üretir.")
    ayr.add_argument("--cikti-dizini", required=True, type=Path,
                     help="Şifreli PEM'lerin yazılacağı dizin (yoksa 0700 ile oluşturulur).")
    ayr.add_argument("--onek", default="ege_lisans_uretim", help="Dosya adı öneki (varsayılan: ege_lisans_uretim).")
    arg = ayr.parse_args(argv)

    dizin: Path = arg.cikti_dizini
    yollar = {k: dizin / dosya_adi(arg.onek, k) for k in ANAHTARLAR}
    try:
        var_olan = [str(y) for y in yollar.values() if y.exists()]
        if var_olan:
            raise AracHatasi("Dosya zaten var, üzerine YAZILMAZ: " + ", ".join(var_olan))

        parolalar: dict[str, bytes] = {}
        for k in ANAHTARLAR:
            parolalar[k] = parola_sor(k, girdi)
        if parolalar["birincil"] == parolalar["yedek"]:
            raise AracHatasi("Birincil ve yedek parolası AYNI olamaz — hiçbir dosya yazılmadı.")

        if not dizin.exists():
            dizin.mkdir(parents=True, mode=0o700)

        acik: dict[str, str] = {}
        for k in ANAHTARLAR:
            acik[k] = anahtar_uret_ve_yaz(yollar[k], parolalar[k])
        parolalar.clear()
    except AracHatasi as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2

    print()
    print("Üretim anahtarları oluşturuldu (özel anahtarlar parolayla şifreli):")
    for k in ANAHTARLAR:
        print(f"  {k:9} {yollar[k]}")
    print()
    print("AÇIK ANAHTARLAR (gizli değil):")
    for k in ANAHTARLAR:
        print(f"  {k:9} hex         = {acik[k]}")
        print(f"  {k:9} parmak izi  = {parmak_izi(acik[k])}")
    print()
    print("Ürünlerin PUBLIC_KEYS satırı (mapEGE, sisEGE, colEGE — HEPSİNDE AYNI ANDA):")
    print("PUBLIC_KEYS: tuple[str, ...] = (")
    print(f'    "{acik["birincil"]}",  # birincil (üretim, {parmak_izi(acik["birincil"])})')
    print(f'    "{acik["yedek"]}",  # yedek    (üretim, {parmak_izi(acik["yedek"])})')
    print(")")
    print()
    print("Portal (deploy/.env):")
    print("  EGE_LISANS_ANAHTAR_KIMLIGI=birincil")
    print(f"  EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI={parmak_izi(acik['birincil'])}")
    print()
    print("ÇEVRİMDIŞI YEDEK — ŞİMDİ yapın (ayrıntı: deploy/OKUBENI.md \"Üretim anahtarı\"):")
    print("  1. İKİ şifreli PEM'i İKİ ayrı çevrimdışı ortama (USB + kasa) kopyalayın;")
    print("     her kopyayı parolasıyla açılabildiğini doğrulayın.")
    print("  2. Parolaları anahtarlardan AYRI yerde saklayın (parola yöneticisi / ayrı zarf);")
    print("     birincil ve yedek parolası da birbirinden ayrı dursun.")
    print("  3. YEDEK özel anahtarı sunucudan SİLİN (shred -u) — yalnız kasada kalmalı.")
    print("  4. Birincil PEM'i ve parola dosyasını portalın sır dizinine 1000:1000, 0400 ile kurun.")
    print("  5. Yukarıdaki açık anahtar satırını ve parmak izlerini kayda geçirin.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
