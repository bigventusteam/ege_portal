"""
Lisans imzalama arayüzü.

`ege_lisans` (ortak imzalama/doğrulama kütüphanesi, bkz.
ege_platform/ege_lisans, ege_platform/PLAN.md §3) artık hazır ve bir yol
bağımlılığı olarak kurulu (`requirements.txt`'teki `-e ../ege_lisans`).
`LisansImzalayici` protokolü yine de korunuyor — testler gerçek Ed25519
imzalama yerine sahte bir imzalayıcı (`tests/fakes.py::FakeImzalayici`)
kullanmaya devam ediyor, üretim/geliştirme `EgeLisansImzalayici`'yi kullanır.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.config import settings


@runtime_checkable
class LisansImzalayici(Protocol):
    """Bir lisans payload'ını (bkz. PLAN.md §3) imzalayıp imza dizesini döner."""

    def imzala(self, payload: dict[str, Any]) -> str: ...


class EgeLisansImzalayici:
    """`ege_lisans.signing.sign_payload` ile gerçek Ed25519 imzalama.

    Özel anahtarın dosya YOLU `EGE_LISANS_OZEL_ANAHTAR` ortam değişkeninden
    (ya da doğrudan `private_key_path` argümanından, testler için) gelir —
    anahtar İÇERİĞİ hiçbir zaman bu sınıfın içinde tutulmaz/loglanmaz, her
    çağrıda `ege_lisans` dosyadan okuyup imzalar ve bırakır. Yol tanımlı
    değilse (ya da dosya yoksa) AÇIK bir hatayla durur — sessizce imzasız
    lisans üretmek yerine."""

    def __init__(self, private_key_path: str | Path | None = None):
        self._private_key_path = private_key_path

    def imzala(self, payload: dict[str, Any]) -> str:
        path = self._private_key_path or settings.ege_lisans_private_key_path
        if not path:
            raise RuntimeError(
                "EGE_LISANS_OZEL_ANAHTAR tanımlı değil — lisans imzalanamaz "
                "(sessizce imzasız lisans üretilmez, bkz. app/licensing.py)."
            )
        if not Path(path).is_file():
            raise RuntimeError(f"EGE_LISANS_OZEL_ANAHTAR dosyası bulunamadı: {path!r}")

        from ege_lisans.signing import sign_payload  # gecikmeli import — yalnız gerçekten imzalanırken yüklenir

        return sign_payload(payload, Path(path))
