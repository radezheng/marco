from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


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


class CnIndustryOut(BaseModel):
    code: str
    name: str


class CnIndustryTopItemOut(BaseModel):
    code: str
    name: str
    value: float


class CnIndustryTopOut(BaseModel):
    asof: dt.date
    metric: str
    window_days: int
    items: list[CnIndustryTopItemOut]


class CnSectorOverviewItemOut(BaseModel):
    code: str
    name: str
    main_net: float
    flow_strength: float | None = None
    flow_5d: float | None = None
    flow_10d: float | None = None
    price_return_5d: float | None = None
    divergence_score: int | None = None
    state: str
    rank: int
    rank_change: int | None = None


class CnSectorSignalOut(BaseModel):
    code: str
    name: str
    main_net: float
    state: str
    prev_state: str | None = None
    rotation_speed: int | None = None
    rank: int | None = None
    divergence_score: int | None = None


class CnSectorOverviewOut(BaseModel):
    asof: dt.date
    top_inflow: list[CnSectorOverviewItemOut]
    top_outflow: list[CnSectorOverviewItemOut]
    new_mainline: list[CnSectorSignalOut] = Field(default_factory=list)
    fading: list[CnSectorSignalOut] = Field(default_factory=list)


class CnSectorMatrixRowOut(BaseModel):
    code: str
    name: str
    values: list[float]


class CnSectorMatrixOut(BaseModel):
    asof: dt.date
    dates: list[dt.date]
    rows: list[CnSectorMatrixRowOut]


class CnSectorBreadthOut(BaseModel):
    asof: dt.date
    code: str
    name: str
    breadth: float
    up: int
    total: int
