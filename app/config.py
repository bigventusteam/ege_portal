"""
Ortam değişkenlerini okuyan tek yer. colEGE'deki gibi `.env` + `os.getenv`
kullanılıyor — ekstra bir ayar kütüphanesi (pydantic-settings vb.) gerekmiyor.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        # "production" iken app/startup_checks.py EK zorunluluklar uygular
        # (SECRET_KEY boş/varsayılan OLAMAZ, COOKIE_SECURE=true OLMALI) —
        # sisEGE'nin startup_checks.py'sindeki AYNI "fail-closed" deseni.
        self.environment = os.getenv("ENVIRONMENT", "development")

        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./ege_portal.db")

        self.secret_key = os.getenv("SECRET_KEY", "")
        # Yalnız TLS sonlandıran bir ters proxy arkasında True yapın —
        # aksi halde tarayıcı çerezi hiç göndermez (bkz. colEGE'deki aynı not).
        self.cookie_secure = os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"

        self.allowed_origins = [
            o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ]

        # `app/net.py::client_ip` — `X-Forwarded-For`e YALNIZ bağlantının
        # KENDİSİ (request.client.host) bu listedeki bir IP/CIDR'deyse
        # güvenilir (ör. deploy/docker-compose.yml'deki Caddy alt ağı).
        # BOŞSA (varsayılan) başlık HİÇ okunmaz — vekilsiz/yanlış bağlı bir
        # dağıtımda saldırganın sahte bir XFF ile IP hız sınırını atlatması
        # ÖNLENİR (bkz. app/startup_checks.py'deki production uyarısı).
        self.trusted_proxies = [
            p.strip() for p in os.getenv("TRUSTED_PROXIES", "").split(",") if p.strip()
        ]

        self.bvpay_url = os.getenv("BVPAY_URL", "http://localhost:9000")
        self.bvpay_api_key = os.getenv("BVPAY_API_KEY", "")

        # Ed25519 ÖZEL anahtarının dosya YOLU (içeriği değil) — bkz.
        # app/licensing.py::EgeLisansImzalayici. Tanımlı değilse imzalama
        # açık bir hatayla durur, sessizce imzasız lisans üretilmez.
        self.ege_lisans_private_key_path = os.getenv("EGE_LISANS_OZEL_ANAHTAR", "")

        # PLAN.md §3: süre bitince bu kadar gün "grace" (uyarı) modunda
        # çalışmaya devam edilir, sonra lite/kilitli moda düşülür.
        self.license_grace_days = int(os.getenv("LICENSE_GRACE_DAYS", "14"))

        # İndirme merkezi (PLAN.md §5.4/F5) — sürüm dosyalarının saklandığı
        # kök dizin. `Release.storage_key` bu kökün ALTINDA göreli bir yoldur;
        # çözümleme app/services/releases.py::resolve_release_path'ten geçer
        # (path traversal + sembolik bağ reddi).
        self.portal_release_dir = os.getenv("PORTAL_RELEASE_DIR", "./release_storage")


settings = Settings()
