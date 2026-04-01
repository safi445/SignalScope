from __future__ import annotations

from functools import lru_cache
from typing import Optional

from app.oui_db import load_oui_map


# Small built-in sample OUI map (expand later or load a file).
_OUI_PREFIX_TO_VENDOR: dict[str, str] = {
    "00:1A:79": "Hikvision",
    "3C:5A:B4": "Google",
    "F4:F5:D8": "Apple",
    "FC:FB:FB": "Samsung",
    "DC:A6:32": "TP-Link",
    "44:65:0D": "Xiaomi",
}


def _norm_mac_prefix(mac: str) -> Optional[str]:
    if not mac:
        return None
    m = mac.strip().upper().replace("-", ":")
    parts = m.split(":")
    if len(parts) < 3:
        return None
    return ":".join(parts[:3])


@lru_cache(maxsize=4096)
def vendor_from_mac(mac: str) -> Optional[str]:
    prefix = _norm_mac_prefix(mac)
    if not prefix:
        return None
    # Prefer external DB if present; fallback to built-in sample.
    db = load_oui_map()
    return db.get(prefix) or _OUI_PREFIX_TO_VENDOR.get(prefix)

