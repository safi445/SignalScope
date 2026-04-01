from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from typing import Iterable, Optional

from app.collectors.base import Collector
from app.models import Observation
from app.oui import vendor_from_mac
from app.wifi_enrich import band_from_frequency_mhz, normalize_security


def _run_json(cmd: list[str], timeout_s: int = 8) -> Optional[object]:
    if not shutil.which(cmd[0]):
        return None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except Exception:
        return None
    out = (p.stdout or "").strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


class TermuxWifiCollector(Collector):
    def collect(self, now: datetime) -> Iterable[Observation]:
        data = _run_json(["termux-wifi-scaninfo"])
        if not isinstance(data, list):
            return []

        obs: list[Observation] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            bssid = item.get("bssid") or item.get("BSSID")
            if not bssid:
                continue
            ssid = item.get("ssid") or item.get("SSID")
            rssi = item.get("level") if "level" in item else item.get("rssi")
            try:
                rssi_i = int(rssi) if rssi is not None else None
            except Exception:
                rssi_i = None

            freq = item.get("frequency")
            try:
                freq_i = int(freq) if freq is not None else None
            except Exception:
                freq_i = None

            band = band_from_frequency_mhz(freq_i)

            security = item.get("capabilities") or item.get("security") or item.get("capability")
            security_s = normalize_security(str(security)) if security is not None else None

            # Channel is optional; not always provided.
            channel = item.get("channel")
            try:
                channel_i = int(channel) if channel is not None else None
            except Exception:
                channel_i = None

            obs.append(
                Observation(
                    ts=now,
                    signal_type="wifi",
                    device_id=str(bssid),
                    source="termux",
                    name=None,
                    rssi=rssi_i,
                    frequency_mhz=freq_i,
                    channel=channel_i,
                    ssid=str(ssid) if ssid is not None else None,
                    security=security_s,
                    band=band,
                    vendor=vendor_from_mac(str(bssid)),
                    raw=item,
                )
            )
        return obs


class TermuxBleCollector(Collector):
    """
    Best-effort BLE metadata collection.

    Termux:API support varies by Android version/device; if unavailable, returns no observations.
    """

    def collect(self, now: datetime) -> Iterable[Observation]:
        # On some devices: termux-bluetooth-scaninfo returns a JSON list.
        data = _run_json(["termux-bluetooth-scaninfo"])
        if not isinstance(data, list):
            return []

        obs: list[Observation] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            addr = item.get("address") or item.get("mac") or item.get("id")
            if not addr:
                continue
            name = item.get("name")
            rssi = item.get("rssi") or item.get("level")
            try:
                rssi_i = int(rssi) if rssi is not None else None
            except Exception:
                rssi_i = None

            obs.append(
                Observation(
                    ts=now,
                    signal_type="ble",
                    device_id=str(addr),
                    source="termux",
                    name=str(name) if name is not None else None,
                    rssi=rssi_i,
                    vendor=vendor_from_mac(str(addr)),
                    raw=item,
                )
            )
        return obs

