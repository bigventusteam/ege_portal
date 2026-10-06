"""Saat geri alma tespiti — yalnızca süreli lisanslarda çağrılır.

``state_file``'da son görülen UTC zaman saklanır. Saat 1 günden fazla geri
alınmışsa güvenilmez sayılır (lisans süresini uzatmak için makine saatini
geri almaya karşı). Küçük geri kaymalar (NTP düzeltmesi, saat dilimi) tolere
edilir ve son-görülen zaman ileri gitmediği sürece güncellenmez.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def check_clock(state_file: Path) -> bool:
    now = datetime.now(timezone.utc)
    last_seen = None
    try:
        st = json.loads(state_file.read_text(encoding="utf-8"))
        last_seen = datetime.fromisoformat(st.get("last_seen"))
    except Exception:
        pass
    if last_seen and (last_seen - now).total_seconds() > 86400:
        return False  # saat 1 günden fazla geri alınmış
    if last_seen is None or now > last_seen:
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(
                json.dumps({"last_seen": now.isoformat(timespec="seconds")}), encoding="utf-8")
        except Exception:
            pass
    return True
