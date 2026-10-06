"""
`GET /api/v1/plans` — oturumsuz erişilebilir katalog ucu (portal frontend
satın alma akışı, 2026-10-05 görevi). Tutar istemciye HESAPLANMIŞ gelir
(`app/services/pricing.py::kdv_hesapla` — `create_order`'ın kullandığı AYNI
formül), istemci KENDİSİ hesaplamaz.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models import Plan, Price


def test_oturumsuz_erisilebilir_ve_fiyat_kdv_dahil_hesaplanir(client, plan_pro, fiyat_12_ay, urun_mapege):
    resp = client.get("/api/v1/plans")  # auth_headers YOK — kasıtlı
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1

    plan = body[0]
    assert plan["code"] == "mapege-pro"
    # Kademe yok — yanıt tier taşımaz.
    assert plan["items"] == [{"product_code": "mapege", "product_name": "mapEGE"}]
    assert len(plan["prices"]) == 1
    fiyat = plan["prices"][0]
    assert fiyat["months"] == 12
    assert fiyat["net"] == "12000.00"
    assert fiyat["vat_rate"] == "20.00"
    assert fiyat["vat_amount"] == "2400.00"
    assert fiyat["total"] == "14400.00"
    assert fiyat["currency"] == "949"


def test_pasif_plan_listelenmez(client, db, plan_pro, fiyat_12_ay):
    plan_pro.is_active = False
    db.commit()

    resp = client.get("/api/v1/plans")
    assert resp.json() == []


def test_suresi_dolmus_fiyat_listelenmez(client, db, plan_pro, fiyat_12_ay):
    fiyat_12_ay.valid_until = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    resp = client.get("/api/v1/plans")
    assert resp.json()[0]["prices"] == []


def test_henuz_baslamamis_fiyat_listelenmez(client, db, plan_pro):
    db.add(
        Price(
            plan_id=plan_pro.id,
            months=1,
            amount=Decimal("1500.00"),
            currency="949",
            vat_rate=Decimal("20.00"),
            valid_from=datetime.now(timezone.utc) + timedelta(days=1),
            valid_until=None,
        )
    )
    db.commit()

    resp = client.get("/api/v1/plans")
    assert resp.json()[0]["prices"] == []


def test_birden_fazla_sure_secenegi_ayri_ayri_listelenir(client, db, plan_pro, fiyat_12_ay):
    db.add(
        Price(
            plan_id=plan_pro.id,
            months=1,
            amount=Decimal("1200.00"),
            currency="949",
            vat_rate=Decimal("20.00"),
            valid_from=datetime.now(timezone.utc) - timedelta(days=1),
            valid_until=None,
        )
    )
    db.commit()

    resp = client.get("/api/v1/plans")
    aylar = sorted(f["months"] for f in resp.json()[0]["prices"])
    assert aylar == [1, 12]


def test_eski_fiyat_yerine_en_guncel_gecerli_fiyat_donulur(client, db, plan_pro, fiyat_12_ay):
    """Aynı `months` için iki çakışan geçerli Price varsa (ör. fiyat
    güncellemesi), en son `valid_from` kazanır — `gecerli_fiyat` ile AYNI
    kural (bkz. app/services/pricing.py)."""
    db.add(
        Price(
            plan_id=plan_pro.id,
            months=12,
            amount=Decimal("13000.00"),
            currency="949",
            vat_rate=Decimal("20.00"),
            valid_from=datetime.now(timezone.utc) - timedelta(hours=1),
            valid_until=None,
        )
    )
    db.commit()

    resp = client.get("/api/v1/plans")
    fiyatlar = resp.json()[0]["prices"]
    assert len(fiyatlar) == 1
    assert fiyatlar[0]["net"] == "13000.00"


def test_plan_yoksa_bos_liste_doner(client):
    resp = client.get("/api/v1/plans")
    assert resp.status_code == 200
    assert resp.json() == []
