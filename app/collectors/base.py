from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

from app.models import Observation


class Collector(ABC):
    @abstractmethod
    def collect(self, now: datetime) -> Iterable[Observation]:
        raise NotImplementedError

