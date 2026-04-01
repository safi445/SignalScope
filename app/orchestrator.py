from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.collectors.bleak_ble import BleakBleCollector
from app.collectors.mock import MockCollector
from app.collectors.termux import TermuxBleCollector, TermuxWifiCollector
from app.collectors.windows_wifi import WindowsNetshWifiCollector
from app.db import (
    fetch_density_baseline,
    fetch_new_device_rate_baseline,
    fetch_seen_devices_in_window,
    init_db,
    insert_event,
    insert_observation,
)
from app.events import compute_burst_anomaly, compute_density_anomaly
from app.state import AppState
from app.watchlist import load_rules, match_device


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScannerOrchestrator:
    db_path: str
    scan_interval_s: float = 3.0
    state: AppState = field(default_factory=AppState)

    wifi: TermuxWifiCollector = field(default_factory=TermuxWifiCollector)
    ble: TermuxBleCollector = field(default_factory=TermuxBleCollector)
    bleak_ble: BleakBleCollector = field(init=False)
    windows_wifi: WindowsNetshWifiCollector = field(default_factory=WindowsNetshWifiCollector)

    mock: MockCollector = field(default_factory=MockCollector)
    force_mock: bool = field(init=False)

    _task: Optional[asyncio.Task[None]] = field(default=None, init=False)
    _prev_scores: dict[str, int] = field(default_factory=dict, init=False)
    _watchlist_last_emitted: dict[str, datetime] = field(default_factory=dict, init=False)
    _prev_device_ids_60s: set[str] = field(default_factory=set, init=False)
    _prev_device_keys: set[str] = field(default_factory=set, init=False)
    _last_event_ts: Optional[datetime] = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.force_mock = os.environ.get("RECON_MODE", "").lower() == "mock"
        self.bleak_ble = BleakBleCollector(
            scan_seconds=min(2.0, max(0.8, self.scan_interval_s - 0.5))
        )

    async def start(self) -> None:
        await init_db(self.db_path)
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        while True:
            now = utcnow()
            observations: list[Any] = []

            if not self.force_mock:
                observations.extend(list(self.wifi.collect(now)))
                observations.extend(list(self.ble.collect(now)))

                if not any(o.signal_type == "wifi" for o in observations):
                    observations.extend(list(self.windows_wifi.collect(now)))

                if not any(o.signal_type == "ble" for o in observations):
                    observations.extend(list(await self.bleak_ble.collect(now)))

            if self.force_mock or len(observations) == 0:
                observations = list(self.mock.collect(now))

            for obs in observations:
                self.state.ingest(obs)
                await insert_observation(self.db_path, obs)

            await self._detect_anomalies()
            await asyncio.sleep(self.scan_interval_s)

    async def _emit_event(
        self,
        *,
        event_type: str,
        severity: str,
        title: str,
        details: dict[str, Any],
        device_key: Optional[str] = None,
    ) -> None:
        import json

        await insert_event(
            self.db_path,
            ts=utcnow().isoformat(),
            event_type=event_type,
            severity=severity,
            title=title,
            device_key=device_key,
            details_json=json.dumps(details),
        )

    async def _detect_anomalies(self) -> None:
        snap = self.snapshot()
        devices = snap["devices"]
        device_keys = {f"{d.get('signal_type')}:{d.get('device_id')}" for d in devices}
        rules = load_rules()

        new_keys = sorted(device_keys - self._prev_device_keys)
        lost_keys = sorted(self._prev_device_keys - device_keys)
        self._prev_device_keys = device_keys

        now_ts = utcnow()
        if self._last_event_ts is None or (now_ts - self._last_event_ts).total_seconds() >= 10:
            if new_keys:
                await self._emit_event(
                    event_type="devices_new",
                    severity="info",
                    title=f"New devices observed (+{len(new_keys)})",
                    details={"new": new_keys[:50]},
                )
                self._last_event_ts = now_ts
            if lost_keys:
                await self._emit_event(
                    event_type="devices_lost",
                    severity="info",
                    title=f"Devices disappeared (-{len(lost_keys)})",
                    details={"lost": lost_keys[:50]},
                )
                self._last_event_ts = now_ts

        baseline = await fetch_density_baseline(self.db_path, minutes=30)
        dens = compute_density_anomaly(
            baseline_avg=float(baseline.get("avg", 0.0)),
            baseline_std=float(baseline.get("std", 0.0)),
            current=int(snap["device_count"]),
        )
        if dens and int(baseline.get("buckets", 0)) >= 8:
            await self._emit_event(
                event_type="density_spike",
                severity="warn",
                title="Density spike detected",
                details=dens,
            )

        since = utcnow() - timedelta(seconds=60)
        now_seen = await fetch_seen_devices_in_window(self.db_path, since=since)
        new_last_min = len(now_seen - self._prev_device_ids_60s)
        self._prev_device_ids_60s = now_seen

        baseline_new = await fetch_new_device_rate_baseline(self.db_path, minutes=30)
        burst = compute_burst_anomaly(
            baseline_new_per_min=float(baseline_new.get("avg_new", 0.0)),
            current_new_per_min=float(new_last_min),
        )
        if (burst and int(baseline_new.get("buckets", 0)) >= 8) or (new_last_min >= 8):
            await self._emit_event(
                event_type="new_device_burst",
                severity="info",
                title="New device burst (last 60s)",
                details={"new_last_min": new_last_min, **(burst or {})},
            )

        for d in devices:
            key = f"{d.get('signal_type')}:{d.get('device_id')}"
            score = int(d.get("suspicion_score") or 0)
            prev = self._prev_scores.get(key)
            self._prev_scores[key] = score
            if prev is None:
                continue
            if score - prev >= 25 and score >= 40:
                await self._emit_event(
                    event_type="score_jump",
                    severity="alert" if score >= 60 else "warn",
                    title="Suspicion score jumped",
                    device_key=key,
                    details={"previous": prev, "current": score},
                )

            hits = match_device(rules, d)
            if hits:
                last = self._watchlist_last_emitted.get(key)
                if last and (utcnow() - last).total_seconds() < 60:
                    continue
                await self._emit_event(
                    event_type="watchlist_hit",
                    severity="alert",
                    title="Watchlist hit",
                    device_key=key,
                    details={
                        "hits": hits,
                        "device": {
                            "ssid": d.get("ssid"),
                            "name": d.get("name"),
                            "vendor": d.get("vendor"),
                        },
                    },
                )
                self._watchlist_last_emitted[key] = utcnow()

    def snapshot(self) -> dict[str, Any]:
        devices = [d.to_summary() for d in self.state.devices.values()]
        devices.sort(key=lambda x: (x.suspicion_score, x.last_rssi or -999), reverse=True)

        def ser_dt(dt: datetime) -> str:
            return dt.astimezone(timezone.utc).isoformat()

        return {
            "ts": ser_dt(self.state.last_scan_ts) if self.state.last_scan_ts else None,
            "device_count": len(devices),
            "devices": [
                {
                    "signal_type": d.signal_type,
                    "device_id": d.device_id,
                    "source": d.source,
                    "name": d.name,
                    "ssid": d.ssid,
                    "security": d.security,
                    "band": d.band,
                    "vendor": d.vendor,
                    "tags": d.tags or [],
                    "first_seen": ser_dt(d.first_seen),
                    "last_seen": ser_dt(d.last_seen),
                    "last_rssi": d.last_rssi,
                    "seen_count": d.seen_count,
                    "suspicion_score": d.suspicion_score,
                    "category": d.category,
                }
                for d in devices
            ],
        }

