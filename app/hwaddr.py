from __future__ import annotations

import re

# EUI-48 with : or - separators (common on Android, Windows, Linux tools).
_MAC_SPLIT_RE = re.compile(r"^[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}$")


def normalize_hw_address(addr: str) -> str:
    """
    Canonical form for Wi‑Fi BSSID / BLE public MAC-like addresses.

    - Accepts ``aa:bb:...``, ``aa-bb-...``, ``aabbccddeeff``, ``aa bb cc dd ee ff`` (mixed case).
    - Returns ``AA:BB:...`` or the original string if it does not look like a MAC.
      (BLE UUID / opaque IDs are left unchanged.)
    """
    if not addr:
        return addr
    s = addr.strip()
    # Strip zero-width / BOM-like characters some stacks inject.
    s = "".join(ch for ch in s if ch not in "\u200b\u200c\u200d\ufeff")
    s = s.strip()

    # Exactly 12 hex digits (any separators/spaces removed).
    hex_digits = re.sub(r"[^0-9A-Fa-f]", "", s, flags=re.I)
    if len(hex_digits) == 12:
        parts = [hex_digits[i : i + 2].upper() for i in range(0, 12, 2)]
        return ":".join(parts)

    if not _MAC_SPLIT_RE.fullmatch(s):
        return s
    parts = re.split(r"[:-]", s)
    if len(parts) != 6:
        return s
    if not all(len(p) == 2 and re.fullmatch(r"[0-9A-Fa-f]{2}", p) for p in parts):
        return s
    return ":".join(p.upper() for p in parts)
