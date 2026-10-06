import pytest

from app.licensing import EgeLisansImzalayici, LisansImzalayici
from tests.fakes import FakeImzalayici


def test_fake_imzalayici_protokole_uyar():
    fake = FakeImzalayici()
    assert isinstance(fake, LisansImzalayici)


def test_fake_imzalayici_ayni_payload_icin_ayni_imzayi_dondurur():
    fake = FakeImzalayici()
    payload = {"schema": 2, "license_id": "lic_x"}
    assert fake.imzala(payload) == fake.imzala(dict(payload))


def test_fake_imzalayici_farkli_payload_icin_farkli_imza_dondurur():
    fake = FakeImzalayici()
    assert fake.imzala({"a": 1}) != fake.imzala({"a": 2})


def test_ege_lisans_imzalayici_anahtar_yolu_tanimsizsa_acik_hata_verir():
    """Anahtar yolu (ne argüman ne env) tanımlı değilse sessizce imzasız
    lisans üretilmemeli — açık bir hatayla durmalı."""
    with pytest.raises(RuntimeError, match="EGE_LISANS_OZEL_ANAHTAR"):
        EgeLisansImzalayici(private_key_path=None).imzala({"schema": 2})


def test_ege_lisans_imzalayici_olmayan_dosya_yolu_hata_verir(tmp_path):
    with pytest.raises(RuntimeError, match="bulunamadı"):
        EgeLisansImzalayici(private_key_path=tmp_path / "yok.pem").imzala({"schema": 2})


def test_ege_lisans_imzalayici_gercek_anahtarla_imzalar_ve_dogrular(tmp_path):
    """Uçtan uca: geçici bir Ed25519 anahtar çifti üretip gerçek `ege_lisans`
    ile imzalar, sonra yine `ege_lisans` ile doğrular — protokolün üretim
    implementasyonunun gerçekten çalıştığını kanıtlar (sahte değil)."""
    from ege_lisans.keys import verify_signature
    from ege_lisans.signing import generate_keypair

    key_path = tmp_path / "test_key.pem"
    public_key_hex = generate_keypair(key_path)

    imzalayici = EgeLisansImzalayici(private_key_path=key_path)
    payload = {"schema": 2, "license_id": "lic_test", "expires": "2027-01-01"}
    signature = imzalayici.imzala(payload)

    assert verify_signature(payload, signature, [public_key_hex]) == 0
