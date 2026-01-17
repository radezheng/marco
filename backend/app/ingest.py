from __future__ import annotations

import datetime as dt

import pandas as pd
import requests
from sqlalchemy import func
from sqlalchemy import select

from .db import SessionLocal, init_db
from .indicator_defs import FRED_BASE_SERIES
from .models import IndicatorState, Observation, RegimeState
from .rules import realized_vol_annualized, state_from_quantiles, structure_state_from_slope
from .sources.fred import align_on_dates, fetch_fred_series_csv, today_utc_date
from .allocations import template_for_regime


def _upsert_observations(db, indicator_key: str, series: pd.Series, source: str = "fred") -> int:
    # MVP: row-by-row upsert to keep dependencies minimal.
    count = 0
    for d, v in series.items():
        if pd.isna(v):
            continue
        existing = db.execute(
            select(Observation).where(Observation.indicator_key == indicator_key, Observation.date == d)
        ).scalar_one_or_none()
        if existing is None:
            db.add(Observation(indicator_key=indicator_key, date=d, value=float(v), source=source))
            count += 1
        else:
            if float(existing.value) != float(v):
                existing.value = float(v)
                existing.source = source
    return count


def _load_history(db, indicator_key: str, days: int = 365 * 5) -> pd.Series:
    asof = today_utc_date()
    start = asof - dt.timedelta(days=days)
    rows = db.execute(
        select(Observation.date, Observation.value)
        .where(Observation.indicator_key == indicator_key, Observation.date >= start)
        .order_by(Observation.date)
    ).all()
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({r[0]: float(r[1]) for r in rows})
    s.index = pd.Index(s.index, name="date")
    return s.sort_index()


def _write_indicator_state(db, indicator_key: str, date: dt.date, state: str, score: float | None, details: dict):
    existing = db.execute(
        select(IndicatorState).where(IndicatorState.indicator_key == indicator_key, IndicatorState.date == date)
    ).scalar_one_or_none()
    if existing is None:
        db.add(IndicatorState(indicator_key=indicator_key, date=date, state=state, score=score, details=details))
    else:
        existing.state = state
        existing.score = score
        existing.details = details


def _write_regime_state(db, date: dt.date, regime: str, risk_score: float, template_name: str, drivers: dict):
    existing = db.execute(select(RegimeState).where(RegimeState.date == date)).scalar_one_or_none()
    if existing is None:
        db.add(RegimeState(date=date, regime=regime, risk_score=risk_score, template_name=template_name, drivers=drivers))
    else:
        existing.regime = regime
        existing.risk_score = risk_score
        existing.template_name = template_name
        existing.drivers = drivers


def ingest_and_compute() -> dict:
    init_db()

    fetched: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}

    for key, series_id in FRED_BASE_SERIES.items():
        try:
            fetched[key] = fetch_fred_series_csv(series_id)
        except (requests.RequestException, ValueError, RuntimeError) as e:
            errors[key] = str(e)

    with SessionLocal() as db:
        inserted = 0
        for key, s in fetched.items():
            inserted += _upsert_observations(db, key, s, source="fred")

        # Derived: synthetic liquidity
        # IMPORTANT: WALCL is weekly; TGA is daily; RRP is sparse/starts late. Use backward asof-alignment
        # on WALCL dates to avoid artificial gaps in pre-2010 history.
        if {"walcl", "tga"}.issubset(fetched.keys()):
            walcl = fetched["walcl"].sort_index()
            tga = fetched["tga"].sort_index()
            rrp = fetched.get("rrp", pd.Series(dtype=float)).sort_index()

            base_df = pd.DataFrame({"date": pd.to_datetime(walcl.index), "walcl": walcl.values})
            tga_df = pd.DataFrame({"date": pd.to_datetime(tga.index), "tga": tga.values})
            out = pd.merge_asof(base_df, tga_df, on="date", direction="backward")

            if not rrp.empty:
                rrp_df = pd.DataFrame({"date": pd.to_datetime(rrp.index), "rrp": rrp.values})
                out = pd.merge_asof(out, rrp_df, on="date", direction="backward")
            else:
                out["rrp"] = 0.0

            out["rrp"] = out["rrp"].fillna(0.0)
            out = out.dropna(subset=["walcl", "tga"])

            idx = out["date"].dt.date
            level = pd.Series(out["walcl"].values - out["tga"].values - out["rrp"].values, index=idx, name="synthetic_liquidity_level")
            level.index = pd.Index(level.index, name="date")
            level = level.sort_index()

            # WALCL is weekly; use 1-period change as the "weekly" delta.
            delta_w = level.diff(1).dropna()
            delta_w.name = "synthetic_liquidity_delta_w"

            inserted += _upsert_observations(db, "synthetic_liquidity_level", level)
            inserted += _upsert_observations(db, "synthetic_liquidity_delta_w", delta_w)

        # Derived: funding spread
        if "sofr" in fetched and ("iorb" in fetched or "effr" in fetched):
            base = fetched["iorb"] if "iorb" in fetched else fetched["effr"]
            sofr, base_aligned = align_on_dates(fetched["sofr"], base)
            spread = sofr - base_aligned
            spread.name = "funding_spread"
            inserted += _upsert_observations(db, "funding_spread", spread)

        # Derived: VIX slope
        if "vix" in fetched and "vxv" in fetched:
            vix, vxv = align_on_dates(fetched["vix"], fetched["vxv"])
            slope = vix - vxv
            slope.name = "vix_slope"
            inserted += _upsert_observations(db, "vix_slope", slope)

        # Derived: realized vol from DGS10
        if "dgs10" in fetched:
            dgs10 = fetched["dgs10"].dropna()
            changes = dgs10.diff().dropna()
            rv = realized_vol_annualized(changes, window=20).dropna()
            rv.name = "treasury_realized_vol_20d"
            inserted += _upsert_observations(db, "treasury_realized_vol_20d", rv)

        db.commit()

        # Compute states on a date that exists across core series (some series lag)
        core_source_keys: list[str] = ["synthetic_liquidity_delta_w", "hy_oas", "funding_spread"]
        core_source_keys.append("vix_slope" if "vxv" in fetched else "vix")

        max_dates: list[dt.date] = []
        for k in core_source_keys:
            d = db.execute(select(func.max(Observation.date)).where(Observation.indicator_key == k)).scalar_one_or_none()
            if d is not None:
                max_dates.append(d)

        asof = min(max_dates) if max_dates else None
        if asof is None:
            return {
                "inserted_or_updated": inserted,
                "base_series_fetched": list(fetched.keys()),
                "errors": errors,
                "asof": None,
                "regime": None,
                "risk_score": None,
                "core_states": {},
            }

        states = {}

        # Liquidity (direction via delta quantiles)
        liq_hist = _load_history(db, "synthetic_liquidity_delta_w")
        if not liq_hist.empty and asof in liq_hist.index:
            val = float(liq_hist.loc[asof])
            # For direction-like series, use 33/66 quantiles in a 3y window
            start = asof - dt.timedelta(days=365 * 3)
            window = liq_hist.loc[(liq_hist.index >= start) & (liq_hist.index < asof)]
            if window.shape[0] >= 60:
                q_lo = float(window.quantile(0.33))
                q_hi = float(window.quantile(0.66))
                if val >= q_hi:
                    state, score = "G", 0.0
                    details = {"value": val, "q_lo": q_lo, "q_hi": q_hi, "label": "net_inject"}
                elif val <= q_lo:
                    state, score = "R", 2.0
                    details = {"value": val, "q_lo": q_lo, "q_hi": q_hi, "label": "net_withdraw"}
                else:
                    state, score = "Y", 1.0
                    details = {"value": val, "q_lo": q_lo, "q_hi": q_hi, "label": "flat"}
            else:
                state, score, details = "U", None, {"reason": "insufficient_history"}
            _write_indicator_state(db, "synthetic_liquidity", asof, state, score, details)
            states["synthetic_liquidity"] = (state, score)

        # Credit (HY OAS: high is risk-off)
        credit_hist = _load_history(db, "hy_oas")
        if not credit_hist.empty and asof in credit_hist.index:
            v = float(credit_hist.loc[asof])
            state, score, details = state_from_quantiles(history=credit_hist, asof=asof, value=v, qs=(0.90, 0.95))
            _write_indicator_state(db, "credit_spread", asof, state, score, {**details, "proxy": "hy_oas"})
            states["credit_spread"] = (state, score)

        # Funding (spread: high is risk-off)
        fund_hist = _load_history(db, "funding_spread")
        if not fund_hist.empty and asof in fund_hist.index:
            v = float(fund_hist.loc[asof])
            state, score, details = state_from_quantiles(history=fund_hist, asof=asof, value=v, qs=(0.90, 0.95))
            _write_indicator_state(db, "funding_stress", asof, state, score, details)
            states["funding_stress"] = (state, score)

        # Treasury vol (high is risk-off)
        vol_hist = _load_history(db, "treasury_realized_vol_20d")
        if not vol_hist.empty and asof in vol_hist.index:
            v = float(vol_hist.loc[asof])
            state, score, details = state_from_quantiles(history=vol_hist, asof=asof, value=v, qs=(0.90, 0.95))
            _write_indicator_state(db, "treasury_vol", asof, state, score, details)
            states["treasury_vol"] = (state, score)

        # VIX structure (slope) OR fallback to VIX level
        slope_hist = _load_history(db, "vix_slope")
        if not slope_hist.empty and asof in slope_hist.index:
            v = float(slope_hist.loc[asof])
            state, score, details = structure_state_from_slope(v)
            _write_indicator_state(db, "vix_structure", asof, state, score, details)
            states["vix_structure"] = (state, score)
        else:
            vix_hist = _load_history(db, "vix")
            if not vix_hist.empty and asof in vix_hist.index:
                v = float(vix_hist.loc[asof])
                state, score, details = state_from_quantiles(history=vix_hist, asof=asof, value=v, qs=(0.90, 0.95))
                _write_indicator_state(db, "vix_level", asof, state, score, {**details, "proxy": "vix"})
                states["vix_level"] = (state, score)

        # USD TWI momentum: use 60d return; high positive is risk-off
        usd_hist = _load_history(db, "usd_twi_broad")
        if not usd_hist.empty and asof in usd_hist.index:
            # compute 60d pct change
            s = usd_hist
            s = s.sort_index()
            if s.shape[0] > 70:
                # align by index position to avoid missing dates
                idx = list(s.index)
                i = idx.index(asof)
                if i >= 60:
                    ret = float(s.iloc[i] / s.iloc[i - 60] - 1.0)
                    # build a synthetic history of 60d returns
                    rets = s.pct_change(periods=60).dropna()
                    state, score, details = state_from_quantiles(history=rets, asof=asof, value=ret, qs=(0.90, 0.95))
                    _write_indicator_state(db, "usd_strength", asof, state, score, {**details, "return_60d": ret})
                    states["usd_strength"] = (state, score)

        # Regime A/B/C
        def _score(st: str) -> int:
            return 0 if st == "G" else (1 if st == "Y" else (2 if st == "R" else 0))

        # Use the 4 core signals first
        core_keys = ["synthetic_liquidity", "credit_spread", "funding_stress"]
        vix_key = "vix_structure" if "vix_structure" in states else ("vix_level" if "vix_level" in states else None)
        if vix_key:
            core_keys.append(vix_key)

        core_states = {k: states.get(k, ("U", None))[0] for k in core_keys}
        reds = sum(1 for v in core_states.values() if v == "R")
        greens = sum(1 for v in core_states.values() if v == "G")

        if greens == len(core_keys) and len(core_keys) >= 3:
            regime = "A"
        elif reds >= 3 or (reds >= 2 and core_states.get(vix_key) == "R"):
            regime = "C"
        else:
            regime = "B"

        risk_score = float(sum(_score(v) for v in core_states.values()))
        drivers = {"core": core_states, "reds": reds, "greens": greens}

        tmpl = template_for_regime(regime)
        if tmpl:
            _write_regime_state(db, asof, regime, risk_score, tmpl.name, drivers)
        db.commit()

        return {
            "inserted_or_updated": inserted,
            "base_series_fetched": list(fetched.keys()),
            "errors": errors,
            "asof": str(asof),
            "regime": regime,
            "risk_score": risk_score,
            "core_states": core_states,
        }


def main():
    out = ingest_and_compute()
    print(out)


if __name__ == "__main__":
    main()
