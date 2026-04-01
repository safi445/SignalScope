from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Optional


@dataclass(frozen=True)
class MovementResult:
    movement: str  # static/moving/unknown
    score: float   # higher => more variable RSSI


def classify_movement(
    *,
    last_rssi: Optional[int],
    rssi_mean: Optional[float],
    rssi_std: Optional[float],
    seen_count: int,
) -> MovementResult:
    if seen_count < 6 or rssi_std is None:
        return MovementResult(movement="unknown", score=float(rssi_std or 0.0))

    score = float(rssi_std)
    # Heuristic thresholds: >= 6 dB std tends to indicate movement / multipath changes.
    if score >= 6.0:
        return MovementResult(movement="moving", score=score)
    return MovementResult(movement="static", score=score)

