from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd


try:
    import akshare as ak  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    ak = None


@dataclass(frozen=True)
class SectorFundFlowPoint:
    date: pd.Timestamp
    main_net: float | None = None
    super_net: float | None = None
    big_net: float | None = None
    mid_net: float | None = None
    small_net: float | None = None


def _retry(
    fn,
    *,
    attempts: int = 4,
    base_delay_s: float = 0.6,
    exc_types: tuple[type[Exception], ...] = (Exception,),
):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except exc_types as e:  # noqa: PERF203
            last = e
            if i == attempts - 1:
                break
            time.sleep(base_delay_s * (2**i))
    assert last is not None
    raise last


def akshare_available() -> bool:
    return ak is not None


def fetch_sector_fund_flow_hist_em(symbol: str) -> pd.DataFrame:
    """Eastmoney sector historical fund flow via AkShare.

    `symbol` is the sector/industry name in Chinese.
    Output columns include (CN): 日期, 主力净流入-净额, 超大单净流入-净额, 大单净流入-净额, 中单净流入-净额, 小单净流入-净额.
    """
    if ak is None:
        raise RuntimeError("AkShare not installed")

    sym = str(symbol).strip()
    if not sym:
        return pd.DataFrame()

    def _call():
        return ak.stock_sector_fund_flow_hist(symbol=sym)  # type: ignore[attr-defined]

    df = _retry(_call)
    if df is None or df.empty:
        return pd.DataFrame()

    return df.copy()


def df_to_main_net_series(df: pd.DataFrame) -> pd.Series:
    """Convert Eastmoney fund-flow hist df to a date-indexed main net inflow series."""
    if df is None or df.empty:
        return pd.Series(dtype=float)

    df = df.copy()

    if "日期" in df.columns:
        df["date"] = pd.to_datetime(df["日期"], errors="coerce").dt.date
    elif "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    else:
        return pd.Series(dtype=float)

    # Main net inflow
    if "主力净流入-净额" in df.columns:
        df["main_net"] = pd.to_numeric(df["主力净流入-净额"], errors="coerce")
    elif "main_net" in df.columns:
        df["main_net"] = pd.to_numeric(df["main_net"], errors="coerce")
    else:
        return pd.Series(dtype=float)

    df = df.dropna(subset=["date"]).sort_values("date")
    idx = pd.Index(df["date"].tolist(), name="date")
    s = pd.Series(df["main_net"].values, index=idx, dtype=float).dropna()
    s.name = "main_net"
    return s
