"""
Eklenti EŞ-SONLANMA (kullanıcı kararı 2026-10-12) — bkz. app/services/eklentiler.py:
eklenti temel (colEGE) aboneliğe bağlanır, onunla AYNI gün biter, ücret kalan
güne orantılıdır; temel abonelik yenilenince bağlı eklenti aynı döneme
yenilenir; eklenti tek başına yenilenmez; iptal edilen eklenti sonraki
aktivasyona girmez. Ödemeler gerçek akıştan (personel havale işaretleme →
apply_payment_effects) geçer.
"""
import importlib.util
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from ege_lisans import LicenseContext, activation_request
from sqlalchemy import select

from app.models import AuditEvent, Customer, Plan, PlanItem, Price, Product, Subscription
from app.services.eklentiler import kalan_gun
from app.services.pricing import orantili_net
from app.services.subscriptions import extend_subscription

_spec = importlib.util.spec_from_file_location(
    "eklenti_tohumla", Path(__file__).resolve().parents[1] / "scripts" / "eklenti_tohumla.py")
_tohum = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tohum)

GECMIS = datetime.now(timezone.utc) - timedelta(days=1)
SORU_YILLIK = _tohum.YER_TUTUCU_NET_FIYAT  # 1000.00 — yer tutucu


@pytest.fixture
def urun_colege(db):
    p = Product(code="colege", name="colEGE")
    db.add(p)
    db.commit()
    return p


def _plan(db, kod, urunler, fiyat=None):
    plan = Plan(code=kod, name=kod)
    for u in urunler:
        plan.items.append(PlanItem(product=u))
    db.add(plan)
    db.flush()
    if fiyat is not None:
        db.add(Price(plan_id=plan.id, months=12, amount=Decimal(fiyat), valid_from=GECMIS))
    db.commit()
    return plan


@pytest.fixture
def plan_colege(db, urun_colege):
    return _plan(db, "colege-yillik", [urun_colege], "8000.00")


@pytest.fixture
def plan_soru(db, plan_colege):
    plan = _tohum.colege_soru_tohumla(db, yer_tutucuyla_ac=True)
    plan.prices[0].valid_from = GECMIS
    db.commit()
    return plan


def _abonelik(db, customer_id, plan, *, bitis=None, seats=1):
    sub = extend_subscription(db, customer_id=customer_id, plan_id=plan.id, months=12, quantity=seats)
    if bitis is not None:
        sub.current_period_end = bitis
    db.commit()
    db.refresh(sub)
    return sub


def _siparis(client, headers, plan, **ek):
    return client.post("/api/v1/orders", json={"plan_id": plan.id, "months": 12, **ek}, headers=headers)


def _ode(client, admin_headers, order: dict):
    r = client.post(f"/api/v1/admin/orders/{order['id']}/mark-paid", headers=admin_headers, json={
        "amount": order["total"], "bank_reference": f"DEKONT-{uuid.uuid4().hex[:8]}",
        "received_at": datetime.now(timezone.utc).isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


def _eklenti_sub(db, customer_id, plan_soru):
    return db.scalar(select(Subscription).where(Subscription.customer_id == customer_id,
                                                Subscription.plan_id == plan_soru.id))


# ─── Orantılı fiyat ─────────────────────────────────────────────────────────


def test_orantili_net_kurus_yarim_yukari():
    assert orantili_net(Decimal("1000.00"), 365) == Decimal("1000.00")
    assert orantili_net(Decimal("1000.00"), 100) == Decimal("273.97")  # 273.9726… (tavan değil)
    assert orantili_net(Decimal("1000.00"), 1) == Decimal("2.74")      # 2.7397… (taban değil)
    assert orantili_net(Decimal("18.25"), 1) == Decimal("0.05")
    assert orantili_net(Decimal("0.73"), 3) == Decimal("0.01")         # 0.006 → 0.01


def test_eklenti_siparisi_kalan_gune_orantili_ve_colegeye_baglanir(client, db, musteri, auth_headers, plan_colege, plan_soru):
    now = datetime.now(timezone.utc)
    colege = _abonelik(db, musteri.id, plan_colege, bitis=now + timedelta(days=100, hours=1))
    r = _siparis(client, auth_headers, plan_soru)
    assert r.status_code == 201, r.text
    o = r.json()
    gun = kalan_gun(colege.current_period_end, now)
    assert o["prorated_days"] == gun
    assert o["base_subscription_id"] == colege.id
    assert o["addon_period_end"][:19] == colege.current_period_end.isoformat()[:19]
    assert Decimal(o["net"]) == orantili_net(SORU_YILLIK, gun)
    assert Decimal(o["vat_amount"]) == (Decimal(o["net"]) * Decimal("0.20")).quantize(Decimal("0.01"))
    assert Decimal(o["total"]) == Decimal(o["net"]) + Decimal(o["vat_amount"])
    assert o["addons"] == []


def test_adet_orantiya_toplamda_bir_kez_yuvarlanir_ve_temel_koltugu_asamaz(
    client, db, musteri, auth_headers, plan_colege, plan_soru
):
    now = datetime.now(timezone.utc)
    colege = _abonelik(db, musteri.id, plan_colege, seats=2, bitis=now + timedelta(days=100, hours=1))
    o = _siparis(client, auth_headers, plan_soru, quantity=2).json()
    assert Decimal(o["net"]) == orantili_net(SORU_YILLIK * 2, kalan_gun(colege.current_period_end, now))
    r = _siparis(client, auth_headers, plan_soru, quantity=3)
    assert r.status_code == 422 and "koltuk" in r.json()["detail"]


def test_yeni_alinan_colege_ile_eklenti_tam_yila_yakin(client, db, musteri, auth_headers, plan_colege, plan_soru):
    _abonelik(db, musteri.id, plan_colege)  # bugün + 12 ay
    o = _siparis(client, auth_headers, plan_soru).json()
    assert o["prorated_days"] in (365, 366)
    assert Decimal(o["net"]) == orantili_net(SORU_YILLIK, o["prorated_days"])


def test_paket_ayni_sepet_tam_yil_normal_fiyat(client, db, musteri, auth_headers, urun_colege, plan_soru):
    soru = db.scalar(select(Product).where(Product.code == "colege_soru"))
    paket = _plan(db, "colege-soru-paket", [urun_colege, soru], "8800.00")
    o = _siparis(client, auth_headers, paket).json()
    assert Decimal(o["net"]) == Decimal("8800.00")
    assert o["prorated_days"] is None and o["base_subscription_id"] is None


# ─── Bağlama ────────────────────────────────────────────────────────────────


def test_temel_abonelik_bittiyse_eklenti_satilmaz(client, db, musteri, auth_headers, plan_colege, plan_soru):
    _abonelik(db, musteri.id, plan_colege, bitis=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert _siparis(client, auth_headers, plan_soru).status_code == 409


def test_bugun_biten_temel_aboneliğe_eklenti_satilmaz(client, db, musteri, auth_headers, plan_colege, plan_soru):
    now = datetime.now(timezone.utc)
    gun_sonu = datetime.combine(now.date(), time(23, 59, 59), tzinfo=timezone.utc)
    if gun_sonu <= now + timedelta(seconds=5):
        pytest.skip("UTC gün sonuna çok yakın")
    _abonelik(db, musteri.id, plan_colege, bitis=gun_sonu)
    r = _siparis(client, auth_headers, plan_soru)
    assert r.status_code == 409  # 0 gün kalan — asgari 1 gün


def test_birden_cok_temel_abonelikte_secim_zorunlu(client, db, musteri, auth_headers, urun_colege, plan_colege, plan_soru):
    mapege = Product(code="mapege", name="mapEGE")
    db.add(mapege)
    db.commit()
    paket = _plan(db, "colege-mapege-paket", [urun_colege, mapege], "15000.00")
    a = _abonelik(db, musteri.id, plan_colege)
    b = _abonelik(db, musteri.id, paket, bitis=datetime.now(timezone.utc) + timedelta(days=50, hours=1))

    r = _siparis(client, auth_headers, plan_soru)
    assert r.status_code == 422 and str(a.id) in r.json()["detail"] and str(b.id) in r.json()["detail"]

    o = _siparis(client, auth_headers, plan_soru, base_subscription_id=b.id).json()
    assert o["base_subscription_id"] == b.id
    assert o["prorated_days"] == kalan_gun(b.current_period_end, datetime.now(timezone.utc))


def test_gecersiz_temel_abonelik_secimi(client, db, musteri, auth_headers, urun_colege, plan_colege, plan_soru):
    baska = Customer(name="Başka", email="b@example.com")
    db.add(baska)
    db.commit()
    yabanci = _abonelik(db, baska.id, plan_colege)
    _abonelik(db, musteri.id, plan_colege)
    assert _siparis(client, auth_headers, plan_soru, base_subscription_id=yabanci.id).status_code == 422
    assert _siparis(client, auth_headers, plan_soru, base_subscription_id=999999).status_code == 422

    mapege = Product(code="mapege", name="mapEGE")
    db.add(mapege)
    db.commit()
    m = _abonelik(db, musteri.id, _plan(db, "mapege-yillik", [mapege], "12000.00"))
    r = _siparis(client, auth_headers, plan_soru, base_subscription_id=m.id)
    assert r.status_code == 422 and "taşımıyor" in r.json()["detail"]


def test_odeme_eklentiyi_baglar_ve_bitisi_colegeye_esitler(
    client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru
):
    colege = _abonelik(db, musteri.id, plan_colege, bitis=datetime.now(timezone.utc) + timedelta(days=200))
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru, quantity=1).json())
    soru = _eklenti_sub(db, musteri.id, plan_soru)
    assert soru.base_subscription_id == colege.id
    assert soru.current_period_end == colege.current_period_end
    assert soru.seats == 1

    subs = {s["id"]: s for s in client.get("/api/v1/subscriptions", headers=auth_headers).json()}
    assert subs[soru.id]["base_subscription_id"] == colege.id
    assert subs[soru.id]["current_period_end"] == subs[colege.id]["current_period_end"]


def test_eklenti_tek_basina_yenilenemez(client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru):
    _abonelik(db, musteri.id, plan_colege)
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru).json())
    r = _siparis(client, auth_headers, plan_soru)
    assert r.status_code == 409 and "tek başına yenilenmez" in r.json()["detail"]


# ─── Yenileme hizalaması ────────────────────────────────────────────────────


def test_colege_yenilemesi_bagli_eklentiyi_ayni_doneme_yeniler(
    client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru
):
    colege = _abonelik(db, musteri.id, plan_colege, bitis=datetime.now(timezone.utc) + timedelta(days=30))
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru).json())
    soru = _eklenti_sub(db, musteri.id, plan_soru)

    o = _siparis(client, auth_headers, plan_colege).json()  # colEGE yenileme (12 ay)
    assert o["addons"] == [{"subscription_id": soru.id, "plan_id": plan_soru.id, "quantity": 1, "net": "1000.00"}]
    assert Decimal(o["net"]) == Decimal("8000.00") + SORU_YILLIK
    _ode(client, admin_headers, o)

    db.refresh(colege)
    db.refresh(soru)
    assert colege.current_period_end.date() > (datetime.now(timezone.utc) + timedelta(days=360)).date()
    assert soru.current_period_end == colege.current_period_end


def test_hizasiz_eklenti_yenilemede_gun_orantisiyla_hizalanir(
    client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru
):
    now = datetime.now(timezone.utc)
    colege = _abonelik(db, musteri.id, plan_colege, bitis=now + timedelta(days=60))
    soru = _abonelik(db, musteri.id, plan_soru, bitis=now + timedelta(days=20))  # eski/hizasız kayıt
    soru.base_subscription_id = colege.id
    db.commit()

    o = _siparis(client, auth_headers, plan_colege).json()
    yeni_bitis = colege.current_period_end.replace(year=colege.current_period_end.year + 1)
    beklenen = orantili_net(SORU_YILLIK, kalan_gun(yeni_bitis, soru.current_period_end))
    assert [Decimal(a["net"]) for a in o["addons"]] == [beklenen]
    _ode(client, admin_headers, o)
    db.refresh(colege)
    db.refresh(soru)
    assert soru.current_period_end == colege.current_period_end


def test_ilk_colege_alimi_eklenti_satiri_icermez(client, db, musteri, auth_headers, plan_colege, plan_soru):
    o = _siparis(client, auth_headers, plan_colege).json()
    assert o["addons"] == [] and Decimal(o["net"]) == Decimal("8000.00")


# ─── İptal ──────────────────────────────────────────────────────────────────


def _kurulum_dosyasi(tmp_path):
    istek = activation_request(LicenseContext(product="colege", public_keys=(), data_dir=tmp_path / "kurulum"))
    return ("files", ("colege.json", json.dumps(istek).encode("utf-8"), "application/json"))


def test_iptal_edilen_eklenti_sonraki_aktivasyona_ve_yenilemeye_girmez(
    client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru, tmp_path
):
    colege = _abonelik(db, musteri.id, plan_colege)
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru).json())
    soru = _eklenti_sub(db, musteri.id, plan_soru)
    dosya = _kurulum_dosyasi(tmp_path)

    ilk = client.post(f"/api/v1/subscriptions/{colege.id}/offline-activation", files=[dosya], headers=auth_headers).json()
    assert set(ilk["payload"]["products"]) == {"colege", "colege_soru"}
    assert ilk["payload"]["expires"] == colege.current_period_end.date().isoformat()  # eş-sonlanma: min = ikisi de

    r = client.post(f"/api/v1/admin/eklentiler/{soru.id}/iptal", json={"reason": "iade"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and len(r.json()["revoked_activation_ids"]) == 1
    assert client.post(f"/api/v1/admin/eklentiler/{soru.id}/iptal", json={"reason": "x"},
                       headers=admin_headers).status_code == 409
    assert client.post(f"/api/v1/admin/eklentiler/{colege.id}/iptal", json={"reason": "x"},
                       headers=admin_headers).status_code == 409

    sonra = client.post(f"/api/v1/subscriptions/{colege.id}/offline-activation", files=[dosya], headers=auth_headers).json()
    assert set(sonra["payload"]["products"]) == {"colege"}
    assert sonra["payload"]["expires"] == colege.current_period_end.date().isoformat()

    o = _siparis(client, auth_headers, plan_colege).json()
    assert o["addons"] == []
    olay = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "addon.cancelled_by_staff")).one()
    assert olay.data["reason"] == "iade"


def test_iptal_sonrasi_yeniden_satin_alinabilir(client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru):
    _abonelik(db, musteri.id, plan_colege)
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru).json())
    soru = _eklenti_sub(db, musteri.id, plan_soru)
    client.post(f"/api/v1/admin/eklentiler/{soru.id}/iptal", json={"reason": "iade"}, headers=admin_headers)
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru).json())
    db.refresh(soru)
    assert soru.status.value == "active"


def test_yenileme_sirasinda_iptal_edilen_eklenti_uygulanmaz(
    client, db, musteri, auth_headers, admin_headers, plan_colege, plan_soru
):
    colege = _abonelik(db, musteri.id, plan_colege, bitis=datetime.now(timezone.utc) + timedelta(days=30))
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru).json())
    soru = _eklenti_sub(db, musteri.id, plan_soru)
    o = _siparis(client, auth_headers, plan_colege).json()
    assert len(o["addons"]) == 1
    client.post(f"/api/v1/admin/eklentiler/{soru.id}/iptal", json={"reason": "vazgeçti"}, headers=admin_headers)
    _ode(client, admin_headers, o)
    db.refresh(soru)
    assert soru.status.value == "cancelled"
    assert soru.current_period_end.date() == (datetime.now(timezone.utc) + timedelta(days=30)).date()
    assert db.scalars(select(AuditEvent).where(AuditEvent.event_type == "addon.renewal_skipped_cancelled")).one()


# ─── Aktivasyon bağlaması / satış kapalı ────────────────────────────────────


def test_eklenti_yalniz_bagli_oldugu_temel_aboneligin_aktivasyonuna_eklenir(
    client, db, musteri, auth_headers, admin_headers, urun_colege, plan_colege, plan_soru, tmp_path
):
    mapege = Product(code="mapege", name="mapEGE")
    db.add(mapege)
    db.commit()
    paket = _plan(db, "colege-mapege-paket", [urun_colege, mapege], "15000.00")
    a = _abonelik(db, musteri.id, plan_colege)
    b = _abonelik(db, musteri.id, paket)
    _ode(client, admin_headers, _siparis(client, auth_headers, plan_soru, base_subscription_id=a.id).json())

    colege_dosya = _kurulum_dosyasi(tmp_path / "a")
    r = client.post(f"/api/v1/subscriptions/{a.id}/offline-activation", files=[colege_dosya], headers=auth_headers)
    assert set(r.json()["payload"]["products"]) == {"colege", "colege_soru"}

    mapege_istek = activation_request(LicenseContext(product="mapege", public_keys=(), data_dir=tmp_path / "m"))
    r = client.post(f"/api/v1/subscriptions/{b.id}/offline-activation", headers=auth_headers, files=[
        _kurulum_dosyasi(tmp_path / "b"),
        ("files", ("mapege.json", json.dumps(mapege_istek).encode(), "application/json"))])
    assert r.status_code == 200
    assert set(r.json()["payload"]["products"]) == {"colege", "mapege"}


def test_tohum_varsayilan_plan_satisa_kapali(client, db, musteri, auth_headers, plan_colege):
    plan = _tohum.colege_soru_tohumla(db)
    db.commit()
    assert plan.is_active is False
    assert "colege-soru-yillik" not in {p["code"] for p in client.get("/api/v1/plans").json()}
    _abonelik(db, musteri.id, plan_colege)
    assert _siparis(client, auth_headers, plan).status_code == 404
