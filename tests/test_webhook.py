from decimal import Decimal

from app.models import LicenseKey, Order, OrderStatus, Subscription
from tests.fakes import ornek_odeme


def _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay):
    resp = client.post("/api/v1/orders", json={"plan_id": plan_pro.id, "months": 12}, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()


def test_webhook_dogru_odemeyi_isler(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay)
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_wh_1", status="approved", amount=Decimal(order["total"]), passthrough={"order_id": order["id"]})
    )

    resp = client.post(
        "/api/v1/webhooks/bvpay",
        json={"payment_id": "pay_wh_1", "passthrough": {"order_id": order["id"]}},
    )
    assert resp.status_code == 202
    assert resp.json()["processed"] is True

    db_order = db.get(Order, order["id"])
    assert db_order.status == OrderStatus.PAID


def test_webhook_tutar_net_degil_kdv_dahil_total_ile_karsilastirilir(
    client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay
):
    """bvpay doğrulaması KDV HARİÇ `net` ile DEĞİL, KDV DAHİL `total` ile
    karşılaştırılmalı (2026-09-28 kararı) — bankanın gönderdiği tutar yalnız
    `net`'e (KDV'siz) eşitse reddedilmeli, tam `total`'a eşit olmalı."""
    order = _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay)
    net = Decimal(order["net"])
    total = Decimal(order["total"])
    assert net != total  # KDV sıfır değilse (fiyat_12_ay: vat_rate=20.00) ikisi ayrışmalı

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_wh_net_only", status="approved", amount=net, passthrough={"order_id": order["id"]})
    )
    resp = client.post(
        "/api/v1/webhooks/bvpay",
        json={"payment_id": "pay_wh_net_only", "passthrough": {"order_id": order["id"]}},
    )
    assert resp.status_code == 202
    assert resp.json()["processed"] is False
    assert db.get(Order, order["id"]).status == OrderStatus.PENDING

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_wh_total", status="approved", amount=total, passthrough={"order_id": order["id"]})
    )
    resp = client.post(
        "/api/v1/webhooks/bvpay",
        json={"payment_id": "pay_wh_total", "passthrough": {"order_id": order["id"]}},
    )
    assert resp.status_code == 202
    assert resp.json()["processed"] is True
    assert db.get(Order, order["id"]).status == OrderStatus.PAID


def test_webhook_iki_kez_gelirse_abonelik_bir_kez_uzar(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay)
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_wh_dup", status="approved", amount=Decimal(order["total"]), passthrough={"order_id": order["id"]})
    )

    body = {"payment_id": "pay_wh_dup", "passthrough": {"order_id": order["id"]}}
    r1 = client.post("/api/v1/webhooks/bvpay", json=body)
    r2 = client.post("/api/v1/webhooks/bvpay", json=body)
    assert r1.status_code == 202
    assert r2.status_code == 202

    sub = db.query(Subscription).filter_by(customer_id=kullanici.customer_id, plan_id=plan_pro.id).one()
    lisanslar = db.query(LicenseKey).filter_by(subscription_id=sub.id).count()
    assert lisanslar == 1


def test_webhook_gecersiz_odemede_siparis_paid_olmaz(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    order = _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay)
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_wh_bad", status="declined", amount=Decimal(order["total"]), passthrough={"order_id": order["id"]})
    )

    resp = client.post(
        "/api/v1/webhooks/bvpay",
        json={"payment_id": "pay_wh_bad", "passthrough": {"order_id": order["id"]}},
    )
    assert resp.status_code == 202
    assert resp.json()["processed"] is False

    db_order = db.get(Order, order["id"])
    assert db_order.status == OrderStatus.PENDING


def test_webhook_govdeye_guvenmez_gercek_dogrulama_get_ile(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    """Webhook gövdesinde `passthrough.order_id` doğru siparişi gösterse
    bile, bvpay'den GET ile dönen gerçek `passthrough` başka bir siparişi
    gösteriyorsa işlem reddedilmeli — gövde yalnız tetikleyicidir."""
    order_a = _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay)
    order_b = _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay)

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(
            payment_id="pay_wh_spoof",
            status="approved",
            amount=Decimal(order_a["total"]),
            passthrough={"order_id": order_b["id"]},  # GET'in gerçek yanıtı B'yi gösteriyor
        )
    )

    resp = client.post(
        "/api/v1/webhooks/bvpay",
        # Webhook gövdesi A'yı iddia ediyor (güvenilmez).
        json={"payment_id": "pay_wh_spoof", "passthrough": {"order_id": order_a["id"]}},
    )
    assert resp.status_code == 202
    assert resp.json()["processed"] is False

    assert db.get(Order, order_a["id"]).status == OrderStatus.PENDING
    assert db.get(Order, order_b["id"]).status == OrderStatus.PENDING


def test_webhook_ayni_siparise_ikinci_odeme_reddedilir(client, db, fake_bvpay, kullanici, auth_headers, plan_pro, fiyat_12_ay):
    """Müşteri aynı siparişi iki farklı payment_id ile iki kez öderse
    (ör. çift tıklama, iki sekme) ikinci ödeme aboneliği İKİNCİ kez
    UZATMAMALI — bkz. app/services/payments.py::OrderAlreadyPaid."""
    order = _siparis_olustur(client, auth_headers, plan_pro, fiyat_12_ay)
    total = Decimal(order["total"])

    fake_bvpay.kuyruga_ekle(ornek_odeme(payment_id="pay_wh_ilk", status="approved", amount=total, passthrough={"order_id": order["id"]}))
    r1 = client.post("/api/v1/webhooks/bvpay", json={"payment_id": "pay_wh_ilk", "passthrough": {"order_id": order["id"]}})
    assert r1.status_code == 202
    assert r1.json()["processed"] is True

    sub = db.query(Subscription).filter_by(customer_id=kullanici.customer_id, plan_id=plan_pro.id).one()
    bitis_ilk = sub.current_period_end

    fake_bvpay.kuyruga_ekle(ornek_odeme(payment_id="pay_wh_ikinci", status="approved", amount=total, passthrough={"order_id": order["id"]}))
    r2 = client.post("/api/v1/webhooks/bvpay", json={"payment_id": "pay_wh_ikinci", "passthrough": {"order_id": order["id"]}})
    assert r2.status_code == 202
    assert r2.json()["processed"] is False

    db.refresh(sub)
    assert sub.current_period_end == bitis_ilk  # 24 aya değil, hâlâ 12 ayda

    ikinci_odeme = db.get(Order, order["id"]).payments[-1]
    assert ikinci_odeme.bvpay_payment_id == "pay_wh_ikinci"
    assert ikinci_odeme.processed_at is None  # elle iade gerekiyor işareti
