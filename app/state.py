from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.hwaddr import normalize_hw_address
from app.models import Observation, DeviceSummary
from app.movement import classify_movement
from app.scoring import score_device


@dataclass
class TrackedDevice:
    signal_type: str
    device_id: str
    source: str = "unknown"
    name: Optional[str] = None
    ssid: Optional[str] = None
    security: Optional[str] = None
    band: Optional[str] = None
    vendor: Optional[str] = None
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    last_rssi: Optional[int] = None
    seen_count: int = 0

    def update(self, obs: Observation) -> None:
        self.last_seen = obs.ts
        self.seen_count += 1
        if obs.source:
            self.source = obs.source
        if obs.name:
            self.name = obs.name
        if obs.ssid is not None:
            self.ssid = obs.ssid
        if obs.security is not None:
            self.security = obs.security
        if obs.band is not None:
            self.band = obs.band
        if obs.vendor:
            self.vendor = obs.vendor
        if obs.rssi is not None:
            self.last_rssi = obs.rssi

    def to_summary(self) -> DeviceSummary:
        persistent_seconds = (self.last_seen - self.first_seen).total_seconds()
        scored = score_device(
            signal_type=self.signal_type,
            device_id=self.device_id,
            name=self.name,
            ssid=self.ssid,
            security=self.security,
            vendor=self.vendor,
            last_rssi=self.last_rssi,
            seen_count=self.seen_count,
            persistent_seconds=persistent_seconds,
        )
        tags: list[str] = []
        if scored.camera_confidence >= 60:
            tags.append("potential_camera")
        return DeviceSummary(
            signal_type=self.signal_type,  # type: ignore[arg-type]
            device_id=self.device_id,
            source=self.source,
            name=self.name,
            ssid=self.ssid,
            security=self.security,
            band=self.band,
            vendor=self.vendor,
            movement=None,
            movement_score=None,
            tags=tags,
            first_seen=self.first_seen,
            last_seen=self.last_seen,
            last_rssi=self.last_rssi,
            seen_count=self.seen_count,
            suspicion_score=scored.score,
            category=scored.category,  # type: ignore[arg-type]
        )


@dataclass
class AppState:
    devices: dict[str, TrackedDevice] = field(default_factory=dict)
    last_scan_ts: Optional[datetime] = None

    def ingest(self, obs: Observation) -> None:
        device_id = normalize_hw_address(obs.device_id) if obs.signal_type in ("wifi", "ble") else obs.device_id
        key = f"{obs.signal_type}:{device_id}"
        d = self.devices.get(key)
        if d is None:
            d = TrackedDevice(
                signal_type=obs.signal_type,
                device_id=device_id,
                source=obs.source,
                name=obs.name,
                ssid=obs.ssid,
                security=obs.security,
                band=obs.band,
                vendor=obs.vendor,
                first_seen=obs.ts,
                last_seen=obs.ts,
                last_rssi=obs.rssi,
                seen_count=0,
            )
            self.devices[key] = d
        d.update(obs)
        self.last_scan_ts = obs.ts

