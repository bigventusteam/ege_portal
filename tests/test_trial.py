"""
Deneme (trial) lisansı — servis katmanı (bkz. app/services/trial.py).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import AuditEvent, Customer, Product, TrialActivation, TrialCampaign, TrialGrant, TrialLicense
from app.services.trial import (
    DuplicateTrialError,
    InstanceIdAlreadyTrialedError,
    NoActivationFilesError,
    UnknownProductError,
    create_trial_grant,
    create_trial_campaign,
    create_trial_license,
    find_active_campaign,
    get_or_create_trial_settings,
    resolve_trial_days,
    set_customer_trial_override,
)
from tests.test_offline_activation import MAPEGE_FP, SISEGE_FP, _activation_request_bytes, _hex


@pytest.fixture
def urun_sisege(db):
    p = Product(code="sisege", name="sisEGE")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ─── Süre çözümleme önceliği ─────────────────────────────────────────────────


def test_varsayilan_gun_sayisi_7(db, musteri):
    gun, kaynak = resolve_trial_days(db, musteri)
    assert gun == 7
    assert kaynak["source"] == "general"


def test_genel_ayar_degistirilebilir(db, musteri, yonetici):
    trial_service_settings = get_or_create_trial_settings(db)
    trial_service_settings.default_days = 14
    db.commit()

    gun, kaynak = resolve_trial_days(db, musteri)
    assert gun == 14
    assert kaynak["source"] == "general"


def test_kampanya_genel_ayari_gecersiz_kilar(db, musteri, yonetici):
    now = datetime.now(timezone.utc)
    create_trial_campaign(
        db, name="Ekim kampanyası", days=30, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
        created_by=yonetici,
    )

    gun, kaynak = resolve_trial_days(db, musteri)
    assert gun == 30
    assert kaynak["source"] == "campaign"


def test_musteri_override_kampanyayi_da_gecersiz_kilar(db, musteri, yonetici):
    now = datetime.now(timezone.utc)
    create_trial_campaign(
        db, name="Ekim kampanyası", days=30, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
        created_by=yonetici,
    )
    set_customer_trial_override(db, customer=musteri, days=45, updated_by=yonetici)

    gun, kaynak = resolve_trial_days(db, musteri)
    assert gun == 45
    assert kaynak["source"] == "customer_override"


def test_oncelik_musteri_kampanya_genel_hepsi_bir_arada(db, musteri, yonetici):
    """Üçü de aynı anda tanımlıyken: müşteri override > kampanya > genel."""
    genel = get_or_create_trial_settings(db)
    genel.default_days = 7
    db.commit()

    now = datetime.now(timezone.utc)
    create_trial_campaign(
        db, name="Kampanya", days=20, starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1),
        created_by=yonetici,
    )

    gun, kaynak = resolve_trial_days(db, musteri)
    assert (gun, kaynak["source"]) == (20, "campaign")  # kampanya genel'i eziyor

    set_customer_trial_override(db, customer=musteri, days=99, updated_by=yonetici)
    gun, kaynak = resolve_trial_days(db, musteri)
    assert (gun, kaynak["source"]) == (99, "customer_override")  # müşteri hepsini eziyor


# ─── Kampanya tarih aralığı ──────────────────────────────────────────────────


def test_suresi_gecmis_kampanya_uygulanmaz(db, musteri, yonetici):
    now = datetime.now(timezone.utc)
    create_trial_campaign(
        db, name="Geçen ay", days=30, starts_at=now - timedelta(days=10), ends_at=now - timedelta(days=1),
        created_by=yonetici,
    )
    gun, kaynak = resolve_trial_days(db, musteri)
    assert (gun, kaynak["source"]) == (7, "general")


def test_henuz_baslamamis_kampanya_uygulanmaz(db, musteri, yonetici):
    now = datetime.now(timezone.utc)
    create_trial_campaign(
        db, name="Gelecek ay", days=30, starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=10),
        created_by=yonetici,
    )
    gun, kaynak = resolve_trial_days(db, musteri)
    assert (gun, kaynak["source"]) == (7, "general")


def test_tam_sinirda_kampanya_uygulanir(db, musteri, yonetici):
    now = datetime.now(timezone.utc)
    create_trial_campaign(db, name="Tam şimdi", days=30, starts_at=now, ends_at=now + timedelta(days=1), created_by=yonetici)
    kampanya = find_active_campaign(db, now)
    assert kampanya is not None
    assert kampanya.days == 30


def test_cakisan_iki_kampanyada_en_son_olusturulan_kazanir(db, musteri, yonetici):
    now = datetime.now(timezone.utc)
    create_trial_campaign(
        db, name="Önce", days=15, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=5),
        created_by=yonetici,
    )
    create_trial_campaign(
        db, name="Sonra (kazanan)", days=25, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=5),
        created_by=yonetici,
    )
    gun, kaynak = resolve_trial_days(db, musteri)
    assert (gun, kaynak["campaign_name"]) == (25, "Sonra (kazanan)")


def test_hepsi_auditevente_yazilir(db, musteri, yonetici):
    now = datetime.now(timezone.utc)
    create_trial_campaign(db, name="X", days=10, starts_at=now, ends_at=now + timedelta(days=1), created_by=yonetici)
    set_customer_trial_override(db, customer=musteri, days=12, updated_by=yonetici)
    create_trial_grant(db, customer=musteri, extra_days=5, reason="test", granted_by=yonetici)

    tipler = {e.event_type for e in db.query(AuditEvent).all()}
    assert "trial.campaign_created" in tipler
    assert "trial.customer_override_set" in tipler
    assert "trial.grant_created" in tipler


# ─── Deneme lisansı üretimi ──────────────────────────────────────────────────


@pytest.fixture
def musteri2(db) -> Customer:
    c = Customer(name="Başka Kurum", email="baska@example.com")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_deneme_lisansi_uretilir(db, musteri, urun_mapege, urun_sisege, fake_imzalayici):
    doc = create_trial_license(
        db,
        customer=musteri,
        activation_files=[
            ("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP)),
            ("sisege.json", _activation_request_bytes("sisege", SISEGE_FP)),
        ],
        imzalayici=fake_imzalayici,
    )
    assert doc["payload"]["license_type"] == "trial"
    assert doc["payload"]["grace_days"] == 0
    assert set(doc["payload"]["products"]) == {"mapege", "sisege"}
    assert all(p["tier"] == "pro" for p in doc["payload"]["products"].values())

    beklenen_bitis = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    assert doc["payload"]["expires"] == beklenen_bitis

    assert db.query(TrialLicense).filter_by(customer_id=musteri.id).count() == 1
    assert db.query(TrialActivation).count() == 2


def test_dosyasiz_istek_hata_verir(db, musteri, fake_imzalayici):
    with pytest.raises(NoActivationFilesError):
        create_trial_license(db, customer=musteri, activation_files=[], imzalayici=fake_imzalayici)


def test_katalogda_olmayan_urun_hata_verir(db, musteri, urun_mapege, fake_imzalayici):
    with pytest.raises(UnknownProductError):
        create_trial_license(
            db,
            customer=musteri,
            activation_files=[("x.json", _activation_request_bytes("bilinmeyen-urun", {"instance_id": _hex("x")}))],
            imzalayici=fake_imzalayici,
        )


def test_ikinci_deneme_reddedilir(db, musteri, urun_mapege, fake_imzalayici):
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    with pytest.raises(DuplicateTrialError):
        create_trial_license(
            db, customer=musteri,
            activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
            imzalayici=fake_imzalayici,
        )


def test_farkli_urun_icin_ikinci_deneme_serbest(db, musteri, urun_mapege, urun_sisege, fake_imzalayici):
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    # sisEGE için ilk deneme — reddedilmemeli.
    doc = create_trial_license(
        db, customer=musteri,
        activation_files=[("sisege.json", _activation_request_bytes("sisege", SISEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    assert doc["payload"]["products"].keys() == {"sisege"}


def test_instance_id_baska_musteride_kullanilmissa_reddedilir(db, musteri, musteri2, urun_mapege, fake_imzalayici):
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    with pytest.raises(InstanceIdAlreadyTrialedError):
        create_trial_license(
            db, customer=musteri2,
            activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],  # AYNI instance_id
            imzalayici=fake_imzalayici,
        )

    olay = db.query(AuditEvent).filter_by(event_type="trial.instance_id_collision").one()
    assert olay.entity_id == str(musteri2.id)


def test_ayni_musterinin_farkli_instance_id_ile_ikinci_denemesi_yine_de_reddedilir(
    db, musteri, urun_mapege, fake_imzalayici
):
    """instance_id çarpışma kontrolü çapraz-müşteri kuralıdır — aynı
    müşterinin AYNI ürün için ikinci denemesi farklı bir instance_id ile
    gelse bile hâlâ DuplicateTrialError'a takılır (instance_id'den önce)."""
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    farkli_fp = {"instance_id": _hex("baska-bir-makine")}
    with pytest.raises(DuplicateTrialError):
        create_trial_license(
            db, customer=musteri,
            activation_files=[("mapege.json", _activation_request_bytes("mapege", farkli_fp))],
            imzalayici=fake_imzalayici,
        )


def test_yonetici_grant_ikinci_denemeyi_ac_ve_gun_ekler(db, musteri, urun_mapege, yonetici, fake_imzalayici):
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    grant = create_trial_grant(db, customer=musteri, extra_days=5, reason="müşteri şikayet etti", granted_by=yonetici)
    assert grant.consumed_at is None

    farkli_fp = {"instance_id": _hex("ikinci-makine")}
    doc = create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", farkli_fp))],
        imzalayici=fake_imzalayici,
    )
    # 7 (genel) + 5 (grant) = 12 gün.
    beklenen_bitis = (datetime.now(timezone.utc) + timedelta(days=12)).date().isoformat()
    assert doc["payload"]["expires"] == beklenen_bitis

    db.refresh(grant)
    assert grant.consumed_at is not None


def test_grant_tukenince_ucuncu_deneme_yine_reddedilir(db, musteri, urun_mapege, yonetici, fake_imzalayici):
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    create_trial_grant(db, customer=musteri, extra_days=5, reason=None, granted_by=yonetici)
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", {"instance_id": _hex("m2")}))],
        imzalayici=fake_imzalayici,
    )
    # grant tüketildi — üçüncü deneme yine reddedilmeli.
    with pytest.raises(DuplicateTrialError):
        create_trial_license(
            db, customer=musteri,
            activation_files=[("mapege.json", _activation_request_bytes("mapege", {"instance_id": _hex("m3")}))],
            imzalayici=fake_imzalayici,
        )


def test_birden_fazla_grant_birikmeli_toplanir_ve_hepsi_tuketilir(db, musteri, urun_mapege, yonetici, fake_imzalayici):
    """EGE lider'in kararı: tüketilmemiş TÜM grant'lar toplanır, hiçbiri
    askıda kalmaz — yalnız en sonuncusu değil."""
    create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", MAPEGE_FP))],
        imzalayici=fake_imzalayici,
    )
    grant1 = create_trial_grant(db, customer=musteri, extra_days=5, reason="birinci", granted_by=yonetici)
    grant2 = create_trial_grant(db, customer=musteri, extra_days=9, reason="ikinci", granted_by=yonetici)

    farkli_fp = {"instance_id": _hex("baska-makine-birikmeli")}
    doc = create_trial_license(
        db, customer=musteri,
        activation_files=[("mapege.json", _activation_request_bytes("mapege", farkli_fp))],
        imzalayici=fake_imzalayici,
    )
    # 7 (genel) + 5 + 9 = 21 gün — İKİ grant da birlikte uygulandı.
    beklenen_bitis = (datetime.now(timezone.utc) + timedelta(days=21)).date().isoformat()
    assert doc["payload"]["expires"] == beklenen_bitis

    db.refresh(grant1)
    db.refresh(grant2)
    assert grant1.consumed_at is not None
    assert grant2.consumed_at is not None

    olay = db.query(AuditEvent).filter_by(event_type="trial.issued").order_by(AuditEvent.id.desc()).first()
    assert set(olay.data["grant_ids"]) == {grant1.id, grant2.id}
