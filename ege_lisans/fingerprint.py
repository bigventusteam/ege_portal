"""Makine parmak izi: bileşen hash'leri + eşleştirme kuralı.

Hash biçimi mapEGE'deki ``{ürün}|{bileşen}|{değer}`` ile birebir aynı olmalı;
aksi hâlde sahadaki mapEGE lisansları (şema v1) bu kütüphaneye geçince
bozulur. ``product`` parametresi bu yüzden var: mapEGE için HER ZAMAN
``"mapege"`` verilmelidir (mapEGE'nin ``_hash`` fonksiyonu bu değeri sabit
yazıyordu).

Parmak izi bileşenleri iki sınıfa ayrılır:

    ÇAPA          — kurulum ömrü boyunca kararlı olanlar. Lisansta yer
                    alıyorsa MUTLAKA eşleşmelidir (``instance_id``,
                    ``machine_id``).
    DESTEKLEYİCİ  — ortama göre değişebilenler (``hostname``, ``mac``).
                    Eşleşmeleri güveni artırır; eşleşmemeleri lisansı
                    DÜŞÜRMEZ.

Çapa içermeyen (eski biçim) lisanslar "en az ``min_match`` bileşen eşleşsin"
kuralıyla değerlendirilir; böylece sahadaki eski lisanslar geçersizleşmez.
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ANCHOR_COMPONENTS: tuple[str, ...] = ("instance_id", "machine_id")
DEFAULT_MIN_MATCH = 2


def component_hash(product: str, name: str, value: str) -> str:
    return hashlib.sha256(f"{product}|{name}|{value}".encode("utf-8")).hexdigest()


def _machine_id() -> str | None:
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    v = f.read().strip()
                if v:
                    return v
    except Exception:
        pass
    return None


def _mac() -> str | None:
    node = uuid.getnode()
    # Multicast biti set ise uuid.getnode rastgele üretmiştir — güvenilmez.
    if (node >> 40) & 1:
        return None
    return f"{node:012x}"


def _hostname() -> str | None:
    try:
        import platform
        return platform.node() or None
    except Exception:
        return None


def _instance_id(instance_file: Path) -> str:
    """Kuruluma özel kalıcı kimlik — ``instance_file``de saklanır (DATA_DIR
    volume). Okunamıyor/yazılamıyorsa (salt-okunur veri dizini, silinmiş
    volume, izin hatası) ``None`` döner — SABİT bir yer tutucu (ör.
    "unknown") ASLA dönmez: böyle bir değer her etkilenen kurulumda AYNI
    olur ve kendisi bir çapaya dönüşür, tam da parmak izinin önlemesi
    gereken şeyi (kurulumlar arası paylaşılan bir kimlik) üretir. Yazma
    başarıyla dönse bile geri okunarak DOĞRULANIR — bazı ağ/overlay
    bağlama noktaları yazmayı sessizce kabul edip kalıcılaştırmaz."""
    try:
        if instance_file.exists():
            v = instance_file.read_text(encoding="utf-8").strip()
            if v:
                return v
        v = uuid.uuid4().hex
        instance_file.parent.mkdir(parents=True, exist_ok=True)
        instance_file.write_text(v, encoding="utf-8")
        if instance_file.read_text(encoding="utf-8").strip() != v:
            return None
        return v
    except Exception:
        return None


def current_fingerprint(product: str, instance_file: Path) -> dict[str, str]:
    """Mevcut makinenin bileşen hash'leri. Bulunamayan bileşen dahil edilmez
    (``instance_id`` dahil — bkz. ``_instance_id``: okunamıyorsa hiç
    eklenmez, sahte bir değerle eklenmez). Doğrulama tarafında bunun
    sonucu: lisansın çapası ``instance_id`` içeriyorsa ama BURADA yoksa,
    ``fingerprint_matches`` bunu normal bir çapa uyuşmazlığı olarak ele
    alır (durum ``fingerprint_mismatch`` olur) — ayrı bir özel durum
    gerekmez."""
    comps: dict[str, str] = {}
    if (iid := _instance_id(instance_file)):
        comps["instance_id"] = component_hash(product, "instance_id", iid)
    if (mid := _machine_id()):
        comps["machine_id"] = component_hash(product, "machine_id", mid)
    if (mac := _mac()):
        comps["mac"] = component_hash(product, "mac", mac)
    if (hn := _hostname()):
        comps["hostname"] = component_hash(product, "hostname", hn)
    return comps


class FingerprintError(Exception):
    """``instance_id`` kalıcı kimliği okunamıyor/yazılamıyor (bkz.
    ``_instance_id``). Böyle bir kurulum aktivasyon isteği ÜRETEMEZ:
    ``instance_id``'siz bir parmak izi, kurulumlar arası paylaşılabilen
    zayıf bir çapaya dönüşürdü — bu, sabit "unknown" yer tutucusuyla aynı
    açığın bir başka biçimidir, bu yüzden burada da erken ve açıkça
    reddedilir."""


def activation_request(product: str, instance_file: Path) -> dict:
    """Çevrimdışı aktivasyon için üreticiye/portala gönderilecek parmak izi
    dosyası. Kalıcı kurulum kimliği kurulamıyorsa (veri dizini yazılabilir
    değil) ``FingerprintError`` fırlatır — sessizce zayıf bir aktivasyon
    isteği üretmek yerine."""
    fingerprint = current_fingerprint(product, instance_file)
    if "instance_id" not in fingerprint:
        raise FingerprintError(
            f"Kalıcı kurulum kimliği okunamıyor/yazılamıyor: {instance_file}. "
            "Lisans veri dizininin var olduğundan ve yazılabilir olduğundan emin olun."
        )
    return {
        "product": product,
        "schema": 1,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hostname_hint": _hostname() or "",
        "fingerprint": {"components": fingerprint},
    }


def fingerprint_matches(
    current: dict[str, str],
    lic_components: dict[str, str],
    *,
    anchor_components: tuple[str, ...] = DEFAULT_ANCHOR_COMPONENTS,
    min_match: int = DEFAULT_MIN_MATCH,
) -> tuple[int, int, bool]:
    """(eşleşen sayısı, beklenen sayı, kabul edildi mi).

    Kural: lisanstaki TÜM çapa bileşenleri eşleşmelidir. Destekleyici
    bileşenlerin (hostname, mac) değişmesi sonucu etkilemez. Çapa içermeyen
    lisanslarda k-of-n kuralı uygulanır.
    """
    matched = sum(1 for k, v in lic_components.items() if current.get(k) == v)

    anchors = {k: v for k, v in lic_components.items() if k in anchor_components}
    if anchors:
        accepted = all(current.get(k) == v for k, v in anchors.items())
        return matched, len(anchors), accepted

    required = min(min_match, len(lic_components)) if lic_components else min_match
    return matched, required, matched >= required
