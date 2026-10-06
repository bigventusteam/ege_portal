from decimal import Decimal

import pytest

from app.models import OrderStatus
from app.services.orders import CustomerNotFoundError, PlanNotFoundError, create_order
from app.services.pricing import PriceNotFoundError


def test_siparis_tutari_gecerli_fiyattan_hesaplanir(db, musteri, plan_pro, fiyat_12_ay):
    order = create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)
    assert order.net == Decimal("12000.00")
    assert order.vat_rate == Decimal("20.00")
    assert order.vat_amount == Decimal("2400.00")
    assert order.total == Decimal("14400.00")
    assert order.currency == "949"
    assert order.status == OrderStatus.PENDING


def test_siparis_kdv_yuvarlama_round_half_up(db, musteri, plan_pro, fiyat_12_ay):
    """99.99 * %20 = 19.998 (yarım kuruş) — ROUND_HALF_UP ile 20.00'a
    yuvarlanmalı, total = 119.99 (bankacılık/faturalama kuralı, `float`
    ile hesaplansa ikili kayan nokta hatasıyla sessizce yanlış sonuç
    üretebilirdi)."""
    fiyat_12_ay.amount = Decimal("99.99")
    db.commit()

    order = create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)
    assert order.net == Decimal("99.99")
    assert order.vat_amount == Decimal("20.00")
    assert order.total == Decimal("119.99")


def test_siparis_olmayan_musteri_icin_hata_verir(db, plan_pro, fiyat_12_ay):
    with pytest.raises(CustomerNotFoundError):
        create_order(db, customer_id=999, plan_id=plan_pro.id, months=12)


def test_siparis_olmayan_plan_icin_hata_verir(db, musteri):
    with pytest.raises(PlanNotFoundError):
        create_order(db, customer_id=musteri.id, plan_id=999, months=12)


def test_siparis_fiyati_olmayan_sure_icin_hata_verir(db, musteri, plan_pro, fiyat_12_ay):
    with pytest.raises(PriceNotFoundError):
        create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=1)


def test_api_istemcinin_gonderdigi_tutari_yoksayar(client, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    """`POST /api/v1/orders` şeması `amount`/`total` alanı KABUL ETMEZ —
    istemci ne gönderirse göndersin tutar sunucudaki Price'tan hesaplanır."""
    resp = client.post(
        "/api/v1/orders",
        json={"plan_id": plan_pro.id, "months": 12, "total": "1.00", "amount": "1.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["net"] == "12000.00"
    assert body["vat_amount"] == "2400.00"
    assert body["total"] == "14400.00"
    assert body["status"] == "pending"
    assert body["customer_id"] == kullanici.customer_id


def test_api_bilinmeyen_plan_404_doner(client, kullanici, auth_headers):
    resp = client.post("/api/v1/orders", json={"plan_id": 999, "months": 12}, headers=auth_headers)
    assert resp.status_code == 404


def test_api_oturumsuz_siparis_401_doner(client, plan_pro, fiyat_12_ay):
    resp = client.post("/api/v1/orders", json={"plan_id": plan_pro.id, "months": 12})
    assert resp.status_code == 401


def test_api_gecersiz_token_401_doner(client, plan_pro, fiyat_12_ay):
    resp = client.post(
        "/api/v1/orders",
        json={"plan_id": plan_pro.id, "months": 12},
        headers={"Authorization": "Bearer bu-gecersiz-bir-token"},
    )
    assert resp.status_code == 401


def test_api_baskasinin_customer_id_gonderemez(client, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    """Eski davranış (customer_id query param) IDOR'a açıktı — şema artık
    customer_id alanını hiç kabul etmiyor, sipariş her zaman oturumdaki
    kullanıcının customer_id'sine açılır."""
    resp = client.post(
        "/api/v1/orders",
        json={"plan_id": plan_pro.id, "months": 12, "customer_id": 999999},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["customer_id"] == kullanici.customer_id
