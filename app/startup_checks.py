"""
Süreç başlatılırken BİR KEZ çalışan, fail-closed yapılandırma kontrolleri —
sisEGE'nin `startup_checks.py`'sindeki AYNI desen (kopyalanmadı, ayrı
yazıldı): `ENVIRONMENT=production` iken yetersiz/varsayılan bir
yapılandırmayla sessizce AÇILMAK yerine süreç HİÇ BAŞLAMAZ.

`development`/`test` ortamlarında (varsayılan) HİÇBİR kontrol çalışmaz —
yerel geliştirme SECRET_KEY'siz/COOKIE_SECURE=false ile sorunsuz sürer.
"""
from __future__ import annotations

import logging

from app.config import settings

_logger = logging.getLogger("ege_portal.startup")

# Geliştirmede/örneklerde sık kullanılan, YANLIŞLIKLA production'a taşınması
# en olası değerler — bu TÜKETİCİ bir liste DEĞİL (hiçbir liste olamaz),
# yalnız en sık rastlanan kazaya karşı ek bir ağ. Asıl güvence "boş değil"
# kontrolüdür.
_BILINEN_ZAYIF_SECRET_KEY_LER = {
    "",
    "dev-only",
    "dev-only-smoke-test",
    "change-me",
    "changeme",
    "secret",
    "test",
    "test-secret",
}


class StartupConfigError(Exception):
    """`str(exc)` basılır, süreç sıfırdan FARKLI bir kodla çıkar — ASGI
    sunucusu HİÇ başlamaz (bkz. app/main.py)."""


def validate_startup_config() -> None:
    if settings.environment != "production":
        return

    if not settings.secret_key or settings.secret_key.strip().lower() in _BILINEN_ZAYIF_SECRET_KEY_LER:
        raise StartupConfigError(
            "ENVIRONMENT=production icin SECRET_KEY tanimli ve bilinen bir varsayilan/zayif deger "
            "OLMAMALI - oturum token'lari (bkz. app/routers/auth.py::issue_session_token) bu "
            "anahtarla imzalanir; tahmin edilebilir bir anahtar herkesin gecerli bir oturum "
            "uretebilmesi anlamina gelir."
        )

    if not settings.cookie_secure:
        raise StartupConfigError(
            "ENVIRONMENT=production icin COOKIE_SECURE=true OLMALI - aksi halde oturum cerezi "
            "(HttpOnly ama Secure=False) duz HTTP uzerinden de gonderilir, bir ortadaki-adam "
            "cerezi acikca okuyabilir (bkz. app/routers/auth.py::_giris_yanitla)."
        )

    # UYARI, HATA DEĞİL — TRUSTED_PROXIES boş olsa da süreç (fail-closed
    # olarak) doğru çalışır: app/net.py::client_ip basitçe X-Forwarded-For'u
    # hiç OKUMAZ, her zaman doğrudan bağlantı adresine düşer. Ama Caddy
    # arkasında (bkz. deploy/docker-compose.yml) TÜM istekler Caddy'nin
    # container IP'sinden geliyormuş GİBİ görünür — IP başına hız sınırı
    # (app/services/auth_throttle.py) o zaman FİİLEN tüm kullanıcılar için
    # TEK bir paylaşımlı sayaca döner, yanlışlıkla meşru kullanıcıları
    # birbirine kilitleyebilir. Bu, süreci DURDURACAK kadar ağır değil
    # (sessiz bir güvenlik açığı değil, yalnız hız sınırının ETKİNLİĞİNİN
    # azalması) — bu yüzden uyarı yeterli.
    if not settings.trusted_proxies:
        _logger.warning(
            "ENVIRONMENT=production ama TRUSTED_PROXIES tanımlı değil — X-Forwarded-For hiç "
            "okunmayacak, IP başına hız sınırı (app/services/auth_throttle.py) Caddy arkasında "
            "TÜM istekleri aynı IP'den geliyormuş gibi görecek. deploy/docker-compose.yml'deki "
            "Caddy alt ağını TRUSTED_PROXIES'e ekleyin."
        )
