"""
`app/middleware.py::OriginDogrulamaMiddleware` — CSRF savunması. Durum
değiştiren (POST/PUT/PATCH/DELETE) istekler izinli bir `Origin` (yoksa
`Referer`'den türetilen origin) taşımalı; `/api/v1/webhooks/bvpay` muaftır.
"""


def test_izinli_origin_ile_post_calisir(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"customer_name": "X", "email": "iyi-origin@example.com", "password": "gecerli-parola-123"},
    )
    assert resp.status_code == 201


def test_origin_hic_yoksa_post_403_doner(client_raw):
    resp = client_raw.post(
        "/api/v1/auth/register",
        json={"customer_name": "X", "email": "origin-yok@example.com", "password": "gecerli-parola-123"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "izin verilmeyen origin"


def test_izinsiz_origin_ile_post_403_doner(client_raw):
    resp = client_raw.post(
        "/api/v1/auth/register",
        json={"customer_name": "X", "email": "kotu-origin@example.com", "password": "gecerli-parola-123"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403


def test_referer_dan_turetilen_origin_kabul_edilir(client_raw):
    """Origin yoksa Referer'in scheme+host'u kullanılır (bazı aynı-origin
    navigasyonlar Origin taşımayabilir)."""
    resp = client_raw.post(
        "/api/v1/auth/register",
        json={"customer_name": "X", "email": "referer-ile@example.com", "password": "gecerli-parola-123"},
        headers={"Referer": "http://localhost:5173/kayit"},
    )
    assert resp.status_code == 201


def test_webhook_origin_kontrolunden_muaftir(client_raw, fake_bvpay):
    """bvpay sunucudan sunucuya POST eder, Origin/Referer HİÇ taşımaz —
    middleware bu yolu engellemiyor olmalı (webhook'un KENDİ mantığı
    `processed: False` dönebilir, ama 403 ASLA DEĞİL)."""
    resp = client_raw.post(
        "/api/v1/webhooks/bvpay", json={"payment_id": "pay_bilinmeyen", "passthrough": {"order_id": 1}}
    )
    assert resp.status_code == 202


def test_guvenli_metotlar_origin_kontrolune_tabi_degil(client_raw):
    resp = client_raw.get("/api/v1/plans")
    assert resp.status_code == 200
