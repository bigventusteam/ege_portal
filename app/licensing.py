"""
Lisans imzalama arayüzü.

`ege_lisans` (ortak imzalama/doğrulama kütüphanesi, bkz.
ege_platform/ege_lisans, ege_platform/PLAN.md §3) bu depoda vendorlu.
`LisansImzalayici` protokolü korunuyor — testler gerçek Ed25519 imzalama
yerine sahte bir imzalayıcı (`tests/fakes.py::FakeImzalayici`) kullanır,
üretim/geliştirme `EgeLisansImzalayici`'yi kullanır.

Üretim anahtarı (karar 2026-10-10, runbook: deploy/OKUBENI.md "Üretim
anahtarı"): özel anahtar portal sunucusunda PAROLAYLA ŞİFRELİ PKCS8 PEM
dosyasında durur; parola AYRI bir gizli dosyadan (Docker secret) okunur.
- `EGE_LISANS_OZEL_ANAHTAR`            — özel anahtar PEM dosyasının yolu
- `EGE_LISANS_ANAHTAR_PAROLA_DOSYASI`  — parolayı içeren dosyanın yolu
- `EGE_LISANS_ANAHTAR_KIMLIGI`         — birincil | yedek (etiket; loglanır)
- `EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI` — (ops.) beklenen açık anahtar parmak
  izi; tanımlıysa yüklenen anahtar bununla eşleşmek ZORUNDA
Parola ortam değişkeninde DÜZ METİN olarak KABUL EDİLMEZ (süreç
listesinden / `docker inspect`ten görünür) — `_DUZ_PAROLA_ENV_ADLARI`'ndan
biri tanımlıysa yükleme reddedilir. `ENVIRONMENT=production`'da şifresiz
anahtar reddedilir; geliştirmede şifresiz anahtar izinli.

Anahtar bir kez yüklenir ve nesnede tutulur (production'da açılışta,
app/startup_checks.py); parola yalnız yükleme süresince bir `bytearray`de
durur ve hemen sıfırlanır. Hata mesajları ASLA parola/anahtar içeriği
taşımaz — yalnız dosya yolu ve nedeni.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.config import settings

# Parolayı DÜZ METİN taşıyabilecek, bilerek REDDEDİLEN ortam değişkeni adları.
_DUZ_PAROLA_ENV_ADLARI = (
    "EGE_LISANS_ANAHTAR_PAROLA",
    "EGE_LISANS_ANAHTAR_PAROLASI",
    "EGE_LISANS_OZEL_ANAHTAR_PAROLA",
    "EGE_LISANS_PAROLA",
)

ANAHTAR_KIMLIKLERI = ("birincil", "yedek")


class LisansAnahtariHatasi(RuntimeError):
    """İmza anahtarı yüklenemedi. Mesaj gizli değer İÇERMEZ."""


@runtime_checkable
class LisansImzalayici(Protocol):
    """Bir lisans payload'ını (bkz. PLAN.md §3) imzalayıp imza dizesini döner."""

    def imzala(self, payload: dict[str, Any]) -> str: ...


def acik_anahtar_parmak_izi(acik_anahtar_hex: str) -> str:
    """Açık anahtarın kısa parmak izi: ``sha256:`` + ham 32 baytın SHA-256
    özetinin ilk 16 hex karakteri. Gizli DEĞİL — ürün derlemesinde gömülen
    anahtarın portalınkiyle aynı olduğunu doğrulamak için.
    (scripts/uretim_anahtari_olustur.py'deki AYNI hesap — test eşitliği kontrol eder.)"""
    return "sha256:" + hashlib.sha256(bytes.fromhex(acik_anahtar_hex)).hexdigest()[:16]


def duz_parola_env_adlari() -> list[str]:
    """Şu an tanımlı (boş olmayan) düz-parola env adları — DEĞERLERİ döndürülmez."""
    return [ad for ad in _DUZ_PAROLA_ENV_ADLARI if os.environ.get(ad)]


def _parolayi_oku(parola_dosyasi: Path) -> bytearray:
    if not parola_dosyasi.is_file():
        raise LisansAnahtariHatasi(
            f"EGE_LISANS_ANAHTAR_PAROLA_DOSYASI bulunamadı: {str(parola_dosyasi)!r}"
        )
    try:
        ham = bytearray(parola_dosyasi.read_bytes())
    except OSError as exc:
        raise LisansAnahtariHatasi(
            f"EGE_LISANS_ANAHTAR_PAROLA_DOSYASI okunamadı ({type(exc).__name__}): {str(parola_dosyasi)!r}"
        ) from None
    # `echo parola > dosya` gibi yazımlardaki SONDAKİ satır sonu atılır.
    while ham and ham[-1] in (0x0A, 0x0D):
        ham.pop()
    if not ham:
        raise LisansAnahtariHatasi(
            f"EGE_LISANS_ANAHTAR_PAROLA_DOSYASI boş: {str(parola_dosyasi)!r}"
        )
    return ham


def _sifirla(tampon: bytearray | None) -> None:
    if tampon is not None:
        for i in range(len(tampon)):
            tampon[i] = 0


def ozel_anahtari_yukle(
    anahtar_yolu: str | Path | None,
    parola_dosyasi: str | Path | None,
    *,
    uretim: bool,
):
    """Ed25519 özel anahtarını yükler; kurallar modül docstring'inde."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    duz = duz_parola_env_adlari()
    if duz:
        raise LisansAnahtariHatasi(
            f"Parola ortam değişkeninde düz metin olarak verilemez ({', '.join(duz)} tanımlı) — "
            "süreç listesinden/docker inspect'ten görünür. Değişkeni kaldırın, parolayı "
            "EGE_LISANS_ANAHTAR_PAROLA_DOSYASI ile bir gizli dosyadan verin."
        )
    if not anahtar_yolu:
        raise LisansAnahtariHatasi(
            "EGE_LISANS_OZEL_ANAHTAR tanımlı değil — lisans imzalanamaz "
            "(sessizce imzasız lisans üretilmez, bkz. app/licensing.py)."
        )
    yol = Path(anahtar_yolu)
    if not yol.is_file():
        raise LisansAnahtariHatasi(f"EGE_LISANS_OZEL_ANAHTAR dosyası bulunamadı: {str(yol)!r}")

    try:
        pem = yol.read_bytes()
    except OSError as exc:
        raise LisansAnahtariHatasi(
            f"EGE_LISANS_OZEL_ANAHTAR okunamadı ({type(exc).__name__}): {str(yol)!r}"
        ) from None

    parola: bytearray | None = None
    try:
        if parola_dosyasi:
            parola = _parolayi_oku(Path(parola_dosyasi))
        try:
            anahtar = serialization.load_pem_private_key(pem, password=parola)
        except TypeError:
            # cryptography: parola verildi ama anahtar şifresiz / tersi.
            if parola is None:
                raise LisansAnahtariHatasi(
                    f"Özel anahtar şifreli ama EGE_LISANS_ANAHTAR_PAROLA_DOSYASI tanımlı değil: {str(yol)!r}"
                ) from None
            raise LisansAnahtariHatasi(
                f"Parola dosyası verildi ama özel anahtar ŞİFRESİZ: {str(yol)!r} — üretimde "
                "anahtar parolayla şifreli olmalı (scripts/uretim_anahtari_olustur.py)."
            ) from None
        except ValueError:
            if parola is not None:
                raise LisansAnahtariHatasi(
                    f"Özel anahtar çözülemedi — parola yanlış ya da dosya bozuk: {str(yol)!r}"
                ) from None
            raise LisansAnahtariHatasi(
                f"Özel anahtar okunamadı — geçerli bir PKCS8 PEM değil: {str(yol)!r}"
            ) from None
    finally:
        _sifirla(parola)
        del parola

    if not isinstance(anahtar, Ed25519PrivateKey):
        raise LisansAnahtariHatasi(f"Özel anahtar Ed25519 değil: {str(yol)!r}")

    if uretim and b"ENCRYPTED PRIVATE KEY" not in pem:
        # Buraya yalnız parola dosyası hiç verilmemişse düşülür (verilmişse
        # şifresiz anahtar yukarıda TypeError ile zaten reddedildi).
        raise LisansAnahtariHatasi(
            f"ENVIRONMENT=production iken özel anahtar parolayla ŞİFRELİ olmalı: {str(yol)!r} "
            "(scripts/uretim_anahtari_olustur.py + EGE_LISANS_ANAHTAR_PAROLA_DOSYASI)."
        )
    return anahtar


class EgeLisansImzalayici:
    """Gerçek Ed25519 imzalama (`ege_lisans.canonical` + `cryptography`).

    Anahtar ilk kullanımda (ya da `yukle()` ile açılışta) BİR KEZ yüklenir ve
    nesnede tutulur; anahtar/parola İÇERİĞİ loglanmaz, hata mesajlarına girmez.
    Yol tanımlı değilse / dosya yoksa / parola yanlışsa AÇIK bir hatayla durur
    — sessizce imzasız lisans üretmek yerine."""

    def __init__(
        self,
        private_key_path: str | Path | None = None,
        parola_dosyasi: str | Path | None = None,
        *,
        uretim: bool | None = None,
        anahtar_kimligi: str | None = None,
        beklenen_parmak_izi: str | None = None,
    ):
        self._private_key_path = private_key_path
        self._parola_dosyasi = parola_dosyasi
        self._uretim = uretim
        self._anahtar_kimligi = anahtar_kimligi
        self._beklenen_parmak_izi = beklenen_parmak_izi
        self._anahtar = None
        self._kilit = threading.Lock()
        self.acik_anahtar_hex: str | None = None
        self.parmak_izi: str | None = None

    @property
    def anahtar_kimligi(self) -> str:
        return self._anahtar_kimligi or settings.ege_lisans_anahtar_kimligi or "birincil"

    def yukle(self) -> None:
        with self._kilit:
            if self._anahtar is not None:
                return
            kimlik = self.anahtar_kimligi
            if kimlik not in ANAHTAR_KIMLIKLERI:
                raise LisansAnahtariHatasi(
                    f"EGE_LISANS_ANAHTAR_KIMLIGI geçersiz: {kimlik!r} (birincil | yedek olmalı)"
                )
            uretim = self._uretim if self._uretim is not None else settings.environment == "production"
            anahtar = ozel_anahtari_yukle(
                self._private_key_path or settings.ege_lisans_private_key_path,
                self._parola_dosyasi or settings.ege_lisans_anahtar_parola_dosyasi,
                uretim=uretim,
            )
            from cryptography.hazmat.primitives import serialization

            acik = anahtar.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            ).hex()
            parmak_izi = acik_anahtar_parmak_izi(acik)
            beklenen = (self._beklenen_parmak_izi or settings.ege_lisans_acik_anahtar_parmak_izi or "").strip()
            if beklenen and beklenen.lower() != parmak_izi:
                raise LisansAnahtariHatasi(
                    f"Yüklenen anahtarın parmak izi ({parmak_izi}) EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI "
                    f"({beklenen}) ile eşleşmiyor — yanlış anahtar dosyası bağlanmış olabilir."
                )
            self._anahtar = anahtar
            self.acik_anahtar_hex = acik
            self.parmak_izi = parmak_izi

    def imzala(self, payload: dict[str, Any]) -> str:
        if self._anahtar is None:
            self.yukle()
        from ege_lisans.canonical import canonical_bytes

        # ege_lisans.signing.sign_payload ile AYNI: kanonik baytlar, hex imza.
        return self._anahtar.sign(canonical_bytes(payload)).hex()
