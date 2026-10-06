"""Ürün başına lisans bağlamı.

Bir ürünün (mapege/sisege/colege) hangi parmak izi/durum dosyalarını
kullanacağını, hangi ürün adı ve açık anahtarlarla doğrulama yapacağını
tanımlar. Vendorlanan her ürün kendi ``LicenseContext``'ini oluşturur.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import fingerprint as _fp
from .fingerprint import DEFAULT_ANCHOR_COMPONENTS, DEFAULT_MIN_MATCH


@dataclass(frozen=True)
class LicenseContext:
    """``product``: mapEGE için HER ZAMAN ``"mapege"`` olmalı — parmak izi
    hash'i ve şema v1 ürün kapısı bu değere göre çalışır; başka bir değer
    sahadaki mapEGE lisanslarını bozar.
    """

    product: str
    public_keys: Sequence[str]
    data_dir: Path
    min_match: int = DEFAULT_MIN_MATCH
    anchor_components: tuple[str, ...] = DEFAULT_ANCHOR_COMPONENTS

    @property
    def instance_file(self) -> Path:
        return Path(self.data_dir) / "instance_id"

    @property
    def state_file(self) -> Path:
        return Path(self.data_dir) / "license_state.json"


def current_fingerprint(ctx: LicenseContext) -> dict[str, str]:
    return _fp.current_fingerprint(ctx.product, ctx.instance_file)


def activation_request(ctx: LicenseContext) -> dict:
    return _fp.activation_request(ctx.product, ctx.instance_file)
