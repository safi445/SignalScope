from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import csv
import io

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.collectors.mock import MockCollector
from app.collectors.bleak_ble import BleakBleCollector
from app.collectors.termux import TermuxBleCollector, TermuxWifiCollector
from app.collectors.windows_wifi import WindowsNetshWifiCollector
from app.db import (
    fetch_device_history,
    fetch_events,
    fetch_density_baseline,
    fetch_new_device_rate_baseline,
    fetch_device_rssi_stats,
    fetch_last_seen_before,
    fetch_seen_devices_in_window,
    fetch_window_summary,
    init_db,
    insert_event,
    insert_observation,
)
from app.state import AppState
from app.events import compute_burst_anomaly, compute_density_anomaly, utcnow
from app.watchlist import load_rules, match_device
from app.scoring import score_device
from app.context.arp_cache import read_arp_cache


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScannerOrchestrator:
    def __init__(self, *, db_path: str, scan_interval_s: float = 3.0) -> None:
        self.db_path = db_path
        self.scan_interval_s = scan_interval_s
        self.state = AppState()

        # Try Termux collectors; they will return [] if commands missing.
        self.wifi = TermuxWifiCollector()
        self.ble = TermuxBleCollector()
        self.bleak_ble = BleakBleCollector(scan_seconds=min(2.0, max(0.8, scan_interval_s - 0.5)))
        self.windows_wifi = WindowsNetshWifiCollector()

        self.mock = MockCollector()
        self.force_mock = os.environ.get("RECON_MODE", "").lower() == "mock"

        self._task: Optional[asyncio.Task[None]] = None
        self._prev_scores: dict[str, int] = {}
        self._watchlist_last_emitted: dict[str, datetime] = {}
        self._prev_device_ids_60s: set[str] = set()
        self._prev_device_keys: set[str] = set()
        self._last_event_ts: Optional[datetime] = None

    async def start(self) -> None:
        await init_db(self.db_path)
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        while True:
            now = _utcnow()
            observations: list[Any] = []

            if not self.force_mock:
                observations.extend(list(self.wifi.collect(now)))
                observations.extend(list(self.ble.collect(now)))

                # Desktop Wi‑Fi fallback (Windows) when Termux Wi‑Fi is unavailable.
                if not any(o.signal_type == "wifi" for o in observations):
                    observations.extend(list(self.windows_wifi.collect(now)))

                # Desktop BLE fallback (Windows/macOS/Linux) when Termux BLE is unavailable.
                if not any(o.signal_type == "ble" for o in observations):
                    observations.extend(list(await self.bleak_ble.collect(now)))

            # Fallback to mock if nothing collected (or forced).
            if self.force_mock or len(observations) == 0:
                observations = list(self.mock.collect(now))

            for obs in observations:
                self.state.ingest(obs)
                await insert_observation(self.db_path, obs)

            # After ingest, run anomaly detection on the current snapshot.
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
            ts=_utcnow().isoformat(),
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

        # Always emit basic change events (useful even before a baseline exists).
        new_keys = sorted(device_keys - self._prev_device_keys)
        lost_keys = sorted(self._prev_device_keys - device_keys)
        self._prev_device_keys = device_keys

        # Throttle repetitive "change" events to avoid spam.
        now_ts = _utcnow()
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

        # Density anomaly (distinct device count) vs baseline.
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

        # New device burst (new devices in last ~60s) vs baseline new/min.
        since = _utcnow() - timedelta(seconds=60)
        now_seen = await fetch_seen_devices_in_window(self.db_path, since=since)
        new_last_min = len(now_seen - self._prev_device_ids_60s)
        self._prev_device_ids_60s = now_seen

        baseline_new = await fetch_new_device_rate_baseline(self.db_path, minutes=30)
        burst = compute_burst_anomaly(
            baseline_new_per_min=float(baseline_new.get("avg_new", 0.0)),
            current_new_per_min=float(new_last_min),
        )
        # If we don't have baseline yet, still emit a burst event on obvious spikes.
        if (burst and int(baseline_new.get("buckets", 0)) >= 8) or (new_last_min >= 8):
            await self._emit_event(
                event_type="new_device_burst",
                severity="info",
                title="New device burst (last 60s)",
                details={"new_last_min": new_last_min, **(burst or {})},
            )

        # Suspicion score jump per device.
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

            # Watchlist matches -> alert events (throttled per device via score cache presence).
            hits = match_device(rules, d)
            if hits:
                last = self._watchlist_last_emitted.get(key)
                if last and (_utcnow() - last).total_seconds() < 60:
                    continue
                await self._emit_event(
                    event_type="watchlist_hit",
                    severity="alert",
                    title="Watchlist hit",
                    device_key=key,
                    details={"hits": hits, "device": {"ssid": d.get("ssid"), "name": d.get("name"), "vendor": d.get("vendor")}},
                )
                self._watchlist_last_emitted[key] = _utcnow()

    def snapshot(self) -> dict[str, Any]:
        devices = [d.to_summary() for d in self.state.devices.values()]
        devices.sort(key=lambda x: (x.suspicion_score, x.last_rssi or -999), reverse=True)

        def ser_dt(dt: datetime) -> str:
            return dt.astimezone(timezone.utc).isoformat()

        # Enrich with movement classification from recent RSSI variability.
        from app.movement import classify_movement

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
                    # movement fields filled lazily on client via /device_stats; kept here for compatibility
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


def create_app(*, db_path: str) -> FastAPI:
    app = FastAPI(title="SignalScope", version="0.1.0")
    orchestrator = ScannerOrchestrator(db_path=db_path)
    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "web", "templates"))

    static_dir = os.path.join(os.path.dirname(__file__), "..", "web", "static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.on_event("startup")
    async def _startup() -> None:
        await orchestrator.start()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "title": "SignalScope Radar",
            },
        )

    @app.get("/scan")
    async def scan() -> dict[str, Any]:
        return orchestrator.snapshot()

    @app.get("/devices")
    async def devices() -> dict[str, Any]:
        return orchestrator.snapshot()

    @app.get("/suspicious")
    async def suspicious() -> dict[str, Any]:
        snap = orchestrator.snapshot()
        snap["devices"] = [d for d in snap["devices"] if d["suspicion_score"] >= 60]
        snap["device_count"] = len(snap["devices"])
        return snap

    @app.get("/history")
    async def history(device_id: str = Query(...), limit: int = Query(200, ge=1, le=2000)) -> dict[str, Any]:
        rows = await fetch_device_history(orchestrator.db_path, device_id=device_id, limit=limit)
        return {"device_id": device_id, "rows": rows}

    @app.get("/device_stats")
    async def device_stats(device_id: str = Query(...), minutes: int = Query(10, ge=1, le=120)) -> dict[str, Any]:
        stats = await fetch_device_rssi_stats(orchestrator.db_path, device_id=device_id, minutes=minutes)
        from app.movement import classify_movement

        # Find current summary if present.
        snap = orchestrator.snapshot()
        cur = next((d for d in snap["devices"] if d["device_id"] == device_id), None)
        mv = classify_movement(
            last_rssi=cur.get("last_rssi") if cur else None,
            rssi_mean=stats.get("mean"),
            rssi_std=stats.get("std"),
            seen_count=int(cur.get("seen_count") or 0) if cur else int(stats.get("n") or 0),
        )
        return {"device_id": device_id, "minutes": minutes, "rssi_stats": stats, "movement": mv.movement, "movement_score": mv.score}

    @app.get("/device_detail")
    async def device_detail(device_id: str = Query(...), minutes: int = Query(10, ge=1, le=120)) -> dict[str, Any]:
        snap = orchestrator.snapshot()
        d = next((x for x in snap["devices"] if x["device_id"] == device_id), None)
        if not d:
            return {"device_id": device_id, "found": False}

        persistent_seconds = 0.0
        try:
            persistent_seconds = (
                datetime.fromisoformat(d["last_seen"]) - datetime.fromisoformat(d["first_seen"])
            ).total_seconds()
        except Exception:
            persistent_seconds = 0.0

        scored = score_device(
            signal_type=d.get("signal_type"),
            device_id=d.get("device_id"),
            name=d.get("name"),
            ssid=d.get("ssid"),
            security=d.get("security"),
            vendor=d.get("vendor"),
            last_rssi=d.get("last_rssi"),
            seen_count=int(d.get("seen_count") or 0),
            persistent_seconds=persistent_seconds,
        )

        rules = load_rules()
        watch_hits = match_device(rules, d)

        stats = await fetch_device_rssi_stats(orchestrator.db_path, device_id=device_id, minutes=minutes)
        history = await fetch_device_history(orchestrator.db_path, device_id=device_id, limit=60)

        return {
            "found": True,
            "device": d,
            "score": {
                "score": scored.score,
                "category": scored.category,
                "reasons": scored.reasons,
            },
            "camera": {
                "confidence": scored.camera_confidence,
                "reasons": scored.camera_reasons,
                "tagged": scored.camera_confidence >= 60,
            },
            "watchlist": {
                "hits": watch_hits,
                "matched": len(watch_hits) > 0,
            },
            "rssi_stats": stats,
            "history": history,
        }

    @app.get("/neighbors")
    async def neighbors() -> dict[str, Any]:
        # Passive/local-only: ARP cache (no scanning/probing).
        return read_arp_cache()

    @app.get("/events")
    async def events(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        rows = await fetch_events(orchestrator.db_path, limit=limit)
        return {"rows": rows}

    @app.get("/rules")
    async def rules() -> dict[str, Any]:
        return {"rules": load_rules()}

    @app.get("/debrief")
    async def debrief(minutes: int = Query(5, ge=1, le=120)) -> dict[str, Any]:
        now = _utcnow()
        since = now - timedelta(minutes=minutes)
        summary = await fetch_window_summary(orchestrator.db_path, since=since)

        now_seen = await fetch_seen_devices_in_window(orchestrator.db_path, since=since)
        prior_seen = await fetch_last_seen_before(orchestrator.db_path, before=since)
        new_devices = sorted(now_seen - prior_seen)
        lost_devices = sorted(prior_seen - now_seen)

        snap = orchestrator.snapshot()
        suspicious_now = [d for d in snap["devices"] if d["suspicion_score"] >= 60]

        density = "Low" if snap["device_count"] < 8 else "Medium" if snap["device_count"] < 20 else "High"

        return {
            "scan_window_minutes": minutes,
            "now": now.isoformat(),
            "observations_in_window": summary.get("obs_count", 0),
            "unique_devices_in_window": summary.get("device_count", 0),
            "new_devices": new_devices[:50],
            "lost_devices": lost_devices[:50],
            "suspicious": suspicious_now[:20],
            "recent_events": (await fetch_events(orchestrator.db_path, limit=25)),
            "environment": {
                "density": density,
                "note": "Passive metadata only; scores are heuristic, not proof.",
            },
        }

    @app.get("/export/devices.csv")
    async def export_devices_csv() -> Response:
        snap = orchestrator.snapshot()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "signal_type",
                "device_id",
                "source",
                "ssid",
                "name",
                "vendor",
                "band",
                "security",
                "last_rssi",
                "seen_count",
                "first_seen",
                "last_seen",
                "suspicion_score",
                "category",
            ]
        )
        for d in snap["devices"]:
            w.writerow(
                [
                    d.get("signal_type"),
                    d.get("device_id"),
                    d.get("source"),
                    d.get("ssid"),
                    d.get("name"),
                    d.get("vendor"),
                    d.get("band"),
                    d.get("security"),
                    d.get("last_rssi"),
                    d.get("seen_count"),
                    d.get("first_seen"),
                    d.get("last_seen"),
                    d.get("suspicion_score"),
                    d.get("category"),
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=devices.csv"},
        )

    @app.get("/export/events.csv")
    async def export_events_csv(limit: int = Query(500, ge=1, le=5000)) -> Response:
        rows = await fetch_events(orchestrator.db_path, limit=limit)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "event_type", "severity", "title", "device_key", "details_json"])
        for e in rows:
            w.writerow([e.get("ts"), e.get("event_type"), e.get("severity"), e.get("title"), e.get("device_key"), e.get("details_json")])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=events.csv"},
        )

    return app

