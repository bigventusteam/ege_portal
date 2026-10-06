"""
Çevrimdışı aktivasyon (PLAN.md §5.3, §3).

Akış: müşteri her ürün için ürünün kendi `GET /api/license/fingerprint`
ekranından indirdiği `activation_request` JSON dosyasını (bkz.
`ege_lisans.context.activation_request` — `{"product", "schema", "created",
"hostname_hint", "fingerprint": {"components": {...}}}`) portala yükler.
Portal abonelikteki HER ürün için tam olarak bir dosya bekler (ürünler
`Subscription.plan.items`'taki `PlanItem`'larla eşleşmeli), tek bir imzalı
şema v2 `license.json` üretir — her ürünün kendi `tier`'ı ve kendi
`fingerprint.components`'i ile (ürün başına parmak izi, paket satışında
ürünler farklı makinelerde olabildiği için — bkz. ege_lisans README).

`activation_request` dosyasının kendisinin (instance_id zorunluluğu, bilinen
bileşenler, hex biçimi, "unknown" reddi) doğrulaması burada DEĞİL —
app/services/activation_request.py'de (deneme lisansıyla, bkz.
app/services/trial.py, PAYLAŞILIYOR — bkz. o modülün docstring'i).

## Makine/koltuk limiti (KARAR 2026-10-05, kullanıcı — PLAN.md §8 madde 3 ARTIK KAPALI)

Lisans birimi MAKİNE. Abonelik başına (HER ÜRÜN İÇİN AYRI AYRI sayılır —
yukarıdaki not: paket satışında ürünler farklı makinelerde olabilir, bu
yüzden "1 koltuk" bir PAKETTEKİ HER ürün için 1 makine anlamına gelir,
TOPLAMDA 1 aktivasyon değil) en çok `Subscription.seats` kadar AKTİF
(`revoked_at IS NULL`) `Activation` olabilir — `_aktif_aktivasyon_sayisi`
ile ZORLANIR, aşılırsa `SeatLimitExceededError` (409).

**Aynı makineye yeniden lisans = YENİLEME, yeni koltuk HARCAMAZ:** bir
`activation_request`'in `instance_id`'si o ürün için HÂLİHAZIRDA aktif bir
`Activation`'la eşleşiyorsa (`_mevcut_aktivasyonu_bul`), yeni bir satır
AÇILMAZ — var olanın `fingerprint`/`last_seen_at`'i güncellenir. Bu kontrol
TÜM ürünler için, HERHANGİ bir yazma yapılmadan ÖNCE tek bir ön-geçişte
yapılır (bkz. `app/services/trial.py`'deki AYNI "kısmi/tutarsız durum
oluşmasın" ilkesi) — paket bir aboneliğin bir ürünü limitinin dolu olması,
diğer ürünün (o ana kadar başarıyla eklenmiş) bir Activation'ı YARIM
bırakmaz, İSTEĞİN TAMAMI reddedilir.

**Makine değişikliği:** personel `POST /api/v1/admin/activations/{id}/revoke`
ile var olan bir aktivasyonu iptal eder (gerekçe zorunlu, `AuditEvent`) —
koltuk SERBEST kalır, müşteri yeni makineyle aktivasyon yapabilir (bkz.
app/routers/admin.py).

## Çapraz-müşteri instance_id çarpışma tespiti

Aynı `instance_id` hash'i BAŞKA bir müşterinin aktif (`revoked_at` boş)
`Activation`'ında zaten varsa istek REDDEDİLMEZ (yanlış pozitif riski var —
iki farklı müşteri gerçekten aynı durağan bir değere düşmüş olabilir),
yalnızca `AuditEvent("activation.instance_id_collision")` yazılır — birinin
kurulum kimliği dosyasını kopyaladığının (ya da veri dizinini paylaştığının)
sinyali, elle incelenir.

**Sınırlama** (README'de de var): bu katman, veri dizinini (instance_id
dosyasını) makineler arasında KOPYALAYIP `machine_id`'yi silen KARARLI bir
müşteriye karşı TAM koruma sağlamaz — o durumda `instance_id` hash'i
GERÇEK ve BİRİCİK görünür (rastgele üretilmiş, "unknown" değil), yalnızca
paylaşılmıştır. Asıl kontrol çevrimiçi aktivasyondaki koltuk sayımı
olacak (PLAN.md §8 madde 3, henüz kararlaştırılmadı).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from ege_lisans.signing import build_v2_payload
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.licensing import LisansImzalayici
from app.models import TAM_SURUM_TIER, Activation, ActivationMode, AuditEvent, IssuedLicense, Subscription
from app.services.activation_request import InvalidActivationRequestError, parse_activation_request
from app.services.licenses import get_or_create_license_key

__all__ = ["InvalidActivationRequestError", "OfflineActivationError", "ProductMismatchError",
           "SeatLimitExceededError", "SubscriptionNotActiveError", "create_offline_license"]


class OfflineActivationError(Exception):
    """Tüm çevrimdışı aktivasyon hatalarının ortak üst sınıfı."""


class SubscriptionNotActiveError(OfflineActivationError):
    def __init__(self, subscription_id: int):
        self.subscription_id = subscription_id
        super().__init__(f"subscription_id={subscription_id} aktif değil (süresi dolmuş)")


class ProductMismatchError(OfflineActivationError):
    def __init__(self, *, beklenen: set[str], gelen: set[str]):
        self.beklenen = beklenen
        self.gelen = gelen
        eksik = beklenen - gelen
        fazla = gelen - beklenen
        parcalar = []
        if eksik:
            parcalar.append(f"eksik: {sorted(eksik)}")
        if fazla:
            parcalar.append(f"abonelikte olmayan: {sorted(fazla)}")
        super().__init__(
            f"yüklenen activation_request dosyaları abonelikteki ürünlerle eşleşmiyor ({', '.join(parcalar)})"
        )


class SeatLimitExceededError(OfflineActivationError):
    def __init__(self, *, subscription_id: int, product_code: str, seats: int):
        self.subscription_id = subscription_id
        self.product_code = product_code
        self.seats = seats
        super().__init__(
            f"'{product_code}' için bu abonelikte zaten {seats} aktif makine var (satın alınan koltuk "
            "sayısı doldu) — yeni bir makinede kullanmak için önce bir aktivasyonu iptal ettirin "
            "(personel: POST /api/v1/admin/activations/{id}/revoke)"
        )


def _mevcut_aktivasyonu_bul(
    db: Session, *, license_key_id: int, product_id: int, instance_id_hash: str
) -> Activation | None:
    """Bu LicenseKey/ürün için AYNI `instance_id`'ye sahip, hâlâ AKTİF bir
    `Activation` var mı? Varsa bu bir YENİLEME'dir (aynı makineye yeniden
    lisans) — yeni bir koltuk HARCAMAZ (bkz. modül docstring'i)."""
    for aday in db.scalars(
        select(Activation).where(
            Activation.license_key_id == license_key_id,
            Activation.product_id == product_id,
            Activation.revoked_at.is_(None),
        )
    ).all():
        try:
            bilesenler = json.loads(aday.fingerprint)
        except (TypeError, ValueError):
            continue
        if isinstance(bilesenler, dict) and bilesenler.get("instance_id") == instance_id_hash:
            return aday
    return None


def _aktif_aktivasyon_sayisi(db: Session, *, license_key_id: int, product_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Activation)
            .where(
                Activation.license_key_id == license_key_id,
                Activation.product_id == product_id,
                Activation.revoked_at.is_(None),
            )
        )
        or 0
    )


def _instance_id_carpismasini_isaretle(
    db: Session, *, product_id: int, product_code: str, instance_id_hash: str, customer_id: int
) -> None:
    """Aynı `instance_id` hash'i BAŞKA bir müşterinin aktif (`revoked_at`
    boş) `Activation`'ında zaten varsa isteği REDDETMEZ — yalnız
    `AuditEvent` yazar (bkz. modül docstring'i). `Activation.fingerprint`
    tüm bileşenlerin JSON'ı olarak saklandığı için (yalnız instance_id
    değil) burada Python tarafında ayrıştırıp karşılaştırıyoruz — bu, ayrı
    bir DB-özel JSON sorgusuna göre SQLite/PostgreSQL arasında taşınabilir."""
    adaylar = db.scalars(
        select(Activation).where(Activation.product_id == product_id, Activation.revoked_at.is_(None))
    ).all()
    for aday in adaylar:
        try:
            aday_components = json.loads(aday.fingerprint)
        except (TypeError, ValueError):
            continue
        if not isinstance(aday_components, dict) or aday_components.get("instance_id") != instance_id_hash:
            continue

        mevcut_customer_id = aday.license_key.subscription.customer_id
        if mevcut_customer_id == customer_id:
            continue  # aynı müşterinin kendi önceki aktivasyonu — çarpışma değil

        db.add(
            AuditEvent(
                event_type="activation.instance_id_collision",
                entity_type="activation",
                entity_id=str(aday.id),
                data={
                    "product": product_code,
                    "instance_id_hash": instance_id_hash,
                    "existing_customer_id": mevcut_customer_id,
                    "new_customer_id": customer_id,
                },
            )
        )


def create_offline_license(
    db: Session,
    *,
    subscription: Subscription,
    activation_files: list[tuple[str, bytes]],
    imzalayici: LisansImzalayici,
) -> dict:
    """`activation_files`: `[(dosya_adı, ham_bayt), ...]` — bkz. modül
    docstring'i. Dönen değer imzalı `{"payload": ..., "signature": ...}`
    (istemcinin `license.json` olarak kaydedeceği belge)."""
    now = datetime.now(timezone.utc)
    if subscription.current_period_end <= now:
        raise SubscriptionNotActiveError(subscription.id)

    istekler: dict[str, dict] = {}
    for filename, raw in activation_files:
        data = parse_activation_request(filename, raw)
        product = data["product"]
        if product in istekler:
            raise InvalidActivationRequestError(filename, f"'{product}' için birden fazla dosya yüklendi")
        istekler[product] = data

    beklenen = {item.product.code: item for item in subscription.plan.items}
    if set(istekler) != set(beklenen):
        raise ProductMismatchError(beklenen=set(beklenen), gelen=set(istekler))

    # Yalnız insan-okur LicenseKey'i garantiler, imzalı bir belge ÜRETMEZ —
    # onu birazdan biz kendimiz (gerçek fingerprint'lerle) yazacağız. Ödeme
    # akışı (app/services/payments.py::apply_payment_effects) da AYNI
    # fonksiyonu çağırır (bkz. app/services/licenses.py docstring'i) — hiçbir
    # yerde fingerprint'siz, placeholder bir IssuedLicense ÜRETİLMEZ.
    license_key, _ = get_or_create_license_key(db, subscription)

    # Ön kontrol — HİÇBİR yazma yapılmadan ÖNCE: hangi ürünler bir YENİLEME
    # (aynı instance_id, var olan Activation'ı güncelleriz), hangileri YENİ
    # bir makine mi, YENİLERİN koltuk sınırını aşıp aşmadığı. Paket bir
    # aboneliğin BİR ürünü doluyken diğer ürün için (o ana kadar başarıyla
    # eklenmiş) bir Activation YARIM bırakılmasın diye TEK bir geçişte
    # (bkz. app/services/trial.py'deki AYNI ilke, modül docstring'i).
    yenilenecek: dict[str, Activation] = {}
    for code, item in beklenen.items():
        instance_id_hash = istekler[code]["fingerprint"]["components"]["instance_id"]
        mevcut = _mevcut_aktivasyonu_bul(
            db, license_key_id=license_key.id, product_id=item.product_id, instance_id_hash=instance_id_hash
        )
        if mevcut is not None:
            yenilenecek[code] = mevcut
            continue
        if _aktif_aktivasyon_sayisi(db, license_key_id=license_key.id, product_id=item.product_id) >= subscription.seats:
            raise SeatLimitExceededError(subscription_id=subscription.id, product_code=code, seats=subscription.seats)

    products_payload: dict[str, dict] = {}
    for code, item in beklenen.items():
        products_payload[code] = {
            # Kademe yok: DB satırına bakılmaz, her zaman tam sürüm.
            "tier": TAM_SURUM_TIER,
            "fingerprint_components": istekler[code]["fingerprint"]["components"],
        }

    activation_id = f"act_{uuid.uuid4().hex[:16]}"
    payload = build_v2_payload(
        license_id=f"lic_{uuid.uuid4().hex[:16]}",
        subscription_id=f"sub_{subscription.id}",
        customer={
            "id": f"cus_{subscription.customer.id}",
            "name": subscription.customer.name,
            "email": subscription.customer.email,
        },
        products=products_payload,
        issued=date.today().isoformat(),
        expires=subscription.current_period_end.date().isoformat(),
        grace_days=settings.license_grace_days,
        activation={"id": activation_id, "mode": "offline"},
    )
    signature = imzalayici.imzala(payload)

    for code, item in beklenen.items():
        components = istekler[code]["fingerprint"]["components"]

        _instance_id_carpismasini_isaretle(
            db,
            product_id=item.product_id,
            product_code=code,
            instance_id_hash=components["instance_id"],
            customer_id=subscription.customer_id,
        )

        yenilenen = yenilenecek.get(code)
        if yenilenen is not None:
            # YENİLEME — aynı makineye yeniden lisans, yeni koltuk HARCAMAZ
            # (bkz. _mevcut_aktivasyonu_bul). Bileşenler teknik olarak aynı
            # instance_id ile eşleşti ama diğer bileşenler (mac, hostname vb.)
            # değişmiş olabilir — fingerprint'i GÜNCELLİYORUZ.
            yenilenen.fingerprint = json.dumps(components, sort_keys=True)
            yenilenen.last_seen_at = now
            continue

        db.add(
            Activation(
                license_key_id=license_key.id,
                product_id=item.product_id,
                fingerprint=json.dumps(components, sort_keys=True),
                version=None,
                mode=ActivationMode.OFFLINE,
                last_seen_at=now,
            )
        )

    db.add(
        IssuedLicense(
            subscription_id=subscription.id,
            license_key_id=license_key.id,
            payload=payload,
            signature=signature,
            issued_at=now,
            expires_at=subscription.current_period_end,
        )
    )
    db.commit()

    return {"payload": payload, "signature": signature}
