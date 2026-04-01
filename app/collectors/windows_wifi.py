from __future__ import annotations

import platform
import re
import subprocess
from datetime import datetime
from typing import Iterable, Optional

from app.collectors.base import Collector
from app.models import Observation
from app.oui import vendor_from_mac
from app.wifi_enrich import band_from_channel, normalize_security


_RE_SSID = re.compile(r"^\s*SSID\s+\d+\s*:\s*(.*)\s*$", re.IGNORECASE)
_RE_AUTH = re.compile(r"^\s*Authentication\s*:\s*(.*)\s*$", re.IGNORECASE)
_RE_BSSID = re.compile(r"^\s*BSSID\s+\d+\s*:\s*([0-9A-Fa-f:]{17})\s*$")
_RE_SIGNAL = re.compile(r"^\s*Signal\s*:\s*(\d+)\s*%\s*$", re.IGNORECASE)
_RE_CHANNEL = re.compile(r"^\s*Channel\s*:\s*(\d+)\s*$", re.IGNORECASE)


def _pct_to_rssi(pct: int) -> int:
    """
    Convert Windows signal percent to approximate RSSI.
    Very rough mapping: 0% -> -100 dBm, 100% -> -50 dBm
    """
    pct = max(0, min(100, pct))
    return int(-100 + (pct * 0.5))


class WindowsNetshWifiCollector(Collector):
    """
    Passive Wi‑Fi metadata scan using:
      netsh wlan show networks mode=bssid
    """

    def collect(self, now: datetime) -> Iterable[Observation]:
        if platform.system().lower() != "windows":
            return []

        try:
            p = subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=bssid"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
            )
        except Exception:
            return []

        text = (p.stdout or "").splitlines()
        if not text:
            return []

        ssid: Optional[str] = None
        security: Optional[str] = None
        bssid: Optional[str] = None
        signal_pct: Optional[int] = None
        channel: Optional[int] = None

        obs: list[Observation] = []

        def flush_bssid() -> None:
            nonlocal bssid, signal_pct, channel
            if not bssid:
                return
            rssi = _pct_to_rssi(signal_pct) if signal_pct is not None else None
            band = band_from_channel(channel)
            obs.append(
                Observation(
                    ts=now,
                    signal_type="wifi",
                    device_id=bssid.upper(),
                    source="windows",
                    name=None,
                    rssi=rssi,
                    frequency_mhz=None,
                    channel=channel,
                    ssid=ssid,
                    security=normalize_security(security),
                    band=band,
                    vendor=vendor_from_mac(bssid),
                    raw={
                        "ssid": ssid,
                        "authentication": security,
                        "signal_pct": signal_pct,
                        "channel": channel,
                    },
                )
            )
            bssid = None
            signal_pct = None
            channel = None

        for line in text:
            m = _RE_SSID.match(line)
            if m:
                # new SSID block
                flush_bssid()
                ssid = m.group(1).strip()
                if ssid == "":
                    ssid = "<hidden>"
                security = None
                continue

            m = _RE_AUTH.match(line)
            if m:
                security = m.group(1).strip()
                continue

            m = _RE_BSSID.match(line)
            if m:
                flush_bssid()
                bssid = m.group(1)
                continue

            m = _RE_SIGNAL.match(line)
            if m:
                try:
                    signal_pct = int(m.group(1))
                except Exception:
                    signal_pct = None
                continue

            m = _RE_CHANNEL.match(line)
            if m:
                try:
                    channel = int(m.group(1))
                except Exception:
                    channel = None
                continue

        flush_bssid()
        return obs

