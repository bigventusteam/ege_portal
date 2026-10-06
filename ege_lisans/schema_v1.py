"""Şema v1 doğrulama — mapEGE'nin bugünkü ``mode`` alanlı lisansı.

mapEGE ``services/licensing.py::validate_license`` ile birebir aynı
davranışı uygular. Yalnızca ``product == "mapege"`` için geçerli sayılır
(bkz. ``ege_portal/PLAN.md`` §3 — şema v2'ye geçiş planı); başka bir ürün
için çağrılırsa lisansta o ürün yokmuş gibi ``"missing"`` döner.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .clock import check_clock
from .fingerprint import DEFAULT_ANCHOR_COMPONENTS, DEFAULT_MIN_MATCH, fingerprint_matches
from .keys import verify_signature

V1_MODES = ("lite", "standard", "pro")


def validate_v1(
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
        "schema": 1, "state": "malformed", "product": product,
        "customer": None, "email": None, "mode": None,
        "issued": None, "expires": None, "days_left": None,
        "matched": 0, "required": min_match, "key": None,
    }
    payload = doc.get("payload") if isinstance(doc, dict) else None
    signature = doc.get("signature") if isinstance(doc, dict) else None
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return base

    base.update({
        "customer": payload.get("customer"),
        "email": payload.get("email"),
        "mode": payload.get("mode"),
        "issued": payload.get("issued"),
        "expires": payload.get("expires"),
    })

    if payload.get("mode") not in V1_MODES:
        return base

    # Biçimi geçerli bir v1 lisans, ama bu şema yalnız mapEGE için tanımlı —
    # başka ürün için lisansta o ürün "yok" sayılır.
    if product != "mapege":
        base["state"] = "missing"
        return base

    key_index = verify_signature(payload, signature, public_keys)
    if key_index is None:
        base["state"] = "invalid_signature"
        return base
    base["key"] = "birincil" if key_index == 0 else f"yedek-{key_index}"

    comps = (payload.get("fingerprint") or {}).get("components") or {}
    matched, required, accepted = fingerprint_matches(
        current_fingerprint, comps, anchor_components=anchor_components, min_match=min_match)
    base["matched"] = matched
    base["required"] = required
    if not accepted:
        base["state"] = "fingerprint_mismatch"
        return base

    expires = payload.get("expires")
    if expires:
        if not check_clock(state_file):
            base["state"] = "clock_rollback"
            return base
        try:
            exp_dt = datetime.strptime(expires, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            return base
        delta = exp_dt - datetime.now(timezone.utc)
        base["days_left"] = max(0, delta.days)
        if delta.total_seconds() <= 0:
            base["state"] = "expired"
            return base

    base["state"] = "valid"
    return base
