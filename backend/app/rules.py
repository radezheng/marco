from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd


def _rolling_window_days(asof: dt.date, days: int) -> tuple[dt.date, dt.date]:
    return (asof - dt.timedelta(days=days), asof)


def quantile_thresholds(history: pd.Series, asof: dt.date, window_days: int, qs: tuple[float, float]) -> tuple[float, float] | None:
    start, end = _rolling_window_days(asof, window_days)
    window = history.loc[(history.index >= start) & (history.index < end)]
    if window.shape[0] < 60:
        return None
    return (float(window.quantile(qs[0])), float(window.quantile(qs[1])))


def state_from_quantiles(
    *,
    history: pd.Series,
    asof: dt.date,
    value: float,
    window_days: int = 365 * 3,
    qs: tuple[float, float] = (0.90, 0.95),
    high_is_riskoff: bool = True,
) -> tuple[str, float | None, dict]:
    th = quantile_thresholds(history, asof, window_days, qs)
    if th is None:
        return ("U", None, {"reason": "insufficient_history"})
    q1, q2 = th

    if high_is_riskoff:
        if value >= q2:
            return ("R", 2.0, {"q1": q1, "q2": q2, "value": value})
        if value >= q1:
            return ("Y", 1.0, {"q1": q1, "q2": q2, "value": value})
        return ("G", 0.0, {"q1": q1, "q2": q2, "value": value})

    # low is risk-off (rare here)
    if value <= q2:
        return ("R", 2.0, {"q1": q1, "q2": q2, "value": value})
    if value <= q1:
        return ("Y", 1.0, {"q1": q1, "q2": q2, "value": value})
    return ("G", 0.0, {"q1": q1, "q2": q2, "value": value})


def structure_state_from_slope(slope: float, flat_band: float = 0.25) -> tuple[str, float, dict]:
    # slope = VIX - VXV
    if slope > flat_band:
        return ("R", 2.0, {"slope": slope, "structure": "backwardation"})
    if slope >= -flat_band:
        return ("Y", 1.0, {"slope": slope, "structure": "flat"})
    return ("G", 0.0, {"slope": slope, "structure": "contango"})


def realized_vol_annualized(changes: pd.Series, window: int = 20) -> pd.Series:
    # changes are in yield points, daily.
    rv = changes.rolling(window).std() * np.sqrt(252)
    return rv
