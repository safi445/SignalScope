from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


SignalType = Literal["wifi", "ble"]


@dataclass(frozen=True)
class Observation:
    ts: datetime
    signal_type: SignalType
    device_id: str  # wifi: bssid, ble: address (or stable id)
    source: str  # termux / bleak / windows / mock
    name: Optional[str]
    rssi: Optional[int]
    frequency_mhz: Optional[int] = None  # wifi only
    channel: Optional[int] = None  # wifi only
    ssid: Optional[str] = None  # wifi only
    security: Optional[str] = None  # wifi only (best effort)
    band: Optional[str] = None  # wifi only (2.4GHz/5GHz/6GHz)
    vendor: Optional[str] = None
    raw: Optional[dict] = None


@dataclass(frozen=True)
class DeviceSummary:
    signal_type: SignalType
    device_id: str
    source: str
    name: Optional[str]
    ssid: Optional[str]
    security: Optional[str]
    band: Optional[str]
    vendor: Optional[str]
    first_seen: datetime
    last_seen: datetime
    last_rssi: Optional[int]
    seen_count: int
    suspicion_score: int
    category: Literal["Normal", "Interesting", "Suspicious"]
    movement: Optional[Literal["static", "moving", "unknown"]] = None
    movement_score: Optional[float] = None
    tags: Optional[list[str]] = None

