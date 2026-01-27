from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


try:
    import akshare as ak  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    ak = None


@dataclass(frozen=True)
class CnIndustry:
    code: str
    name: str


_FALLBACK_PATH = Path(__file__).with_name("cn_industries_fallback.json")


def _load_fallback_list() -> list[CnIndustry]:
    try:
        raw = _FALLBACK_PATH.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        data = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        return []

    out: list[CnIndustry] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            if not code or not name:
                continue
            out.append(CnIndustry(code=code, name=name))
    out.sort(key=lambda x: x.name)
    return out


def _retry(fn, *, attempts: int = 4, base_delay_s: float = 0.6, exc_types: tuple[type[Exception], ...] = (Exception,)):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except exc_types as e:  # noqa: PERF203,BLE001
            last = e
            if i == attempts - 1:
                break
            time.sleep(base_delay_s * (2**i))
    assert last is not None
    raise last


def akshare_available() -> bool:
    return ak is not None


def fetch_industry_list_em(*, allow_fallback: bool = True) -> list[CnIndustry]:
    """Return Eastmoney industry board list via AkShare.

    Code examples look like 'BK0428'. Name is Chinese board name.
    """
    if ak is None:
        raise RuntimeError("AkShare not installed; set up akshare or disable CN industries ingest")

    def _call():
        return ak.stock_board_industry_name_em()  # type: ignore[attr-defined]

    df = _retry(_call)
    if df is None or df.empty:
        if allow_fallback:
            fb = _load_fallback_list()
            if fb:
                return fb
        return []

    out: list[CnIndustry] = []
    for _, r in df.iterrows():
        name = str(r.get("板块名称") or r.get("name") or "").strip()
        code = str(r.get("板块代码") or r.get("code") or "").strip()
        if not name or not code:
            continue
        out.append(CnIndustry(code=code, name=name))

    # Stable ordering by name.
    out.sort(key=lambda x: x.name)
    return out


def fetch_industry_hist_em(symbol: str, start: dt.date | None = None, end: dt.date | None = None) -> pd.DataFrame:
    """Return historical daily data for one industry board.

    Note: AkShare's `stock_board_industry_hist_em` defaults to a fixed date range
    (20211201-20220401). Always pass an explicit date range to get recent data.

    The underlying AkShare API expects `symbol` as the board name (CN), e.g. "小金属".
    Expected columns (CN): 日期/收盘/成交额 ...
    """
    if ak is None:
        raise RuntimeError("AkShare not installed")

    sym = str(symbol).strip()
    end_d = end or dt.date.today()
    start_d = start or (end_d - dt.timedelta(days=400))
    start_date = start_d.strftime("%Y%m%d")
    end_date = end_d.strftime("%Y%m%d")

    def _call():
        return ak.stock_board_industry_hist_em(  # type: ignore[attr-defined]
            symbol=sym,
            start_date=start_date,
            end_date=end_date,
            period="日k",
            adjust="",
        )

    df = _retry(_call)
    if df is None or df.empty:
        return pd.DataFrame()

    # Normalize columns.
    # AkShare uses Chinese headers.
    df = df.copy()
    if "日期" in df.columns:
        df["date"] = pd.to_datetime(df["日期"], errors="coerce").dt.date
    elif "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    if "收盘" in df.columns:
        df["close"] = pd.to_numeric(df["收盘"], errors="coerce")
    elif "close" in df.columns:
        df["close"] = pd.to_numeric(df["close"], errors="coerce")

    if "成交额" in df.columns:
        df["amount"] = pd.to_numeric(df["成交额"], errors="coerce")
    elif "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    df = df.dropna(subset=["date"]).sort_values("date")
    return df[[c for c in ["date", "close", "amount"] if c in df.columns]]


def df_to_series(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Build close/amount/return series from normalized dataframe."""
    if df.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    df = df.copy().dropna(subset=["date"]).sort_values("date")
    idx = pd.Index([dt.date.fromisoformat(str(d)) if isinstance(d, str) else d for d in df["date"]], name="date")

    close = pd.Series(df["close"].values, index=idx, dtype=float).dropna()
    amount = pd.Series(df["amount"].values, index=idx, dtype=float).dropna() if "amount" in df.columns else pd.Series(dtype=float)

    # daily return as decimal (e.g., 0.01 means 1%).
    ret = close.pct_change().dropna()

    close.name = "close"
    amount.name = "amount"
    ret.name = "return"
    return close, amount, ret
