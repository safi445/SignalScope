from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from app.models import Observation
from app.oui import vendor_from_mac


class BleakBleCollector:
    """
    Desktop BLE metadata collector using bleak.

    - Windows: uses WinRT backend
    - Linux: BlueZ (may require permissions)
    - macOS: CoreBluetooth
    """

    def __init__(self, scan_seconds: float = 2.0) -> None:
        self.scan_seconds = scan_seconds

    async def collect(self, now: datetime) -> Iterable[Observation]:
        try:
            from bleak import BleakScanner  # type: ignore
        except Exception:
            return []

        try:
            devices = await BleakScanner.discover(timeout=self.scan_seconds)
        except Exception:
            return []

        obs: list[Observation] = []
        for d in devices:
            addr = getattr(d, "address", None) or getattr(d, "id", None)
            if not addr:
                continue
            name = getattr(d, "name", None)
            rssi = getattr(d, "rssi", None)
            try:
                rssi_i: Optional[int] = int(rssi) if rssi is not None else None
            except Exception:
                rssi_i = None

            obs.append(
                Observation(
                    ts=now,
                    signal_type="ble",
                    device_id=str(addr),
                    source="bleak",
                    name=str(name) if name else None,
                    rssi=rssi_i,
                    vendor=vendor_from_mac(str(addr)),
                    raw={"source": "bleak"},
                )
            )
        return obs

