from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import Plan, Price
from app.services.pricing import PriceNotFoundError, gecerli_fiyat


def test_gecerli_fiyat_dogru_tutari_dondurur(db, fiyat_12_ay, plan_pro):
    price = gecerli_fiyat(db, plan_pro.id, 12)
    assert price.amount == Decimal("12000.00")
    assert price.currency == "949"


def test_gecerli_fiyat_eslesmeyen_ay_icin_hata_verir(db, fiyat_12_ay, plan_pro):
    with pytest.raises(PriceNotFoundError):
        gecerli_fiyat(db, plan_pro.id, 1)


def test_gecerli_fiyat_suresi_dolmus_fiyati_gormez(db, plan_pro):
    now = datetime.now(timezone.utc)
    eski_fiyat = Price(
        plan_id=plan_pro.id,
        months=12,
        amount=Decimal("9000.00"),
        currency="949",
        vat_rate=Decimal("20.00"),
        valid_from=now - timedelta(days=60),
        valid_until=now - timedelta(days=1),
    )
    db.add(eski_fiyat)
    db.commit()

    with pytest.raises(PriceNotFoundError):
        gecerli_fiyat(db, plan_pro.id, 12)


def test_gecerli_fiyat_en_yeni_gecerli_fiyati_secer(db, plan_pro):
    now = datetime.now(timezone.utc)
    eski = Price(
        plan_id=plan_pro.id, months=12, amount=Decimal("9000.00"), currency="949",
        vat_rate=Decimal("20.00"), valid_from=now - timedelta(days=60), valid_until=None,
    )
    yeni = Price(
        plan_id=plan_pro.id, months=12, amount=Decimal("12000.00"), currency="949",
        vat_rate=Decimal("20.00"), valid_from=now - timedelta(days=1), valid_until=None,
    )
    db.add_all([eski, yeni])
    db.commit()

    price = gecerli_fiyat(db, plan_pro.id, 12)
    assert price.amount == Decimal("12000.00")
