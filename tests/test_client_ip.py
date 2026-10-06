"""
`app/net.py::client_ip` — `X-Forwarded-For` yalnız `TRUSTED_PROXIES`'teki
(IP/CIDR listesi) bir ağdan gelen bağlantılarda okunur; aksi halde (ve
`TRUSTED_PROXIES` boşken, varsayılan) başlık HİÇ okunmaz — doğrudan
bağlantı adresine düşülür (fail-closed, bkz. modül docstring'i, EGE
lider'in incelemesinde bulundu).
"""
import pytest

from app.config import settings
from app.net import client_ip


class _SahteIstemci:
    def __init__(self, host):
        self.host = host


class _SahteIstek:
    def __init__(self, host, headers=None):
        self.client = _SahteIstemci(host) if host is not None else None
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def _trusted_proxies_bos(monkeypatch):
    """Varsayılan: boş — her testin KENDİ monkeypatch'i bunu değiştirebilir."""
    monkeypatch.setattr(settings, "trusted_proxies", [])


def test_trusted_proxies_bosken_xff_hic_okunmaz():
    istek = _SahteIstek("203.0.113.9", {"x-forwarded-for": "9.9.9.9"})
    assert client_ip(istek) == "203.0.113.9"


def test_guvenilmeyen_dogrudan_baglantidan_sahte_xff_yok_sayilir(monkeypatch):
    """Saldırgan DOĞRUDAN bağlanıp sahte bir XFF göndermeye çalışırsa —
    bağlantının kendi adresi güvenilir listede OLMADIĞI için başlık hiç
    okunmaz, gerçek (sahte olmayan) bağlantı adresi döner."""
    monkeypatch.setattr(settings, "trusted_proxies", ["172.28.0.0/24"])
    istek = _SahteIstek("203.0.113.9", {"x-forwarded-for": "9.9.9.9"})
    assert client_ip(istek) == "203.0.113.9"


def test_guvenilir_vekilden_gelen_xff_okunur(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ["172.28.0.0/24"])
    istek = _SahteIstek("172.28.0.5", {"x-forwarded-for": "198.51.100.7"})
    assert client_ip(istek) == "198.51.100.7"


def test_guvenilir_iki_vekil_zinciri_dogru_cozulur(monkeypatch):
    """XFF = "gerçek-istemci, güvenilir-ara-vekil" — sağdan sola taranır,
    güvenilir ara vekil ATLANIR, ilk güvenilmeyen (gerçek istemci) alınır."""
    monkeypatch.setattr(settings, "trusted_proxies", ["172.28.0.0/24"])
    istek = _SahteIstek("172.28.0.5", {"x-forwarded-for": "198.51.100.7, 172.28.0.9"})
    assert client_ip(istek) == "198.51.100.7"


def test_zincirdeki_her_adres_guvenilirse_en_soldakine_duser(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ["172.28.0.0/24"])
    istek = _SahteIstek("172.28.0.5", {"x-forwarded-for": "172.28.0.2, 172.28.0.9"})
    assert client_ip(istek) == "172.28.0.2"


def test_guvenilir_baglantida_xff_yoksa_dogrudan_adrese_duser(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ["172.28.0.0/24"])
    istek = _SahteIstek("172.28.0.5")
    assert client_ip(istek) == "172.28.0.5"


def test_tekil_ip_de_trusted_proxies_olarak_calisir(monkeypatch):
    """CIDR değil, tam bir IP de kabul edilir (/32 gibi)."""
    monkeypatch.setattr(settings, "trusted_proxies", ["172.28.0.5"])
    istek = _SahteIstek("172.28.0.5", {"x-forwarded-for": "198.51.100.7"})
    assert client_ip(istek) == "198.51.100.7"

    istek_baska = _SahteIstek("172.28.0.6", {"x-forwarded-for": "9.9.9.9"})
    assert client_ip(istek_baska) == "172.28.0.6"  # listede değil — okunmaz
