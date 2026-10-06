"""İmza anahtarı üretimi ve şema v2 lisans imzalama — yalnızca üretici/portal
tarafında kullanılır (ürünlere yalnızca doğrulama tarafı vendorlanır).

Özel anahtar İÇERİĞİ asla loglanmaz ya da argümana/döndürülen değere
konmaz — yalnızca dosya YOLU parametre olarak alınır.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .canonical import canonical_bytes


def generate_keypair(private_key_path: Path) -> str:
    """Yeni Ed25519 anahtar çifti üretir.

    Özel anahtarı ``private_key_path``'e yazar (GİZLİ TUTUN — dağıtıma
    koymayın). Açık anahtarın hex'ini döner (ürünün ``PUBLIC_KEYS``
    listesine eklenecek olan).
    """
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    Path(private_key_path).write_bytes(pem)
    public_bytes = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return public_bytes.hex()


def _load_private_key(private_key_path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Anahtar Ed25519 değil")
    return key


def sign_payload(payload: dict, private_key_path: Path) -> str:
    """``payload``'ın kanonik baytlarını imzalar, hex imza döner."""
    return _load_private_key(private_key_path).sign(canonical_bytes(payload)).hex()


def build_v2_payload(
    *,
    license_id: str,
    subscription_id: str,
    customer: dict[str, Any],
    products: dict[str, dict[str, Any]],
    issued: str,
    expires: str,
    grace_days: int,
    activation: dict[str, Any],
    fingerprint_components: dict[str, str] | None = None,
    license_type: str | None = None,
) -> dict:
    """Şema v2 payload'ını kurar (bkz. ``ege_portal/PLAN.md`` §3).

    ``products``: ``{"mapege": {"tier": "pro", "fingerprint_components": {...}},
    "sisege": {"tier": "standard", "fingerprint_components": {...}}}``. Paket
    satışında her ürün farklı kurulumda/makinede olabileceği için ürün başına
    ayrı parmak izi taşınabilir — her ürünün ``activation_request(ctx)``'inden
    gelen ``fingerprint.components``'i buraya geçirin.

    ``fingerprint_components`` (üst düzey, opsiyonel): yalnızca TEK ürünlü ya
    da tüm ürünleri AYNI kurulumun kapsadığı lisanslar için kısayol. Bir ürün
    girdisinde kendi ``fingerprint_components``'i yoksa doğrulama buna düşer.
    ``expires`` zorunludur — v2 abonelik lisansıdır, süresiz lisans yalnız
    şema v1'de vardır.

    ``license_type``: ``"subscription"`` (verilmezse VARSAYILAN) ya da
    ``"trial"`` — bir GERÇEK, imzalı deneme lisansı üretirken ``"trial"``
    geçin (raporlama/destek amaçlı; doğrulama/süre kuralları AYNIDIR). Bu,
    ürünlerin kendi gömülü, imzasız kurulum denemesinden (``ege_lisans.
    trial``) TAMAMEN AYRIDIR.
    """
    built_products: dict[str, dict[str, Any]] = {}
    for name, spec in products.items():
        entry: dict[str, Any] = {"tier": spec["tier"]}
        fp = spec.get("fingerprint_components")
        if fp:
            entry["fingerprint"] = {"components": fp}
        built_products[name] = entry

    payload: dict[str, Any] = {
        "schema": 2,
        "license_id": license_id,
        "subscription_id": subscription_id,
        "customer": customer,
        "products": built_products,
        "issued": issued,
        "expires": expires,
        "grace_days": grace_days,
        "activation": activation,
    }
    if fingerprint_components:
        payload["fingerprint"] = {"components": fingerprint_components}
    if license_type is not None:
        payload["license_type"] = license_type
    return payload


def sign_v2_license(payload: dict, private_key_path: Path) -> dict:
    """Şema v2 payload'ını imzalar; ``{"payload": ..., "signature": ...}`` döner."""
    return {"payload": payload, "signature": sign_payload(payload, private_key_path)}
