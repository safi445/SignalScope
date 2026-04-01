from __future__ import annotations

import random
from datetime import datetime
from typing import Iterable

from app.models import Observation
from app.oui import vendor_from_mac
from app.collectors.base import Collector


def _jitter(v: int, spread: int = 4) -> int:
    return v + random.randint(-spread, spread)


class MockCollector(Collector):
    def __init__(self, seed: int | None = 7) -> None:
        self._rnd = random.Random(seed)

    def collect(self, now: datetime) -> Iterable[Observation]:
        # Deterministic-ish devices, RSSI jitters each scan.
        wifi_devices = [
            {"ssid": "HomeWiFi", "bssid": "DC:A6:32:11:22:33", "rssi": -48, "freq": 2412, "chan": 1},
            {"ssid": "<hidden>", "bssid": "00:1A:79:AA:BB:CC", "rssi": -42, "freq": 5180, "chan": 36},
            {"ssid": "PrinterNet", "bssid": "44:65:0D:10:20:30", "rssi": -67, "freq": 2462, "chan": 11},
        ]
        ble_devices = [
            {"name": "Earbuds", "addr": "F4:F5:D8:01:02:03", "rssi": -55},
            {"name": None, "addr": "12:34:56:78:9A:BC", "rssi": -38},
        ]

        # Randomly drop/appear one device to simulate environment changes.
        if self._rnd.random() < 0.25:
            wifi_devices.append(
                {"ssid": "Cafe_Free", "bssid": "3C:5A:B4:AA:00:01", "rssi": -72, "freq": 2417, "chan": 2}
            )
        if self._rnd.random() < 0.20:
            ble_devices.append({"name": "Beacon", "addr": "FC:FB:FB:BE:EF:01", "rssi": -62})

        for w in wifi_devices:
            bssid = w["bssid"]
            yield Observation(
                ts=now,
                signal_type="wifi",
                device_id=bssid,
                source="mock",
                name=None,
                rssi=_jitter(w["rssi"], 3),
                frequency_mhz=w["freq"],
                channel=w["chan"],
                ssid=w["ssid"],
                security="WPA2-Personal",
                band="2.4GHz" if w["freq"] < 3000 else "5GHz",
                vendor=vendor_from_mac(bssid),
                raw=w,
            )

        for b in ble_devices:
            addr = b["addr"]
            yield Observation(
                ts=now,
                signal_type="ble",
                device_id=addr,
                source="mock",
                name=b["name"],
                rssi=_jitter(b["rssi"], 4),
                vendor=vendor_from_mac(addr),
                raw=b,
            )

