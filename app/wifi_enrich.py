from __future__ import annotations

from typing import Optional


def band_from_frequency_mhz(freq: Optional[int]) -> Optional[str]:
    if freq is None:
        return None
    # Very rough bands.
    if 2400 <= freq <= 2500:
        return "2.4GHz"
    if 4900 <= freq <= 5900:
        return "5GHz"
    if 5925 <= freq <= 7125:
        return "6GHz"
    return None


def band_from_channel(channel: Optional[int]) -> Optional[str]:
    if channel is None:
        return None
    if 1 <= channel <= 14:
        return "2.4GHz"
    if 32 <= channel <= 177:
        return "5GHz"
    if channel >= 1_000:
        return "6GHz"
    return None


def normalize_security(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = " ".join(s.strip().split())
    return t

