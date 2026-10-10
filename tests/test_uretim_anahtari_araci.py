"""
`scripts/uretim_anahtari_olustur.py` — geçici dizinde, getpass sahtelenerek.
Gerçek üretim anahtarı ÜRETİLMEZ (tmp_path, test sonunda silinir).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

ARAC = Path(__file__).resolve().parents[1] / "scripts" / "uretim_anahtari_olustur.py"

P_BIRINCIL = "birincil-test-parolasi-0123"
P_YEDEK = "yedek-test-parolasi-456789"


@pytest.fixture(scope="module")
def arac():
    spec = importlib.util.spec_from_file_location("uretim_anahtari_olustur", ARAC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _girdi(*yanitlar):
    sira = iter(yanitlar)

    def sahte(_soru=""):
        return next(sira)

    return sahte


def _calistir(arac, dizin, *yanitlar):
    return arac.main(["--cikti-dizini", str(dizin)], girdi=_girdi(*yanitlar))


def test_iki_sifreli_cift_uretir_ciktida_ozel_anahtar_yok(arac, tmp_path, capsys):
    dizin = tmp_path / "anahtarlar"
    kod = _calistir(arac, dizin, P_BIRINCIL, P_BIRINCIL, P_YEDEK, P_YEDEK)
    assert kod == 0
    cikti = capsys.readouterr()
    tum = cikti.out + cikti.err

    birincil = dizin / "ege_lisans_uretim_birincil.pem"
    yedek = dizin / "ege_lisans_uretim_yedek.pem"
    acik = {}
    for yol, parola, ad in ((birincil, P_BIRINCIL, "birincil"), (yedek, P_YEDEK, "yedek")):
        pem = yol.read_bytes()
        assert pem.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")
        with pytest.raises(TypeError):
            serialization.load_pem_private_key(pem, password=None)
        with pytest.raises(ValueError):  # diğer parola açmaz — parolalar ayrı
            serialization.load_pem_private_key(pem, password=(P_YEDEK if ad == "birincil" else P_BIRINCIL).encode())
        anahtar = serialization.load_pem_private_key(pem, password=parola.encode())
        acik[ad] = anahtar.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        # özel anahtar baytları çıktıda YOK
        ham = anahtar.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption()).hex()
        assert ham not in tum
        assert pem.decode() not in tum

    assert acik["birincil"] != acik["yedek"]
    assert "PRIVATE KEY" not in tum
    assert P_BIRINCIL not in tum and P_YEDEK not in tum
    # açık anahtarlar + parmak izi + PUBLIC_KEYS satırı yazdırılır
    for ad in ("birincil", "yedek"):
        assert acik[ad] in tum
        assert arac.parmak_izi(acik[ad]) in tum
    assert f'    "{acik["birincil"]}",  # birincil' in cikti.out
    assert "PUBLIC_KEYS: tuple[str, ...] = (" in cikti.out
    assert "ÇEVRİMDIŞI YEDEK" in cikti.out

    # Portal imzalayıcısı bu dosyayı parola dosyasıyla açıp imzalayabilmeli
    from ege_lisans.keys import verify_signature

    from app.licensing import EgeLisansImzalayici

    parola_dosyasi = tmp_path / "parola"
    parola_dosyasi.write_text(P_BIRINCIL, encoding="utf-8")
    payload = {"schema": 2, "license_id": "lic_arac"}
    imza = EgeLisansImzalayici(birincil, parola_dosyasi, uretim=True).imzala(payload)
    assert verify_signature(payload, imza, [acik["birincil"], acik["yedek"]]) == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX izin bitleri")
def test_posix_dosya_izni_600(arac, tmp_path):
    dizin = tmp_path / "a"
    assert _calistir(arac, dizin, P_BIRINCIL, P_BIRINCIL, P_YEDEK, P_YEDEK) == 0
    for yol in dizin.iterdir():
        assert (yol.stat().st_mode & 0o777) == 0o600
        assert yol.stat().st_uid == os.getuid()
    assert (dizin.stat().st_mode & 0o777) == 0o700


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL")
def test_windows_acl_yalniz_calistiran_kullanici(arac, tmp_path):
    dizin = tmp_path / "a"
    assert _calistir(arac, dizin, P_BIRINCIL, P_BIRINCIL, P_YEDEK, P_YEDEK) == 0
    kullanici = os.environ["USERNAME"].lower()
    for yol in dizin.iterdir():
        acl = subprocess.run(["icacls", str(yol)], capture_output=True, text=True).stdout
        satirlar = [s.strip() for s in acl.splitlines()[:-1] if s.strip()]
        satirlar[0] = satirlar[0][len(str(yol)):].strip()
        assert len(satirlar) == 1, acl  # yalnız TEK erişim girdisi (kalıtım kapalı)
        assert kullanici in satirlar[0].lower() and "(F)" in satirlar[0]
        assert "(I)" not in acl


def test_var_olan_dosyanin_uzerine_yazmaz(arac, tmp_path, capsys):
    dizin = tmp_path / "a"
    dizin.mkdir()
    eski = dizin / "ege_lisans_uretim_yedek.pem"
    eski.write_bytes(b"ESKI-ICERIK")
    kod = _calistir(arac, dizin, P_BIRINCIL, P_BIRINCIL, P_YEDEK, P_YEDEK)
    assert kod == 2
    assert "üzerine YAZILMAZ" in capsys.readouterr().err
    assert eski.read_bytes() == b"ESKI-ICERIK"
    assert not (dizin / "ege_lisans_uretim_birincil.pem").exists()  # hiçbiri yazılmadı


def test_gizli_dosya_yaz_o_excl(arac, tmp_path):
    yol = tmp_path / "x.pem"
    yol.write_bytes(b"var")
    with pytest.raises(arac.AracHatasi, match="üzerine"):
        arac.gizli_dosya_yaz(yol, b"yeni")
    assert yol.read_bytes() == b"var"


def test_ayni_parola_reddedilir(arac, tmp_path, capsys):
    dizin = tmp_path / "a"
    kod = _calistir(arac, dizin, P_BIRINCIL, P_BIRINCIL, P_BIRINCIL, P_BIRINCIL)
    assert kod == 2
    assert "AYNI olamaz" in capsys.readouterr().err
    assert not dizin.exists()


def test_kisa_ve_eslesmeyen_parola_tekrar_sorulur(arac, tmp_path):
    dizin = tmp_path / "a"
    kod = _calistir(
        arac, dizin,
        "kisa", P_BIRINCIL, "farkli-ikinci-giris-xxxxxx", P_BIRINCIL, P_BIRINCIL,  # 3. denemede olur
        P_YEDEK, P_YEDEK,
    )
    assert kod == 0


def test_uc_basarisiz_denemede_dosya_yazilmaz(arac, tmp_path):
    dizin = tmp_path / "a"
    assert _calistir(arac, dizin, "a", "b", "c") == 2
    assert not dizin.exists()


def test_parola_argumandan_alinmaz(arac, tmp_path):
    with pytest.raises(SystemExit):
        arac.main(["--cikti-dizini", str(tmp_path), "--parola", "x"], girdi=_girdi())
