def test_kayit_ve_giris(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"customer_name": "Test A.Ş.", "email": "kayit@example.com", "password": "cok-gizli-123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"]

    resp2 = client.post("/api/v1/auth/login", json={"email": "kayit@example.com", "password": "cok-gizli-123"})
    assert resp2.status_code == 200
    assert resp2.json()["customer_id"] == body["customer_id"]


def test_yanlis_parola_401_doner(client):
    client.post(
        "/api/v1/auth/register",
        json={"customer_name": "Test A.Ş.", "email": "yanlis@example.com", "password": "dogru-parola"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": "yanlis@example.com", "password": "yanlis-parola"})
    assert resp.status_code == 401


def test_ayni_eposta_ile_ikinci_kayit_409_doner(client):
    body = {"customer_name": "X", "email": "tekrar@example.com", "password": "sifre-12345678"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    assert client.post("/api/v1/auth/register", json=body).status_code == 409


def test_parolalar_bcrypt_ile_saklanir():
    from app.security import hash_password, verify_password

    hashed = hash_password("herhangi-bir-parola")
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password("herhangi-bir-parola", hashed)
    assert not verify_password("yanlis-parola", hashed)


def test_giris_httponly_cerez_verir_ve_sipariste_kullanilir(client, plan_pro, fiyat_12_ay):
    """Login yalnız bearer token değil, HttpOnly bir oturum çerezi de verir
    — tarayıcı tabanlı bir arayüz `Authorization` header'ı hiç eklemeden,
    yalnız çerezle korumalı bir uca (`POST /api/v1/orders`) erişebilmeli."""
    kayit = client.post(
        "/api/v1/auth/register",
        json={"customer_name": "Çerez A.Ş.", "email": "cerez@example.com", "password": "cok-gizli-456"},
    )
    assert kayit.status_code == 201
    assert "ege_portal_session" in kayit.cookies

    # `client` (TestClient/httpx) aynı istemci içinde çerezi otomatik taşır —
    # burada BİLEREK Authorization header'ı GÖNDERMİYORUZ, yalnız çerez.
    resp = client.post("/api/v1/orders", json={"plan_id": plan_pro.id, "months": 12})
    assert resp.status_code == 201
    assert resp.json()["customer_id"] == kayit.json()["customer_id"]


def test_cikis_cerezi_temizler(client):
    kayit = client.post(
        "/api/v1/auth/register",
        json={"customer_name": "Çıkış A.Ş.", "email": "cikis@example.com", "password": "cok-gizli-789"},
    )
    assert "ege_portal_session" in kayit.cookies

    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    assert client.cookies.get("ege_portal_session") in (None, "")
