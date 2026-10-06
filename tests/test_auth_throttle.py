"""
Giriş/kayıt brute-force hız sınırlaması (app/services/auth_throttle.py,
app/routers/auth.py). Pencere: 15 dk, eşik: 5 (hem giriş hem kayıt).
"""
from app.security import hash_password, verify_password_or_dummy


def test_5_basarisiz_girisin_ardindan_dogru_parolayla_bile_kilitli(client, kullanici):
    for _ in range(5):
        resp = client.post("/api/v1/auth/login", json={"email": kullanici.email, "password": "yanlis-parola"})
        assert resp.status_code == 401

    resp = client.post("/api/v1/auth/login", json={"email": kullanici.email, "password": "test-parola-123"})
    assert resp.status_code == 401
    # Kilitliyken de AYNI genel hata — "kilitli" ile "yanlış parola" ayrımı sızdırılmaz.
    assert resp.json()["detail"] == "e-posta veya parola yanlış"


def test_4_basarisiz_girisin_ardindan_dogru_parola_hala_calisir(client, kullanici):
    for _ in range(4):
        client.post("/api/v1/auth/login", json={"email": kullanici.email, "password": "yanlis-parola"})

    resp = client.post("/api/v1/auth/login", json={"email": kullanici.email, "password": "test-parola-123"})
    assert resp.status_code == 200


def test_ip_basina_da_kilitlenir_farkli_bilinmeyen_epostalarla(client, kullanici):
    """Aynı istemciden (aynı IP) 5 farklı, VAR OLMAYAN e-postayla deneme —
    e-posta bazlı sayaç her biri için ayrı ayrı 1'de kalır, ama IP sayacı
    5'e ulaşır ve kilitler (gerçek kullanıcının e-postasıyla bile)."""
    for i in range(5):
        resp = client.post("/api/v1/auth/login", json={"email": f"yok-{i}@example.com", "password": "her-neyse-12"})
        assert resp.status_code == 401

    resp = client.post("/api/v1/auth/login", json={"email": kullanici.email, "password": "test-parola-123"})
    assert resp.status_code == 401


def test_kayitta_ip_basina_hiz_siniri_6_denemede_429(client):
    for i in range(5):
        resp = client.post(
            "/api/v1/auth/register",
            json={"customer_name": "X", "email": f"yeni-{i}@example.com", "password": "gecerli-parola-123"},
        )
        assert resp.status_code == 201

    resp = client.post(
        "/api/v1/auth/register",
        json={"customer_name": "Y", "email": "altinci@example.com", "password": "gecerli-parola-123"},
    )
    assert resp.status_code == 429


# ─── Zamanlama eşitlemesi (user enumeration'a karşı) ─────────────────────────


def test_bilinmeyen_eposta_icin_de_gercek_bir_bcrypt_karsilastirmasi_calisir():
    """`password_hash=None` (e-posta yok) → sahte hash'e karşı karşılaştırır,
    sonuç HER ZAMAN False ama bir bcrypt ÇAĞRISI gerçekten yapılmış olur —
    bilinmeyen e-postada yanıt süresi, var olan ama yanlış parolalı bir
    denemeyle aynı büyüklükte kalır."""
    assert verify_password_or_dummy("herhangi-bir-parola", None) is False


def test_var_olan_hash_ile_dogru_calisir():
    h = hash_password("dogru-parola-123456")
    assert verify_password_or_dummy("dogru-parola-123456", h) is True
    assert verify_password_or_dummy("yanlis-parola-xxxxx", h) is False
