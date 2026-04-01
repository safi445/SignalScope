from __future__ import annotations

import platform
import re
import subprocess
from typing import Any


def _run(cmd: list[str], timeout_s: int = 6) -> str:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
        return (p.stdout or "").strip()
    except Exception:
        return ""


def read_arp_cache() -> dict[str, Any]:
    """
    Passive/local-only:
    Reads the OS ARP cache (does NOT probe the network).
    """
    if platform.system().lower() != "windows":
        return {"supported": False, "rows": []}

    out = _run(["arp", "-a"], timeout_s=6)
    rows: list[dict[str, str]] = []
    ip_re = re.compile(
        r"^\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\s+([0-9a-fA-F\-]{17})\s+(\w+)\s*$"
    )
    for line in out.splitlines():
        m = ip_re.match(line)
        if not m:
            continue
        rows.append(
            {
                "ip": m.group(1),
                "mac": m.group(2).upper().replace("-", ":"),
                "type": m.group(3),
            }
        )
    return {"supported": True, "rows": rows}

