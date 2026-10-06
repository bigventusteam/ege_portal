"""Ed25519 çoklu-anahtar imza doğrulama.

Bir lisans, verilen anahtar listesindeki HERHANGİ BİRİYLE imzalanmışsa
geçerlidir (birincil + yedek anahtar deseni — bkz. mapEGE ``PUBLIC_KEYS``
yorumu). Sıra anlamlıdır: 0 = birincil, 1+ = yedek.
"""
from __future__ import annotations

from collections.abc import Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .canonical import canonical_bytes


def verify_signature(payload: dict, signature_hex: str, public_keys: Sequence[str]) -> int | None:
    """İmzayı doğrulayan anahtarın ``public_keys`` içindeki sırasını döner.

    Hiçbir anahtar doğrulamıyorsa ``None``. Ed25519 doğrulaması hızlı olduğu
    için birkaç anahtar denemenin maliyeti ihmal edilebilir.
    """
    data = canonical_bytes(payload)
    try:
        signature = bytes.fromhex(signature_hex)
    except (ValueError, TypeError):
        return None
    for index, key_hex in enumerate(public_keys):
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))
            public_key.verify(signature, data)
            return index
        except (InvalidSignature, ValueError):
            continue
    return None
