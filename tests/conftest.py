"""
Testler için ortak ayarlar (bkz. colEGE tests/conftest.py — aynı gerekçe):
proje modülleri import edilmeden ÖNCE sahte ortam değişkenleri enjekte
edilir, böylece testler gerçek `.env`'e ya da PostgreSQL'e bağımlı olmaz.
"""
import os

os.environ["SECRET_KEY"] = "pytest-fixture-secret-not-a-real-secret"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173"
os.environ["BVPAY_URL"] = "http://bvpay.invalid"
os.environ["BVPAY_API_KEY"] = "pytest-fixture-not-real"

from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import get_db  # noqa: E402
from app.deps import get_bvpay_client, get_imzalayici  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Customer, Plan, PlanItem, Price, Product, User, UserRole  # noqa: E402
from app.routers.auth import issue_session_token  # noqa: E402
from app.security import hash_password  # noqa: E402
from tests.fakes import FakeBVPayClient, FakeImzalayici  # noqa: E402


@pytest.fixture
def db() -> Session:
    """Her testin kendi izole, bellek içi SQLite'ı — `alembic upgrade head`
    yerine `create_all()` (yalnız test fixture'ı, bkz. app/db.py notu)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def fake_bvpay() -> FakeBVPayClient:
    return FakeBVPayClient()


@pytest.fixture
def fake_imzalayici() -> FakeImzalayici:
    return FakeImzalayici()


@pytest.fixture
def client(db: Session, fake_bvpay: FakeBVPayClient, fake_imzalayici: FakeImzalayici) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_bvpay_client] = lambda: fake_bvpay
    app.dependency_overrides[get_imzalayici] = lambda: fake_imzalayici
    try:
        # `OriginDogrulamaMiddleware` (bkz. app/middleware.py, CSRF savunması)
        # durum değiştiren HER istekte izinli bir Origin ister — gerçek bir
        # tarayıcı bunu otomatik gönderir, burada testlerin VARSAYILANI bu
        # (ALLOWED_ORIGINS ile AYNI, yukarıda ayarlandı). Middleware'in
        # KENDİSİNİ (reddetme davranışını) test eden dosyalar bu header'ı
        # elle override eder/kaldırır (bkz. tests/test_csrf.py).
        yield TestClient(app, headers={"Origin": "http://localhost:5173"})
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client_raw(db: Session, fake_bvpay: FakeBVPayClient, fake_imzalayici: FakeImzalayici) -> TestClient:
    """`client`'ın Origin header'SIZ hâli — yalnız CSRF/Origin doğrulama
    middleware'ini test eden dosyalar için (bkz. tests/test_csrf.py); diğer
    tüm testler `client`'ı kullanmalı (gerçek bir tarayıcı Origin'i her
    zaman gönderir)."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_bvpay_client] = lambda: fake_bvpay
    app.dependency_overrides[get_imzalayici] = lambda: fake_imzalayici
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def musteri(db: Session) -> Customer:
    customer = Customer(name="Test Belediyesi", email="test@example.com")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@pytest.fixture
def urun_mapege(db: Session) -> Product:
    product = Product(code="mapege", name="mapEGE")
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@pytest.fixture
def plan_pro(db: Session, urun_mapege: Product) -> Plan:
    plan = Plan(code="mapege-pro", name="mapEGE Pro")
    db.add(plan)
    db.flush()
    db.add(PlanItem(plan_id=plan.id, product_id=urun_mapege.id, tier="pro"))
    db.commit()
    db.refresh(plan)
    return plan


@pytest.fixture
def kullanici(db: Session, musteri: Customer) -> User:
    user = User(customer_id=musteri.id, email="siparis@example.com", password_hash=hash_password("test-parola-123"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_headers(kullanici: User) -> dict:
    token = issue_session_token(kullanici.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def yonetici(db: Session) -> User:
    """Üretici (EGE) PERSONELİ — `is_staff=True`. Müşteri kurumu içi
    `role`'den (bkz. `musteri_ici_yonetici`) tamamen bağımsız; role burada
    bilerek varsayılan (`MEMBER`) bırakıldı, ikisinin karışmadığını
    göstermek için."""
    yonetici_musteri = Customer(name="EGE Üretici", email="admin@example.com")
    db.add(yonetici_musteri)
    db.flush()
    user = User(
        customer_id=yonetici_musteri.id,
        email="admin-user@example.com",
        password_hash=hash_password("admin-parola-123"),
        is_staff=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_headers(yonetici: User) -> dict:
    token = issue_session_token(yonetici.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def musteri_ici_yonetici(db: Session, musteri: Customer) -> User:
    """Müşteri KURUMU İÇİNDE `role=ADMIN` ama `is_staff=False` — üretici
    yetkisi OLMAMALI (bkz. app/routers/auth.py::require_staff docstring'i,
    "rol karışıklığı" düzeltmesi)."""
    user = User(
        customer_id=musteri.id,
        email="musteri-admin@example.com",
        password_hash=hash_password("musteri-admin-parola"),
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def musteri_ici_yonetici_headers(musteri_ici_yonetici: User) -> dict:
    token = issue_session_token(musteri_ici_yonetici.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fiyat_12_ay(db: Session, plan_pro: Plan) -> Price:
    price = Price(
        plan_id=plan_pro.id,
        months=12,
        amount=Decimal("12000.00"),
        currency="949",
        vat_rate=Decimal("20.00"),
        valid_from=datetime.now(timezone.utc) - timedelta(days=1),
        valid_until=None,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return price
