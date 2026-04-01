from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


@dataclass(frozen=True)
class Event:
    ts: datetime
    event_type: str
    severity: str  # info/warn/alert
    title: str
    details: dict[str, Any]
    device_key: Optional[str] = None  # "wifi:xx" or "ble:yy"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_density_anomaly(*, baseline_avg: float, baseline_std: float, current: int) -> Optional[dict[str, Any]]:
    if baseline_avg <= 0:
        return None
    # z-score-ish
    denom = baseline_std if baseline_std > 0.5 else 0.5
    z = (current - baseline_avg) / denom
    if current >= max(10, int(baseline_avg * 1.6)) and z >= 2.5:
        return {"z": z, "baseline_avg": baseline_avg, "baseline_std": baseline_std, "current": current}
    return None


def compute_burst_anomaly(*, baseline_new_per_min: float, current_new_per_min: float) -> Optional[dict[str, Any]]:
    if current_new_per_min >= max(6.0, baseline_new_per_min * 2.5):
        return {"baseline_new_per_min": baseline_new_per_min, "current_new_per_min": current_new_per_min}
    return None

