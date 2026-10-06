"""
`GET /api/v1/subscriptions` ve `GET /api/v1/subscriptions/{id}/licenses/
{license_id}` — müşterinin kendi aboneliklerini/lisanslarını görmesi
(2026-09-28 görevi). IDOR deseni `app/routers/activations.py` ile aynı:
abonelik yoksa VEYA başka müşteriye aitse ikisi de aynı 404.
"""
from decimal import Decimal

from app.models import AuditEvent, Customer, IssuedLicense, Subscription, User
from app.routers.auth import issue_session_token
from app.security import hash_password
from tests.fakes import ornek_odeme


def _siparis_olustur(client, auth_headers, plan_pro):
    resp = client.post("/api/v1/orders", json={"plan_id": plan_pro.id, "months": 12}, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()


def _odeme_yap(client, fake_bvpay, order, payment_id="pay_sub_1"):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id=payment_id, status="approved", amount=Decimal(order["total"]), passthrough={"order_id": order["id"]})
    )
    resp = client.post("/api/v1/webhooks/bvpay", json={"payment_id": payment_id, "passthrough": {"order_id": order["id"]}})
    assert resp.status_code == 202
    assert resp.json()["processed"] is True


def _lisans_belgesi_ekle(db, sub: Subscription, *, license_id: str = "lic_test123") -> IssuedLicense:
    """KARAR (2026-10-06, EGE lider onayı): ödeme artık imzalı bir
    IssuedLicense ÜRETMEZ (yalnız LicenseKey — bkz. app/services/
    licenses.py::get_or_create_license_key docstring'i), o belge yalnız
    GERÇEK bir çevrimdışı aktivasyonda oluşur. Bu dosyadaki testler yeniden
    indirme UCUNU test ediyor, çevrimdışı aktivasyonun KENDİSİNİ değil (o
    ayrı test_offline_activation.py'de) — bu yüzden var olan LicenseKey'e
    elle, doğrudan bir IssuedLicense ekliyoruz."""
    from app.models import LicenseKey

    lisans_anahtari = db.query(LicenseKey).filter_by(subscription_id=sub.id).one()
    issued = IssuedLicense(
        subscription_id=sub.id,
        license_key_id=lisans_anahtari.id,
        payload={"license_id": license_id, "schema": 2},
        signature="deadbeef",
        issued_at=sub.created_at,
        expires_at=sub.current_period_end,
    )
    db.add(issued)
    db.commit()
    db.refresh(issued)
    return issued


def _baska_musteri_headers(db) -> dict:
    musteri = Customer(name="Başka Belediye", email="baska@example.com")
    db.add(musteri)
    db.flush()
    user = User(customer_id=musteri.id, email="baska-kullanici@example.com", password_hash=hash_password("baska-parola-123"))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = issue_session_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def test_abonelikleri_listele_odenmis_siparisten_sonra_gorunur(
    client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay, urun_mapege
):
    order = _siparis_olustur(client, auth_headers, plan_pro)
    _odeme_yap(client, fake_bvpay, order)

    resp = client.get("/api/v1/subscriptions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1

    sub = body[0]
    assert sub["plan_id"] == plan_pro.id
    assert sub["plan_code"] == plan_pro.code
    assert sub["status"] == "active"
    assert sub["items"] == [{"product_code": urun_mapege.code, "product_name": urun_mapege.name}]

    # KARAR (2026-10-06, EGE lider onayı): ödeme artık imzalı bir
    # IssuedLicense ÜRETMEZ (yalnız LicenseKey) — bkz. _lisans_belgesi_ekle.
    assert sub["issued_licenses"] == []


def test_abonelikleri_listele_baskasinin_abonesini_gostermez(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro)
    _odeme_yap(client, fake_bvpay, order)

    baska_headers = _baska_musteri_headers(db)
    resp = client.get("/api/v1/subscriptions", headers=baska_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_abonelikleri_listele_oturumsuz_401_doner(client):
    resp = client.get("/api/v1/subscriptions")
    assert resp.status_code == 401


def test_lisans_yeniden_indir_dogru_belgeyi_doner(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro)
    _odeme_yap(client, fake_bvpay, order)

    sub = db.query(Subscription).filter_by(customer_id=kullanici.customer_id, plan_id=plan_pro.id).one()
    issued = _lisans_belgesi_ekle(db, sub)
    license_id = issued.payload["license_id"]

    resp = client.get(f"/api/v1/subscriptions/{sub.id}/licenses/{license_id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["payload"]["license_id"] == license_id
    assert body["signature"] == issued.signature


def test_lisans_yeniden_indir_baskasinin_aboneligi_404_doner(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro)
    _odeme_yap(client, fake_bvpay, order)

    sub = db.query(Subscription).filter_by(customer_id=kullanici.customer_id, plan_id=plan_pro.id).one()
    issued = _lisans_belgesi_ekle(db, sub)
    license_id = issued.payload["license_id"]

    baska_headers = _baska_musteri_headers(db)
    resp = client.get(f"/api/v1/subscriptions/{sub.id}/licenses/{license_id}", headers=baska_headers)
    assert resp.status_code == 404


def test_lisans_yeniden_indir_bilinmeyen_license_id_404_doner(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro)
    _odeme_yap(client, fake_bvpay, order)

    sub = db.query(Subscription).filter_by(customer_id=kullanici.customer_id, plan_id=plan_pro.id).one()

    resp = client.get(f"/api/v1/subscriptions/{sub.id}/licenses/lic_bilinmeyen", headers=auth_headers)
    assert resp.status_code == 404


def test_lisans_yeniden_indir_audit_kaydi_yazar(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro)
    _odeme_yap(client, fake_bvpay, order)

    sub = db.query(Subscription).filter_by(customer_id=kullanici.customer_id, plan_id=plan_pro.id).one()
    issued = _lisans_belgesi_ekle(db, sub)
    license_id = issued.payload["license_id"]

    resp = client.get(f"/api/v1/subscriptions/{sub.id}/licenses/{license_id}", headers=auth_headers)
    assert resp.status_code == 200

    event = db.query(AuditEvent).filter_by(event_type="license.redownloaded").one()
    assert event.entity_type == "issued_license"
    assert event.entity_id == str(issued.id)
    assert event.data == {"subscription_id": sub.id, "license_id": license_id, "customer_id": kullanici.customer_id}
