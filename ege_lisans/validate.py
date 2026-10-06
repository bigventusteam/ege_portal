"""Şema-farkında doğrulama girişi — ``payload.schema``'ya göre v1/v2'ye yönlendirir."""
from __future__ import annotations

from .context import LicenseContext, current_fingerprint
from .schema_v1 import validate_v1
from .schema_v2 import validate_v2


def validate_license(doc: dict, ctx: LicenseContext, *, fingerprint: dict[str, str] | None = None) -> dict:
    """Lisans belgesini doğrular; durum sözlüğü döner (diske yazmaz — saklamak
    çağıranın işidir).

    ``fingerprint`` verilmezse bu makinenin gerçek parmak izi hesaplanır
    (``instance_id`` dosyası ``ctx.data_dir``'da yoksa oluşturulur — yan
    etkilidir). Testler sahte bir parmak izi geçirerek bu yan etkiden kaçınır.
    """
    fp = fingerprint if fingerprint is not None else current_fingerprint(ctx)
    payload = doc.get("payload") if isinstance(doc, dict) else None
    schema = payload.get("schema") if isinstance(payload, dict) else None

    kwargs = dict(
        product=ctx.product,
        public_keys=ctx.public_keys,
        current_fingerprint=fp,
        state_file=ctx.state_file,
        min_match=ctx.min_match,
        anchor_components=ctx.anchor_components,
    )
    if schema == 2:
        return validate_v2(doc, **kwargs)
    # schema == 1 ya da eksik/bozuk → v1 yoluna düşer; malformed belgeler de
    # burada "malformed" olarak işaretlenir (mapEGE'nin bugünkü davranışı).
    return validate_v1(doc, **kwargs)
