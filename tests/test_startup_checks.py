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


def test_production_da_gecerli_yapilandirma_kabul_edilir(monkeypatch):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", True)
    monkeypatch.setattr(s, "trusted_proxies", ["172.28.0.0/24"])
    validate_startup_config()  # hata ATMAZ


def test_production_da_trusted_proxies_bossa_uyari_loglanir_hata_atmaz(monkeypatch, caplog):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", True)
    monkeypatch.setattr(s, "trusted_proxies", [])

    with caplog.at_level("WARNING"):
        validate_startup_config()  # hata ATMAZ — yalnız uyarı

    assert any("TRUSTED_PROXIES" in kayit.message for kayit in caplog.records)


def test_production_da_trusted_proxies_doluyken_uyari_YAZILMAZ(monkeypatch, caplog):
    s = _settings()
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "secret_key", "gercekten-rastgele-uretilmis-uzun-bir-anahtar")
    monkeypatch.setattr(s, "cookie_secure", True)
    monkeypatch.setattr(s, "trusted_proxies", ["172.28.0.0/24"])

    with caplog.at_level("WARNING"):
        validate_startup_config()

    assert not any("TRUSTED_PROXIES" in kayit.message for kayit in caplog.records)
