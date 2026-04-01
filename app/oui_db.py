from __future__ import annotations

import csv
import os
from functools import lru_cache
from typing import Optional


def _default_oui_path() -> str:
    # Prefer env override; otherwise look for repo-local data/oui.csv
    env = os.environ.get("RECON_OUI_DB")
    if env:
        return env
    here = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(here, "..", "data", "oui.csv"))


def _norm_prefix(prefix: str) -> Optional[str]:
    if not prefix:
        return None
    p = prefix.strip().upper().replace("-", ":").replace(".", "")

    # Accept forms:
    # - "A1B2C3" (hex)
    # - "A1:B2:C3"
    # - "A1B2C3xxxx" (take first 6)
    hex_only = "".join(ch for ch in p if ch in "0123456789ABCDEF")
    if len(hex_only) >= 6:
        hex_only = hex_only[:6]
        return f"{hex_only[0:2]}:{hex_only[2:4]}:{hex_only[4:6]}"

    parts = p.split(":")
    if len(parts) >= 3 and all(len(x) == 2 for x in parts[:3]):
        return ":".join(parts[:3])
    return None


def _try_parse_ieee_oui_csv_row(row: list[str]) -> Optional[tuple[str, str]]:
    # IEEE "oui.csv" format usually includes:
    # Assignment, Organization Name, Organization Address...
    if not row or len(row) < 2:
        return None
    assignment = row[0].strip()
    org = row[1].strip()
    prefix = _norm_prefix(assignment)
    if not prefix or not org:
        return None
    return prefix, org


def _try_parse_simple_csv_row(row: list[str]) -> Optional[tuple[str, str]]:
    # Simple format: prefix,vendor
    if not row or len(row) < 2:
        return None
    prefix = _norm_prefix(row[0])
    vendor = row[1].strip()
    if not prefix or not vendor:
        return None
    return prefix, vendor


@lru_cache(maxsize=1)
def load_oui_map(path: Optional[str] = None) -> dict[str, str]:
    p = path or _default_oui_path()
    if not os.path.exists(p):
        return {}

    out: dict[str, str] = {}
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                # Skip obvious headers
                if row[0].lower().strip() in {"assignment", "oui", "prefix"}:
                    continue
                parsed = _try_parse_ieee_oui_csv_row(row) or _try_parse_simple_csv_row(row)
                if not parsed:
                    continue
                prefix, vendor = parsed
                out[prefix] = vendor
    except Exception:
        return {}

    return out

