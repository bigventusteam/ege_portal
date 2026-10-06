"""
Havale/EFT için personel "ödendi" işaretlemesi (kullanıcı kararı,
2026-10-05) — `GET /api/v1/admin/orders` ve
`POST /api/v1/admin/orders/{id}/mark-paid`. Kontrol sırası/gerekçesi için
bkz. app/services/manual_payments.py modül docstring'i.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models import AuditEvent, Customer, IssuedLicense, Order, OrderStatus, Subscription, User
from app.routers.auth import issue_session_token
from app.security import hash_password
from app.services.orders import create_order
from tests.fakes import ornek_odeme


def _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay) -> Order:
    return create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)


def _odeme_govdesi(toplam: Decimal, *, referans="REF-0001", not_metni=None) -> dict:
    return {
        "amount": str(toplam),
        "bank_reference": referans,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "note": not_metni,
    }


# ─── Yetki ────────────────────────────────────────────────────────────────────


def test_personel_olmayan_listeyi_goremez_403(client, db, kullanici, auth_headers, musteri, plan_pro, fiyat_12_ay):
    _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    resp = client.get("/api/v1/admin/orders", headers=auth_headers)
    assert resp.status_code == 403


def test_personel_olmayan_isaretleyemez_403(client, db, kullanici, auth_headers, musteri, plan_pro, fiyat_12_ay):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    resp = client.post(
        f"/api/v1/admin/orders/{order.id}/mark-paid", json=_odeme_govdesi(order.total), headers=auth_headers
    )
    assert resp.status_code == 403


def test_oturumsuz_401(client):
    assert client.get("/api/v1/admin/orders").status_code == 401


# ─── Listeleme ────────────────────────────────────────────────────────────────


def test_bekleyen_siparisler_listelenir(client, db, musteri, plan_pro, fiyat_12_ay, admin_headers):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)

    resp = client.get("/api/v1/admin/orders?status=pending", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    satir = body[0]
    assert satir["id"] == order.id
    assert satir["customer_name"] == musteri.name
    assert satir["plan_name"] == plan_pro.name
    assert satir["months"] == 12
    assert satir["net"] == "12000.00"
    assert satir["vat_amount"] == "2400.00"
    assert satir["total"] == "14400.00"
    assert satir["status"] == "pending"


def test_odenmis_siparis_bekleyenler_listesinde_yok(client, db, musteri, plan_pro, fiyat_12_ay, admin_headers):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    order.status = OrderStatus.PAID
    db.commit()

    resp = client.get("/api/v1/admin/orders?status=pending", headers=admin_headers)
    assert resp.json() == []


def test_gecersiz_status_422(client, admin_headers):
    resp = client.get("/api/v1/admin/orders?status=boyle-bir-durum-yok", headers=admin_headers)
    assert resp.status_code == 422


# ─── mark-paid: başarı ────────────────────────────────────────────────────────


def test_basarili_isaretlemede_abonelik_lisans_audit_olusur(
    client, db, musteri, plan_pro, fiyat_12_ay, admin_headers, yonetici
):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)

    resp = client.post(
        f"/api/v1/admin/orders/{order.id}/mark-paid",
        json=_odeme_govdesi(order.total, referans="DEKONT-42", not_metni="şubeden elden"),
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["order_status"] == "paid"
    assert body["bank_reference"] == "DEKONT-42"
    assert body["marked_by_user_id"] == yonetici.id

    db.refresh(order)
    assert order.status == OrderStatus.PAID

    sub = db.query(Subscription).filter_by(customer_id=musteri.id, plan_id=plan_pro.id).one()
    assert sub.current_period_end > datetime.now(timezone.utc) + timedelta(days=300)

    # KARAR (2026-10-06, EGE lider onayı): ödeme (bvpay YA DA burada elle
    # havale/EFT işaretleme) artık imzalı bir IssuedLicense ÜRETMEZ — bkz.
    # app/services/licenses.py::get_or_create_license_key docstring'i,
    # tests/test_payments_verification.py'deki aynı karar.
    lisans_sayisi = db.query(IssuedLicense).join(Subscription).filter(Subscription.id == sub.id).count()
    assert lisans_sayisi == 0

    olay = db.query(AuditEvent).filter_by(event_type="payment.marked_paid_manual").one()
    assert olay.entity_id == str(order.id)
    assert olay.data["staff_user_id"] == yonetici.id
    assert olay.data["bank_reference"] == "DEKONT-42"


# ─── mark-paid: reddedilen senaryolar ─────────────────────────────────────────


def test_yanlis_tutar_422(client, db, musteri, plan_pro, fiyat_12_ay, admin_headers):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    resp = client.post(
        f"/api/v1/admin/orders/{order.id}/mark-paid",
        json=_odeme_govdesi(order.total - Decimal("1.00")),
        headers=admin_headers,
    )
    assert resp.status_code == 422
    db.refresh(order)
    assert order.status == OrderStatus.PENDING
    assert db.query(AuditEvent).filter_by(event_type="payment.mark_paid_rejected").count() == 1


def test_ikinci_isaretleme_409(client, db, musteri, plan_pro, fiyat_12_ay, admin_headers):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    ilk = client.post(
        f"/api/v1/admin/orders/{order.id}/mark-paid",
        json=_odeme_govdesi(order.total, referans="REF-A"),
        headers=admin_headers,
    )
    assert ilk.status_code == 200

    ikinci = client.post(
        f"/api/v1/admin/orders/{order.id}/mark-paid",
        json=_odeme_govdesi(order.total, referans="REF-B"),
        headers=admin_headers,
    )
    assert ikinci.status_code == 409


def test_bvpay_ile_odenmis_siparis_409(
    client, db, fake_bvpay, kullanici, auth_headers, musteri, plan_pro, fiyat_12_ay, admin_headers
):
    resp = client.post("/api/v1/orders", json={"plan_id": plan_pro.id, "months": 12}, headers=auth_headers)
    order_body = resp.json()
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(
            payment_id="pay_bvpay_1", status="approved", amount=Decimal(order_body["total"]),
            passthrough={"order_id": order_body["id"]},
        )
    )
    webhook = client.post(
        "/api/v1/webhooks/bvpay", json={"payment_id": "pay_bvpay_1", "passthrough": {"order_id": order_body["id"]}}
    )
    assert webhook.json()["processed"] is True

    manual = client.post(
        f"/api/v1/admin/orders/{order_body['id']}/mark-paid",
        json=_odeme_govdesi(Decimal(order_body["total"])),
        headers=admin_headers,
    )
    assert manual.status_code == 409


def test_tekrar_kullanilan_referans_409(client, db, musteri, plan_pro, fiyat_12_ay, admin_headers):
    siparis_1 = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    siparis_2 = create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)

    ilk = client.post(
        f"/api/v1/admin/orders/{siparis_1.id}/mark-paid",
        json=_odeme_govdesi(siparis_1.total, referans="AYNI-DEKONT"),
        headers=admin_headers,
    )
    assert ilk.status_code == 200

    ikinci = client.post(
        f"/api/v1/admin/orders/{siparis_2.id}/mark-paid",
        json=_odeme_govdesi(siparis_2.total, referans="AYNI-DEKONT"),
        headers=admin_headers,
    )
    assert ikinci.status_code == 409
    db.refresh(siparis_2)
    assert siparis_2.status == OrderStatus.PENDING  # ikinci sipariş ETKİLENMEDİ


def test_gelecek_tarihli_received_at_422(client, db, musteri, plan_pro, fiyat_12_ay, admin_headers):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    govde = _odeme_govdesi(order.total)
    govde["received_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    resp = client.post(f"/api/v1/admin/orders/{order.id}/mark-paid", json=govde, headers=admin_headers)
    assert resp.status_code == 422


def test_kendi_musterisinin_siparisini_isaretleyemez_403(client, db, musteri, plan_pro, fiyat_12_ay):
    """Personelin müşteri kaydı siparişin müşterisiyle AYNIYSA reddedilir
    (görevler ayrılığı) — `yonetici` fixture'ı farklı bir müşteriye bağlı
    olduğu için burada KASITLI ayrı bir personel oluşturuluyor."""
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)

    kendi_personeli = User(
        customer_id=musteri.id,
        email="personel-aynı-musteri@example.com",
        password_hash=hash_password("parola123456"),
        is_staff=True,
    )
    db.add(kendi_personeli)
    db.commit()
    headers = {"Authorization": f"Bearer {issue_session_token(kendi_personeli.id)}"}

    resp = client.post(
        f"/api/v1/admin/orders/{order.id}/mark-paid", json=_odeme_govdesi(order.total), headers=headers
    )
    assert resp.status_code == 403
    db.refresh(order)
    assert order.status == OrderStatus.PENDING
    assert db.query(AuditEvent).filter_by(event_type="payment.mark_paid_rejected").count() == 1


def test_bos_referans_422(client, db, musteri, plan_pro, fiyat_12_ay, admin_headers):
    order = _bekleyen_siparis(db, musteri, plan_pro, fiyat_12_ay)
    govde = _odeme_govdesi(order.total, referans="   ")
    resp = client.post(f"/api/v1/admin/orders/{order.id}/mark-paid", json=govde, headers=admin_headers)
    assert resp.status_code == 422
