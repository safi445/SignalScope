from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.context.arp_cache import read_arp_cache
from app.db import (
    fetch_device_history,
    fetch_device_rssi_stats,
    fetch_events,
    fetch_last_seen_before,
    fetch_seen_devices_in_window,
    fetch_window_summary,
)
from app.orchestrator import ScannerOrchestrator, utcnow
from app.scoring import score_device
from app.watchlist import load_rules, match_device


def register_routes(*, app: FastAPI, orchestrator: ScannerOrchestrator, templates: Jinja2Templates) -> None:
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

        snap = orchestrator.snapshot()
        cur = next((d for d in snap["devices"] if d["device_id"] == device_id), None)
        mv = classify_movement(
            last_rssi=cur.get("last_rssi") if cur else None,
            rssi_mean=stats.get("mean"),
            rssi_std=stats.get("std"),
            seen_count=int(cur.get("seen_count") or 0) if cur else int(stats.get("n") or 0),
        )
        return {
            "device_id": device_id,
            "minutes": minutes,
            "rssi_stats": stats,
            "movement": mv.movement,
            "movement_score": mv.score,
        }

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
        history_rows = await fetch_device_history(orchestrator.db_path, device_id=device_id, limit=60)

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
            "history": history_rows,
        }

    @app.get("/neighbors")
    async def neighbors() -> dict[str, Any]:
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
        now = utcnow()
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
            w.writerow(
                [
                    e.get("ts"),
                    e.get("event_type"),
                    e.get("severity"),
                    e.get("title"),
                    e.get("device_key"),
                    e.get("details_json"),
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=events.csv"},
        )

