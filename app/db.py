from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import aiosqlite

from app.models import Observation


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  device_id TEXT NOT NULL,
  source TEXT,
  name TEXT,
  rssi INTEGER,
  frequency_mhz INTEGER,
  channel INTEGER,
  ssid TEXT,
  security TEXT,
  band TEXT,
  vendor TEXT,
  raw_json TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  device_key TEXT,
  details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_time
  ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type
  ON events(event_type, ts);

CREATE INDEX IF NOT EXISTS idx_obs_device_time
  ON observations(device_id, ts);
CREATE INDEX IF NOT EXISTS idx_obs_time
  ON observations(ts);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA_SQL)
        # Lightweight migration for older DBs.
        cur = await db.execute("PRAGMA table_info(observations)")
        cols = {row[1] for row in await cur.fetchall()}
        for col, ddl in [
            ("source", "ALTER TABLE observations ADD COLUMN source TEXT"),
            ("security", "ALTER TABLE observations ADD COLUMN security TEXT"),
            ("band", "ALTER TABLE observations ADD COLUMN band TEXT"),
        ]:
            if col not in cols:
                await db.execute(ddl)
        await db.commit()


async def insert_event(
    db_path: str,
    *,
    ts: str,
    event_type: str,
    severity: str,
    title: str,
    device_key: Optional[str],
    details_json: Optional[str],
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO events (ts, event_type, severity, title, device_key, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, event_type, severity, title, device_key, details_json),
        )
        await db.commit()


async def fetch_events(db_path: str, limit: int = 100) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT ts, event_type, severity, title, device_key, details_json
            FROM events
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def fetch_density_baseline(db_path: str, minutes: int = 30) -> dict[str, Any]:
    """
    Baseline computed over the last N minutes using 1-minute buckets of distinct devices.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            WITH buckets AS (
              SELECT
                substr(ts, 1, 16) AS minute_bucket,
                COUNT(DISTINCT device_id) AS device_count
              FROM observations
              WHERE ts >= datetime('now', ?)
              GROUP BY minute_bucket
            )
            SELECT
              AVG(device_count) AS avg_count,
              AVG(device_count * device_count) - AVG(device_count) * AVG(device_count) AS var_count,
              COUNT(*) AS bucket_count
            FROM buckets
            """,
            (f"-{minutes} minutes",),
        )
        row = await cur.fetchone()
        if not row:
            return {"avg": 0.0, "std": 0.0, "buckets": 0}
        avg = float(row["avg_count"] or 0.0)
        var = float(row["var_count"] or 0.0)
        std = (var ** 0.5) if var > 0 else 0.0
        return {"avg": avg, "std": std, "buckets": int(row["bucket_count"] or 0)}


async def fetch_new_device_rate_baseline(db_path: str, minutes: int = 30) -> dict[str, Any]:
    """
    Baseline new devices per minute in the last N minutes.
    A "new device" is the first time a device_id appears in each minute bucket.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            WITH first_seen AS (
              SELECT device_id, MIN(ts) AS first_ts
              FROM observations
              GROUP BY device_id
            ),
            buckets AS (
              SELECT substr(first_ts, 1, 16) AS minute_bucket, COUNT(*) AS new_devices
              FROM first_seen
              WHERE first_ts >= datetime('now', ?)
              GROUP BY minute_bucket
            )
            SELECT AVG(new_devices) AS avg_new, COUNT(*) AS bucket_count
            FROM buckets
            """,
            (f"-{minutes} minutes",),
        )
        row = await cur.fetchone()
        return {"avg_new": float(row["avg_new"] or 0.0), "buckets": int(row["bucket_count"] or 0)}


async def insert_observation(db_path: str, obs: Observation) -> None:
    import json

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO observations
              (ts, signal_type, device_id, source, name, rssi, frequency_mhz, channel, ssid, security, band, vendor, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs.ts.isoformat(),
                obs.signal_type,
                obs.device_id,
                obs.source,
                obs.name,
                obs.rssi,
                obs.frequency_mhz,
                obs.channel,
                obs.ssid,
                obs.security,
                obs.band,
                obs.vendor,
                json.dumps(obs.raw) if obs.raw is not None else None,
            ),
        )
        await db.commit()


async def fetch_device_history(db_path: str, device_id: str, limit: int = 200) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT ts, signal_type, device_id, source, name, rssi, frequency_mhz, channel, ssid, security, band, vendor, raw_json
            FROM observations
            WHERE device_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (device_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def fetch_device_rssi_stats(db_path: str, device_id: str, minutes: int = 10) -> dict[str, Any]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
              COUNT(rssi) AS n,
              AVG(rssi) AS mean_rssi,
              AVG(rssi * rssi) - AVG(rssi) * AVG(rssi) AS var_rssi
            FROM observations
            WHERE device_id = ?
              AND rssi IS NOT NULL
              AND ts >= datetime('now', ?)
            """,
            (device_id, f"-{minutes} minutes"),
        )
        row = await cur.fetchone()
        if not row:
            return {"n": 0, "mean": None, "std": None}
        n = int(row["n"] or 0)
        mean = float(row["mean_rssi"]) if row["mean_rssi"] is not None else None
        var = float(row["var_rssi"]) if row["var_rssi"] is not None else None
        std = (var ** 0.5) if (var is not None and var > 0) else 0.0 if n > 0 else None
        return {"n": n, "mean": mean, "std": std}


async def fetch_window_summary(
    db_path: str,
    since: datetime,
) -> dict[str, Any]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
              COUNT(*) AS obs_count,
              COUNT(DISTINCT device_id) AS device_count
            FROM observations
            WHERE ts >= ?
            """,
            (since.isoformat(),),
        )
        row = await cur.fetchone()
        return dict(row) if row else {"obs_count": 0, "device_count": 0}


async def fetch_seen_devices_in_window(db_path: str, since: datetime) -> set[str]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            SELECT DISTINCT device_id
            FROM observations
            WHERE ts >= ?
            """,
            (since.isoformat(),),
        )
        rows = await cur.fetchall()
        return {r[0] for r in rows}


async def fetch_last_seen_before(db_path: str, before: datetime) -> set[str]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            SELECT DISTINCT device_id
            FROM observations
            WHERE ts < ?
            """,
            (before.isoformat(),),
        )
        rows = await cur.fetchall()
        return {r[0] for r in rows}

