"""
İndirme merkezi (PLAN.md §5.4/F5) — `GET /api/v1/downloads` ve
`GET /api/v1/downloads/{release_id}`.

Oturum açmış her kayıtlı müşteri tüm aktif İMZALI sürümleri görür ve indirir
(2026-10-06 kararı, bkz. app/services/releases.py modül docstring'i). İmzasız
sürümler müşteriye ASLA görünmez/inemez, yalnız personel (is_staff).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.deps import get_release_storage_root
from app.main import app
from app.models import AuditEvent, PackageType, Product, Release, TrialActivation, TrialLicense
from app.services.releases import PathTraversalError, resolve_release_path
from app.services.subscriptions import extend_subscription


@pytest.fixture
def urun_sisege(db):
    p = Product(code="sisege", name="sisEGE")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def depo_koku(tmp_path, client):
    """`get_release_storage_root`'u gerçek `PORTAL_RELEASE_DIR` yerine bir
    `tmp_path`'e yönlendirir — testler gerçek dosya sistemine HİÇ dokunmaz.
    `client` fixture'ı ZATEN `app.dependency_overrides`'ı set/temizliyor
    (bkz. conftest.py), burada yalnız bu EK override'ı ekliyoruz."""
    app.dependency_overrides[get_release_storage_root] = lambda: tmp_path
    yield tmp_path


def _dosya_yaz(depo_koku: Path, *parcalar: str, icerik: bytes = b"sahte paket icerigi") -> tuple[Path, str, int]:
    hedef = depo_koku.joinpath(*parcalar)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_bytes(icerik)
    return hedef, hashlib.sha256(icerik).hexdigest(), len(icerik)


def _release_olustur(db, depo_koku, *, product, version="1.0.0", signed=True, is_active=True, icerik=b"paket") -> Release:
    storage_key = f"{product.code}/{version}/docker-linux/{product.code}-{version}.zip"
    _dosya, sha256, boyut = _dosya_yaz(depo_koku, *storage_key.split("/"), icerik=icerik)
    release = Release(
        product_id=product.id,
        version=version,
        package_type=PackageType.DOCKER_LINUX,
        os="linux",
        arch="x64",
        file_name=f"{product.code}-{version}.zip",
        size_bytes=boyut,
        sha256=sha256,
        storage_key=storage_key,
        signed=signed,
        is_active=is_active,
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    return release


def _aktif_abonelik(db, musteri, plan_pro):
    sub = extend_subscription(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)
    db.commit()
    return sub


def _suresi_dolmus_abonelik(db, musteri, plan_pro):
    sub = extend_subscription(db, customer_id=musteri.id, plan_id=plan_pro.id, months=12)
    sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    return sub


def _aktif_deneme_lisansi(db, musteri, urun):
    trial = TrialLicense(
        customer_id=musteri.id,
        payload={"schema": 2, "license_type": "trial"},
        signature="fake-sig",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(trial)
    db.flush()
    db.add(TrialActivation(trial_license_id=trial.id, product_id=urun.id, instance_id_hash="a" * 64, fingerprint="{}"))
    db.commit()
    return trial


# ─── Hak var/yok ──────────────────────────────────────────────────────────────


def test_aktif_abonelikle_surum_listelenir_ve_indirilebilir(
    client, db, kullanici, auth_headers, musteri, plan_pro, urun_mapege, depo_koku
):
    _aktif_abonelik(db, musteri, plan_pro)
    release = _release_olustur(db, depo_koku, product=urun_mapege, icerik=b"gercek paket baytlari")

    liste = client.get("/api/v1/downloads", headers=auth_headers)
    assert liste.status_code == 200
    body = liste.json()
    assert len(body) == 1
    assert body[0]["id"] == release.id
    assert body[0]["product_code"] == "mapege"
    assert body[0]["sha256"] == release.sha256
    assert "storage_key" not in body[0]

    indir = client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers)
    assert indir.status_code == 200
    assert indir.content == b"gercek paket baytlari"
    assert indir.headers["x-checksum-sha256"] == release.sha256
    assert "mapege-1.0.0.zip" in indir.headers["content-disposition"]

    olay = db.query(AuditEvent).filter_by(event_type="release.downloaded").one()
    assert olay.entity_id == str(release.id)
    assert olay.data["customer_id"] == musteri.id
    assert olay.data["product_code"] == "mapege"


def test_aboneligi_olmayan_kayitli_musteri_imzali_surumu_indirir(
    client, db, kullanici, auth_headers, musteri, urun_mapege, depo_koku
):
    """2026-10-06 kararı: kurulum kendi 7 günlük denemesiyle başlar, indirme
    için abonelik/portal denemesi GEREKMEZ — oturum açmış her kayıtlı
    müşteri aktif imzalı sürümü indirir; indirme müşteri kimliğiyle audit'e
    yazılır."""
    release = _release_olustur(db, depo_koku, product=urun_mapege)

    liste = client.get("/api/v1/downloads", headers=auth_headers)
    assert [r["id"] for r in liste.json()] == [release.id]

    indir = client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers)
    assert indir.status_code == 200
    olay = db.query(AuditEvent).filter_by(event_type="release.downloaded").one()
    assert olay.data["customer_id"] == musteri.id


def test_suresi_dolmus_abonelik_indirmeyi_engellemez(
    client, db, kullanici, auth_headers, musteri, plan_pro, urun_mapege, depo_koku
):
    """Abonelik bitince ürünün kendi kilidi devreye girer; paket indirmek
    (yeniden kurulum, güncelleme) yine mümkün olmalı."""
    _suresi_dolmus_abonelik(db, musteri, plan_pro)
    release = _release_olustur(db, depo_koku, product=urun_mapege)

    assert [r["id"] for r in client.get("/api/v1/downloads", headers=auth_headers).json()] == [release.id]
    assert client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers).status_code == 200


def test_aktif_deneme_lisansiyla_da_indirilebilir(client, db, kullanici, auth_headers, musteri, urun_mapege, depo_koku):
    _aktif_deneme_lisansi(db, musteri, urun_mapege)
    release = _release_olustur(db, depo_koku, product=urun_mapege)

    liste = client.get("/api/v1/downloads", headers=auth_headers)
    assert len(liste.json()) == 1

    indir = client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers)
    assert indir.status_code == 200


def test_tum_urunlerin_imzali_surumleri_listelenir(
    client, db, kullanici, auth_headers, musteri, plan_pro, urun_mapege, urun_sisege, depo_koku
):
    """Müşterinin yalnız mapege aboneliği var — sisege sürümü de görünür ve
    indirilebilir (ürün seçimi abonelikle sınırlı değil)."""
    _aktif_abonelik(db, musteri, plan_pro)
    mapege_surumu = _release_olustur(db, depo_koku, product=urun_mapege, version="1.0.0")
    sisege_surumu = _release_olustur(db, depo_koku, product=urun_sisege, version="1.0.0")

    liste = client.get("/api/v1/downloads", headers=auth_headers)
    assert {r["id"] for r in liste.json()} == {mapege_surumu.id, sisege_surumu.id}
    assert client.get(f"/api/v1/downloads/{sisege_surumu.id}", headers=auth_headers).status_code == 200


def test_olmayan_surum_404(client, kullanici, auth_headers, depo_koku):
    assert client.get("/api/v1/downloads/99999", headers=auth_headers).status_code == 404


def test_oturumsuz_401_doner(client, depo_koku):
    assert client.get("/api/v1/downloads").status_code == 401


# ─── İmzasız sürüm — yalnız personel ─────────────────────────────────────────


def test_imzasiz_surum_musteriye_404_personele_gorunur(
    client, db, kullanici, auth_headers, musteri, plan_pro, urun_mapege, admin_headers, depo_koku
):
    _aktif_abonelik(db, musteri, plan_pro)  # aboneliği olsa bile imzasız'ı göremeyecek
    release = _release_olustur(db, depo_koku, product=urun_mapege, signed=False)

    musteri_liste = client.get("/api/v1/downloads", headers=auth_headers)
    assert musteri_liste.json() == []
    musteri_indir = client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers)
    assert musteri_indir.status_code == 404

    # Personel imzasız sürümü görmeli ve indirebilmeli (test/QA).
    personel_liste = client.get("/api/v1/downloads", headers=admin_headers)
    assert [r["id"] for r in personel_liste.json()] == [release.id]
    assert personel_liste.json()[0]["signed"] is False

    personel_indir = client.get(f"/api/v1/downloads/{release.id}", headers=admin_headers)
    assert personel_indir.status_code == 200


def test_pasif_surum_kimseye_gorunmez(client, db, kullanici, auth_headers, musteri, plan_pro, urun_mapege, admin_headers, depo_koku):
    """`is_active=False` — yayından kaldırılmış, personel için bile gizli."""
    _aktif_abonelik(db, musteri, plan_pro)
    release = _release_olustur(db, depo_koku, product=urun_mapege, is_active=False)

    assert client.get("/api/v1/downloads", headers=auth_headers).json() == []
    assert client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/downloads", headers=admin_headers).json() == []
    assert client.get(f"/api/v1/downloads/{release.id}", headers=admin_headers).status_code == 404


# ─── Path traversal / sembolik bağ ───────────────────────────────────────────


def test_path_traversal_mutlak_yol_reddedilir(tmp_path):
    with pytest.raises(PathTraversalError):
        resolve_release_path(tmp_path, "/etc/passwd")


def test_path_traversal_ust_dizin_reddedilir(tmp_path):
    with pytest.raises(PathTraversalError):
        resolve_release_path(tmp_path, "../../etc/passwd")
    with pytest.raises(PathTraversalError):
        resolve_release_path(tmp_path, "mapege/../../disari.txt")


def test_path_traversal_var_olmayan_dosya_bulunamadi_hatasi(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_release_path(tmp_path, "mapege/1.0.0/yok.zip")


def test_path_traversal_sembolik_bag_reddedilir(tmp_path):
    disari = tmp_path.parent / "disaridaki_dosya.txt"
    disari.write_text("sir icerik")
    try:
        (tmp_path / "bag.zip").symlink_to(disari)
    except (OSError, NotImplementedError):
        pytest.skip("bu ortamda sembolik bağ oluşturulamıyor (ör. Windows'ta Geliştirici Modu kapalı)")

    with pytest.raises(PathTraversalError):
        resolve_release_path(tmp_path, "bag.zip")


def test_path_traversal_bozuk_storage_key_indirmede_500_doner_detay_sizdirmaz(
    client, db, kullanici, auth_headers, musteri, plan_pro, urun_mapege, depo_koku
):
    """`storage_key` normalde yalnız scripts/surum_yayinla.py tarafından
    yazılır — ama DB satırı bir şekilde bozulsa/kurcalansa bile indirme ucu
    güvenli şekilde BAŞARISIZ olmalı, iç yol/sebep istemciye SIZMAMALI."""
    _aktif_abonelik(db, musteri, plan_pro)
    release = Release(
        product_id=urun_mapege.id,
        version="1.0.0",
        package_type=PackageType.DOCKER_LINUX,
        os="linux",
        arch="x64",
        file_name="x.zip",
        size_bytes=1,
        sha256="0" * 64,
        storage_key="../disari.zip",
        signed=True,
    )
    db.add(release)
    db.commit()

    resp = client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers)
    assert resp.status_code == 500
    assert "disari" not in resp.text
    assert str(depo_koku) not in resp.text
