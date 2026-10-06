"""Gömülü kurulum denemesi — lisans doğrulama/imzalama ALTYAPISINDAN
TAMAMEN AYRI, imzasız bir yerel mekanizma: "hiç lisans yüklenmemiş bir
kurulum ilk çalıştırmadan itibaren N gün çalışsın" kuralı.

Bu, ``schema_v2.py``'nin ``license_type: "trial"`` alanından (portalın
ürettiği GERÇEK, imzalı bir deneme lisansı) TAMAMEN FARKLI bir şeydir — o
lisans VARSA zaten normal v2 doğrulama/süre kuralları geçerlidir, bu modüle
hiç gelinmez. Bu modül yalnızca HİÇ LİSANS YOKKEN devreye girer.

Süreyi (``gun``) ÇAĞIRAN ÜRÜN belirler — bu modül HİÇBİR ORTAM DEĞİŞKENİ
OKUMAZ. Bilinçli: müşterinin env ile deneme süresini uzatabildiği bir kaçış
kapısı YOK (bkz. ege_portal/PLAN.md §8 madde 7 — süreyi yalnız üretici,
genel olarak ya da müşteri bazında/kampanya için, KOD/VERİ üzerinden
değiştirir, env üzerinden değil).

İlk çalıştırma zamanı ``ctx.data_dir``'de, ``instance_id`` ile AYNI dizinde,
ayrı bir dosyada saklanır. Dosya yoksa ŞİMDİKİ zamanla oluşturulur; yazma
gerçekten kalıcılaşmıyorsa (bazı ağ/overlay bağlama noktaları yazmayı
sessizce kabul edip kalıcılaştırmaz — bkz. ``fingerprint._instance_id``'nin
AYNI disiplini) ya da hiç okunamıyorsa fail-closed "süresi dolmuş" sayılır —
sessizce sınırsız bir deneme üretmek yerine.

Saat geri alma tespiti ``clock.check_clock`` ile yapılır (kendi ayrı durum
dosyasında — lisansın ``license_state.json``'ından BAĞIMSIZ, deneme lisanstan
önce/lisanssız devreye girdiği için)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .clock import check_clock
from .context import LicenseContext

_TRIAL_STARTED_FILENAME = "trial_started_at"
_TRIAL_CLOCK_STATE_FILENAME = "trial_clock_state.json"


def _trial_started_file(ctx: LicenseContext) -> Path:
    return Path(ctx.data_dir) / _TRIAL_STARTED_FILENAME


def _trial_clock_state_file(ctx: LicenseContext) -> Path:
    return Path(ctx.data_dir) / _TRIAL_CLOCK_STATE_FILENAME


def _read_or_create_started_at(path: Path) -> datetime | None:
    """İlk çalıştırma zamanını okur; dosya yoksa ŞİMDİ (UTC) ile oluşturur.
    Okunamıyor/yazılamıyor/kalıcılaşmıyorsa ``None`` — çağıran bunu
    fail-closed "süresi dolmuş" sayar."""
    try:
        if path.exists():
            metin = path.read_text(encoding="utf-8").strip()
            return datetime.fromisoformat(metin)
        now = datetime.now(timezone.utc)
        deger = now.isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(deger, encoding="utf-8")
        if path.read_text(encoding="utf-8").strip() != deger:
            return None
        return now
    except Exception:
        return None


def kurulum_deneme_baslat(ctx: LicenseContext) -> None:
    """Kurulum denemesinin başlangıç zamanını, HENÜZ KAYITLI DEĞİLSE, ŞİMDİ
    (UTC) olarak kaydeder — lisans durumu ne olursa olsun. İdempotenttir:
    dosya zaten varsa hiç dokunmaz.

    Ürün başlatılırken (lifespan/startup) TEK NOKTADA, HER ZAMAN çağrılmalı
    — yalnız lisanssızken değil. Amaç: "geçerli bir lisansla kurulup aylar
    sonra süresi dolan bir kurulum, süre dolduğu ANDA taze bir 7 günlük
    kurulum denemesi kazanmasın" — bu çağrı yapılmazsa deneme penceresi
    yalnız ``kurulum_deneme_durumu`` İLK KEZ (lisanssızken) çağrıldığında
    açılır, ki bu da tam olarak istenmeyen "bonus grace" hatasıdır.

    Geçiş kuralı: bu sürümden önce kurulmuş, dosyası hiç olmayan bir
    kurulum bu çağrıda "şimdi" ile başlar (bu, o kurulum için lisans
    bitince kullanılamayan, bir kerelik bir pencere anlamına gelir — bkz.
    README).

    Yazma başarısız olursa sessizce yutulur (``_read_or_create_started_at``
    zaten kendi içinde ``except Exception`` ile fail-safe'tir): bir sonraki
    ``kurulum_deneme_durumu`` çağrısı tekrar dener ve gerekirse fail-closed
    "süresi dolmuş" döner."""
    _read_or_create_started_at(_trial_started_file(ctx))


def kurulum_deneme_durumu(ctx: LicenseContext, gun: int) -> dict:
    """Kurulum denemesinin durumu.

    ``gun`` ÇAĞIRAN ÜRÜNDEN gelir (ör. mapEGE/sisEGE kendi sabitini geçirir)
    — bu fonksiyon hiçbir ortam değişkeni OKUMAZ.

    Döner: ``{"state": "trial_active" | "trial_expired", "days_left",
    "started_at", "ends_at"}``. ``started_at``/``ends_at`` ISO 8601 dize ya
    da ``None`` (durum belirlenemiyorsa — dosya okunamıyor/yazılamıyor).

    ``days_left`` KULLANICIYA GÖSTERİLEN kalan gün sayısıdır ve TAVANLA
    (ceil) hesaplanır — TABAN (floor/``timedelta.days``) İLE DEĞİL: kurulum
    ANINDA (7 gün 0 saniye kalmışken) ``7`` gösterir, son gün (birkaç saat
    kalmışken) ``1`` gösterir. Taban kullanılsaydı kurulum anında "6 gün
    kaldı" görünürdü (7 gün - birkaç saniye = 6.99999 gün, floor 6) ve son
    saatlerde "0 gün kaldı" görünürdü (hâlâ aktifken). BU YALNIZCA GÖSTERİM
    İÇİNDİR — kilit ZAMANI (``state``) her zaman ``delta.total_seconds() <=
    0``'a bakar, ``days_left``'ten TAMAMEN bağımsızdır."""
    started_at = _read_or_create_started_at(_trial_started_file(ctx))
    if started_at is None:
        return {"state": "trial_expired", "days_left": 0, "started_at": None, "ends_at": None}

    if not check_clock(_trial_clock_state_file(ctx)):
        # Saat geri alınmış — güvenilmez; deneme süresini "uzatmak" için
        # saatin geri alınması ihtimaline karşı fail-closed süresi dolmuş say.
        return {
            "state": "trial_expired", "days_left": 0,
            "started_at": started_at.isoformat(), "ends_at": None,
        }

    ends_at = started_at + timedelta(days=gun)
    now = datetime.now(timezone.utc)
    delta = ends_at - now
    if delta.total_seconds() <= 0:
        return {
            "state": "trial_expired", "days_left": 0,
            "started_at": started_at.isoformat(), "ends_at": ends_at.isoformat(),
        }
    return {
        "state": "trial_active", "days_left": math.ceil(delta.total_seconds() / 86400),
        "started_at": started_at.isoformat(), "ends_at": ends_at.isoformat(),
    }
