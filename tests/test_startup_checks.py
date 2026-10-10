"""
`app/startup_checks.py` — `ENVIRONMENT=production` iken fail-closed
kontroller (sisEGE'nin startup_checks.py'sindeki AYNI desen).
"""
import pytest

from app.startup_checks import StartupConfigError, validate_startup_config


def _settings():
    """`settings` import-anında oluşturulan tekil bir nesne — testler onun
    özniteliklerini `monkeypatch.setattr` ile değiştirir, her testin SONUNDA
    pytest otomatik olarak eski hâline geri alır."""
    from app.config import settings

    return settings


@pytest.fixture
def uretim_anahtari(tmp_path, monkeypatch):
    """Geçici, parolayla şifreli bir Ed25519 anahtarı + parola dosyası —
    production açılış kontrolü anahtarı GERÇEKTEN yükler (bkz.
    app/startup_checks.py). Önbellekteki imzalayıcı önce/sonra temizlenir."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.deps import _default_imzalayici

    parola = "startup-test-parolasi-0123456789"
    anahtar = tmp_path / "k.pem"
    anahtar.write_bytes(Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(parola.encode())))
    parola_dosyasi = tmp_path / "parola"
    parola_dosyasi.write_text(parola, encoding="utf-8")
    s = _settings()
    monkeypatch.setattr(s, "ege_lisans_private_key_path", str(anahtar))
    monkeypatch.setattr(s, "ege_lisans_anahtar_parola_dosyasi", str(parola_dosyasi))
    monkeypatch.setattr(s, "ege_lisans_acik_anahtar_parmak_izi", "")
    _default_imzalayici.cache_clear()
    yield {"anahtar": anahtar, "parola_dosyasi": parola_dosyasi}
    _default_imzalayici.cache_clear()


def _uretim(monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", True)
    monkeypatch.setattr(s, "trusted_proxies", ["172.28.0.0/24"])
    return s


def test_development_da_hicbir_kontrol_calismaz(monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "development")
    monkeypatch.setattr(s, "secret_key", "")
    monkeypatch.setattr(s, "cookie_secure", False)
    validate_startup_config()  # hata ATMAZ


def test_production_da_bos_secret_key_reddedilir(monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "")
    monkeypatch.setattr(s, "cookie_secure", True)
    with pytest.raises(StartupConfigError, match="SECRET_KEY"):
        validate_startup_config()


def test_production_da_bilinen_varsayilan_secret_key_reddedilir(monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "dev-only")
    monkeypatch.setattr(s, "cookie_secure", True)
    with pytest.raises(StartupConfigError, match="SECRET_KEY"):
        validate_startup_config()


def test_production_da_cookie_secure_false_reddedilir(monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", False)
    with pytest.raises(StartupConfigError, match="COOKIE_SECURE"):
        validate_startup_config()


def test_production_da_gecerli_yapilandirma_kabul_edilir(uretim_anahtari, monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", True)
    monkeypatch.setattr(s, "trusted_proxies", ["172.28.0.0/24"])
    validate_startup_config()  # hata ATMAZ


def test_production_da_trusted_proxies_bossa_uyari_loglanir_hata_atmaz(uretim_anahtari, monkeypatch, caplog):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", True)
    monkeypatch.setattr(s, "trusted_proxies", [])

    with caplog.at_level("WARNING"):
        validate_startup_config()  # hata ATMAZ — yalnız uyarı

    assert any("TRUSTED_PROXIES" in kayit.message for kayit in caplog.records)


def test_production_da_trusted_proxies_doluyken_uyari_YAZILMAZ(uretim_anahtari, monkeypatch, caplog):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", True)
    monkeypatch.setattr(s, "trusted_proxies", ["172.28.0.0/24"])

    with caplog.at_level("WARNING"):
        validate_startup_config()

    assert not any("TRUSTED_PROXIES" in kayit.message for kayit in caplog.records)


# ─── Lisans imza anahtarı (açılışta bir kez yüklenir) ──────────────────────


def test_production_da_anahtar_acilista_yuklenir_ve_onbellege_girer(uretim_anahtari, monkeypatch, caplog):
    from app.deps import _default_imzalayici

    _uretim(monkeypatch)
    with caplog.at_level("INFO", logger="ege_portal.startup"):
        validate_startup_config()
    imz = _default_imzalayici()
    assert imz.parmak_izi and imz.parmak_izi.startswith("sha256:")
    assert any(imz.parmak_izi in k.message and "birincil" in k.message for k in caplog.records)
    # parola/anahtar içeriği log'a girmez
    parola = uretim_anahtari["parola_dosyasi"].read_text(encoding="utf-8")
    assert all(parola not in k.getMessage() for k in caplog.records)


def test_production_da_anahtar_tanimsizsa_baslamaz(uretim_anahtari, monkeypatch):
    s = _uretim(monkeypatch)
    monkeypatch.setattr(s, "ege_lisans_private_key_path", "")
    with pytest.raises(StartupConfigError, match="EGE_LISANS_OZEL_ANAHTAR"):
        validate_startup_config()


def test_production_da_yanlis_parola_baslamaz_parola_mesajda_yok(uretim_anahtari, monkeypatch):
    _uretim(monkeypatch)
    uretim_anahtari["parola_dosyasi"].write_text("yanlis-parola-ZZZZZZZZZZZZZZZZ", encoding="utf-8")
    with pytest.raises(StartupConfigError, match="parola yanlış") as exc:
        validate_startup_config()
    assert "ZZZZ" not in str(exc.value)


def test_production_da_sifresiz_anahtar_baslamaz(uretim_anahtari, monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    s = _uretim(monkeypatch)
    duz = tmp_path / "duz.pem"
    duz.write_bytes(Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    monkeypatch.setattr(s, "ege_lisans_private_key_path", str(duz))
    monkeypatch.setattr(s, "ege_lisans_anahtar_parola_dosyasi", "")
    with pytest.raises(StartupConfigError, match="ŞİFRELİ olmalı"):
        validate_startup_config()


def test_production_da_envde_duz_parola_baslamaz(uretim_anahtari, monkeypatch):
    _uretim(monkeypatch)
    monkeypatch.setenv("EGE_LISANS_ANAHTAR_PAROLA", "duz-parola-QQQQQQQQQQQQ")
    with pytest.raises(StartupConfigError, match="düz metin") as exc:
        validate_startup_config()
    assert "QQQQ" not in str(exc.value)


def test_production_da_parmak_izi_eslesmezse_baslamaz(uretim_anahtari, monkeypatch):
    s = _uretim(monkeypatch)
    monkeypatch.setattr(s, "ege_lisans_acik_anahtar_parmak_izi", "sha256:0000000000000000")
    with pytest.raises(StartupConfigError, match="eşleşmiyor"):
        validate_startup_config()


def test_development_da_anahtar_acilista_yuklenmez(monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "development")
    monkeypatch.setattr(s, "ege_lisans_private_key_path", "")
    validate_startup_config()  # anahtar yoksa da hata ATMAZ (imzalamada açık hata verir)
