from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


CAMERA_KEYWORDS = [
    "cam",
    "ipcam",
    "cctv",
    "hikvision",
    "dahua",
    "ezviz",
    "imou",
]


SUSPICIOUS_VENDORS = {
    "Hikvision",
    "Dahua",
}


@dataclass(frozen=True)
class ScoreResult:
    score: int
    category: str
    reasons: list[str]
    camera_confidence: int
    camera_reasons: list[str]


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def score_device(
    *,
    signal_type: str,
    device_id: str,
    name: Optional[str],
    ssid: Optional[str],
    security: Optional[str],
    vendor: Optional[str],
    last_rssi: Optional[int],
    seen_count: int,
    persistent_seconds: float,
) -> ScoreResult:
    score = 0
    reasons: list[str] = []
    camera_conf = 0
    camera_reasons: list[str] = []

    # Wi‑Fi hidden SSID heuristic.
    if signal_type == "wifi":
        if ssid is None or ssid.strip() == "" or ssid.strip() == "<hidden>":
            score += 30
            reasons.append("hidden_ssid")
        # Open networks can be relevant for awareness (not “hacking”, just a flag).
        if security and security.lower() in {"open", "none"}:
            score += 10
            reasons.append("open_network")

    if not name or name.strip() == "":
        score += 25
        reasons.append("unknown_name")

    # Strong signal = very close.
    if last_rssi is not None and last_rssi >= -50:
        score += 20
        reasons.append("strong_signal")

    # Persistent presence.
    if persistent_seconds >= 180:
        score += 15
        reasons.append("persistent_presence")

    # Suspicious vendor / keyword match.
    text_blob = " ".join(
        x for x in [name or "", ssid or "", vendor or "", device_id] if x is not None
    )
    if vendor in SUSPICIOUS_VENDORS:
        score += 10
        reasons.append("suspicious_vendor")
        camera_conf += 35
        camera_reasons.append("camera_vendor")
    if text_blob and _contains_keyword(text_blob, CAMERA_KEYWORDS):
        score += 10
        reasons.append("keyword_match")
        camera_conf += 45
        camera_reasons.append("camera_keyword")

    # Very stable signal could indicate fixed device (weak heuristic).
    if seen_count >= 8 and last_rssi is not None and -65 <= last_rssi <= -45:
        score += 10
        reasons.append("stable_signal_range")
        camera_conf += 10
        camera_reasons.append("fixed_presence_hint")

    if last_rssi is not None and last_rssi >= -50:
        camera_conf += 10
        camera_reasons.append("very_close_hint")

    # Clamp and categorize.
    score = max(0, min(100, score))
    camera_conf = max(0, min(100, camera_conf))
    if score >= 60:
        category = "Suspicious"
    elif score >= 30:
        category = "Interesting"
    else:
        category = "Normal"

    return ScoreResult(
        score=score,
        category=category,
        reasons=reasons,
        camera_confidence=camera_conf,
        camera_reasons=camera_reasons,
    )

