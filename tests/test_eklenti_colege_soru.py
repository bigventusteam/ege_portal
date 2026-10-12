"""
colEGE "Soru sor" EK ÜRÜNÜ (eklenti, `colege_soru`) — bkz. app/services/eklentiler.py.

Lisanslar GERÇEK `ege_lisans` ile imzalanır; aktivasyon dosyaları GERÇEK
`ege_lisans.activation_request(product="colege")` ile (geçici dizinde)
üretilir ve doğrulama colEGE'nin `license_service.soru_ozelligi_acik_mi()`
mantığını birebir taklit eder: önce `products.colege` geçerli olmalı, sonra
`validate_v2(product="colege_soru", current_fingerprint=current_fingerprint(
colege bağlamı))` valid/grace olmalı. (colEGE worktree'sinin kendi koduyla
uçtan uca kanıt ayrıca test düzeneğinde yapıldı — bkz. rapor.)
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from ege_lisans import LicenseContext, activation_request, current_fingerprint, validate_license
from ege_lisans.schema_v2 import validate_v2
from ege_lisans.signing import generate_keypair
from sqlalchemy import select

from app.deps import get_imzalayici
from app.licensing import EgeLisansImzalayici
from app.main import app
from app.models import Activation, AuditEvent, IssuedLicense, Plan, PlanItem, Price, Product, Subscription
from app.services.subscriptions import extend_subscription

_spec = importlib.util.spec_from_file_location(
    "eklenti_tohumla", Path(__file__).resolve().parents[1] / "scripts" / "eklenti_tohumla.py")
_tohum = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tohum)
YER_TUTUCU_NET_FIYAT = _tohum.YER_TUTUCU_NET_FIYAT
colege_soru_tohumla = _tohum.colege_soru_tohumla

LISANSLI = {"valid", "grace"}


# ─── Fixture'lar ─────────────────────────────────────────────────────────────


@pytest.fixture
def anahtar_cifti(tmp_path):
    key_path = tmp_path / "test_key.pem"
    return key_path, generate_keypair(key_path)


@pytest.fixture(autouse=True)
def _gercek_imzalayici(client, anahtar_cifti):
    imzalayici = EgeLisansImzalayici(private_key_path=anahtar_cifti[0])
    app.dependency_overrides[get_imzalayici] = lambda: imzalayici
    yield


@pytest.fixture
def urun_colege(db):
    p = Product(code="colege", name="colEGE")
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def plan_colege(db, urun_colege):
    plan = Plan(code="colege-yillik", name="colEGE Yıllık")
    plan.items.append(PlanItem(product=urun_colege))
    db.add(plan)
    db.flush()
    db.add(Price(plan_id=plan.id, months=12, amount=Decimal("8000.00"),
                 valid_from=datetime.now(timezone.utc) - timedelta(days=1)))
    db.commit()
    return plan


@pytest.fixture
def plan_soru(db, plan_colege):
    plan = colege_soru_tohumla(db, yer_tutucuyla_ac=True)
    plan.prices[0].valid_from = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    return plan


def _abonelik(db, customer_id, plan, *, months=12, seats=1, bitis: datetime | None = None) -> Subscription:
    sub = extend_subscription(db, customer_id=customer_id, plan_id=plan.id, months=months, quantity=seats)
    if bitis is not None:
        sub.current_period_end = bitis
    db.commit()
    db.refresh(sub)
    return sub


class Kurulum:
    """Bir colEGE kurulumu: kendi veri dizini, GERÇEK ege_lisans aktivasyon dosyası."""

    def __init__(self, dizin, public_key_hex):
        self.ctx = LicenseContext(product="colege", public_keys=(public_key_hex,), data_dir=dizin)
        self.istek = activation_request(self.ctx)

    def dosya(self):
        return ("files", ("colege.json", json.dumps(self.istek).encode("utf-8"), "application/json"))

    def colege_durumu(self, doc) -> str:
        return validate_license(doc, self.ctx)["state"]

    def soru_acik_mi(self, doc) -> bool:
        """colEGE license_service.soru_ozelligi_acik_mi()'nin lisanslı dalı."""
        if self.colege_durumu(doc) not in LISANSLI:
            return False
        if doc["payload"].get("schema") != 2:
            return False
        sonuc = validate_v2(
            doc, product="colege_soru", public_keys=self.ctx.public_keys,
            current_fingerprint=current_fingerprint(self.ctx), state_file=self.ctx.state_file,
            min_match=self.ctx.min_match, anchor_components=self.ctx.anchor_components,
        )
        return sonuc["state"] in LISANSLI


@pytest.fixture
def kurulum(tmp_path, anahtar_cifti):
    return Kurulum(tmp_path / "kurulum_a", anahtar_cifti[1])


@pytest.fixture
def kurulum_b(tmp_path, anahtar_cifti):
    return Kurulum(tmp_path / "kurulum_b", anahtar_cifti[1])


def _aktive_et(client, sub_id, headers, *dosyalar):
    return client.post(f"/api/v1/subscriptions/{sub_id}/offline-activation", files=list(dosyalar), headers=headers)


def _siparis(client, plan_id, headers):
    return client.post("/api/v1/orders", json={"plan_id": plan_id, "months": 12}, headers=headers)


# ─── Katalog / satış ─────────────────────────────────────────────────────────


def test_tohum_yer_tutucu_fiyatla_plani_kapali_olusturur_ve_idempotent(db, urun_colege):
    plan = colege_soru_tohumla(db)
    db.commit()
    assert plan.code == "colege-soru-yillik"
    assert plan.is_active is False  # yer tutucu fiyatla satışa AÇILMAZ
    assert [(p.months, p.amount) for p in plan.prices] == [(12, YER_TUTUCU_NET_FIYAT)]
    urun = plan.items[0].product
    assert urun.code == "colege_soru" and urun.requires_product.code == "colege" and urun.is_addon

    tekrar = colege_soru_tohumla(db, net=Decimal("5000.00"))
    db.commit()
    assert tekrar.id == plan.id and len(tekrar.prices) == 1  # var olan plana fiyat eklenmez


def test_tohum_gercek_fiyatla_plan_acik(db, urun_colege):
    plan = colege_soru_tohumla(db, net=Decimal("4800.00"))
    assert plan.is_active is True and plan.prices[0].amount == Decimal("4800.00")


def test_tohum_temel_urun_yoksa_hata(db):
    with pytest.raises(RuntimeError):
        colege_soru_tohumla(db)


def test_planlar_ucu_eklentiyi_isaretler(client, plan_soru, plan_colege):
    planlar = {p["code"]: p for p in client.get("/api/v1/plans").json()}
    assert planlar["colege-yillik"]["is_addon"] is False
    soru = planlar["colege-soru-yillik"]
    assert soru["is_addon"] is True
    assert soru["items"] == [{"product_code": "colege_soru", "product_name": "colEGE Soru Sor",
                              "requires_product_code": "colege", "requires_product_name": "colEGE"}]
    assert soru["prices"][0]["net"] == str(YER_TUTUCU_NET_FIYAT)


def test_colege_aboneligi_yoksa_eklenti_satilmaz(client, auth_headers, plan_soru):
    resp = _siparis(client, plan_soru.id, auth_headers)
    assert resp.status_code == 409
    assert "colege" in resp.json()["detail"]


def test_colege_aboneligi_suresi_dolmussa_eklenti_satilmaz(client, db, musteri, auth_headers, plan_colege, plan_soru):
    _abonelik(db, musteri.id, plan_colege, bitis=datetime.now(timezone.utc) - timedelta(days=1))
    assert _siparis(client, plan_soru.id, auth_headers).status_code == 409


def test_aktif_colege_aboneligi_varsa_eklenti_satilir(client, db, musteri, auth_headers, plan_colege, plan_soru):
    _abonelik(db, musteri.id, plan_colege)
    assert _siparis(client, plan_soru.id, auth_headers).status_code == 201


def test_baska_musterinin_colege_aboneligi_sayilmaz(client, db, auth_headers, plan_colege, plan_soru):
    from app.models import Customer
    baska = Customer(name="Başka", email="baska@example.com")
    db.add(baska)
    db.commit()
    _abonelik(db, baska.id, plan_colege)
    assert _siparis(client, plan_soru.id, auth_headers).status_code == 409


# ─── Aktivasyon ──────────────────────────────────────────────────────────────


def test_eklenti_tek_basina_aktive_edilemez(client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum):
    _abonelik(db, musteri.id, plan_colege)
    soru = _abonelik(db, musteri.id, plan_soru)
    resp = _aktive_et(client, soru.id, auth_headers, kurulum.dosya())
    assert resp.status_code == 422
    assert "tek başına" in resp.json()["detail"]
    assert db.scalars(select(Activation)).all() == []
    assert db.scalars(select(IssuedLicense)).all() == []


def test_eklentisiz_colege_lisansi_soru_kapali(client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum):
    colege = _abonelik(db, musteri.id, plan_colege)
    resp = _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    assert resp.status_code == 200
    doc = resp.json()
    assert set(doc["payload"]["products"]) == {"colege"}
    assert kurulum.colege_durumu(doc) == "valid"
    assert kurulum.soru_acik_mi(doc) is False


def test_colege_ve_eklenti_tek_lisansta_ikisi_de_gecerli(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum
):
    colege = _abonelik(db, musteri.id, plan_colege)
    soru = _abonelik(db, musteri.id, plan_soru)
    resp = _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    assert resp.status_code == 200
    doc = resp.json()
    urunler = doc["payload"]["products"]
    assert set(urunler) == {"colege", "colege_soru"}
    # Eklentinin parmak izi = colEGE aktivasyon dosyasındaki "colege" bileşenleri, birebir.
    assert urunler["colege_soru"]["fingerprint"]["components"] == kurulum.istek["fingerprint"]["components"]
    assert urunler["colege_soru"]["fingerprint"] == urunler["colege"]["fingerprint"]
    assert urunler["colege_soru"]["tier"] == "full"
    assert kurulum.colege_durumu(doc) == "valid"
    assert kurulum.soru_acik_mi(doc) is True

    # Kayıtlar: colEGE aktivasyonu colEGE aboneliğinde, eklenti aktivasyonu eklenti aboneliğinde.
    akt = db.scalars(select(Activation)).all()
    assert sorted((a.license_key.subscription_id, a.product.code) for a in akt) == sorted(
        [(colege.id, "colege"), (soru.id, "colege_soru")])
    issued = db.scalars(select(IssuedLicense)).all()
    assert [i.subscription_id for i in issued] == [colege.id]


def test_baska_kurulumda_eklenti_lisansi_gecersiz(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum, kurulum_b
):
    colege = _abonelik(db, musteri.id, plan_colege)
    _abonelik(db, musteri.id, plan_soru)
    doc = _aktive_et(client, colege.id, auth_headers, kurulum.dosya()).json()
    assert kurulum_b.colege_durumu(doc) == "fingerprint_mismatch"
    assert kurulum_b.soru_acik_mi(doc) is False


def test_bitis_eklenti_daha_erken_biterse_eklentinin_bitisi(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum
):
    now = datetime.now(timezone.utc)
    colege = _abonelik(db, musteri.id, plan_colege, bitis=now + timedelta(days=300))
    _abonelik(db, musteri.id, plan_soru, bitis=now + timedelta(days=100))
    doc = _aktive_et(client, colege.id, auth_headers, kurulum.dosya()).json()
    assert doc["payload"]["expires"] == (now + timedelta(days=100)).date().isoformat()
    issued = db.scalars(select(IssuedLicense)).one()
    assert issued.expires_at.date() == (now + timedelta(days=100)).date()


def test_bitis_eklenti_colegeden_uzunsa_colege_bitisini_asamaz(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum
):
    now = datetime.now(timezone.utc)
    colege = _abonelik(db, musteri.id, plan_colege, bitis=now + timedelta(days=60))
    _abonelik(db, musteri.id, plan_soru, bitis=now + timedelta(days=365))
    doc = _aktive_et(client, colege.id, auth_headers, kurulum.dosya()).json()
    assert doc["payload"]["expires"] == (now + timedelta(days=60)).date().isoformat()
    assert kurulum.soru_acik_mi(doc) is True


def test_suresi_dolmus_eklenti_eklenmez_colege_tam_sure(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum
):
    now = datetime.now(timezone.utc)
    colege = _abonelik(db, musteri.id, plan_colege, bitis=now + timedelta(days=200))
    _abonelik(db, musteri.id, plan_soru, bitis=now - timedelta(days=1))
    doc = _aktive_et(client, colege.id, auth_headers, kurulum.dosya()).json()
    assert set(doc["payload"]["products"]) == {"colege"}
    assert doc["payload"]["expires"] == (now + timedelta(days=200)).date().isoformat()


def test_ayni_kurulum_yeniden_aktivasyon_koltuk_harcamaz_ve_eklenti_sonradan_eklenir(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum
):
    colege = _abonelik(db, musteri.id, plan_colege)  # 1 koltuk
    ilk = _aktive_et(client, colege.id, auth_headers, kurulum.dosya()).json()
    assert kurulum.soru_acik_mi(ilk) is False

    # Müşteri eklentiyi SONRADAN satın alır, AYNI kurulumun dosyasıyla yeniden aktive eder.
    _abonelik(db, musteri.id, plan_soru)
    ikinci = _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    assert ikinci.status_code == 200  # 1 koltuk dolu ama aynı kurulum = YENİLEME
    assert kurulum.soru_acik_mi(ikinci.json()) is True

    ucuncu = _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    assert ucuncu.status_code == 200
    akt = db.scalars(select(Activation)).all()
    assert sorted(a.product.code for a in akt) == ["colege", "colege_soru"]  # yeni satır yok


def test_eklenti_koltugu_doluysa_ikinci_kurulum_eklentisiz_lisans_alir(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum, kurulum_b
):
    colege = _abonelik(db, musteri.id, plan_colege, seats=2)
    soru = _abonelik(db, musteri.id, plan_soru, seats=1)
    a = _aktive_et(client, colege.id, auth_headers, kurulum.dosya()).json()
    assert kurulum.soru_acik_mi(a) is True

    b = _aktive_et(client, colege.id, auth_headers, kurulum_b.dosya())
    assert b.status_code == 200  # colEGE'nin 2. koltuğu eklenti yüzünden kilitlenmez
    assert set(b.json()["payload"]["products"]) == {"colege"}
    assert kurulum_b.colege_durumu(b.json()) == "valid"
    assert kurulum_b.soru_acik_mi(b.json()) is False
    olay = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "activation.addon_seat_full")).one()
    assert olay.entity_id == str(soru.id) and olay.data["base_subscription_id"] == colege.id


def test_paket_planda_eklenti_dosya_beklemez(client, db, musteri, auth_headers, urun_colege, plan_soru, kurulum):
    soru_urun = db.scalar(select(Product).where(Product.code == "colege_soru"))
    paket = Plan(code="colege-soru-paket", name="colEGE + Soru")
    paket.items += [PlanItem(product=urun_colege), PlanItem(product=soru_urun)]
    db.add(paket)
    db.commit()
    sub = _abonelik(db, musteri.id, paket)
    resp = _aktive_et(client, sub.id, auth_headers, kurulum.dosya())
    assert resp.status_code == 200
    assert kurulum.soru_acik_mi(resp.json()) is True


def test_eklenti_dosyasi_elle_uretilse_de_colege_aboneliginde_reddedilir(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum
):
    colege = _abonelik(db, musteri.id, plan_colege)
    _abonelik(db, musteri.id, plan_soru)
    sahte = dict(kurulum.istek, product="colege_soru")
    resp = _aktive_et(client, colege.id, auth_headers, kurulum.dosya(),
                      ("files", ("soru.json", json.dumps(sahte).encode(), "application/json")))
    assert resp.status_code == 422


def test_deneme_lisansi_eklenti_icin_verilmez(client, auth_headers, plan_soru, kurulum):
    sahte = dict(kurulum.istek, product="colege_soru")
    resp = client.post("/api/v1/trial-activation", files=[("files", ("soru.json", json.dumps(sahte).encode(), "application/json"))],
                       headers=auth_headers)
    assert resp.status_code == 422
    assert "colege_soru" in resp.json()["detail"]


# ─── Müşteri görünümü / yönetici ─────────────────────────────────────────────


def test_aboneliklerim_eklentiyi_ve_aktivasyonunu_gosterir(
    client, db, musteri, auth_headers, plan_colege, plan_soru, kurulum
):
    colege = _abonelik(db, musteri.id, plan_colege)
    soru = _abonelik(db, musteri.id, plan_soru)
    _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    subs = {s["id"]: s for s in client.get("/api/v1/subscriptions", headers=auth_headers).json()}
    assert subs[colege.id]["is_addon"] is False and len(subs[colege.id]["issued_licenses"]) == 1
    s = subs[soru.id]
    assert s["is_addon"] is True
    assert s["items"] == [{"product_code": "colege_soru", "product_name": "colEGE Soru Sor",
                           "requires_product_code": "colege"}]
    assert [a["product_code"] for a in s["activations"]] == ["colege_soru"]


def test_yonetici_colege_aktivasyonunu_iptal_edince_eklenti_de_iptal_ve_koltuk_bosalir(
    client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru, kurulum, kurulum_b
):
    colege = _abonelik(db, musteri.id, plan_colege)
    _abonelik(db, musteri.id, plan_soru)
    _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    colege_akt = db.scalar(select(Activation).join(Product).where(Product.code == "colege"))
    soru_akt = db.scalar(select(Activation).join(Product).where(Product.code == "colege_soru"))

    resp = client.post(f"/api/v1/admin/activations/{colege_akt.id}/revoke", json={"reason": "makine değişti"},
                       headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["addon_activation_ids"] == [soru_akt.id]
    db.refresh(soru_akt)
    assert soru_akt.revoked_at is not None

    yeni = _aktive_et(client, colege.id, auth_headers, kurulum_b.dosya())
    assert yeni.status_code == 200
    assert kurulum_b.soru_acik_mi(yeni.json()) is True


def test_yonetici_eklenti_iptali_colegeyi_etkilemez(
    client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru, kurulum
):
    colege = _abonelik(db, musteri.id, plan_colege)
    _abonelik(db, musteri.id, plan_soru)
    _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    soru_akt = db.scalar(select(Activation).join(Product).where(Product.code == "colege_soru"))
    resp = client.post(f"/api/v1/admin/activations/{soru_akt.id}/revoke", json={"reason": "x"}, headers=admin_headers)
    assert resp.json()["addon_activation_ids"] == []
    assert db.scalar(select(Activation).join(Product).where(Product.code == "colege")).revoked_at is None


def test_yonetici_eklenti_listesi(client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru, kurulum):
    colege = _abonelik(db, musteri.id, plan_colege)
    soru = _abonelik(db, musteri.id, plan_soru, seats=3)
    _aktive_et(client, colege.id, auth_headers, kurulum.dosya())
    satirlar = client.get("/api/v1/admin/eklentiler", headers=admin_headers).json()
    assert satirlar == [{
        "subscription_id": soru.id, "customer_id": musteri.id, "customer_name": musteri.name,
        "plan_code": "colege-soru-yillik", "addon_product_code": "colege_soru", "base_product_code": "colege",
        "current_period_end": satirlar[0]["current_period_end"], "is_active": True,
        "base_subscription_active": True, "seats": 3, "seats_used": 1,
    }]


def test_yonetici_eklenti_listesi_personel_ister(client, auth_headers):
    assert client.get("/api/v1/admin/eklentiler", headers=auth_headers).status_code == 403
