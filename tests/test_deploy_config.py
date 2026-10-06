"""
`deploy/` dosyalarının STATİK doğrulaması (Docker KULLANMAZ — bu testler
normal `pytest` koşusunun parçası). İmajın GERÇEKTEN build olduğu ayrıca
elle doğrulandı (bkz. görev raporu); burada yalnız yapılandırmanın
BEKLENEN şekli kontrol edilir.
"""
from pathlib import Path

import yaml

KOK = Path(__file__).resolve().parents[1]
DEPLOY = KOK / "deploy"


def _compose() -> dict:
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_gecerli_yaml():
    belge = _compose()
    assert "services" in belge
    assert set(belge["services"]) == {"db", "app", "caddy"}


def test_postgres_16_ve_kalici_volume():
    servisler = _compose()["services"]
    assert servisler["db"]["image"].startswith("postgres:16")
    assert any("portal_pgdata" in v for v in servisler["db"]["volumes"])
    assert "portal_pgdata" in _compose()["volumes"]


def test_sirlar_zorunlu_var_sozdizimiyle_tanimli():
    """`${VAR:?...}` — tanımsızsa compose AÇIKÇA hatayla durur, sessizce
    boş/varsayılan bir sıra DÜŞMEZ."""
    metin = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    for degisken in ("POSTGRES_PASSWORD", "SECRET_KEY", "BVPAY_URL", "BVPAY_API_KEY", "EGE_LISANS_PRIVATE_KEY_PATH"):
        assert f"${{{degisken}:?" in metin, degisken


def test_app_servisi_yalniz_127_0_0_1e_baglanir():
    """Tek internet'e açık giriş Caddy olmalı — `app` host'un TÜM
    arayüzlerine (0.0.0.0) AÇIK OLMAMALI."""
    servisler = _compose()["services"]
    portlar = servisler["app"].get("ports", [])
    assert portlar, "app servisinin bir port eşlemesi olmalı (hata ayıklama için)"
    for p in portlar:
        assert str(p).startswith("127.0.0.1:"), p


def test_app_production_ortaminda_calisir():
    servisler = _compose()["services"]
    assert servisler["app"]["environment"]["ENVIRONMENT"] == "production"
    assert servisler["app"]["environment"]["COOKIE_SECURE"] == "true"


def test_app_trusted_proxies_sabit_alt_aga_isaret_eder():
    """app/net.py::client_ip X-Forwarded-For'u yalnız TRUSTED_PROXIES'teki
    bir ağdan gelen bağlantılarda okur — burada Caddy'nin de üzerinde
    olduğu sabit `portal_net` alt ağı tanımlı olmalı (bkz. app/
    startup_checks.py'deki production uyarısı)."""
    belge = _compose()
    alt_ag = belge["networks"]["portal_net"]["ipam"]["config"][0]["subnet"]
    servisler = belge["services"]
    assert servisler["app"]["environment"]["TRUSTED_PROXIES"] == alt_ag
    assert "portal_net" in servisler["app"]["networks"]
    assert "portal_net" in servisler["caddy"]["networks"]


def test_app_portal_release_dir_kalici_volume_ile_eslesir():
    servisler = _compose()["services"]
    assert any("portal_releases:/data/releases" in v for v in servisler["app"]["volumes"])


def test_caddy_80_443_disa_acik_ve_caddyfile_bagli():
    servisler = _compose()["services"]
    caddy = servisler["caddy"]
    portlar = {str(p) for p in caddy["ports"]}
    assert "80:80" in portlar
    assert "443:443" in portlar
    assert any("Caddyfile" in v for v in caddy["volumes"])


def test_app_db_in_saglikli_olmasini_bekler():
    servisler = _compose()["services"]
    assert servisler["app"]["depends_on"]["db"]["condition"] == "service_healthy"


# ─── Dockerfile ───────────────────────────────────────────────────────────


def test_dockerfile_non_root_kullanici_calistirir():
    metin = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert "USER portal" in metin
    assert "useradd" in metin


def test_dockerfile_healthcheck_tanimli():
    metin = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in metin
    assert "/healthz" in metin


def test_dockerfile_frontend_build_asamasi_var():
    metin = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert "frontend-builder" in metin
    assert "npm run build" in metin
    assert "COPY --from=frontend-builder" in metin


def test_entrypoint_once_migration_sonra_uvicorn_calistirir():
    metin = (DEPLOY / "entrypoint.sh").read_text(encoding="utf-8")
    migration_konumu = metin.index("alembic upgrade head")
    uvicorn_konumu = metin.index("uvicorn")
    assert migration_konumu < uvicorn_konumu
    assert "set -e" in metin  # migration başarısız olursa süreç DURMALI


# ─── Caddyfile ────────────────────────────────────────────────────────────


def test_caddyfile_guvenlik_basliklarini_tasir():
    metin = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    for baslik in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "frame-ancestors"):
        assert baslik in metin, baslik
    assert "script-src 'self';" in metin  # inline script YOK


def test_caddyfile_app_servisine_proxy_yapar():
    metin = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    assert "reverse_proxy app:8002" in metin


def test_caddyfile_portal_domain_varsayilani_bigventus():
    metin = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    assert "portal.bigventus.com" in metin
