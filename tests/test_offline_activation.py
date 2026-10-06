"""
Çevrimdışı aktivasyon uçtan uca — üretilen license.json GERÇEK `ege_lisans`
ile imzalanır ve GERÇEK `ege_lisans.validate_license` ile doğrulanır (fake
imzalayıcı değil — bkz. `gercek_imzalayici` fixture'ı).
"""
import hashlib
import json
from datetime import timedelta

import pytest
from ege_lisans import LicenseContext, validate_license
from ege_lisans.fingerprint import component_hash
from ege_lisans.signing import generate_keypair

from app.deps import get_imzalayici
from app.licensing import EgeLisansImzalayici
from app.main import app
from app.models import Activation, AuditEvent, Customer, IssuedLicense, Plan, PlanItem, Product, Subscription, User
from app.routers.auth import issue_session_token
from app.security import hash_password
from app.services.subscriptions import extend_subscription


@pytest.fixture
def anahtar_cifti(tmp_path):
    key_path = tmp_path / "test_key.pem"
    public_key_hex = generate_keypair(key_path)
    return key_path, public_key_hex


@pytest.fixture
def gercek_imzalayici(anahtar_cifti):
    key_path, _ = anahtar_cifti
    return EgeLisansImzalayici(private_key_path=key_path)


@pytest.fixture(autouse=True)
def _gercek_imzalayiciyi_bagla(client, gercek_imzalayici):
    """Bu dosyadaki testler `FakeImzalayici` yerine GERÇEK imzalamayı
    kullanır — `client` fixture'ının varsayılan override'ını değiştiriyoruz."""
    app.dependency_overrides[get_imzalayici] = lambda: gercek_imzalayici
    yield


@pytest.fixture
def urun_sisege(db):
    p = Product(code="sisege", name="sisEGE")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def paket_plan(db, urun_mapege, urun_sisege):
    plan = Plan(code="paket-pro", name="mapEGE Pro + sisEGE Standard")
    db.add(plan)
    db.flush()
    db.add(PlanItem(plan_id=plan.id, product_id=urun_mapege.id, tier="pro"))
    db.add(PlanItem(plan_id=plan.id, product_id=urun_sisege.id, tier="standard"))
    db.commit()
    db.refresh(plan)
    return plan


@pytest.fixture
def aktif_abonelik(db, musteri, paket_plan) -> Subscription:
    sub = extend_subscription(db, customer_id=musteri.id, plan_id=paket_plan.id, months=12)
    db.commit()
    db.refresh(sub)
    return sub


def _activation_request_bytes(product: str, fingerprint: dict) -> bytes:
    return json.dumps(
        {
            "product": product,
            "schema": 1,
            "created": "2026-09-25T00:00:00+00:00",
            "hostname_hint": "test-host",
            "fingerprint": {"components": fingerprint},
        }
    ).encode("utf-8")


def _hex(seed: str) -> str:
    """Gerçek `component_hash` çıktısıyla aynı BİÇİMDE (64 küçük harf hex) —
    portal, imzalama dışında bu değerlerin nasıl üretildiğiyle ilgilenmez,
    yalnızca biçimi doğrular."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


MAPEGE_FP = {"instance_id": _hex("mapege-instance-abc"), "machine_id": _hex("mapege-machine-xyz")}
SISEGE_FP = {"instance_id": _hex("sisege-instance-abc"), "machine_id": _hex("sisege-machine-xyz")}


def _yukle(client, sub_id, auth_headers, *, mapege_fp=MAPEGE_FP, sisege_fp=SISEGE_FP):
    files = [
        ("files", ("mapege_activation.json", _activation_request_bytes("mapege", mapege_fp), "application/json")),
        ("files", ("sisege_activation.json", _activation_request_bytes("sisege", sisege_fp), "application/json")),
    ]
    return client.post(f"/api/v1/subscriptions/{sub_id}/offline-activation", files=files, headers=auth_headers)


def test_ucdan_uca_lisans_ege_lisans_ile_dogrulanir(
    client, db, kullanici, auth_headers, aktif_abonelik, anahtar_cifti, tmp_path
):
    _, public_key_hex = anahtar_cifti

    resp = _yukle(client, aktif_abonelik.id, auth_headers)
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["payload"]["schema"] == 2
    assert set(doc["payload"]["products"]) == {"mapege", "sisege"}
    assert doc["payload"]["activation"]["mode"] == "offline"
    assert doc["payload"]["expires"] == aktif_abonelik.current_period_end.date().isoformat()
    assert doc["payload"]["grace_days"] == 14

    # GERÇEK ege_lisans doğrulaması — her ürün kendi tier'ı ve kendi
    # parmak iziyle "valid" dönmeli.
    for product, tier, fp in [("mapege", "pro", MAPEGE_FP), ("sisege", "standard", SISEGE_FP)]:
        ctx = LicenseContext(product=product, public_keys=(public_key_hex,), data_dir=tmp_path / f"data_{product}")
        sonuc = validate_license(doc, ctx, fingerprint=fp)
        assert sonuc["state"] == "valid", sonuc
        assert sonuc["tier"] == tier

    # Yanlış parmak izi → fingerprint_mismatch.
    ctx = LicenseContext(product="mapege", public_keys=(public_key_hex,), data_dir=tmp_path / "data_yanlis")
    sonuc = validate_license(doc, ctx, fingerprint={"instance_id": _hex("baska-makine"), "machine_id": _hex("baska")})
    assert sonuc["state"] == "fingerprint_mismatch"

    # Abonelikte olmayan ürün → missing.
    ctx = LicenseContext(product="colege", public_keys=(public_key_hex,), data_dir=tmp_path / "data_colege")
    sonuc = validate_license(doc, ctx, fingerprint={"instance_id": _hex("x")})
    assert sonuc["state"] == "missing"

    # Activation + IssuedLicense kayıtları tutuldu mu? Tam olarak BİR
    # IssuedLicense — offline_activation.py artık `get_or_create_license_key`
    # kullanıyor (ensure_license_key DEĞİL), bu yüzden gereksiz bir
    # "online tarzı" placeholder ikinci satır oluşmuyor (bkz.
    # app/services/licenses.py docstring'i).
    lisans_kaydi = db.query(IssuedLicense).filter_by(subscription_id=aktif_abonelik.id).one()
    assert lisans_kaydi.signature == doc["signature"]
    aktivasyonlar = db.query(Activation).filter_by(license_key_id=lisans_kaydi.license_key_id).all()
    assert len(aktivasyonlar) == 2
    assert {a.mode.value for a in aktivasyonlar} == {"offline"}


def test_suresi_dolmus_abonelik_409_doner(client, db, kullanici, auth_headers, aktif_abonelik):
    aktif_abonelik.current_period_end = aktif_abonelik.current_period_end - timedelta(days=400)
    db.commit()

    resp = _yukle(client, aktif_abonelik.id, auth_headers)
    assert resp.status_code == 409


def test_abonelikte_olmayan_urun_dosyasi_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    files = [
        ("files", ("mapege_activation.json", _activation_request_bytes("mapege", MAPEGE_FP), "application/json")),
        ("files", ("sisege_activation.json", _activation_request_bytes("sisege", SISEGE_FP), "application/json")),
        ("files", ("colege_activation.json", _activation_request_bytes("colege", {"instance_id": _hex("colege-x")}), "application/json")),
    ]
    resp = client.post(f"/api/v1/subscriptions/{aktif_abonelik.id}/offline-activation", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_eksik_urun_dosyasi_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    """Abonelikte 2 ürün var (mapege+sisege) ama yalnız 1 dosya yüklendi."""
    files = [("files", ("mapege_activation.json", _activation_request_bytes("mapege", MAPEGE_FP), "application/json"))]
    resp = client.post(f"/api/v1/subscriptions/{aktif_abonelik.id}/offline-activation", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_bozuk_json_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    files = [
        ("files", ("mapege_activation.json", b"{bozuk json", "application/json")),
        ("files", ("sisege_activation.json", _activation_request_bytes("sisege", SISEGE_FP), "application/json")),
    ]
    resp = client.post(f"/api/v1/subscriptions/{aktif_abonelik.id}/offline-activation", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_fingerprint_alani_eksik_dosya_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    bozuk = json.dumps({"product": "mapege", "schema": 1}).encode("utf-8")
    files = [
        ("files", ("mapege_activation.json", bozuk, "application/json")),
        ("files", ("sisege_activation.json", _activation_request_bytes("sisege", SISEGE_FP), "application/json")),
    ]
    resp = client.post(f"/api/v1/subscriptions/{aktif_abonelik.id}/offline-activation", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_baskasinin_aboneligine_erisim_404_doner(db, client, auth_headers, aktif_abonelik):
    """IDOR: `auth_headers` başka bir müşteriye (musteri fixture'ı DEĞİL,
    `kullanici` fixture'ının customer'ı) ait — bkz. conftest. Burada AYRI
    bir müşteri/kullanıcı ile aboneliğe erişmeye çalışıyoruz."""
    baska_musteri = Customer(name="Başka Kurum", email="baska@example.com")
    db.add(baska_musteri)
    db.flush()
    baska_kullanici = User(customer_id=baska_musteri.id, email="baska-user@example.com", password_hash=hash_password("x"))
    db.add(baska_kullanici)
    db.commit()
    db.refresh(baska_kullanici)

    baska_headers = {"Authorization": f"Bearer {issue_session_token(baska_kullanici.id)}"}
    resp = _yukle(client, aktif_abonelik.id, baska_headers)
    assert resp.status_code == 404


def test_oturumsuz_401_doner(client, aktif_abonelik):
    resp = _yukle(client, aktif_abonelik.id, auth_headers={})
    assert resp.status_code == 401


def test_var_olmayan_abonelik_404_doner(client, kullanici, auth_headers):
    resp = _yukle(client, 999999, auth_headers)
    assert resp.status_code == 404


# ─── Lisans kaçağı düzeltmesi — bkz. offline_activation.py modül docstring'i ─


def test_yalniz_hostname_iceren_istek_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    """Açığın ta kendisi: instance_id/machine_id yok, yalnız hostname —
    çapasız lisans k-of-n'e düşüp aynı hostname'deki her makinede geçerli
    olurdu. Artık instance_id zorunlu olduğu için 422."""
    kacak_fp = {"hostname": _hex("ortak-ofis-bilgisayari")}
    resp = _yukle(client, aktif_abonelik.id, auth_headers, mapege_fp=kacak_fp)
    assert resp.status_code == 422


def test_instance_id_eksik_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    fp = {"machine_id": _hex("sadece-machine-id")}
    resp = _yukle(client, aktif_abonelik.id, auth_headers, mapege_fp=fp)
    assert resp.status_code == 422


def test_bilinmeyen_bilesen_adi_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    fp = {"instance_id": _hex("x"), "makine_seri_no": _hex("uydurma-bilesen")}
    resp = _yukle(client, aktif_abonelik.id, auth_headers, mapege_fp=fp)
    assert resp.status_code == 422


def test_hex_olmayan_deger_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    fp = {"instance_id": "bu-bir-sha256-hex-degil"}
    resp = _yukle(client, aktif_abonelik.id, auth_headers, mapege_fp=fp)
    assert resp.status_code == 422


def test_buyuk_harfli_hex_reddedilir(client, kullanici, auth_headers, aktif_abonelik):
    """Küçük harf zorunlu — `component_hash` (`hashlib...hexdigest()`) hep
    küçük harf üretir, büyük harf gelen bir dosya şüphelidir."""
    fp = {"instance_id": _hex("x").upper()}
    resp = _yukle(client, aktif_abonelik.id, auth_headers, mapege_fp=fp)
    assert resp.status_code == 422


def test_buyuk_dosya_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    from app.services.activation_request import MAX_ACTIVATION_REQUEST_BYTES

    buyuk_deger = "a" * (MAX_ACTIVATION_REQUEST_BYTES + 1000)
    buyuk_dosya = json.dumps(
        {"product": "mapege", "fingerprint": {"components": {"instance_id": buyuk_deger}}}
    ).encode("utf-8")
    files = [
        ("files", ("mapege_activation.json", buyuk_dosya, "application/json")),
        ("files", ("sisege_activation.json", _activation_request_bytes("sisege", SISEGE_FP), "application/json")),
    ]
    resp = client.post(f"/api/v1/subscriptions/{aktif_abonelik.id}/offline-activation", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_gecerli_istek_hala_valid_doner(client, db, kullanici, auth_headers, aktif_abonelik, anahtar_cifti, tmp_path):
    """Sıkılaştırmanın MEŞRU, doğru biçimli istekleri reddetmediğini
    doğrular — düzeltmeden önceki uçtan uca testle aynı, kısaltılmış hâli."""
    _, public_key_hex = anahtar_cifti
    resp = _yukle(client, aktif_abonelik.id, auth_headers)
    assert resp.status_code == 200
    doc = resp.json()

    ctx = LicenseContext(product="mapege", public_keys=(public_key_hex,), data_dir=tmp_path / "data")
    sonuc = validate_license(doc, ctx, fingerprint=MAPEGE_FP)
    assert sonuc["state"] == "valid"


# ─── "unknown" instance_id + çarpışma tespiti (EGE lider'in ikinci turu) ────


def test_bilinen_kotu_instance_id_422_doner(client, kullanici, auth_headers, aktif_abonelik):
    """Veri dizini okunamaz/yazılamazsa ege_lisans._instance_id() sabit
    "unknown" döner — bunun hash'i BİLİNEN bir kötü değerdir, kabul
    edilmemeli (bkz. offline_activation.py modül docstring'i)."""
    kotu = component_hash("mapege", "instance_id", "unknown")
    resp = _yukle(client, aktif_abonelik.id, auth_headers, mapege_fp={"instance_id": kotu})
    assert resp.status_code == 422
    assert "kurulum kimliği okunamadı" in resp.json()["detail"]


def test_bilinen_kotu_instance_id_urune_ozgu(client, kullanici, auth_headers, aktif_abonelik):
    """Kötü hash `component_hash(product, ...)` ile ürüne göre değişir —
    mapEGE için 'unknown' hash'i sisEGE dosyasında normal bir değer gibi
    görünmemeli (yanlışlıkla başka ürünün verisini reddetmesin)."""
    mapege_icin_kotu = component_hash("mapege", "instance_id", "unknown")
    # sisEGE dosyasına mapEGE'nin kötü hash'ini koyuyoruz — sisEGE için
    # GEÇERSİZ bir "unknown" testi değil, yalnızca rastgele-görünen (ama
    # aslında formatı doğru) bir değer; reddedilmemeli.
    resp = _yukle(client, aktif_abonelik.id, auth_headers, sisege_fp={"instance_id": mapege_icin_kotu})
    assert resp.status_code == 200


def test_instance_id_carpismasi_reddetmez_ama_isaretler(
    client, db, kullanici, auth_headers, aktif_abonelik, paket_plan
):
    """Aynı instance_id hash'i başka bir müşterinin aktif Activation'ında
    varsa istek REDDEDİLMEZ (yanlış pozitif riski), yalnız AuditEvent
    yazılır — kurulum kimliği dosyasının kopyalanmış olabileceğinin
    sinyali (bkz. offline_activation.py modül docstring'i)."""
    resp1 = _yukle(client, aktif_abonelik.id, auth_headers)
    assert resp1.status_code == 200

    baska_musteri = Customer(name="Kopya Kurum", email="kopya@example.com")
    db.add(baska_musteri)
    db.flush()
    baska_kullanici = User(
        customer_id=baska_musteri.id, email="kopya-user@example.com", password_hash=hash_password("x")
    )
    db.add(baska_kullanici)
    db.commit()
    db.refresh(baska_kullanici)

    baska_abonelik = extend_subscription(db, customer_id=baska_musteri.id, plan_id=paket_plan.id, months=12)
    db.commit()
    db.refresh(baska_abonelik)

    baska_headers = {"Authorization": f"Bearer {issue_session_token(baska_kullanici.id)}"}
    # AYNI MAPEGE_FP/SISEGE_FP — instance_id dosyasını kopyalamış gibi.
    resp2 = _yukle(client, baska_abonelik.id, baska_headers)
    assert resp2.status_code == 200  # reddedilmedi

    carpismalar = db.query(AuditEvent).filter_by(event_type="activation.instance_id_collision").all()
    assert {c.data["product"] for c in carpismalar} == {"mapege", "sisege"}
    for c in carpismalar:
        assert c.data["new_customer_id"] == baska_musteri.id
        assert c.data["existing_customer_id"] == kullanici.customer_id


def test_ayni_musterinin_tekrar_aktivasyonu_carpisma_sayilmaz(client, db, kullanici, auth_headers, aktif_abonelik):
    """Aynı müşteri aynı aboneliği (ör. lisansı yeniden indirmek için)
    tekrar aktive ederse bu bir çarpışma DEĞİL."""
    assert _yukle(client, aktif_abonelik.id, auth_headers).status_code == 200
    assert _yukle(client, aktif_abonelik.id, auth_headers).status_code == 200

    assert db.query(AuditEvent).filter_by(event_type="activation.instance_id_collision").count() == 0
