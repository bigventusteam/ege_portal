"""
Paylaşılan FastAPI dependency'leri. `get_bvpay_client`/`get_imzalayici`
testlerde `app.dependency_overrides` ile sahtelerine değiştirilir — gerçek
implementasyonlar (`HTTPBVPayClient`, `EgeLisansImzalayici`) testlerde HİÇ
örneklenmez.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.bvpay import BVPayClient, HTTPBVPayClient
from app.config import settings
from app.licensing import EgeLisansImzalayici, LisansImzalayici


@lru_cache
def _default_bvpay_client() -> HTTPBVPayClient:
    return HTTPBVPayClient(settings.bvpay_url, settings.bvpay_api_key)


def get_bvpay_client() -> BVPayClient:
    return _default_bvpay_client()


@lru_cache
def _default_imzalayici() -> EgeLisansImzalayici:
    return EgeLisansImzalayici()


def get_imzalayici() -> LisansImzalayici:
    return _default_imzalayici()


def get_release_storage_root() -> Path:
    """İndirme merkezi depolama kökü (`PORTAL_RELEASE_DIR`) — testlerde
    `app.dependency_overrides` ile bir `tmp_path`'e değiştirilir, gerçek
    `PORTAL_RELEASE_DIR` testlerde HİÇ kullanılmaz (bkz. modül docstring'i)."""
    root = Path(settings.portal_release_dir)
    os.makedirs(root, exist_ok=True)
    return root
