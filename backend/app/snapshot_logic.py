from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .allocations import template_for_regime
from .models import Observation
from .rules import realized_vol_annualized, state_from_quantiles, structure_state_from_slope
from .schemas import AllocationOut, IndicatorStateOut, RegimeOut, SnapshotOut
from .sources.fred import today_utc_date


def _max_date_leq(db: Session, indicator_key: str, asof: dt.date) -> dt.date | None:
    return db.execute(
        select(func.max(Observation.date)).where(
            Observation.indicator_key == indicator_key,
            Observation.date <= asof,
        )
    ).scalar_one_or_none()


def _load_history_asof(db: Session, indicator_key: str, asof: dt.date, days: int = 365 * 5) -> pd.Series:
    start = asof - dt.timedelta(days=days)
    rows = db.execute(
        select(Observation.date, Observation.value)
        .where(
            Observation.indicator_key == indicator_key,
            Observation.date >= start,
            Observation.date <= asof,
        )
        .order_by(Observation.date)
    ).all()
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({r[0]: float(r[1]) for r in rows})
    s.index = pd.Index(s.index, name="date")
    return s.sort_index()


def _choose_effective_asof(db: Session, requested_asof: dt.date | None) -> dt.date | None:
    end = requested_asof or today_utc_date()

    # Prefer VIX slope if it exists by the requested date; otherwise fallback to VIX level.
    has_vix_slope = _max_date_leq(db, "vix_slope", end) is not None

    # Funding spread only exists from ~2021; for earlier history we should not require it.
    has_funding_spread = _max_date_leq(db, "funding_spread", end) is not None

    # Use WALCL (weekly) as the "clock" for liquidity rather than the pre-derived delta series,
    # because RRP is sparse in pre-2010 history and an inner-join would create artificial gaps.
    core_sources: list[str] = ["walcl", "hy_oas"]
    if has_funding_spread:
        core_sources.append("funding_spread")
    core_sources.append("vix_slope" if has_vix_slope else "vix")

    max_dates: list[dt.date] = []
    for k in core_sources:
        d = _max_date_leq(db, k, end)
        if d is not None:
            max_dates.append(d)

    if not max_dates:
        return None

    # Match the existing ingest behavior: pick the most recent date common to the “slowest” core series.
    return min(max_dates)


def _align_asof(base: pd.Series, other: pd.Series) -> pd.Series:
    """Align other to base's dates via backward asof merge."""
    if base.empty:
        return pd.Series(dtype=float)
    if other.empty:
        return pd.Series([float("nan")] * len(base), index=base.index, name=other.name)

    b = base.sort_index()
    o = other.sort_index()
    bdf = pd.DataFrame({"date": pd.to_datetime(b.index), "base": b.values})
    odf = pd.DataFrame({"date": pd.to_datetime(o.index), "v": o.values})
    merged = pd.merge_asof(bdf, odf, on="date", direction="backward")
    out = pd.Series(merged["v"].values, index=b.index, name=other.name)
    out.index = pd.Index(out.index, name="date")
    return out


def _synthetic_liquidity_delta_w(db: Session, asof: dt.date) -> pd.Series:
    # Use ~6y history so that we can compute 3y quantiles even when the requested date is near the beginning of the window.
    walcl = _load_history_asof(db, "walcl", asof, days=365 * 6)
    if walcl.empty:
        return pd.Series(dtype=float)

    tga = _load_history_asof(db, "tga", asof, days=365 * 6)
    rrp = _load_history_asof(db, "rrp", asof, days=365 * 6)

    tga_a = _align_asof(walcl, tga)
    rrp_a = _align_asof(walcl, rrp)

    # Pre-facility eras may have NaN; treat as 0 for RRP to avoid dropping all early history.
    rrp_a = rrp_a.fillna(0.0)

    level = walcl - tga_a - rrp_a
    delta = level.diff(1)
    delta.name = "synthetic_liquidity_delta_w"
    return delta.dropna()


def synthetic_liquidity_delta_points(db: Session, *, start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """Compute synthetic liquidity weekly delta points for charting.

    Uses WALCL dates as the clock and backward asof-alignment for TGA/RRP.
    """
    # Pull a small buffer before start so diff(1) is well-defined.
    buffer_start = start - dt.timedelta(days=120)
    walcl = _load_history_asof(db, "walcl", end, days=(end - buffer_start).days)
    if walcl.empty:
        return []
    tga = _load_history_asof(db, "tga", end, days=(end - buffer_start).days)
    rrp = _load_history_asof(db, "rrp", end, days=(end - buffer_start).days)

    tga_a = _align_asof(walcl, tga)
    rrp_a = _align_asof(walcl, rrp).fillna(0.0)

    level = walcl - tga_a - rrp_a
    delta = level.diff(1).dropna()
    delta = delta.loc[(delta.index >= start) & (delta.index <= end)]
    return [(d, float(v)) for d, v in delta.items()]


def build_snapshot(db: Session, requested_asof: dt.date | None) -> SnapshotOut:
    asof = _choose_effective_asof(db, requested_asof)
    if asof is None:
        raise ValueError("No observations available yet. Run ingest first.")

    indicators: list[IndicatorStateOut] = []
    states: dict[str, tuple[str, float | None]] = {}

    def add_state(indicator_key: str, state: str, score: float | None, details: dict):
        indicators.append(
            IndicatorStateOut(
                indicator_key=indicator_key,
                date=asof,
                state=state,
                score=score,
                details=details or {},
            )
        )
        states[indicator_key] = (state, score)

    # Liquidity direction (weekly delta quantiles)
    liq_hist = _synthetic_liquidity_delta_w(db, asof)
    if not liq_hist.empty and asof in liq_hist.index:
        val = float(liq_hist.loc[asof])
        start = asof - dt.timedelta(days=365 * 3)
        window = liq_hist.loc[(liq_hist.index >= start) & (liq_hist.index < asof)]
        if window.shape[0] >= 60:
            q_lo = float(window.quantile(0.33))
            q_hi = float(window.quantile(0.66))
            if val >= q_hi:
                add_state("synthetic_liquidity", "G", 0.0, {"value": val, "q_lo": q_lo, "q_hi": q_hi, "label": "net_inject"})
            elif val <= q_lo:
                add_state("synthetic_liquidity", "R", 2.0, {"value": val, "q_lo": q_lo, "q_hi": q_hi, "label": "net_withdraw"})
            else:
                add_state("synthetic_liquidity", "Y", 1.0, {"value": val, "q_lo": q_lo, "q_hi": q_hi, "label": "flat"})
        else:
            add_state("synthetic_liquidity", "U", None, {"reason": "insufficient_history"})

    # Credit (HY OAS)
    credit_hist = _load_history_asof(db, "hy_oas", asof)
    if not credit_hist.empty and asof in credit_hist.index:
        v = float(credit_hist.loc[asof])
        state, score, details = state_from_quantiles(history=credit_hist, asof=asof, value=v, qs=(0.90, 0.95))
        add_state("credit_spread", state, score, {**details, "proxy": "hy_oas"})

    # Funding (SOFR - IORB/EFFR)
    fund_hist = _load_history_asof(db, "funding_spread", asof)
    if not fund_hist.empty and asof in fund_hist.index:
        v = float(fund_hist.loc[asof])
        state, score, details = state_from_quantiles(history=fund_hist, asof=asof, value=v, qs=(0.90, 0.95))
        add_state("funding_stress", state, score, details)

    # Treasury realized vol (20D ann)
    vol_hist = _load_history_asof(db, "treasury_realized_vol_20d", asof)
    if not vol_hist.empty and asof in vol_hist.index:
        v = float(vol_hist.loc[asof])
        state, score, details = state_from_quantiles(history=vol_hist, asof=asof, value=v, qs=(0.90, 0.95))
        add_state("treasury_vol", state, score, details)

    # VIX structure (slope) or fallback to level
    slope_hist = _load_history_asof(db, "vix_slope", asof)
    if not slope_hist.empty and asof in slope_hist.index:
        v = float(slope_hist.loc[asof])
        state, score, details = structure_state_from_slope(v)
        add_state("vix_structure", state, score, details)
    else:
        vix_hist = _load_history_asof(db, "vix", asof)
        if not vix_hist.empty and asof in vix_hist.index:
            v = float(vix_hist.loc[asof])
            state, score, details = state_from_quantiles(history=vix_hist, asof=asof, value=v, qs=(0.90, 0.95))
            add_state("vix_level", state, score, {**details, "proxy": "vix"})

    # USD TWI 60d return
    usd_hist = _load_history_asof(db, "usd_twi_broad", asof, days=365 * 6)
    if not usd_hist.empty and asof in usd_hist.index:
        s = usd_hist.sort_index()
        if s.shape[0] > 70:
            idx = list(s.index)
            i = idx.index(asof)
            if i >= 60:
                ret = float(s.iloc[i] / s.iloc[i - 60] - 1.0)
                rets = s.pct_change(periods=60).dropna()
                state, score, details = state_from_quantiles(history=rets, asof=asof, value=ret, qs=(0.90, 0.95))
                add_state("usd_strength", state, score, {**details, "return_60d": ret})

    # Optional: keep parity with ingest-derived treasury vol if missing by computing from DGS10 on the fly.
    # (Mostly useful when the derived series hasn't been ingested yet.)
    if "treasury_vol" not in states:
        dgs10 = _load_history_asof(db, "dgs10", asof, days=365 * 6)
        if not dgs10.empty and asof in dgs10.index:
            changes = dgs10.dropna().diff().dropna()
            rv = realized_vol_annualized(changes, window=20).dropna()
            if not rv.empty and asof in rv.index:
                v = float(rv.loc[asof])
                state, score, details = state_from_quantiles(history=rv, asof=asof, value=v, qs=(0.90, 0.95))
                add_state("treasury_vol", state, score, details)

    # Regime A/B/C based on available core signals.
    def _score(st: str) -> int:
        return 0 if st == "G" else (1 if st == "Y" else (2 if st == "R" else 0))

    core_keys: list[str] = []
    for k in ["synthetic_liquidity", "credit_spread", "funding_stress"]:
        if k in states:
            core_keys.append(k)

    vix_key = "vix_structure" if "vix_structure" in states else ("vix_level" if "vix_level" in states else None)
    if vix_key:
        core_keys.append(vix_key)

    core_states = {k: states.get(k, ("U", None))[0] for k in core_keys}
    reds = sum(1 for v in core_states.values() if v == "R")
    greens = sum(1 for v in core_states.values() if v == "G")

    regime: RegimeOut | None = None
    allocation: AllocationOut | None = None

    if len(core_keys) >= 3:
        if greens == len(core_keys):
            regime_code = "A"
        elif reds >= 3 or (reds >= 2 and vix_key and core_states.get(vix_key) == "R"):
            regime_code = "C"
        else:
            regime_code = "B"

        risk_score = float(sum(_score(v) for v in core_states.values()))
        tmpl = template_for_regime(regime_code)
        template_name = tmpl.name if tmpl else regime_code

        drivers = {"core": core_states, "reds": reds, "greens": greens}
        regime = RegimeOut(
            date=asof,
            regime=regime_code,
            risk_score=risk_score,
            template_name=template_name,
            drivers=drivers,
        )

        if tmpl:
            allocation = AllocationOut(
                template_name=tmpl.name,
                asset_class_weights=tmpl.asset_class_weights,
                equity_bucket_weights=tmpl.equity_bucket_weights,
                overlays=tmpl.overlays,
            )

    return SnapshotOut(asof=asof, indicators=indicators, regime=regime, allocation=allocation)
