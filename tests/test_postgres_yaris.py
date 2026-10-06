"""ege_portal ödeme doğrulaması — GERÇEK PostgreSQL'de eşzamanlılık (geçici konteyner).

1) Aynı payment_id iki thread'den → abonelik bir kez uzar, iki taraf da aynı Payment'ı döner.
2) Aynı siparişe İKİ FARKLI ödeme aynı anda → yalnız biri kabul edilir,
   diğeri OrderAlreadyPaid; abonelik bir kez uzar. (FOR UPDATE'in asıl işi —
   bkz. app/services/payments.py'deki `with_for_update()`.)
3) Aynı siparişi İKİ PERSONEL eşzamanlı "ödendi" işaretlerse (havale/EFT,
   2026-10-05 kullanıcı kararı) → yalnız biri kabul edilir, diğeri
   OrderAlreadyPaidError; abonelik bir kez uzar (bkz. app/services/
   manual_payments.py'deki AYNI `with_for_update()` deseni).

`PORTAL_PG_URL` tanımlı değilse bu dosyadaki testler ATLANIR — normal
`pytest` çalıştırması (SQLite, ağsız) buna dokunmaz. Koşmak için:

    docker run --rm -d --name portal-pg-yaris -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=portal_yaris -p 55432:5432 postgres:16
    PORTAL_PG_URL="postgresql://postgres:test@localhost:55432/portal_yaris" pytest tests/test_postgres_yaris.py -v
    docker rm -f portal-pg-yaris

Her test kendi `SessionLocal` fixture'ında şemayı DROP+CREATE ediyor —
konteyneri paylaşan başka bir işe DOKUNMAYIN, yalnız bunun için ayrılmış
geçici bir Postgres kullanın.
"""
import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, Customer, Payment, Plan, PlanItem, Price, Product, Subscription, User
from app.security import hash_password
from app.services.manual_payments import OrderAlreadyPaidError, mark_order_paid_manually
from app.services.orders import create_order
from app.services.payments import OrderAlreadyPaid, PaymentVerificationService
from tests.fakes import FakeBVPayClient, ornek_odeme

PG = os.environ.get("PORTAL_PG_URL", "")

pytestmark = pytest.mark.skipif(
    not PG, reason="PORTAL_PG_URL tanımlı değil — gerçek bir PostgreSQL gerektirir, bkz. modül docstring'i"
)


@pytest.fixture
def SessionLocal():
    engine = create_engine(PG)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _hazirla(SessionLocal):
    s = SessionLocal()
    m = Customer(name="Yarış", email="y@example.com"); s.add(m); s.flush()
    u = Product(code="mapege", name="mapEGE"); s.add(u); s.flush()
    p = Plan(code="pro", name="Pro"); s.add(p); s.flush()
    s.add(PlanItem(plan_id=p.id, product_id=u.id, tier="pro"))
    s.add(Price(plan_id=p.id, months=12, amount=Decimal("12000.00"), currency="949",
                vat_rate=Decimal("20.00"), valid_from=datetime.now(timezone.utc) - timedelta(days=1)))
    s.commit()
    o = create_order(s, customer_id=m.id, plan_id=p.id, months=12)
    s.commit()
    ids = (o.id, o.total)
    s.close()
    return ids


def _yaris(SessionLocal, bvpay, is_listesi):
    sonuc, hata = {}, {}
    kapi = threading.Barrier(len(is_listesi), timeout=10)

    def calis(ad, order_id, payment_id):
        db = SessionLocal()
        try:
            servis = PaymentVerificationService(db, bvpay)
            kapi.wait()
            sonuc[ad] = servis.verify_and_process(order_id=order_id, payment_id=payment_id).bvpay_payment_id
        except BaseException as e:  # noqa: BLE001
            hata[ad] = e
        finally:
            db.close()

    ts = [threading.Thread(target=calis, args=a) for a in is_listesi]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    return sonuc, hata


def _abonelik_ay(SessionLocal):
    s = SessionLocal()
    subs = s.scalars(select(Subscription)).all()
    s.close()
    assert len(subs) == 1
    gun = (subs[0].current_period_end - datetime.now(timezone.utc)).days
    return gun


@pytest.mark.parametrize("tekrar", range(5))
def test_ayni_payment_id_eszamanli(SessionLocal, tekrar):
    order_id, toplam = _hazirla(SessionLocal)
    bvpay = FakeBVPayClient()
    for _ in range(2):
        bvpay.kuyruga_ekle(ornek_odeme(payment_id="pay_x", status="approved", amount=toplam,
                                       passthrough={"order_id": order_id}))
    sonuc, hata = _yaris(SessionLocal, bvpay, [("a", order_id, "pay_x"), ("b", order_id, "pay_x")])
    assert not hata, hata
    assert sonuc == {"a": "pay_x", "b": "pay_x"}
    assert 360 <= _abonelik_ay(SessionLocal) <= 366   # bir kez 12 ay


@pytest.mark.parametrize("tekrar", range(5))
def test_ayni_siparise_iki_farkli_odeme_eszamanli(SessionLocal, tekrar):
    order_id, toplam = _hazirla(SessionLocal)
    bvpay = FakeBVPayClient()
    for pid in ("pay_a", "pay_b"):
        bvpay.kuyruga_ekle(ornek_odeme(payment_id=pid, status="approved", amount=toplam,
                                       passthrough={"order_id": order_id}))
    sonuc, hata = _yaris(SessionLocal, bvpay, [("a", order_id, "pay_a"), ("b", order_id, "pay_b")])
    assert len(sonuc) == 1, (sonuc, hata)
    assert len(hata) == 1 and isinstance(next(iter(hata.values())), OrderAlreadyPaid), hata
    assert 360 <= _abonelik_ay(SessionLocal) <= 366   # 24 ay DEĞİL
    s = SessionLocal()
    iade_bekleyen = s.scalar(select(func.count()).select_from(Payment).where(Payment.processed_at.is_(None)))
    s.close()
    assert iade_bekleyen == 1


def _hazirla_personel(SessionLocal) -> int:
    """Siparişin müşterisinden FARKLI bir müşteriye bağlı personel —
    görevler ayrılığı kontrolü bu testin konusu DEĞİL (bkz.
    tests/test_admin_mark_paid.py'deki ayrı test)."""
    s = SessionLocal()
    personel_musterisi = Customer(name="EGE Üretici", email="personel@example.com")
    s.add(personel_musterisi)
    s.flush()
    personel = User(
        customer_id=personel_musterisi.id,
        email="personel-yaris@example.com",
        password_hash=hash_password("parola123456"),
        is_staff=True,
    )
    s.add(personel)
    s.commit()
    personel_id = personel.id
    s.close()
    return personel_id


def _yaris_mark_paid(SessionLocal, personel_id, is_listesi):
    sonuc, hata = {}, {}
    kapi = threading.Barrier(len(is_listesi), timeout=10)

    def calis(ad, order_id, toplam, referans):
        db = SessionLocal()
        try:
            personel = db.get(User, personel_id)
            kapi.wait()
            odeme = mark_order_paid_manually(
                db,
                order_id=order_id,
                staff_user=personel,
                amount=toplam,
                bank_reference=referans,
                received_at=datetime.now(timezone.utc),
                note=None,
            )
            sonuc[ad] = odeme.bank_reference
        except BaseException as e:  # noqa: BLE001
            hata[ad] = e
        finally:
            db.close()

    ts = [threading.Thread(target=calis, args=a) for a in is_listesi]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    return sonuc, hata


@pytest.mark.parametrize("tekrar", range(5))
def test_ayni_siparisi_iki_personel_eszamanli_isaretler(SessionLocal, tekrar):
    order_id, toplam = _hazirla(SessionLocal)
    personel_id = _hazirla_personel(SessionLocal)

    sonuc, hata = _yaris_mark_paid(
        SessionLocal, personel_id, [("a", order_id, toplam, "REF-A"), ("b", order_id, toplam, "REF-B")]
    )

    assert len(sonuc) == 1, (sonuc, hata)
    assert len(hata) == 1 and isinstance(next(iter(hata.values())), OrderAlreadyPaidError), hata
    assert 360 <= _abonelik_ay(SessionLocal) <= 366  # 24 ay DEĞİL, bir kez uzadı
