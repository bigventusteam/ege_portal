"""ege_lisans (ortak lisans doğrulama kütüphanesi) vendorlama senkron aracı.

ege_portal, ege_lisans'ı kaynak olarak `ege_portal/ege_lisans/` altına vendorluyor
(bkz. ege_platform/ege_portal/PLAN.md §3/§7 F1: "ege_lisans ... ürünlere
vendorlanır") — ege_portal'nin kendi paketlemesi ege_platform/ege_lisans'a bir
bağımlılık/sürüm ilişkisi kurmadan, tek başına dağıtılabilsin diye.

Bu betik İKİ komut sunar:

  --kontrol   Vendorlanmış kopyanın (a) kendi VENDOR_MANIFEST.json'ındaki
              hash'lerle VE (b) kaynaktaki (ege_platform/ege_lisans, varsa)
              güncel haliyle eşleştiğini doğrular. Yalnız okur, hiçbir şey
              yazmaz. Kaynak yanında yoksa (ör. ege_portal tek başına paketlenmiş
              bir dağıtımda çalıştırılıyorsa) kaynakla karşılaştırma
              ATLANIR — hata vermez, 0 ile çıkar; yalnızca kendi
              manifestiyle tutarlılık kontrol edilir.

  --kopyala   Kaynaktan yeniden vendorlar: ege_portal/ege_lisans/ içindeki .py
              dosyalarını kaynaktakiyle değiştirir ve VENDOR_MANIFEST.json'ı
              yeniden yazar. Kaynak yoksa hata verir (kopyalanacak bir şey
              yok) — bu komut source'un varlığını ATLAMAZ.

Kullanım:
    python scripts/ege_lisans_senkron.py --kontrol
    python scripts/ege_lisans_senkron.py --kopyala

Çıkış kodları (--kontrol): 0 = eşleşiyor (ya da kaynak yok, atlandı),
1 = vendorlanmış kopya kendi manifestiyle uyuşmuyor (bozuk/elle değiştirilmiş
kopya), 2 = manifestle tutarlı ama kaynaktan farklı (yeniden vendorlamak
gerekebilir).
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# scripts/quality_gate.py'deki aynı düzeltme: bir Windows konsolunun
# varsayılan kod sayfası (cp1252) Türkçe'ye özgü karakterleri (ı, ş, ğ, İ,
# Ş, Ğ) kodlayamaz — reconfigure olmadan bu betiğin kendi print()'i ya da
# argparse'ın --help çıktısı (docstring) ham bir UnicodeEncodeError ile
# çöker.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent  # ege_portal/
VENDORED_DIR = REPO_ROOT / "ege_lisans"
MANIFEST_PATH = VENDORED_DIR / "VENDOR_MANIFEST.json"

# ege_platform kökü, ege_portal'nin bir üst dizini (bkz. ege_portal/ege_lisans/
# README-benzeri not: bu betik iki depo arasında çalışır, ege_portal kendisi
# ege_lisans'a bağımlı bir paket olarak KURULMAZ).
SOURCE_ROOT = REPO_ROOT.parent / "ege_lisans"
SOURCE_PACKAGE_DIR = SOURCE_ROOT / "src" / "ege_lisans"
SOURCE_PYPROJECT = SOURCE_ROOT / "pyproject.toml"

MANIFEST_FILENAME = "VENDOR_MANIFEST.json"


def _iter_package_files(package_dir: Path) -> list[Path]:
    return sorted(p for p in package_dir.rglob("*.py"))


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_hashes(package_dir: Path) -> dict[str, str]:
    return {
        str(p.relative_to(package_dir)).replace("\\", "/"): _hash_file(p)
        for p in _iter_package_files(package_dir)
    }


def _read_source_version() -> str | None:
    if not SOURCE_PYPROJECT.exists():
        return None
    for line in SOURCE_PYPROJECT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"').strip("'")
    return None


def cmd_kopyala() -> int:
    if not SOURCE_PACKAGE_DIR.exists():
        print(f"HATA: kaynak yok: {SOURCE_PACKAGE_DIR}", file=sys.stderr)
        return 1

    if VENDORED_DIR.exists():
        for item in VENDORED_DIR.iterdir():
            if item.name == MANIFEST_FILENAME:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    VENDORED_DIR.mkdir(parents=True, exist_ok=True)

    for src_file in _iter_package_files(SOURCE_PACKAGE_DIR):
        rel = src_file.relative_to(SOURCE_PACKAGE_DIR)
        dst = VENDORED_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)

    source_version = _read_source_version()
    manifest = {
        "source": "ege_platform/ege_lisans",
        "source_version": source_version,
        "vendored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": _relative_hashes(VENDORED_DIR),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ege_lisans {source_version or '?'} -> {VENDORED_DIR} kopyalandi ({len(manifest['files'])} dosya).")
    return 0


def cmd_kontrol() -> int:
    if not MANIFEST_PATH.exists():
        print(f"HATA: {MANIFEST_PATH} yok. Once --kopyala calistirin.", file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    recorded = manifest.get("files", {})
    vendored = _relative_hashes(VENDORED_DIR)

    problems = []
    for name, expected in recorded.items():
        actual = vendored.get(name)
        if actual is None:
            problems.append(f"eksik: {name}")
        elif actual != expected:
            problems.append(f"manifestten farkli (elle mi degistirildi?): {name}")
    for name in vendored:
        if name not in recorded and name != MANIFEST_FILENAME:
            problems.append(f"manifestte yok (fazladan dosya): {name}")

    if problems:
        print("Vendorlanmis kopya kendi VENDOR_MANIFEST.json'iyla UYUSMUYOR:")
        for p in problems:
            print(f"  - {p}")
        return 1

    if not SOURCE_PACKAGE_DIR.exists():
        print(f"Kaynak yok ({SOURCE_PACKAGE_DIR}) — kaynakla karsilastirma atlaniyor.")
        print("Vendorlanmis kopya kendi manifestiyle tutarli.")
        return 0

    source = _relative_hashes(SOURCE_PACKAGE_DIR)
    drift = [name for name, h in source.items() if vendored.get(name) != h]
    drift += [f"{name} (kaynakta yok)" for name in vendored if name not in source]
    if drift:
        print("Vendorlanmis kopya, GUNCEL kaynaktan FARKLI (senkronizasyon gerekebilir):")
        for name in sorted(drift):
            print(f"  - {name}")
        print("Guncellemek icin: python scripts/ege_lisans_senkron.py --kopyala")
        return 2

    print("ege_lisans vendorlanmis kopyasi hem manifestle hem guncel kaynakla eslesiyor.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--kontrol", action="store_true", help="Vendorlanmis kopyayi manifest+kaynakla karsilastir")
    group.add_argument("--kopyala", action="store_true", help="Kaynaktan yeniden vendorla")
    args = parser.parse_args(argv)
    return cmd_kopyala() if args.kopyala else cmd_kontrol()


if __name__ == "__main__":
    sys.exit(main())
