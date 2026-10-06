"""EGE Lisans — mapEGE, sisEGE, colEGE için ortak lisans doğrulama kütüphanesi.

Bkz. ``README.md`` ve ``ege_portal/PLAN.md`` §3 (şema v2).
"""
from .canonical import canonical_bytes
from .context import LicenseContext, activation_request, current_fingerprint
from .fingerprint import FingerprintError, fingerprint_matches
from .keys import verify_signature
from .signing import build_v2_payload, generate_keypair, sign_payload, sign_v2_license
from .trial import kurulum_deneme_baslat, kurulum_deneme_durumu
from .validate import validate_license

__all__ = [
    "LicenseContext",
    "canonical_bytes",
    "verify_signature",
    "current_fingerprint",
    "activation_request",
    "fingerprint_matches",
    "FingerprintError",
    "validate_license",
    "generate_keypair",
    "sign_payload",
    "sign_v2_license",
    "build_v2_payload",
    "kurulum_deneme_durumu",
    "kurulum_deneme_baslat",
]
