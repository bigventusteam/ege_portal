from decimal import Decimal

import pytest

from app.models import AuditEvent, IssuedLicense, LicenseKey, Order, OrderStatus, Payment, Subscription
from app.services.orders import create_order
from app.services.payments import (
    AmountMismatch,
    CurrencyMismatch,
    OrderAlreadyPaid,
    PassthroughMismatch,
    PaymentRefundedOrVoided,
    PaymentVerificationService,
)
from tests.fakes import ornek_odeme


@pytest.fixture
def siparis(db, musteri, plan_pro, fiyat_12_ay):
    return create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)


@pytest.fixture
def servis(db, fake_bvpay):
    return PaymentVerificationService(db, fake_bvpay)


def test_dogru_odeme_siparisi_ve_aboneligi_gunceller(db, siparis, fake_bvpay, servis, musteri, plan_pro):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(
            payment_id="pay_1",
            status="approved",
            amount=siparis.total,
            passthrough={"order_id": siparis.id},
        )
    )

    payment = servis.verify_and_process(order_id=siparis.id, payment_id="pay_1")

    db.refresh(siparis)
    assert siparis.status == OrderStatus.PAID
    assert payment.processed_at is not None

    sub = db.query(Subscription).filter_by(customer_id=musteri.id, plan_id=plan_pro.id).one()
    assert sub.current_period_end is not None

    lisans = db.query(LicenseKey).filter_by(subscription_id=sub.id).one()
    assert lisans.key_hash

    # KARAR (2026-10-06, EGE lider onayı): ödeme artık imzalı bir
    # IssuedLicense ÜRETMEZ — o belge fingerprint'siz olduğu için ege_lisans'ın
    # v2 çapa zorunluluğu yüzünden hiçbir kurulumda geçerli olamıyordu, yalnız
    # müşteriye kafa karıştırıcı bir ikinci "lisans" olarak görünüyordu (bkz.
    # app/services/licenses.py::get_or_create_license_key docstring'i).
    assert db.query(IssuedLicense).filter_by(subscription_id=sub.id).count() == 0


def test_odeme_sonrasi_abonelik_listesinde_lisans_ozeti_bos_aktivasyonda_tek_lisans_gorunur(
    db, siparis, fake_bvpay, servis, musteri, plan_pro, kullanici, client, auth_headers
):
    """`GET /api/v1/subscriptions`'daki `issued_licenses` özeti — ödeme
    sonrası BOŞ, gerçek bir çevrimdışı aktivasyon sonrası TAM OLARAK BİR
    kayıt taşımalı (bkz. app/routers/subscriptions.py::_abonelik_yanitina_cevir,
    `license_key.issued_licenses`'ı doğrudan yansıtıyor — koddan ayrı bir
    değişiklik gerekmedi, bu test o davranışı doğruluyor)."""
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_ozet", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    servis.verify_and_process(order_id=siparis.id, payment_id="pay_ozet")

    sub = db.query(Subscription).filter_by(customer_id=musteri.id, plan_id=plan_pro.id).one()

    yanit = client.get("/api/v1/subscriptions", headers=auth_headers)
    assert yanit.status_code == 200
    abonelik_yaniti = next(s for s in yanit.json() if s["id"] == sub.id)
    assert abonelik_yaniti["issued_licenses"] == []

    # Gerçek fingerprint'li tek bir IssuedLicense elle eklenip (çevrimdışı
    # aktivasyonun kendi davranışı app/services/test_offline_activation.py'de
    # ayrı test ediliyor, burada yalnız ÖZET uç noktasının var olan bir
    # IssuedLicense'ı DOĞRU yansıttığını doğruluyoruz) tekrar kontrol edilir.
    lisans_anahtari = db.query(LicenseKey).filter_by(subscription_id=sub.id).one()
    db.add(
        IssuedLicense(
            subscription_id=sub.id,
            license_key_id=lisans_anahtari.id,
            payload={"license_id": "lic_test123", "schema": 2},
            signature="deadbeef",
            issued_at=siparis.created_at,
            expires_at=sub.current_period_end,
        )
    )
    db.commit()

    yanit = client.get("/api/v1/subscriptions", headers=auth_headers)
    abonelik_yaniti = next(s for s in yanit.json() if s["id"] == sub.id)
    assert len(abonelik_yaniti["issued_licenses"]) == 1
    assert abonelik_yaniti["issued_licenses"][0]["license_id"] == "lic_test123"

def test_tutar_uyusmazligi_reddedilir(db, siparis, fake_bvpay, servis):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(
            payment_id="pay_yanlis_tutar",
            status="approved",
            amount=Decimal("1.00"),
            passthrough={"order_id": siparis.id},
        )
    )

    with pytest.raises(AmountMismatch):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_yanlis_tutar")

    db.refresh(siparis)
    assert siparis.status == OrderStatus.PENDING


def test_yanlis_para_birimi_reddedilir(db, siparis, fake_bvpay, servis):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(
            payment_id="pay_usd",
            status="approved",
            amount=siparis.total,
            currency="840",  # USD
            passthrough={"order_id": siparis.id},
        )
    )

    with pytest.raises(CurrencyMismatch):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_usd")

    db.refresh(siparis)
    assert siparis.status == OrderStatus.PENDING


def test_baskasinin_siparisi_reddedilir(db, musteri, plan_pro, fiyat_12_ay, fake_bvpay, servis):
    siparis_a = create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)
    siparis_b = create_order(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)

    # bvpay'den dönen ödeme aslında B siparişine ait (passthrough.order_id=B)
    # ama A siparişini doğrulamaya çalışıyoruz.
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(
            payment_id="pay_baskasi",
            status="approved",
            amount=siparis_a.total,
            passthrough={"order_id": siparis_b.id},
        )
    )

    with pytest.raises(PassthroughMismatch):
        servis.verify_and_process(order_id=siparis_a.id, payment_id="pay_baskasi")

    db.refresh(siparis_a)
    db.refresh(siparis_b)
    assert siparis_a.status == OrderStatus.PENDING
    assert siparis_b.status == OrderStatus.PENDING


def test_iade_veya_void_reddedilir(db, siparis, fake_bvpay, servis):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(
            payment_id="pay_iade",
            status="refunded",
            amount=siparis.total,
            passthrough={"order_id": siparis.id},
        )
    )

    with pytest.raises(PaymentRefundedOrVoided):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_iade")

    db.refresh(siparis)
    assert siparis.status == OrderStatus.PENDING


def test_voided_odeme_de_reddedilir(db, siparis, fake_bvpay, servis):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_void", status="voided", amount=siparis.total, passthrough={"order_id": siparis.id})
    )

    with pytest.raises(PaymentRefundedOrVoided):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_void")


def test_tekrarlanan_webhook_abonelik_bir_kez_uzatir(db, siparis, fake_bvpay, servis, musteri, plan_pro):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_idemp", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )

    servis.verify_and_process(order_id=siparis.id, payment_id="pay_idemp")
    sub = db.query(Subscription).filter_by(customer_id=musteri.id, plan_id=plan_pro.id).one()
    bitis_ilk = sub.current_period_end
    lisans_sayisi_ilk = db.query(LicenseKey).filter_by(subscription_id=sub.id).count()

    # Aynı webhook ikinci kez gelir (bvpay'in tekrar denemesi, ağ kesintisi vb.)
    servis.verify_and_process(order_id=siparis.id, payment_id="pay_idemp")

    db.refresh(sub)
    assert sub.current_period_end == bitis_ilk
    assert db.query(LicenseKey).filter_by(subscription_id=sub.id).count() == lisans_sayisi_ilk


def test_reddedilen_odeme_sonra_onaylanirsa_islenir(db, siparis, fake_bvpay, servis):
    """Aynı payment_id önce 'declined' olarak gelirse (henüz banka onayı yok)
    işlenmemeli; sonra 'approved' olursa (GET'in ikinci kez okunmasıyla)
    normal şekilde işlenmeli — ilk başarısız deneme idempotency'i BOZMAMALI."""
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_gecikmeli", status="declined", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    with pytest.raises(Exception):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_gecikmeli")

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_gecikmeli", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    payment = servis.verify_and_process(order_id=siparis.id, payment_id="pay_gecikmeli")

    db.refresh(siparis)
    assert siparis.status == OrderStatus.PAID
    assert payment.status.value == "approved"


# ─── Aynı siparişe ikinci ödeme (OrderAlreadyPaid) ──────────────────────────


def test_ayni_siparise_ikinci_odeme_abonelik_uzatmasin(db, siparis, fake_bvpay, servis, musteri, plan_pro):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_ilk", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    servis.verify_and_process(order_id=siparis.id, payment_id="pay_ilk")

    sub = db.query(Subscription).filter_by(customer_id=musteri.id, plan_id=plan_pro.id).one()
    bitis_ilk = sub.current_period_end
    lisans_sayisi_ilk = db.query(LicenseKey).filter_by(subscription_id=sub.id).count()

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_ikinci", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    with pytest.raises(OrderAlreadyPaid):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_ikinci")

    db.refresh(sub)
    assert sub.current_period_end == bitis_ilk  # 24 aya değil, hâlâ ilk ödemenin uzattığı kadar
    assert db.query(LicenseKey).filter_by(subscription_id=sub.id).count() == lisans_sayisi_ilk


def test_ayni_siparise_ikinci_odeme_yine_de_kaydedilir_iade_icin(db, siparis, fake_bvpay, servis):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_ilk_2", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    servis.verify_and_process(order_id=siparis.id, payment_id="pay_ilk_2")

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_ikinci_2", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    with pytest.raises(OrderAlreadyPaid):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_ikinci_2")

    yinelenen = db.query(Payment).filter_by(bvpay_payment_id="pay_ikinci_2").one()
    assert yinelenen.processed_at is None  # elle iade gerekiyor işareti

    olay = (
        db.query(AuditEvent)
        .filter_by(event_type="payment.duplicate_for_order", entity_id=str(siparis.id))
        .one()
    )
    assert olay.data["payment_id"] == "pay_ikinci_2"


def test_ayni_payment_id_ile_tekrar_denemek_tekrar_islemez(db, siparis, fake_bvpay, servis):
    """Yinelenen ödeme bir kez `OrderAlreadyPaid` olarak işaretlendikten
    sonra AYNI payment_id ile tekrar webhook gelirse (bvpay'in kendi
    tekrar denemesi) ikinci bir Payment satırı YARATILMAMALI (UNIQUE) ve
    tekrar bvpay'e sorulmamalı."""
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_ilk_3", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    servis.verify_and_process(order_id=siparis.id, payment_id="pay_ilk_3")

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_yinelenen_3", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    with pytest.raises(OrderAlreadyPaid):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_yinelenen_3")

    with pytest.raises(OrderAlreadyPaid):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_yinelenen_3")

    assert db.query(Payment).filter_by(bvpay_payment_id="pay_yinelenen_3").count() == 1


@pytest.mark.parametrize("durum", [OrderStatus.CANCELLED, OrderStatus.FAILED])
def test_iptal_veya_basarisiz_siparise_onayli_odeme_reddedilir(db, siparis, fake_bvpay, servis, durum):
    siparis.status = durum
    db.commit()

    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_gec_gelen", status="approved", amount=siparis.total, passthrough={"order_id": siparis.id})
    )

    with pytest.raises(OrderAlreadyPaid):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_gec_gelen")

    db.refresh(siparis)
    assert siparis.status == durum  # PAID'e çevrilmedi

    yinelenen = db.query(Payment).filter_by(bvpay_payment_id="pay_gec_gelen").one()
    assert yinelenen.processed_at is None


# ─── Başarısız doğrulamalar AuditEvent'e yazılır ────────────────────────────


@pytest.mark.parametrize(
    "durum, payment_id",
    [("declined", "pay_audit_declined"), ("refunded", "pay_audit_refunded"), ("voided", "pay_audit_voided")],
)
def test_reddedilen_odeme_audit_evente_yazilir(db, siparis, fake_bvpay, servis, durum, payment_id):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id=payment_id, status=durum, amount=siparis.total, passthrough={"order_id": siparis.id})
    )
    with pytest.raises(Exception):
        servis.verify_and_process(order_id=siparis.id, payment_id=payment_id)

    olay = (
        db.query(AuditEvent)
        .filter_by(event_type="payment.verification_failed", entity_id=str(siparis.id))
        .filter(AuditEvent.data["payment_id"].as_string() == payment_id)
        .first()
    )
    # SQLite JSON operatörü sürüme göre değişebilir — bulunamazsa Python
    # tarafında filtrele (taşınabilirlik için).
    if olay is None:
        olaylar = db.query(AuditEvent).filter_by(event_type="payment.verification_failed", entity_id=str(siparis.id)).all()
        olay = next(o for o in olaylar if o.data.get("payment_id") == payment_id)

    assert olay.data["error_type"]
    assert "raw" not in olay.data
    assert "card" not in olay.data


def test_tutar_uyusmazligi_da_audit_evente_yazilir(db, siparis, fake_bvpay, servis):
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_audit_tutar", status="approved", amount=Decimal("1.00"), passthrough={"order_id": siparis.id})
    )
    with pytest.raises(AmountMismatch):
        servis.verify_and_process(order_id=siparis.id, payment_id="pay_audit_tutar")

    olaylar = db.query(AuditEvent).filter_by(event_type="payment.verification_failed", entity_id=str(siparis.id)).all()
    assert any(o.data.get("payment_id") == "pay_audit_tutar" and o.data.get("error_type") == "AmountMismatch" for o in olaylar)
