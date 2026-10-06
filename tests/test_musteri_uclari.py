"""
Müşteri arayüzünün ihtiyaç duyduğu salt-okunur uçlar:
  - GET /api/v1/auth/me          — oturumun sahibi (yenilemede arayüz buradan kurulur)
  - GET /api/v1/orders           — yalnız kendi müşterisinin siparişleri
  - GET /api/v1/trial-settings   — bu müşteri için geçerli deneme gün sayısı
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Customer, TrialCampaign, TrialGrant, TrialSettings, User
from app.security import hash_password
from app.services.orders import create_order


# ─── /auth/me ────────────────────────────────────────────────────────────────


def test_me_oturum_sahibini_doner(client, kullanici, auth_headers, musteri):
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "user_id": kullanici.id,
        "customer_id": musteri.id,
        "customer_name": "Test Belediyesi",
        "email": "siparis@example.com",
        "is_staff": False,
    }


def test_me_oturum_cereziyle_calisir(client, kullanici):
    giris = client.post("/api/v1/auth/login", json={"email": "siparis@example.com", "password": "test-parola-123"})
    assert giris.status_code == 200
    # Bearer YOK — yalnız TestClient'ın sakladığı HttpOnly çerez.
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == kullanici.id


def test_me_oturumsuz_ve_bozuk_token_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer bozuk"}).status_code == 401


def test_me_personel_bayragini_dogru_doner(client, yonetici, admin_headers):
    assert client.get("/api/v1/auth/me", headers=admin_headers).json()["is_staff"] is True


# ─── GET /orders ─────────────────────────────────────────────────────────────


def test_siparislerim_yalniz_kendi_musterisinin_siparisleri(client, db, kullanici, auth_headers, musteri, plan_pro, fiyat_12_ay):
    benim_1 = create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)
    benim_2 = create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12, quantity=2)
    baska = Customer(name="Başka Belediye", email="baska@example.com")
    db.add(baska)
    db.flush()
    create_order(db, customer_id=baska.id, plan_id=plan_pro.id, months=12)
    db.commit()

    resp = client.get("/api/v1/orders", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [o["id"] for o in body] == [benim_2.id, benim_1.id]  # yeniden eskiye
    assert body[0]["quantity"] == 2
    assert body[0]["status"] == "pending"
    for alan in ("net", "vat_rate", "vat_amount", "total", "currency"):
        assert alan in body[0]


def test_siparislerim_bos_liste(client, kullanici, auth_headers):
    resp = client.get("/api/v1/orders", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_siparislerim_oturumsuz_401(client):
    assert client.get("/api/v1/orders").status_code == 401


# ─── GET /trial-settings ─────────────────────────────────────────────────────


def _personel(db) -> User:
    m = Customer(name="EGE", email="ege@example.com")
    db.add(m)
    db.flush()
    u = User(customer_id=m.id, email="p@example.com", password_hash=hash_password("personel-parola-1"), is_staff=True)
    db.add(u)
    db.flush()
    return u


def test_deneme_suresi_genel_varsayilan(client, kullanici, auth_headers):
    resp = client.get("/api/v1/trial-settings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"days": 7}


def test_deneme_suresi_oncelik_musteri_kampanya_genel_ve_ek_sure(client, db, kullanici, auth_headers, musteri):
    simdi = datetime.now(timezone.utc)
    db.merge(TrialSettings(id=1, default_days=10))
    db.add(TrialCampaign(name="Ekim kampanyası", days=21, starts_at=simdi - timedelta(days=1), ends_at=simdi + timedelta(days=5)))
    db.commit()
    assert client.get("/api/v1/trial-settings", headers=auth_headers).json() == {"days": 21}  # kampanya > genel

    musteri.trial_days_override = 30
    db.commit()
    assert client.get("/api/v1/trial-settings", headers=auth_headers).json() == {"days": 30}  # müşteri > kampanya

    db.add(TrialGrant(customer_id=musteri.id, extra_days=5, granted_by_user_id=_personel(db).id))
    db.commit()
    assert client.get("/api/v1/trial-settings", headers=auth_headers).json() == {"days": 35}  # + tüketilmemiş ek süre


def test_deneme_suresi_kaynak_ve_kampanya_sizdirmaz(client, db, kullanici, auth_headers):
    simdi = datetime.now(timezone.utc)
    db.add(TrialCampaign(name="Gizli kampanya", days=14, starts_at=simdi - timedelta(days=1), ends_at=simdi + timedelta(days=1)))
    db.commit()
    resp = client.get("/api/v1/trial-settings", headers=auth_headers)
    assert set(resp.json()) == {"days"}
    assert "Gizli" not in resp.text


def test_deneme_suresi_oturumsuz_401(client):
    assert client.get("/api/v1/trial-settings").status_code == 401
