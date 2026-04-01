from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional


DEFAULT_RULES = {
    "keywords": ["cam", "ipcam", "cctv", "hikvision", "dahua", "ezviz", "imou"],
    "vendors": ["Hikvision", "Dahua"],
    "mac_prefixes": ["00:1A:79"],  # example
}


def rules_path() -> str:
    env = os.environ.get("RECON_RULES")
    if env:
        return env
    here = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(here, "..", "data", "rules.json"))


def load_rules() -> dict[str, Any]:
    p = rules_path()
    if not os.path.exists(p):
        return DEFAULT_RULES
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_RULES


def match_device(rules: dict[str, Any], device: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    blob = " ".join(
        str(x)
        for x in [
            device.get("ssid"),
            device.get("name"),
            device.get("vendor"),
            device.get("device_id"),
        ]
        if x
    ).lower()

    for kw in (rules.get("keywords") or []):
        k = str(kw).lower()
        if k and k in blob:
            hits.append(f"keyword:{k}")
            break

    ven = (device.get("vendor") or "").strip()
    if ven and ven in set(map(str, rules.get("vendors") or [])):
        hits.append(f"vendor:{ven}")

    dev_id = (device.get("device_id") or "").upper().replace("-", ":")
    prefixes = set(str(x).upper().replace("-", ":") for x in (rules.get("mac_prefixes") or []))
    if any(dev_id.startswith(p) for p in prefixes if p):
        hits.append("mac_prefix")

    return hits

