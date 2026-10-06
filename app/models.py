"""
EGE Lisans Portalı — veri modeli (bkz. PLAN.md §4).

Şemanın tek kaynağı `alembic/versions/`dir — burada `Base.metadata.create_all()`
çağrılmaz (bkz. app/db.py, colEGE README'deki aynı kural).
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """`DateTime(timezone=True)` bazı backend'lerde (özellikle SQLite —
    README'de belirtilen geliştirme veritabanı) round-trip'te tzinfo'yu
    KAYBEDER: bir tz-aware datetime yazılır ama okurken NAIVE döner. Bu,
    `datetime.now(timezone.utc)` ile Python-seviyesinde karşılaştıran her
    kod için (ör. app/services/subscriptions.py::extend_subscription'daki
    `max(now, sub.current_period_end)`) sessiz bir `TypeError` riskidir —
    taze bir session'da (her gerçek istek gibi) var olan bir aboneliği
    okuyup uzatmaya çalışan İKİNCİ ödeme bunu tetikler. Okurken tzinfo
    eksikse UTC varsayarak düzeltiyoruz (biz zaten her yerde UTC yazıyoruz,
    bkz. `_utcnow`); PostgreSQL'de zaten tz-aware döndüğü için bu no-op'tur.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


# ─── Durum enum'ları ─────────────────────────────────────────────────────────
# native_enum=False: Postgres'te ayrı bir ENUM tipi yerine VARCHAR + CHECK
# üretir — SQLite ile aynı davranış, Alembic migration'ları basitleşir (yeni
# bir durum eklemek ENUM ALTER gerektirmez).

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    PENDING_3D = "pending_3d"
    APPROVED = "approved"
    DECLINED = "declined"
    ERROR = "error"
    CAPTURED = "captured"
    VOIDED = "voided"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    BVPAY = "bvpay"
    BANK_TRANSFER = "bank_transfer"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ActivationMode(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class PackageType(str, enum.Enum):
    DOCKER_LINUX = "docker-linux"
    DOCKER_WINDOWS = "docker-windows"
    NATIVE_WINDOWS = "native-windows"


def _status_col(enum_cls, *, default):
    return mapped_column(SAEnum(enum_cls, native_enum=False, length=20), default=default, nullable=False)


# ─── Hesap / kurum ───────────────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    tax_no: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    # Müşteri bazında deneme süresi override'ı (gün) — PLAN.md §8 madde 7,
    # bkz. app/services/trial.py::resolve_trial_days. None = override yok,
    # genel ayar/kampanya geçerli.
    trial_days_override: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="customer")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # `role` (owner/admin/member): müşteri KURUMU İÇİNDEKİ rol — bir müşterinin
    # kendi ekibini yönetmesi için. Üretici (EGE) personel yetkisiyle KARIŞTIRMA:
    # bir müşterinin admin'i kendi kurumunu yönetir, üretici platform genelini
    # (deneme ayarları, başka müşterilere grant/override) yönetir — bkz.
    # `is_staff` ve app/routers/auth.py::require_staff. İlk taslakta bu ikisi
    # yanlışlıkla aynı alana (role==ADMIN) bağlanmıştı — EGE lider'in
    # incelemesinde yakalandı: bir müşteri kendi ekibine "admin" rolü verirse
    # (ki bunu yapabilmesi gerekir) o kullanıcı YANLIŞLIKLA tüm platformun
    # deneme ayarlarına erişebiliyordu.
    role: Mapped[UserRole] = _status_col(UserRole, default=UserRole.MEMBER)
    # Üretici (EGE) personeli mi? Müşteri rolünden TAMAMEN BAĞIMSIZ — yalnız
    # scripts/personel_olustur.py ile set edilir, self-servis hiçbir uçtan
    # DEĞİL (bkz. o script ve require_staff).
    is_staff: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)

    customer: Mapped[Customer] = relationship(back_populates="users")


# ─── Katalog ─────────────────────────────────────────────────────────────────

class Product(Base):
    """mapege / sisege / colege."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))


class Release(Base):
    """İndirilebilir bir sürüm paketi (PLAN.md §5.4/F5). Dosyanın kendisi
    veritabanında DEĞİL — `storage_key`, `PORTAL_RELEASE_DIR` (bkz.
    app/config.py) ALTINDA göreli bir yoldur ve yalnızca
    `app/services/releases.py::resolve_release_path` ÜZERİNDEN (path
    traversal + sembolik bağ reddi) çözümlenir; hiçbir yerde doğrudan
    birleştirilmez. Bu turda yükleme YALNIZ `scripts/surum_yayinla.py`
    CLI'sıyla yapılır — API'den dosya yükleme yok (bkz. o betiğin docstring'i)."""

    __tablename__ = "releases"
    __table_args__ = (
        UniqueConstraint("product_id", "version", "package_type", name="uq_releases_product_version_package_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    version: Mapped[str] = mapped_column(String(30))
    package_type: Mapped[PackageType] = _status_col(PackageType, default=PackageType.DOCKER_LINUX)
    os: Mapped[str] = mapped_column(String(30))
    arch: Mapped[str] = mapped_column(String(30))
    file_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger())
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500))
    # İmzasız (signed=False) sürümler müşteriye ASLA listelenmez/indirilmez —
    # yalnız personel (is_staff), bkz. app/services/releases.py.
    signed: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    # Yayından kaldırılmış (yanlışlıkla yüklenmiş, geri çekilmiş) bir sürümü
    # SİLMEDEN gizlemek için — geçmiş AuditEvent/indirme kayıtlarının FK'si
    # kopmasın diye satır hep kalır.
    is_active: Mapped[bool] = mapped_column(default=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    # Yayınlayan personel (`scripts/surum_yayinla.py --personel`). Bu alandan
    # önce yayınlanmış satırlarda boş kalır.
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    product: Mapped[Product] = relationship()


class Plan(Base):
    """Tek ürün+kademe ya da paket (birden çok ürün+kademe) tanımı."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)

    items: Mapped[list["PlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    prices: Mapped[list["Price"]] = relationship(back_populates="plan")


class PlanItem(Base):
    """Bir Plan'ın taşıdığı ürün+kademe satırlarından biri."""

    __tablename__ = "plan_items"
    __table_args__ = (UniqueConstraint("plan_id", "product_id", name="uq_plan_items_plan_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    tier: Mapped[str] = mapped_column(String(30))

    plan: Mapped[Plan] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Price(Base):
    """plan × ay → tutar. Geçerlilik aralığı `valid_from`/`valid_until`."""

    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    months: Mapped[int] = mapped_column()
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="949")
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime)

    plan: Mapped[Plan] = relationship(back_populates="prices")


# ─── Sipariş / ödeme ─────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    months: Mapped[int] = mapped_column()
    # KARAR (2026-10-05, kullanıcı): lisans birimi MAKİNE — bir sipariş
    # birden çok makine/koltuk satın alabilir. `net`/`vat_amount`/`total`
    # BİRİM fiyatın `quantity` İLE ÇARPILMASINDAN SONRAKİ (toplam) tutarlardır
    # (bkz. app/services/orders.py::create_order) — KDV kırılımı adet
    # sonrası uygulanır, `app/services/pricing.py::kdv_hesapla` TEK yerde
    # kalır (önce-adet-sonra-KDV ile sonra-adet-önce-KDV matematiksel
    # olarak AYNI sonucu verir, ama "tek fonksiyon tek sorumluluk" için
    # kdv_hesapla HER ZAMAN nihai net tutara uygulanır). Yeni bir Subscription
    # açılırken `Subscription.seats = quantity` olur (bkz. extend_subscription)
    # — UZATMA (aynı aboneliğe yeni sipariş) seats'i DEĞİŞTİRMEZ, adet
    # artırımı bu turda ayrı bir sipariş tipi değil.
    quantity: Mapped[int] = mapped_column(default=1)

    # Fiyat, sipariş anındaki Price'tan buraya KOPYALANIR (snapshot) — Price
    # ileride değişse/silinse bile bu siparişin tutarı sabit kalır.
    #
    # KARAR (2026-09-28, müşteri testinde bulundu — bkz. PLAN.md §8 madde 1):
    # `Price.amount` (ve dolayısıyla `net`) KDV HARİÇ tutardır. İlk taslakta
    # `total` doğrudan `Price.amount`'a eşitti — KDV hiç EKLENMİYORDU (ör.
    # vat_rate=20 iken total=12000, OLMASI GEREKEN 14400 değil). `net` artık
    # KDV hariç tutarı, `vat_amount` ondan hesaplanan KDV tutarını,
    # `total = net + vat_amount` KDV DAHİL nihai tutarı taşıyor — bvpay'e
    # giden ve `app/services/payments.py`'de karşılaştırılan tutar HÂLÂ
    # `total` (davranış değişmedi, yalnız artık doğru hesaplanıyor).
    net: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    status: Mapped[OrderStatus] = _status_col(OrderStatus, default=OrderStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow, onupdate=_utcnow)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    plan: Mapped[Plan] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    # Yalnız payment_method=bvpay için dolu — havale/EFT (elle işaretlenen)
    # ödemelerde bvpay hiç devreye girmediği için NULL (bkz. bank_reference,
    # onun tekil-anahtarı). İkisi birden NULL/boş OLAMAZ — bu app/services/
    # manual_payments.py ve payments.py'de UYGULAMA seviyesinde zorlanır
    # (DB CHECK kısıtı YOK, projedeki diğer durum alanlarıyla aynı tercih).
    bvpay_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[PaymentStatus] = _status_col(PaymentStatus, default=PaymentStatus.PENDING_3D)
    payment_method: Mapped[PaymentMethod] = _status_col(PaymentMethod, default=PaymentMethod.BVPAY)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    # processed_at DOLU olması "bu payment_id işlendi" idempotency imzasıdır.
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # ─── Havale/EFT (elle işaretleme) — yalnız payment_method=bank_transfer ───
    # Banka dekontu/işlem no'su — SİSTEM GENELİNDE TEKİL (aynı dekont iki
    # siparişe kullanılamaz, bkz. app/services/manual_payments.py).
    bank_reference: Mapped[str | None] = mapped_column(String(100), unique=True)
    marked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    # Paranın banka hesabına GERÇEKTEN geçtiği an (personelin dekonttan
    # okuduğu tarih) — `created_at`/`processed_at`den AYRI: onlar "bu kayıt
    # ne zaman sisteme girildi" bilgisini taşır, `received_at` bankanın
    # kendi tarihidir ve gelecekte OLAMAZ (bkz. manual_payments.py).
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    order: Mapped[Order] = relationship(back_populates="payments")
    marked_by: Mapped["User | None"] = relationship()


# ─── Abonelik / lisans ───────────────────────────────────────────────────────

class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("customer_id", "plan_id", name="uq_subscriptions_customer_plan"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    current_period_end: Mapped[datetime] = mapped_column(UTCDateTime)
    # KARAR (2026-10-05, kullanıcı — PLAN.md §8 madde 3 ARTIK KAPALI):
    # lisans birimi MAKİNE. Abonelik başına (PAKETTEKİ HER ÜRÜN İÇİN AYRI
    # AYRI — bkz. app/services/offline_activation.py'deki gerekçe, paket
    # satışında ürünler farklı makinelerde olabilir) en çok bu kadar AKTİF
    # (revoked_at IS NULL) `Activation` olabilir; ZORLANIR (bkz. aynı
    # dosyadaki `_aktif_aktivasyon_sayisi`). Yeni bir Subscription açılırken
    # `Order.quantity`'den set edilir (bkz. extend_subscription); sonraki
    # bir UZATMA (aynı aboneliğe yeni sipariş) bu alanı DEĞİŞTİRMEZ.
    seats: Mapped[int] = mapped_column(default=1)
    status: Mapped[SubscriptionStatus] = _status_col(SubscriptionStatus, default=SubscriptionStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow, onupdate=_utcnow)

    customer: Mapped[Customer] = relationship(back_populates="subscriptions")
    plan: Mapped[Plan] = relationship()
    license_keys: Mapped[list["LicenseKey"]] = relationship(back_populates="subscription")


class LicenseKey(Base):
    """İnsan-okur anahtar yalnız HASH olarak saklanır; düz metin hiçbir yerde tutulmaz."""

    __tablename__ = "license_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Kullanıcıya panelde göstermek için ilk birkaç karakter (ör. "EGE-A1B2").
    key_prefix: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    subscription: Mapped[Subscription] = relationship(back_populates="license_keys")
    activations: Mapped[list["Activation"]] = relationship(back_populates="license_key")
    issued_licenses: Mapped[list["IssuedLicense"]] = relationship(back_populates="license_key")


class Activation(Base):
    """Çevrimdışı aktivasyonlarda `POST /api/v1/subscriptions/{id}/offline-activation`
    ile yazılır (bkz. app/services/offline_activation.py). Çevrimiçi
    aktivasyon (F4 — anahtar girişi + günlük yenileme ucu) henüz yok."""

    __tablename__ = "activations"

    id: Mapped[int] = mapped_column(primary_key=True)
    license_key_id: Mapped[int] = mapped_column(ForeignKey("license_keys.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    fingerprint: Mapped[str] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(String(30))
    mode: Mapped[ActivationMode] = _status_col(ActivationMode, default=ActivationMode.ONLINE)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    license_key: Mapped[LicenseKey] = relationship(back_populates="activations")
    product: Mapped[Product] = relationship()


class IssuedLicense(Base):
    """İmzalı lisans belgesi kaydı (bkz. PLAN.md §3 — şema v2 payload'ı)."""

    __tablename__ = "issued_licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"))
    license_key_id: Mapped[int] = mapped_column(ForeignKey("license_keys.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)

    subscription: Mapped[Subscription] = relationship()
    license_key: Mapped[LicenseKey] = relationship(back_populates="issued_licenses")


# ─── Deneme (trial) lisansı — PLAN.md §8 madde 7 ────────────────────────────
# Abonelik/Subscription'a bilerek BAĞLI DEĞİL: deneme, satın alma öncesi
# verilir. LicenseKey/Activation/IssuedLicense (yukarıdaki) her zaman bir
# Subscription gerektirdiği için (NOT NULL FK) buraya taşınamazlar —
# paralel, daha basit bir çift tablo (bkz. app/services/trial.py).

class TrialSettings(Base):
    """Tekil satır (id=1) — genel varsayılan deneme süresi. DB'de tutulur
    (env'DE DEĞİL) çünkü üretici çalışma zamanında değiştirebilmeli."""

    __tablename__ = "trial_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_days: Mapped[int] = mapped_column(default=7)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class TrialCampaign(Base):
    """Tarih aralıklı genel deneme süresi override'ı (kampanya). Birden
    çok kampanya aynı anda geçerliyse EN SON OLUŞTURULAN kazanır (bkz.
    app/services/trial.py::find_active_campaign) — basit ve öngörülebilir
    bir kural; kampanyaların kesişmemesi operasyonel bir beklenti,
    veritabanı seviyesinde zorlanmıyor."""

    __tablename__ = "trial_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    days: Mapped[int] = mapped_column()
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class TrialGrant(Base):
    """Üreticinin (yönetici) bir müşteriye elle verdiği ek deneme süresi.
    `consumed_at` dolana kadar hem gün hesabına EKLENİR hem de aynı
    müşteri+ürün için ikinci deneme yasağını (yalnız BU müşteri için —
    çapraz müşteri instance_id kontrolünü DEĞİL, bkz.
    app/services/trial.py) BİR KEZ atlatır; kullanılınca tüketilir."""

    __tablename__ = "trial_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    extra_days: Mapped[int] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text)
    granted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    customer: Mapped[Customer] = relationship()


class TrialLicense(Base):
    """İmzalı deneme lisansı belgesi (v2, `license_type: "trial"`)."""

    __tablename__ = "trial_licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)

    customer: Mapped[Customer] = relationship()
    activations: Mapped[list["TrialActivation"]] = relationship(back_populates="trial_license")


class TrialActivation(Base):
    """Bir deneme lisansının tek bir ürün için aktivasyon kaydı — abonelik
    tarafındaki `Activation`'ın deneme karşılığı, ayrı tabloda (bkz. bu
    bölümün başındaki not)."""

    __tablename__ = "trial_activations"

    id: Mapped[int] = mapped_column(primary_key=True)
    trial_license_id: Mapped[int] = mapped_column(ForeignKey("trial_licenses.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    # Tam bileşen kümesi `fingerprint`'te (Activation ile tutarlı); ayrıca
    # `instance_id_hash` burada tek başına da tutuluyor — dup/çarpraz-müşteri
    # sorguları component JSON'ını her satırda ayrıştırmak zorunda kalmasın.
    instance_id_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    trial_license: Mapped[TrialLicense] = relationship(back_populates="activations")
    product: Mapped[Product] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(60))
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)


class LoginAttempt(Base):
    """Giriş/kayıt denemesi — brute-force hız sınırlaması için (PLAN.md §6,
    2026-10-05 canlıya hazırlık görevi). Redis YOK (tek bir portal süreci
    varsayımı) — DB tablosu hem tek hem ÇOK süreçli dağıtımda doğru
    çalışır (`COUNT(*) WHERE created_at > eşik` tüm süreçler arasında
    PAYLAŞILAN tek bir gerçeğe, veritabanına, bakar — bir süreç-içi
    bellek sözlüğü ÇOK süreçli bir dağıtımda yanlış sonuç verirdi, her
    worker kendi sayacını tutardı). Satırlar bilerek SİLİNMEZ/budanmaz
    bu turda — hacim düşükse (giriş denemesi) sorun değil; büyürse ayrı
    bir temizlik görevi eklenebilir.
    `email`/`ip_address` ayrı ayrı sorgulanır (bkz. app/services/
    auth_throttle.py) — biri aşılınca DİĞERİ etkilenmeden tek başına
    reddeder (ör. aynı IP'den çok sayıda FARKLI e-posta denenmesi de,
    aynı e-postanın çok sayıda IP'den denenmesi de yakalanır)."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        # `app/services/auth_throttle.py`'nin her istekte çalıştırdığı AYNI
        # sorguların ikisi — e-posta başına ve IP başına kayan pencere sayımı.
        Index("ix_login_attempts_kind_email_created", "kind", "email", "created_at"),
        Index("ix_login_attempts_kind_ip_created", "kind", "ip_address", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    ip_address: Mapped[str] = mapped_column(String(45))  # IPv6 azami uzunluk
    kind: Mapped[str] = mapped_column(String(20))  # "login" | "register"
    success: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
