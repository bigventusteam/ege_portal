"""
İndirme merkezi — personel tarafı: `scripts/surum_yayinla.py` ile yayınlama
ve `POST /api/v1/admin/releases/{id}/deactivate` ile yayından kaldırma.

CLI testi uçtan uca: CLI'nın kendi `main()`'i test veritabanına ve geçici bir
`PORTAL_RELEASE_DIR`'e yönlendirilir, ardından aynı sürüm müşteri uçlarından
listelenip indirilir.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.deps import get_release_storage_root
from app.main import app
from app.models import AuditEvent, PackageType, Release

_CLI = Path(__file__).resolve().parent.parent / "scripts" / "surum_yayinla.py"


@pytest.fixture
def cli(db, tmp_path, monkeypatch, client):
    """`surum_yayinla` modülünü yükler; oturumunu test veritabanına, depo
    kökünü (hem CLI hem indirme ucu için) aynı geçici dizine bağlar."""
    spec = importlib.util.spec_from_file_location("surum_yayinla", _CLI)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)

    depo = tmp_path / "depo"
    monkeypatch.setattr(modul, "SessionLocal", sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False))
    monkeypatch.setattr(settings, "portal_release_dir", str(depo))
    app.dependency_overrides[get_release_storage_root] = lambda: depo
    return modul


def _paket(tmp_path: Path, ad: str = "mapege-1.3.0.zip", icerik: bytes = b"gercek paket icerigi") -> Path:
    yol = tmp_path / "kaynak" / ad
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_bytes(icerik)
    return yol


def _yayinla_argv(personel: str, dosya: Path, *ek: str) -> list[str]:
    return [
        "--personel", personel, "--product", "mapege", "--version", "1.3.0",
        "--package-type", "docker-linux", "--os", "linux", "--arch", "x64",
        "--file", str(dosya), *ek,
    ]


# ─── CLI: yayınla → listele → indir ──────────────────────────────────────────


def test_cli_yayinla_listele_indir_uctan_uca(cli, db, tmp_path, client, yonetici, kullanici, auth_headers, urun_mapege):
    icerik = b"gercek paket icerigi" * 1000
    dosya = _paket(tmp_path, icerik=icerik)

    cli.main(_yayinla_argv(yonetici.email, dosya, "--notes", "ilk sürüm"))
    db.expire_all()

    release = db.query(Release).one()
    assert release.sha256 == hashlib.sha256(icerik).hexdigest()  # sunucuda hesaplandı
    assert release.size_bytes == len(icerik)
    assert release.storage_key == "mapege/1.3.0/docker-linux/mapege-1.3.0.zip"
    assert release.created_by_user_id == yonetici.id
    assert release.signed is True

    yayin = db.query(AuditEvent).filter_by(event_type="release.published").one()
    assert yayin.entity_id == str(release.id)
    assert yayin.data["staff_user_id"] == yonetici.id
    assert yayin.data["sha256"] == release.sha256

    liste = client.get("/api/v1/downloads", headers=auth_headers).json()
    assert [r["id"] for r in liste] == [release.id]
    assert liste[0]["sha256"] == release.sha256
    assert liste[0]["notes"] == "ilk sürüm"

    indir = client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers)
    assert indir.status_code == 200
    assert indir.content == icerik
    assert indir.headers["x-checksum-sha256"] == release.sha256
    assert "attachment" in indir.headers["content-disposition"]
    assert db.query(AuditEvent).filter_by(event_type="release.downloaded").count() == 1


def test_cli_personel_olmayan_kullaniciyla_yayinlamaz(cli, db, tmp_path, kullanici, urun_mapege):
    with pytest.raises(SystemExit):
        cli.main(_yayinla_argv(kullanici.email, _paket(tmp_path)))
    assert db.query(Release).count() == 0
    assert not (Path(settings.portal_release_dir) / "mapege").exists()


def test_cli_ayni_urun_surum_paket_tipi_ikinci_kez_yayinlanamaz(cli, db, tmp_path, yonetici, urun_mapege):
    cli.main(_yayinla_argv(yonetici.email, _paket(tmp_path)))
    with pytest.raises(SystemExit):
        cli.main(_yayinla_argv(yonetici.email, _paket(tmp_path, ad="mapege-1.3.0.zip", icerik=b"farkli")))
    db.expire_all()
    assert db.query(Release).count() == 1


def test_cli_imzasiz_yayin_onaysiz_reddedilir(cli, db, tmp_path, yonetici, urun_mapege):
    with pytest.raises(SystemExit):
        cli.main(_yayinla_argv(yonetici.email, _paket(tmp_path), "--unsigned"))
    assert db.query(Release).count() == 0


# ─── Yayından kaldırma (deactivate) ──────────────────────────────────────────


def _release(db, urun) -> Release:
    release = Release(
        product_id=urun.id, version="2.0.0", package_type=PackageType.DOCKER_LINUX, os="linux", arch="x64",
        file_name="mapege-2.0.0.zip", size_bytes=1, sha256="0" * 64,
        storage_key="mapege/2.0.0/docker-linux/mapege-2.0.0.zip", signed=True,
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    return release


def test_deactivate_personel_surumu_gizler_ve_audit_yazar(client, db, yonetici, admin_headers, kullanici, auth_headers, urun_mapege):
    release = _release(db, urun_mapege)

    resp = client.post(f"/api/v1/admin/releases/{release.id}/deactivate", json={"reason": "yanlış paket"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"release_id": release.id, "is_active": False}

    db.refresh(release)
    assert release.is_active is False
    olay = db.query(AuditEvent).filter_by(event_type="release.deactivated").one()
    assert olay.data["staff_user_id"] == yonetici.id
    assert olay.data["reason"] == "yanlış paket"

    assert client.get("/api/v1/downloads", headers=auth_headers).json() == []
    assert client.get(f"/api/v1/downloads/{release.id}", headers=auth_headers).status_code == 404


def test_deactivate_musteri_403(client, db, kullanici, auth_headers, urun_mapege):
    release = _release(db, urun_mapege)
    resp = client.post(f"/api/v1/admin/releases/{release.id}/deactivate", json={"reason": "x"}, headers=auth_headers)
    assert resp.status_code == 403
    db.refresh(release)
    assert release.is_active is True


def test_deactivate_oturumsuz_401(client, db, urun_mapege):
    release = _release(db, urun_mapege)
    assert client.post(f"/api/v1/admin/releases/{release.id}/deactivate", json={"reason": "x"}).status_code == 401


def test_deactivate_gerekce_zorunlu(client, db, admin_headers, urun_mapege):
    release = _release(db, urun_mapege)
    resp = client.post(f"/api/v1/admin/releases/{release.id}/deactivate", json={"reason": ""}, headers=admin_headers)
    assert resp.status_code == 422


def test_deactivate_olmayan_404_ikinci_kez_409(client, db, admin_headers, urun_mapege):
    assert client.post("/api/v1/admin/releases/9999/deactivate", json={"reason": "x"}, headers=admin_headers).status_code == 404
    release = _release(db, urun_mapege)
    assert client.post(f"/api/v1/admin/releases/{release.id}/deactivate", json={"reason": "x"}, headers=admin_headers).status_code == 200
    assert client.post(f"/api/v1/admin/releases/{release.id}/deactivate", json={"reason": "x"}, headers=admin_headers).status_code == 409
