"""Kanonik JSON serileştirme — imzalanan/doğrulanan baytları üretir.

mapEGE'nin ``services/licensing.py::_canonical`` ve ``vendor/app.py::_canonical``
fonksiyonlarıyla birebir aynı biçimi üretir: ``sort_keys``, ayraçsız,
``ensure_ascii=False``. Bu biçim değişirse sahadaki tüm imzalar (mapEGE dahil)
geçersizleşir — asla değiştirmeyin.
"""
from __future__ import annotations

import json


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
