"""
Eşzamanlı doğrulama (webhook + mutabakat görevi aynı anda gelirse) — gerçek
bir IntegrityError senaryosu, GERÇEK thread'lerle.

`tests/conftest.py`'deki `db` fixture'ı bellek-içi SQLite kullanıyor;
`:memory:` birden çok bağımsız bağlantıyı desteklemediği için bu dosya kendi
dosya-tabanlı SQLite'ını kurar ve iki gerçek OS thread'iyle aynı payment_id
için `verify_and_process`'i GERÇEKTEN eşzamanlı çağırır — SQLite'ın kendi
dosya kilidi (busy_timeout ile) ikinci yazan tarafı ilkinin commit'ine kadar
bekletir, sonra `Payment.bvpay_payment_id` UNIQUE kısıtına çarpar. Bu,
`PaymentVerificationService.verify_and_process`'in commit sırasında
yakaladığı gerçek `IntegrityError`'dır (fabrikasyon/mock değil).

Subscription/LicenseKey race'lerinin ayrıştırılabilmesi için (bu testin
odağı olan Payment-satırı çakışmasından bağımsız kalsınlar diye) müşterinin
bu plan için zaten aktif bir aboneliği/lisansı varmış gibi ÖNCEDEN kuruluyor
— test edilen sipariş bir YENİLEME siparişi.
"""
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Customer, Payment, Plan, PlanItem, Price, Product, Subscription
from app.services.licenses import get_or_create_license_key
from app.services.orders import create_order
from app.services.payments import PaymentVerificationService
from app.services.subscriptions import extend_subscription
from tests.fakes import FakeBVPayClient, ornek_odeme


def _kur(tmp_path):
    db_path = tmp_path / "concurrency_test.db"
    # timeout: SQLite busy_timeout (saniye) — ikinci thread ilkinin
    # commit'ini bekleyebilsin diye; check_same_thread=False, bağlantılar
    # ayrı thread'lerden kullanılacak (her thread kendi Session'ını açıyor).
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_eszamanli_iki_dogrulama_kaybeden_integrity_error_yakalayip_idempotent_doner(tmp_path):
    SessionLocal = _kur(tmp_path)

    kurulum = SessionLocal()
    try:
        musteri = Customer(name="Yarış Test A.Ş.", email="yaris@example.com")
        kurulum.add(musteri)
        kurulum.flush()

        urun = Product(code="mapege", name="mapEGE")
        kurulum.add(urun)
        kurulum.flush()

        plan = Plan(code="mapege-pro-yaris", name="mapEGE Pro")
        kurulum.add(plan)
        kurulum.flush()
        kurulum.add(PlanItem(plan_id=plan.id, product_id=urun.id, tier="full"))

        kurulum.add(
            Price(
                plan_id=plan.id, months=12, amount=Decimal("12000.00"), currency="949",
                vat_rate=Decimal("20.00"), valid_from=datetime.now(timezone.utc) - timedelta(days=1), valid_until=None,
            )
        )
        kurulum.commit()

        # Müşterinin bu plan için ZATEN aktif bir aboneliği/lisansı var
        # (bkz. modül docstring'i — bu, testin odağını Payment-satırı
        # çakışmasına daraltıyor).
        sub = extend_subscription(kurulum, customer_id=musteri.id, plan_id=plan.id, months=12)
        get_or_create_license_key(kurulum, sub)
        kurulum.commit()

        siparis = create_order(kurulum, customer_id=musteri.id, plan_id=plan.id, months=12)
        siparis_id = siparis.id
        toplam = siparis.total
        musteri_id = musteri.id
        plan_id = plan.id
        onceki_bitis = sub.current_period_end
    finally:
        kurulum.close()

    fake_bvpay = FakeBVPayClient()
    fake_bvpay.kuyruga_ekle(
        ornek_odeme(payment_id="pay_yaris", status="approved", amount=toplam, passthrough={"order_id": siparis_id})
    )
    sonuclar: dict[str, object] = {}
    hatalar: dict[str, BaseException] = {}
    baslama_kapisi = threading.Barrier(2, timeout=10)

    def calistir(ad: str) -> None:
        db = SessionLocal()
        try:
            servis = PaymentVerificationService(db, fake_bvpay)
            baslama_kapisi.wait()  # iki thread'i olabildiğince aynı anda başlat
            sonuclar[ad] = servis.verify_and_process(order_id=siparis_id, payment_id="pay_yaris")
        except BaseException as e:  # noqa: BLE001 — testte her hatayı yakalayıp raporluyoruz
            hatalar[ad] = e
        finally:
            db.close()

    t1 = threading.Thread(target=calistir, args=("t1",))
    t2 = threading.Thread(target=calistir, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not hatalar, f"beklenmedik hata(lar): {hatalar}"
    assert set(sonuclar) == {"t1", "t2"}
    assert sonuclar["t1"].bvpay_payment_id == "pay_yaris"
    assert sonuclar["t2"].bvpay_payment_id == "pay_yaris"
    assert sonuclar["t1"].processed_at is not None
    assert sonuclar["t2"].processed_at is not None
    # İkisi de AYNI satırı görmüş olmalı — kaybeden kendi satırını değil,
    # kazananınkini döndürür (idempotent).
    assert sonuclar["t1"].id == sonuclar["t2"].id

    dogrulama = SessionLocal()
    try:
        # bvpay_payment_id UNIQUE — iki satır YOK, tek satır var.
        assert dogrulama.query(Payment).filter_by(bvpay_payment_id="pay_yaris").count() == 1

        sub_son = dogrulama.query(Subscription).filter_by(customer_id=musteri_id, plan_id=plan_id).one()
        # Abonelik yalnız BİR kez (12 ay) uzadı — 24 aya değil.
        assert sub_son.current_period_end > onceki_bitis + timedelta(days=330)
        assert sub_son.current_period_end < onceki_bitis + timedelta(days=395)
    finally:
        dogrulama.close()
