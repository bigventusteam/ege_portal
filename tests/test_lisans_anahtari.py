"""
Şifreli üretim imza anahtarı (karar 2026-10-10): PKCS8 PEM + parola DOSYASI,
production'da şifresiz anahtar reddi, env'de düz parola reddi, açılışta tek
yükleme. Tüm anahtarlar testte geçici üretilir (gerçek anahtar YOK).
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing import (
    EgeLisansImzalayici,
    LisansAnahtariHatasi,
    acik_anahtar_parmak_izi,
)

PAROLA = "test-parolasi-gecici-0123456789"


def _anahtar_yaz(dizin, *, parola: str | None, ad: str = "anahtar.pem"):
    anahtar = Ed25519PrivateKey.generate()
    sifre = (
        serialization.BestAvailableEncryption(parola.encode())
        if parola is not None
        else serialization.NoEncryption()
    )
    yol = dizin / ad
    yol.write_bytes(anahtar.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, sifre))
    acik = anahtar.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    return yol, acik


def _parola_dosyasi(dizin, icerik: str, ad: str = "parola"):
    yol = dizin / ad
    yol.write_text(icerik, encoding="utf-8", newline="")
    return yol


@pytest.fixture(autouse=True)
def _duz_parola_env_yok(monkeypatch):
    for ad in ("EGE_LISANS_ANAHTAR_PAROLA", "EGE_LISANS_ANAHTAR_PAROLASI",
               "EGE_LISANS_OZEL_ANAHTAR_PAROLA", "EGE_LISANS_PAROLA"):
        monkeypatch.delenv(ad, raising=False)


def test_sifreli_pem_ve_parola_dosyasiyla_imzalar_ege_lisans_dogrular(tmp_path):
    from ege_lisans.keys import verify_signature

    anahtar, acik = _anahtar_yaz(tmp_path, parola=PAROLA)
    parola = _parola_dosyasi(tmp_path, PAROLA + "\n")  # sondaki satır sonu atılır
    imz = EgeLisansImzalayici(anahtar, parola, uretim=True)
    payload = {"schema": 2, "license_id": "lic_test", "expires": "2027-01-01"}

    imza = imz.imzala(payload)

    assert verify_signature(payload, imza, [acik]) == 0
    # yedek slotundaki anahtarla imzalanmış gibi: ürün "yedek-1" raporlar
    assert verify_signature(payload, imza, ["00" * 32, acik]) == 1
    assert imz.parmak_izi == acik_anahtar_parmak_izi(acik)


def test_ege_lisans_sign_payload_ile_ayni_imza(tmp_path):
    """Portal kendi yükleyicisiyle imzalıyor — ege_lisans.signing ile birebir aynı olmalı."""
    from ege_lisans.signing import sign_payload

    anahtar, _ = _anahtar_yaz(tmp_path, parola=None)
    payload = {"schema": 2, "b": [1, 2], "a": "ç"}
    assert EgeLisansImzalayici(anahtar, uretim=False).imzala(payload) == sign_payload(payload, anahtar)


def test_yanlis_parola_acik_hata_gizli_deger_yok(tmp_path):
    anahtar, _ = _anahtar_yaz(tmp_path, parola=PAROLA)
    yanlis = "yanlis-parola-ABCDEFGHIJKLMNOP"
    parola = _parola_dosyasi(tmp_path, yanlis)
    with pytest.raises(LisansAnahtariHatasi, match="parola yanlış") as exc:
        EgeLisansImzalayici(anahtar, parola, uretim=True).yukle()
    mesaj = str(exc.value)
    assert yanlis not in mesaj and PAROLA not in mesaj
    assert "PRIVATE KEY" not in mesaj
    assert exc.value.__cause__ is None  # cryptography istisnası zincirlenmez


def test_sifreli_anahtar_parola_dosyasi_yoksa_hata(tmp_path):
    anahtar, _ = _anahtar_yaz(tmp_path, parola=PAROLA)
    with pytest.raises(LisansAnahtariHatasi, match="PAROLA_DOSYASI tanımlı değil"):
        EgeLisansImzalayici(anahtar, uretim=False).yukle()


def test_parola_dosyasi_bulunamazsa_ya_da_bossa_hata(tmp_path):
    anahtar, _ = _anahtar_yaz(tmp_path, parola=PAROLA)
    with pytest.raises(LisansAnahtariHatasi, match="bulunamadı"):
        EgeLisansImzalayici(anahtar, tmp_path / "yok", uretim=True).yukle()
    bos = _parola_dosyasi(tmp_path, "\r\n", ad="bos")
    with pytest.raises(LisansAnahtariHatasi, match="boş"):
        EgeLisansImzalayici(anahtar, bos, uretim=True).yukle()


def test_uretimde_sifresiz_anahtar_reddedilir(tmp_path):
    anahtar, _ = _anahtar_yaz(tmp_path, parola=None)
    with pytest.raises(LisansAnahtariHatasi, match="ŞİFRELİ olmalı"):
        EgeLisansImzalayici(anahtar, uretim=True).yukle()


def test_parola_verildi_ama_anahtar_sifresiz_reddedilir(tmp_path):
    anahtar, _ = _anahtar_yaz(tmp_path, parola=None)
    parola = _parola_dosyasi(tmp_path, PAROLA)
    with pytest.raises(LisansAnahtariHatasi, match="ŞİFRESİZ"):
        EgeLisansImzalayici(anahtar, parola, uretim=False).yukle()


def test_gelistirmede_sifresiz_anahtar_izinli(tmp_path):
    anahtar, acik = _anahtar_yaz(tmp_path, parola=None)
    imz = EgeLisansImzalayici(anahtar, uretim=False)
    imz.yukle()
    assert imz.acik_anahtar_hex == acik


def test_uretim_bayragi_settings_environmentten_gelir(tmp_path, monkeypatch):
    from app.config import settings

    anahtar, _ = _anahtar_yaz(tmp_path, parola=None)
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(LisansAnahtariHatasi, match="production"):
        EgeLisansImzalayici(anahtar).yukle()


@pytest.mark.parametrize("ad", ["EGE_LISANS_ANAHTAR_PAROLA", "EGE_LISANS_ANAHTAR_PAROLASI"])
def test_envde_duz_parola_reddedilir_degeri_mesaja_girmez(tmp_path, monkeypatch, ad):
    anahtar, _ = _anahtar_yaz(tmp_path, parola=PAROLA)
    parola = _parola_dosyasi(tmp_path, PAROLA)
    monkeypatch.setenv(ad, PAROLA)
    with pytest.raises(LisansAnahtariHatasi, match="düz metin") as exc:
        EgeLisansImzalayici(anahtar, parola, uretim=True).yukle()
    assert PAROLA not in str(exc.value)
    assert ad in str(exc.value)


def test_anahtar_bir_kez_yuklenir(tmp_path, monkeypatch):
    """Açılışta yüklendikten sonra dosyalar silinse de imzalama sürer — her
    imzada dosya/parola yeniden OKUNMAZ."""
    anahtar, acik = _anahtar_yaz(tmp_path, parola=PAROLA)
    parola = _parola_dosyasi(tmp_path, PAROLA)
    imz = EgeLisansImzalayici(anahtar, parola, uretim=True)
    imz.yukle()
    anahtar.unlink()
    parola.unlink()

    from ege_lisans.keys import verify_signature

    payload = {"schema": 2, "x": 1}
    assert verify_signature(payload, imz.imzala(payload), [acik]) == 0


def test_beklenen_parmak_izi_eslesmezse_hata(tmp_path):
    anahtar, acik = _anahtar_yaz(tmp_path, parola=None)
    EgeLisansImzalayici(anahtar, uretim=False, beklenen_parmak_izi=acik_anahtar_parmak_izi(acik)).yukle()
    with pytest.raises(LisansAnahtariHatasi, match="eşleşmiyor"):
        EgeLisansImzalayici(anahtar, uretim=False, beklenen_parmak_izi="sha256:0000000000000000").yukle()


def test_gecersiz_anahtar_kimligi_hata(tmp_path):
    anahtar, _ = _anahtar_yaz(tmp_path, parola=None)
    with pytest.raises(LisansAnahtariHatasi, match="KIMLIGI"):
        EgeLisansImzalayici(anahtar, uretim=False, anahtar_kimligi="ucuncu").yukle()


def test_bozuk_pem_acik_hata(tmp_path):
    yol = tmp_path / "bozuk.pem"
    yol.write_bytes(b"bozuk")
    with pytest.raises(LisansAnahtariHatasi, match="PKCS8 PEM değil"):
        EgeLisansImzalayici(yol, uretim=False).yukle()


def test_parmak_izi_araci_ile_ayni():
    import importlib.util
    from pathlib import Path

    yol = Path(__file__).resolve().parents[1] / "scripts" / "uretim_anahtari_olustur.py"
    spec = importlib.util.spec_from_file_location("uretim_araci_pi", yol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hex_ = "ab" * 32
    assert mod.parmak_izi(hex_) == acik_anahtar_parmak_izi(hex_)
    assert acik_anahtar_parmak_izi(hex_).startswith("sha256:") and len(acik_anahtar_parmak_izi(hex_)) == 7 + 16
