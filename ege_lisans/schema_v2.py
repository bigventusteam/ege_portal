"""Şema v2 doğrulama — çoklu ürün, abonelik lisansı.

Bkz. ``ege_portal/PLAN.md`` §3. Tek lisans birden çok ürün taşır
(``payload.products``); her ürün yalnız kendi anahtarına bakar — lisansta
``product`` yoksa ``"missing"`` döner. Süre dolunca ``grace_days`` kadar ek
süre boyunca ``"grace"`` durumu döner (ürün kapanmaz), sonrasında
``"expired"``. v2 abonelik lisansıdır: ``expires`` zorunludur — süresiz
lisans yalnız şema v1'de vardır.

Parmak izi: her ürün ayrı kurulumda çalışabileceği için (paket satışında
mapEGE ve sisEGE farklı makinelerde olabilir) önce
``products[product].fingerprint.components`` aranır; orada yoksa üst düzey
``payload.fingerprint.components``'e düşülür (tek ürünlü lisanslar için
kısayol — ürün başına tekrar yazmaya gerek kalmaz).

Alan tipleri doğrulanır (``grace_days`` int ve >= 0, ``tier`` dolu str,
``expires`` "YYYY-MM-DD"); uymayan belge imza doğrulamasına girmeden
``"malformed"`` döner — imzalı bir alan olsa da yanlış tip ürünü
çökertmemeli (ör. ``grace_days`` string gelirse karşılaştırma patlar).

``license_type`` (isteğe bağlı): ``"subscription"`` (alan yoksa/``None``sa
VARSAYILAN) ya da ``"trial"`` — portalın ürettiği GERÇEK, imzalı bir deneme
lisansını normal bir abonelikten ayırt eder (raporlama/destek amaçlı; ikisi
de AYNI doğrulama/süre/tavan kurallarına tabidir). Bu, ürünlerin kendi
gömülü, imzasız "ilk çalıştırmadan N gün" kurulum denemesinden (bkz.
``trial.py``) TAMAMEN AYRIDIR. Tanınmayan bir değer ``"malformed"`` sayılır.

Çapa zorunluluğu (v2'YE ÖZGÜ): doğrulanan ürünün çözümlenen fingerprint'i
(ürün-özel ya da üst düzey) ``instance_id`` İÇERMİYORSA sonuç
``"fingerprint_missing_anchor"`` döner — ``fingerprint_matches``'e hiç
girilmez. Gerekçe: ``fingerprint_matches``'in çapasız (v1 uyumluluk)
dalı "en az k bileşen eşleşsin" kuralına düşer; yalnız ``hostname`` gibi
zayıf/paylaşılabilir bir bileşen taşıyan bir lisans bu dalda AYNI
hostname'e sahip sınırsız kuruluma geçerli olurdu. Bu risk yalnız
üreticinin (portalın) müşteri aktivasyon dosyasını doğrulamadan
imzalaması durumunda gerçek bir açığa dönüşür — kütüphane bunu portaldan
BAĞIMSIZ olarak da kapatır. Bu kontrol YALNIZ v2'dedir; ``schema_v1.py``
sahadaki eski mapEGE lisanslarını bozmamak için çapasız k-of-n davranışını
AYNEN korur (bkz. o dosyanın kendi docstring'i).
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .clock import check_clock
from .fingerprint import DEFAULT_ANCHOR_COMPONENTS, DEFAULT_MIN_MATCH, fingerprint_matches
from .keys import verify_signature

_VALID_LICENSE_TYPES = ("subscription", "trial")


def validate_v2(
    doc: dict,
    *,
    product: str,
    public_keys: Sequence[str],
    current_fingerprint: dict[str, str],
    state_file: Path,
    min_match: int = DEFAULT_MIN_MATCH,
    anchor_components: tuple[str, ...] = DEFAULT_ANCHOR_COMPONENTS,
) -> dict:
    base = {
        "schema": 2, "state": "malformed", "product": product,
        "license_id": None, "subscription_id": None, "customer": None,
        "tier": None, "issued": None, "expires": None, "grace_days": None,
        "days_left": None, "grace_days_left": None, "license_type": None,
        "matched": 0, "required": min_match, "key": None, "activation": None,
    }
    payload = doc.get("payload") if isinstance(doc, dict) else None
    signature = doc.get("signature") if isinstance(doc, dict) else None
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return base

    products = payload.get("products")
    if not isinstance(products, dict) or product not in products:
        base["state"] = "missing"
        return base

    product_entry = products.get(product)
    if not isinstance(product_entry, dict):
        product_entry = {}

    license_type = payload.get("license_type")
    if license_type is None:
        license_type = "subscription"

    base.update({
        "license_id": payload.get("license_id"),
        "subscription_id": payload.get("subscription_id"),
        "customer": payload.get("customer"),
        "tier": product_entry.get("tier"),
        "issued": payload.get("issued"),
        "expires": payload.get("expires"),
        "grace_days": payload.get("grace_days"),
        "activation": payload.get("activation"),
        "license_type": license_type,
    })

    if license_type not in _VALID_LICENSE_TYPES:
        return base

    tier = product_entry.get("tier")
    if not isinstance(tier, str) or not tier:
        return base

    grace_days = payload.get("grace_days")
    if not isinstance(grace_days, int) or isinstance(grace_days, bool) or grace_days < 0:
        return base

    expires = payload.get("expires")
    if not isinstance(expires, str):
        return base  # v2 abonelik lisansıdır — expires zorunlu, süresiz yok
    try:
        exp_dt = datetime.strptime(expires, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
    except ValueError:
        return base

    key_index = verify_signature(payload, signature, public_keys)
    if key_index is None:
        base["state"] = "invalid_signature"
        return base
    base["key"] = "birincil" if key_index == 0 else f"yedek-{key_index}"

    comps = (
        (product_entry.get("fingerprint") or {}).get("components")
        or (payload.get("fingerprint") or {}).get("components")
        or {}
    )
    if "instance_id" not in comps:
        base["state"] = "fingerprint_missing_anchor"
        return base

    matched, required, accepted = fingerprint_matches(
        current_fingerprint, comps, anchor_components=anchor_components, min_match=min_match)
    base["matched"] = matched
    base["required"] = required
    if not accepted:
        base["state"] = "fingerprint_mismatch"
        return base

    if not check_clock(state_file):
        base["state"] = "clock_rollback"
        return base

    now = datetime.now(timezone.utc)
    delta = exp_dt - now
    base["days_left"] = max(0, delta.days)
    if delta.total_seconds() <= 0:
        grace_end = exp_dt + timedelta(days=grace_days)
        if grace_days > 0 and now <= grace_end:
            base["state"] = "grace"
            base["grace_days_left"] = max(0, (grace_end - now).days)
            return base
        base["state"] = "expired"
        return base

    base["state"] = "valid"
    return base
