"""İstemci IP'si çözümlemesi — brute-force hız sınırlaması (app/services/
auth_throttle.py) IP başına da sayım tuttuğu için gerekli.

`X-Forwarded-For` KOŞULSUZ güvenilmez — EGE lider'in incelemesinde
yakalandı: uygulama vekilsiz/yanlış bağlanırsa (ör. bir dağıtım hatası,
TRUSTED_PROXIES hiç ayarlanmamış bir ortam) saldırgan bu başlığı ELLE
UYDURUP IP hız sınırını tamamen ATLATABİLİR. Başlık YALNIZ bağlantının
KENDİSİ (`request.client.host`) `TRUSTED_PROXIES`'teki (virgüllü IP/CIDR
listesi, bkz. app/config.py) bir ağdaysa okunur; o zaman da zincir SAĞDAN
SOLA (en yakın vekilden en uzağa) taranır, güvenilir vekiller ATLANIR, İLK
güvenilmeyen adres alınır — bu, zincire adres ekleyebilen bilinen vekillerin
ARDINDAN geldiği için güvenilir vekillerin kendisinin ilettiği değerdir.
`TRUSTED_PROXIES` BOŞSA (varsayılan) başlık HİÇ okunmaz, her zaman doğrudan
bağlantı adresine düşülür — fail-closed."""
from __future__ import annotations

import ipaddress

from starlette.requests import Request

from app.config import settings


def _agda_mi(adres: str, ag: str) -> bool:
    try:
        return ipaddress.ip_address(adres) in ipaddress.ip_network(ag, strict=False)
    except ValueError:
        return False


def _guvenilir_mi(adres: str) -> bool:
    return any(_agda_mi(adres, ag) for ag in settings.trusted_proxies)


def client_ip(request: Request) -> str:
    dogrudan = request.client.host if request.client else "bilinmiyor"

    if not settings.trusted_proxies or not _guvenilir_mi(dogrudan):
        return dogrudan

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return dogrudan

    zincir = [p.strip() for p in forwarded.split(",") if p.strip()]
    if not zincir:
        return dogrudan

    for adres in reversed(zincir):
        if not _guvenilir_mi(adres):
            return adres

    # Zincirdeki HER adres güvenilir (yalnızca bilinen iç vekiller listelenmiş,
    # olağan dışı ama imkansız değil) — en SOLDAKİ (en eski/orijinal) değere düş.
    return zincir[0]
