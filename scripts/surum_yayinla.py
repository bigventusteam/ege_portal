#!/usr/bin/env python
"""
İndirme merkezine (PLAN.md §5.4/F5) yeni bir sürüm paketi yayınlar.

Bilerek bir API ucu DEĞİL, bir CLI betiği — bu turda API'den dosya yükleme
YOK (bkz. app/models.py::Release docstring'i). Yerel bir zip/tar dosyasını
alır, SHA-256/boyutunu hesaplar, `PORTAL_RELEASE_DIR` altına kopyalar ve bir
`Release` kaydı açar.

İMZASIZ (`--unsigned`) bir sürüm müşteriye ASLA listelenmez/indirilmez
(yalnız personel — bkz. app/services/releases.py) — ama yine de YANLIŞLIKLA
imzasız bir üretim paketinin "signed" olarak işaretlenmesi kadar tehlikeli
bir hata sınıfı: bir geliştiricinin TEST amaçlı imzasız bir paketi fark
etmeden yayınlaması. Bu yüzden `--unsigned` TEK BAŞINA yetmez; açık bir
`--imzasiz-onay` bayrağı da gerekir (bkz. `_imzasiz_onay_kontrol_et`) —
parolasız/korumasız bir dosyanın "bu kasıtlı" onayı olmadan asla
yayınlanmaması için.

`--personel` yayınlayan personelin e-postasıdır (is_staff olmalı); kayda
`created_by_user_id` ve `AuditEvent("release.published")` olarak yazılır.

Kullanım:
    python scripts/surum_yayinla.py --personel admin@bigventus.com \\
        --product mapege --version 1.3.0 --package-type docker-linux \\
        --os linux --arch x64 --file C:\\paket\\mapege-1.3.0.zip

    # imzasız (yalnız personel görür) bir test paketi:
    python scripts/surum_yayinla.py --personel admin@bigventus.com \\
        --product mapege --version 1.3.0-rc1 --package-type docker-linux \\
        --os linux --arch x64 --file C:\\paket\\mapege-1.3.0-rc1.zip \\
        --unsigned --imzasiz-onay
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows konsolunda Türkçe karakterler için (bkz. personel_olustur.py)
sys.stderr.reconfigure(encoding="utf-8")  # HATA/UYARI mesajları da stderr'e gidiyor — o da aynı düzeltmeyi ister

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import AuditEvent, PackageType, Product, Release, User  # noqa: E402

_PARCA_BOYUTU = 1 << 20  # 1 MiB — büyük imaj dosyalarını belleğe tek seferde almamak için


def _sha256_ve_boyut(dosya: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    boyut = 0
    with dosya.open("rb") as f:
        while parca := f.read(_PARCA_BOYUTU):
            h.update(parca)
            boyut += len(parca)
    return h.hexdigest(), boyut


def _imzasiz_onay_kontrol_et(args: argparse.Namespace) -> None:
    if not args.unsigned:
        return
    if args.imzasiz_onay:
        print("UYARI: Bu sürüm İMZASIZ olarak yayınlanıyor — müşteriye ASLA listelenmeyecek/indirilemeyecek,", file=sys.stderr)
        print("       yalnız personel (is_staff) görebilecek.", file=sys.stderr)
        return
    print("HATA: --unsigned verildi ama --imzasiz-onay YOK.", file=sys.stderr)
    print("  İmzasız bir sürümü yayınlamak için ikisini BİRLİKTE verin:", file=sys.stderr)
    print("    --unsigned --imzasiz-onay", file=sys.stderr)
    print("  (Bu çift bayrak, yanlışlıkla imzasız bir üretim paketi yayınlamaya karşı kasıtlı bir sürtünmedir.)", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="İndirme merkezine yeni bir sürüm paketi yayınlar.")
    parser.add_argument("--personel", required=True, help="Yayınlayan personelin e-postası (is_staff olmalı)")
    parser.add_argument("--product", required=True, help="Ürün kodu (ör. mapege, sisege, colege)")
    parser.add_argument("--version", required=True, help="Sürüm (ör. 1.3.0)")
    parser.add_argument("--package-type", required=True, choices=[t.value for t in PackageType])
    parser.add_argument("--os", required=True, help="ör. linux, windows")
    parser.add_argument("--arch", required=True, help="ör. x64")
    parser.add_argument("--file", required=True, help="Yayınlanacak yerel dosyanın yolu")
    parser.add_argument("--notes", default=None, help="İç not (müşteriye gösterilir)")
    parser.add_argument("--unsigned", action="store_true", help="İmzasız yayınla (yalnız personel görür)")
    parser.add_argument("--imzasiz-onay", dest="imzasiz_onay", action="store_true",
                         help="--unsigned ile BİRLİKTE zorunlu açık onay")
    args = parser.parse_args(argv)

    _imzasiz_onay_kontrol_et(args)

    kaynak = Path(args.file)
    if not kaynak.is_file():
        print(f"HATA: dosya bulunamadı ya da normal bir dosya değil: {kaynak}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        personel = db.scalars(select(User).where(User.email == args.personel)).first()
        if personel is None or not personel.is_staff or not personel.is_active:
            print(f"HATA: '{args.personel}' aktif bir personel (is_staff) hesabı değil.", file=sys.stderr)
            sys.exit(1)

        product = db.scalars(select(Product).where(Product.code == args.product)).first()
        if product is None:
            print(f"HATA: katalogda '{args.product}' kodlu bir ürün yok.", file=sys.stderr)
            sys.exit(1)

        print("  SHA-256/boyut hesaplanıyor…")
        sha256, boyut = _sha256_ve_boyut(kaynak)

        depo_koku = Path(settings.portal_release_dir)
        hedef_dizin = depo_koku / product.code / args.version / args.package_type
        hedef_dizin.mkdir(parents=True, exist_ok=True)
        hedef = hedef_dizin / kaynak.name
        if hedef.exists():
            print(f"HATA: hedefte zaten bir dosya var: {hedef} (aynı ürün+sürüm+paket türü daha önce yayınlanmış olabilir)", file=sys.stderr)
            sys.exit(1)

        storage_key = f"{product.code}/{args.version}/{args.package_type}/{kaynak.name}"

        release = Release(
            product_id=product.id,
            version=args.version,
            package_type=PackageType(args.package_type),
            os=args.os,
            arch=args.arch,
            file_name=kaynak.name,
            size_bytes=boyut,
            sha256=sha256,
            storage_key=storage_key,
            signed=not args.unsigned,
            notes=args.notes,
            created_by_user_id=personel.id,
        )
        db.add(release)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            print(
                f"HATA: '{args.product}' / '{args.version}' / '{args.package_type}' için zaten bir Release kaydı var "
                "(product+version+package_type tekil olmalı).",
                file=sys.stderr,
            )
            sys.exit(1)

        # DB satırı başarıyla açıldıktan SONRA dosya kopyalanır — tersi olsaydı
        # (önce dosya, sonra DB) bir IntegrityError'da diskte sahipsiz bir
        # dosya kalırdı (küçük ama gereksiz bir tutarsızlık).
        shutil.copy2(kaynak, hedef)

        db.add(
            AuditEvent(
                event_type="release.published",
                entity_type="release",
                entity_id=str(release.id),
                data={
                    "staff_user_id": personel.id,
                    "product_code": product.code,
                    "version": args.version,
                    "package_type": args.package_type,
                    "sha256": sha256,
                    "size_bytes": boyut,
                    "signed": release.signed,
                },
            )
        )
        db.commit()
        print(f"Yayınlandı: release_id={release.id}")
        print(f"  Ürün        : {product.code} ({product.name})")
        print(f"  Sürüm       : {args.version} / {args.package_type} / {args.os}-{args.arch}")
        print(f"  Dosya       : {kaynak.name} ({boyut:,} bayt)")
        print(f"  SHA-256     : {sha256}")
        print(f"  Depo yolu   : {storage_key}")
        print(f"  İmzalı      : {'evet' if release.signed else 'HAYIR (yalnız personel görür)'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
