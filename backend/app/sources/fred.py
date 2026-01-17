from __future__ import annotations

import datetime as dt
from io import StringIO

import pandas as pd
import requests


def fetch_fred_series_csv(series_id: str) -> pd.Series:
    """Fetches a FRED series via public CSV export (no API key).

    Returns a pandas Series indexed by date with float values.
    Missing values (.) are dropped.
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    df = pd.read_csv(StringIO(resp.text))
    if df.shape[1] < 2:
        raise ValueError(f"Unexpected FRED CSV format for {series_id}")

    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date"])

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    series = pd.Series(df["value"].values, index=df["date"].values, name=series_id)
    series.index = pd.Index(series.index, name="date")
    return series.sort_index()


def align_on_dates(*series: pd.Series) -> list[pd.Series]:
    common = None
    for s in series:
        idx = set(s.index)
        common = idx if common is None else (common & idx)
    common_sorted = sorted(common or [])
    return [s.loc[common_sorted] for s in series]


def today_utc_date() -> dt.date:
    return dt.datetime.utcnow().date()
