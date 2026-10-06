from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderCreateRequest(BaseModel):
    plan_id: int
    months: int
    # Lisans birimi MAKİNE (karar 2026-10-05) — kaç makine/koltuk.
    # Üst sınır keyfî değil, uydurma siparişlere karşı makul bir tavan
    # (bkz. app/services/orders.py::MAX_QUANTITY, tek yerde tanımlı).
    quantity: int = Field(default=1, ge=1, le=100)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    plan_id: int
    months: int
    quantity: int
    net: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total: Decimal  # KDV DAHİL — bvpay'e giden ve orada karşılaştırılan tutar (bkz. Order.net docstring)
    currency: str
    status: str
    created_at: datetime


class BVPayWebhookPayload(BaseModel):
    """`payment.result` webhook gövdesi — İMZASIZ, yalnız tetikleyici olarak
    kullanılır. `order_id`/`passthrough` burada bilgi amaçlıdır; asıl
    doğrulama her zaman ayrı bir GET isteğiyle yapılır."""

    model_config = ConfigDict(extra="allow")

    payment_id: str
    order_id: int | None = None
    passthrough: dict | None = None


class DeactivateReleaseRequest(BaseModel):
    # Yayından kaldırma müşterinin göreceği listeyi değiştirir — gerekçe
    # AuditEvent'e yazılır (bkz. app/routers/admin.py::surumu_yayindan_kaldir).
    reason: str = Field(min_length=1)


class RevokeActivationRequest(BaseModel):
    # Koltuk serbest bırakmak ciddi bir eylem (müşteri yeni makinede
    # aktivasyon yapabilir hâle gelir) — gerekçe ZORUNLU (bkz. app/routers/
    # admin.py::aktivasyonu_iptal_et, 2026-10-05 "lisans birimi makine" kararı).
    reason: str = Field(min_length=1)


# ─── Yönetici — bekleyen siparişler / havale-EFT elle işaretleme ────────────
# Kullanıcı kararı (2026-10-05): bvpay entegrasyonu beklenirken havale/EFT
# siparişleri personel ELLE "ödendi" işaretler. Bkz. app/services/
# manual_payments.py.


class AdminOrderResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    plan_id: int
    plan_name: str
    months: int
    net: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total: Decimal
    currency: str
    status: str
    created_at: datetime


class MarkOrderPaidRequest(BaseModel):
    amount: Decimal
    bank_reference: str
    received_at: datetime
    note: str | None = None


class MarkOrderPaidResponse(BaseModel):
    payment_id: int
    order_id: int
    order_status: str
    amount: Decimal
    bank_reference: str
    received_at: datetime
    marked_by_user_id: int


# ─── Deneme (trial) — yönetici uçları ────────────────────────────────────────


class TrialSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_days: int
    updated_at: datetime
    updated_by_user_id: int | None


class TrialSettingsUpdateRequest(BaseModel):
    default_days: int


class TrialCampaignCreateRequest(BaseModel):
    name: str
    days: int
    starts_at: datetime
    ends_at: datetime


class TrialCampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    days: int
    starts_at: datetime
    ends_at: datetime
    created_at: datetime


class CustomerTrialOverrideRequest(BaseModel):
    days: int | None = None  # None = override'ı kaldır, genel/kampanya geçerli olsun


class TrialGrantCreateRequest(BaseModel):
    extra_days: int
    reason: str | None = None


class TrialGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    extra_days: int
    reason: str | None
    created_at: datetime
    consumed_at: datetime | None


# ─── Abonelikler (müşteri görünümü) ──────────────────────────────────────────
# `from_attributes` ile doğrudan ORM'den DEĞİL — PlanItem.product_code gibi
# alanlar ilişki üzerinden geldiği için app/routers/subscriptions.py bunları
# elle kurar (aynı desen: app/services/licenses.py de payload'ı elle kurar).


class SubscriptionPlanItemSummary(BaseModel):
    # `tier` yok: kademe yok, her lisans tam sürüm (bkz. app/models.py::TAM_SURUM_TIER).
    product_code: str
    product_name: str


class SubscriptionActivationSummary(BaseModel):
    product_code: str
    mode: str
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


class SubscriptionIssuedLicenseSummary(BaseModel):
    """`license.json` gövdesi (payload/signature) DEĞİL — yalnız özet. Tam
    belge için bkz. `GET /api/v1/subscriptions/{id}/licenses/{license_id}`."""

    license_id: str
    issued_at: datetime
    expires_at: datetime


class SubscriptionResponse(BaseModel):
    id: int
    plan_id: int
    plan_code: str
    plan_name: str
    items: list[SubscriptionPlanItemSummary]
    status: str
    current_period_end: datetime
    activations: list[SubscriptionActivationSummary]
    issued_licenses: list[SubscriptionIssuedLicenseSummary]


class LicenseDocumentResponse(BaseModel):
    """İmzalı `license.json` — `GET /api/v1/subscriptions/{id}/licenses/{license_id}`
    yeniden indirme ucunun döndürdüğü TAM belge (bkz. yukarıdaki özetten farkı)."""

    payload: dict
    signature: str


# ─── Katalog (müşteri görünümü, oturumsuz) ───────────────────────────────────
# `GET /api/v1/plans` — portal frontend'inin satın alma akışı için (2026-10-05
# görevi). Tutar istemci tarafında HESAPLANMAZ, sunucu `kdv_hesapla` ile
# `Order` oluşturulurken kullandığı AYNI formülü burada da uygular.


class PlanItemResponse(BaseModel):
    # `tier` yok: kademe yok, her lisans tam sürüm (bkz. app/models.py::TAM_SURUM_TIER).
    product_code: str
    product_name: str


class PlanPriceResponse(BaseModel):
    months: int
    net: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total: Decimal  # KDV DAHİL — sunucu hesaplar, istemci HESAPLAMAZ (bkz. app/services/pricing.py::kdv_hesapla)
    currency: str


class PlanResponse(BaseModel):
    id: int
    code: str
    name: str
    items: list[PlanItemResponse]
    prices: list[PlanPriceResponse]


# ─── İndirme merkezi (PLAN.md §5.4/F5) ───────────────────────────────────────
# `storage_key` BİLEREK burada YOK — depolamadaki iç yol müşteriye/personele
# hiçbir zaman sızmaz (bkz. app/routers/downloads.py).


class ReleaseResponse(BaseModel):
    id: int
    product_code: str
    product_name: str
    version: str
    package_type: str
    os: str
    arch: str
    file_name: str
    size_bytes: int
    sha256: str
    signed: bool
    notes: str | None
    published_at: datetime
