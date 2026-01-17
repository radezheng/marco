from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel


class SeriesPoint(BaseModel):
    date: dt.date
    value: float


class IndicatorStateOut(BaseModel):
    indicator_key: str
    date: dt.date
    state: str
    score: float | None
    details: dict[str, Any]


class RegimeOut(BaseModel):
    date: dt.date
    regime: str
    risk_score: float
    template_name: str
    drivers: dict[str, Any]


class AllocationOut(BaseModel):
    template_name: str
    asset_class_weights: dict[str, float]
    equity_bucket_weights: dict[str, float]
    overlays: dict[str, float]


class SnapshotOut(BaseModel):
    asof: dt.date
    indicators: list[IndicatorStateOut]
    regime: RegimeOut | None
    allocation: AllocationOut | None
