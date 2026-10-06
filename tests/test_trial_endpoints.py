"""
Deneme (trial) lisansı — HTTP uçları: yönetici uçları (403 dışı erişim) ve
`POST /api/v1/trial-activation`. Uçtan uca lisans doğrulaması (GERÇEK
`ege_lisans`) `test_ucdan_uca_deneme_lisansi_valid_ve_trial_doner`'da.
"""
from datetime import datetime, timedelta, timezone

import pytest
from ege_lisans import LicenseContext, validate_license
from ege_lisans.signing import generate_keypair

from app.deps import get_imzalayici
from app.licensing import EgeLisansImzalayici
from app.main import app
from app.models import AuditEvent, Customer, Product, TrialActivation, User
from app.routers.auth import issue_session_token
from app.security import hash_password
from tests.test_offline_activation import MAPEGE_FP, SISEGE_FP, _activation_request_bytes, _hex


@pytest.fixture
def urun_sisege(db):
    p = Product(code="sisege", name="sisEGE")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _yukle(client, headers, urunler):
    files = [(f"{code}.json", _activation_request_bytes(code, fp), "application/json") for code, fp in urunler]
    return client.post("/api/v1/trial-activation", files=[("files", f) for f in files], headers=headers)


# ─── Yönetici uçlarına dışarıdan erişim ─────────────────────────────────────


ADMIN_UCLARI = [
    ("get", "/api/v1/admin/trial-settings", None),
    ("put", "/api/v1/admin/trial-settings", {"default_days": 10}),
    ("get", "/api/v1/admin/trial-campaigns", None),
    (
        "post",
        "/api/v1/admin/trial-campaigns",
        {"name": "X", "days": 10, "starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-10-31T00:00:00Z"},
    ),
]


@pytest.mark.parametrize("method, path, body", ADMIN_UCLARI)
def test_yonetici_uclarina_oturumsuz_401_doner(client, method, path, body):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 401


@pytest.mark.parametrize("method, path, body", ADMIN_UCLARI)
def test_yonetici_uclarina_yonetici_olmayan_403_doner(client, kullanici, auth_headers, method, path, body):
    resp = client.request(method, path, json=body, headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.parametrize("method, path, body", ADMIN_UCLARI)
def test_musteri_ici_admin_role_uretici_uclarina_403_alir(
    client, musteri_ici_yonetici, musteri_ici_yonetici_headers, method, path, body
):
    """Rol karışıklığı düzeltmesi (EGE lider'in incelemesinde bulundu):
    müşteri KURUMU İÇİNDE `role=ADMIN` olmak üretici (platform) yetkisi
    VERMEMELİ — `require_staff` yalnız `User.is_staff`'a bakıyor, `role`'e
    değil. Bu test, `musteri_ici_yonetici` fixture'ının (bkz. conftest.py)
    `role=ADMIN, is_staff=False` olduğunu ve yine de 403 aldığını
    doğrular."""
    assert musteri_ici_yonetici.is_staff is False
    resp = client.request(method, path, json=body, headers=musteri_ici_yonetici_headers)
    assert resp.status_code == 403


def test_yonetici_musteriye_ozel_uclara_yonetici_olmayan_403_doner(client, kullanici, auth_headers, musteri):
    resp1 = client.patch(f"/api/v1/admin/customers/{musteri.id}/trial-override", json={"days": 10}, headers=auth_headers)
    assert resp1.status_code == 403

    resp2 = client.post(
        f"/api/v1/admin/customers/{musteri.id}/trial-grants", json={"extra_days": 5}, headers=auth_headers
    )
    assert resp2.status_code == 403


def test_yonetici_musteriye_ozel_uclara_musteri_ici_admin_403_alir(
    client, musteri_ici_yonetici, musteri_ici_yonetici_headers, musteri
):
    resp1 = client.patch(
        f"/api/v1/admin/customers/{musteri.id}/trial-override", json={"days": 10}, headers=musteri_ici_yonetici_headers
    )
    assert resp1.status_code == 403

    resp2 = client.post(
        f"/api/v1/admin/customers/{musteri.id}/trial-grants",
        json={"extra_days": 5},
        headers=musteri_ici_yonetici_headers,
    )
    assert resp2.status_code == 403


# ─── Yönetici happy-path ─────────────────────────────────────────────────────


def test_yonetici_genel_ayari_okur_ve_gunceller(client, admin_headers):
    resp = client.get("/api/v1/admin/trial-settings", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["default_days"] == 7

    resp2 = client.put("/api/v1/admin/trial-settings", json={"default_days": 21}, headers=admin_headers)
    assert resp2.status_code == 200
    assert resp2.json()["default_days"] == 21


def test_yonetici_kampanya_olusturur_ve_listeler(client, admin_headers):
    body = {"name": "Kasım kampanyası", "days": 30, "starts_at": "2026-11-01T00:00:00Z", "ends_at": "2026-11-30T00:00:00Z"}
    resp = client.post("/api/v1/admin/trial-campaigns", json=body, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.json()["days"] == 30

    resp2 = client.get("/api/v1/admin/trial-campaigns", headers=admin_headers)
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


def test_yonetici_musteri_override_ayarlar_ve_kaldirir(client, admin_headers, musteri):
    resp = client.patch(f"/api/v1/admin/customers/{musteri.id}/trial-override", json={"days": 30}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["trial_days_override"] == 30

    resp2 = client.patch(f"/api/v1/admin/customers/{musteri.id}/trial-override", json={"days": None}, headers=admin_headers)
    assert resp2.status_code == 200
    assert resp2.json()["trial_days_override"] is None


def test_yonetici_musteriye_ek_sure_verir(client, admin_headers, musteri):
    resp = client.post(
        f"/api/v1/admin/customers/{musteri.id}/trial-grants",
        json={"extra_days": 14, "reason": "kampanya sonrası müşteri isteği"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["extra_days"] == 14
    assert body["consumed_at"] is None


def test_var_olmayan_musteriye_override_404_doner(client, admin_headers):
    resp = client.patch("/api/v1/admin/customers/999999/trial-override", json={"days": 10}, headers=admin_headers)
    assert resp.status_code == 404


# ─── POST /api/v1/trial-activation ──────────────────────────────────────────


def test_oturumsuz_401_doner(client):
    resp = _yukle(client, {}, [("mapege", MAPEGE_FP)])
    assert resp.status_code == 401


def test_basarili_deneme_200_doner(client, kullanici, auth_headers, urun_mapege, urun_sisege):
    resp = _yukle(client, auth_headers, [("mapege", MAPEGE_FP), ("sisege", SISEGE_FP)])
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["payload"]["license_type"] == "trial"
    assert doc["payload"]["grace_days"] == 0
    assert all(p["tier"] == "full" for p in doc["payload"]["products"].values())


def test_ikinci_deneme_409_doner(client, kullanici, auth_headers, urun_mapege):
    r1 = _yukle(client, auth_headers, [("mapege", MAPEGE_FP)])
    assert r1.status_code == 200
    r2 = _yukle(client, auth_headers, [("mapege", MAPEGE_FP)])
    assert r2.status_code == 409


def test_instance_id_baska_musteride_409_doner(client, db, kullanici, auth_headers, urun_mapege):
    r1 = _yukle(client, auth_headers, [("mapege", MAPEGE_FP)])
    assert r1.status_code == 200

    baska_musteri = Customer(name="Rakip Kurum", email="rakip@example.com")
    db.add(baska_musteri)
    db.flush()
    baska_kullanici = User(
        customer_id=baska_musteri.id, email="rakip-user@example.com", password_hash=hash_password("x")
    )
    db.add(baska_kullanici)
    db.commit()
    db.refresh(baska_kullanici)
    baska_headers = {"Authorization": f"Bearer {issue_session_token(baska_kullanici.id)}"}

    r2 = _yukle(client, baska_headers, [("mapege", MAPEGE_FP)])  # AYNI instance_id
    assert r2.status_code == 409

    assert db.query(AuditEvent).filter_by(event_type="trial.instance_id_collision").count() == 1


def test_ucdan_uca_deneme_lisansi_valid_ve_trial_doner(client, kullanici, auth_headers, urun_mapege, tmp_path):
    """GERÇEK ege_lisans imzalama + doğrulama — sahte imzalayıcı değil
    (bkz. tests/test_offline_activation.py'deki aynı desen)."""
    key_path = tmp_path / "trial_test_key.pem"
    public_key_hex = generate_keypair(key_path)
    gercek_imzalayici = EgeLisansImzalayici(private_key_path=key_path)
    app.dependency_overrides[get_imzalayici] = lambda: gercek_imzalayici

    resp = _yukle(client, auth_headers, [("mapege", MAPEGE_FP)])
    assert resp.status_code == 200
    doc = resp.json()

    assert doc["payload"]["license_type"] == "trial"

    ctx = LicenseContext(product="mapege", public_keys=(public_key_hex,), data_dir=tmp_path / "data")
    sonuc = validate_license(doc, ctx, fingerprint=MAPEGE_FP)
    assert sonuc["state"] == "valid", sonuc
    assert sonuc["tier"] == "full"
    # ege_lisans artık license_type'ı doğrulama sonucunda da döndürüyor
    # (worker_1'in eklediği alan) — GERÇEK doğrulama sonucundan kontrol.
    assert sonuc["license_type"] == "trial"
