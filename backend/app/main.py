from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from collections.abc import Iterator
from ipaddress import ip_address

import pandas as pd

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from sqlalchemy import func, text as sa_text
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, init_db
from .ingest import ingest_and_compute
from .llm import explain_snapshot, explain_snapshot_stream
from .models import ApiCache, CnIndustry, LlmExplanation, Observation, PageView
from .snapshot_logic import build_snapshot, synthetic_liquidity_delta_points
from .schemas import (
    CnIndustryOut,
    CnIndustryTopItemOut,
    CnIndustryTopOut,
    CnSectorBreadthOut,
    CnSectorMatrixOut,
    CnSectorMatrixRowOut,
    CnSectorOverviewItemOut,
    CnSectorOverviewOut,
    CnSectorSignalOut,
    SeriesPoint,
    SnapshotOut,
)


def _latest_cn_flow_date(db: Session) -> dt.date | None:
    return db.execute(
        select(func.max(Observation.date)).where(Observation.indicator_key.like("cn_industry_flow_main_net:%"))
    ).scalar_one_or_none()


def _prev_cn_flow_date(db: Session, end: dt.date) -> dt.date | None:
    return db.execute(
        select(func.max(Observation.date)).where(
            Observation.indicator_key.like("cn_industry_flow_main_net:%"),
            Observation.date < end,
        )
    ).scalar_one_or_none()


def _load_tail(db: Session, *, indicator_key: str, end: dt.date, limit: int) -> list[tuple[dt.date, float]]:
    rows = db.execute(
        select(Observation.date, Observation.value)
        .where(Observation.indicator_key == indicator_key, Observation.date <= end)
        .order_by(Observation.date.desc())
        .limit(limit)
    ).all()
    out = [(r[0], float(r[1])) for r in rows]
    out.reverse()
    return out


def _compute_state(*, flow_5d: float | None, price_return_5d: float | None) -> str:
    if flow_5d is None or price_return_5d is None:
        return "未知"

    flow_pos = flow_5d > 0
    price_pos = price_return_5d > 0

    if flow_pos and price_pos:
        return "主升"
    if flow_pos and not price_pos:
        return "吸筹"
    if (not flow_pos) and price_pos:
        return "派发"
    return "退潮"


def _divergence_score(*, flow_5d: float | None, price_return_5d: float | None) -> int | None:
    """Simple price-flow divergence score.

    +1: price down + flow in (absorption)
    -1: price up + flow out (distribution)
     0: otherwise
    """
    if flow_5d is None or price_return_5d is None:
        return None
    if price_return_5d > 0 and flow_5d < 0:
        return -1
    if price_return_5d < 0 and flow_5d > 0:
        return 1
    return 0

app = FastAPI(title="Marco Regime Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


def _snapshot_hash(snapshot: SnapshotOut) -> str:
    # Deterministic hash for caching: based on the serialized snapshot content.
    payload = snapshot.model_dump(mode="json")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_llm_cache(db: Session, *, snapshot_hash: str) -> LlmExplanation | None:
    return db.execute(
        select(LlmExplanation).where(LlmExplanation.snapshot_hash == snapshot_hash)
    ).scalar_one_or_none()


def _upsert_llm_cache(db: Session, *, asof: dt.date, snapshot_hash: str, text: str) -> None:
    row = _get_llm_cache(db, snapshot_hash=snapshot_hash)
    if row is None:
        db.add(LlmExplanation(asof=asof, snapshot_hash=snapshot_hash, text=text))
        db.commit()
        return

    row.asof = asof
    row.text = text
    db.commit()


def _cache_get(db: Session, *, cache_key: str, asof: dt.date | None, max_age_s: int) -> dict | None:
    row = db.execute(
        select(ApiCache).where(ApiCache.cache_key == cache_key, ApiCache.asof == asof)
    ).scalar_one_or_none()
    if row is None:
        return None
    age = (dt.datetime.utcnow() - row.updated_at.replace(tzinfo=None)).total_seconds()
    if age > max_age_s:
        return None
    return dict(row.payload or {})


def _cache_set(db: Session, *, cache_key: str, asof: dt.date | None, payload: dict) -> None:
    row = db.execute(
        select(ApiCache).where(ApiCache.cache_key == cache_key, ApiCache.asof == asof)
    ).scalar_one_or_none()
    if row is None:
        db.add(ApiCache(cache_key=cache_key, asof=asof, payload=payload))
        db.commit()
        return
    row.payload = payload
    db.commit()


def _ip_prefix(addr: str) -> str | None:
    try:
        ip = ip_address(addr)
    except ValueError:
        return None

    if ip.version == 4:
        parts = addr.split(".")
        if len(parts) != 4:
            return None
        return ".".join(parts[:3]) + ".0/24"
    # IPv6: /48 prefix
    exploded = ip.exploded  # 8 groups
    groups = exploded.split(":")
    return ":".join(groups[:3]) + "::/48"


def _client_ip(request: Request) -> str | None:
    # If behind a proxy, honor first X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        return first or None
    return request.client.host if request.client else None


def _visitor_hash(*, salt: str, ip_prefix: str | None, user_agent: str | None) -> str:
    raw = (ip_prefix or "") + "|" + (user_agent or "")
    h = hashlib.sha256()
    h.update(salt.encode("utf-8"))
    h.update(raw.encode("utf-8"))
    return h.hexdigest()


@app.get("/api/observations/{indicator_key}", response_model=list[SeriesPoint])
def get_observations(indicator_key: str, days: int = 365, asof: dt.date | None = None, db: Session = Depends(get_db)):
    # Allow chart "time travel" by pinning the series end date.
    end = asof
    if end is None:
        end = db.execute(
            select(func.max(Observation.date)).where(Observation.indicator_key == indicator_key)
        ).scalar_one_or_none()
    if end is None:
        end = dt.datetime.utcnow().date()

    start = end - dt.timedelta(days=days)

    if indicator_key == "synthetic_liquidity_delta_w":
        pts = synthetic_liquidity_delta_points(db, start=start, end=end)
        return [SeriesPoint(date=d, value=v) for d, v in pts]

    rows = db.execute(
        select(Observation.date, Observation.value)
        .where(
            Observation.indicator_key == indicator_key,
            Observation.date >= start,
            Observation.date <= end,
        )
        .order_by(Observation.date)
    ).all()
    return [SeriesPoint(date=r[0], value=float(r[1])) for r in rows]


@app.get("/api/snapshot", response_model=SnapshotOut)
def get_snapshot(asof: dt.date | None = None, db: Session = Depends(get_db)):
    try:
        return build_snapshot(db, asof)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/ingest/run")
def run_ingest():
    return ingest_and_compute()


@app.get("/api/cn/industries", response_model=list[CnIndustryOut])
def cn_industries(db: Session = Depends(get_db)):
    rows = db.execute(select(CnIndustry).order_by(CnIndustry.name)).scalars().all()
    return [CnIndustryOut(code=r.code, name=r.name) for r in rows]


@app.get("/api/cn/industries/top", response_model=CnIndustryTopOut)
def cn_industries_top(
    metric: str = "return",
    days: int = 20,
    n: int = 10,
    asof: dt.date | None = None,
    db: Session = Depends(get_db),
):
    metric = (metric or "return").strip().lower()
    days = max(1, min(int(days), 3650))
    n = max(1, min(int(n), 50))

    # Resolve end date.
    end = asof
    if end is None:
        end = db.execute(
            select(func.max(Observation.date)).where(Observation.indicator_key.like("cn_industry_close:%"))
        ).scalar_one_or_none()
    if end is None:
        raise HTTPException(status_code=400, detail="No CN industry data yet. Run ingest first.")

    cache_key = f"cn_industries_top:{metric}:days={days}:n={n}"
    cached = _cache_get(db, cache_key=cache_key, asof=end, max_age_s=15 * 60)
    if cached is not None:
        items = [CnIndustryTopItemOut(**x) for x in cached.get("items", [])]
        return CnIndustryTopOut(asof=end, metric=metric, window_days=days, items=items)

    start = end - dt.timedelta(days=days)

    name_map = {r.code: r.name for r in db.execute(select(CnIndustry)).scalars().all()}

    items: list[CnIndustryTopItemOut] = []

    if metric == "amount":
        rows = db.execute(
            select(Observation.indicator_key, func.sum(Observation.value))
            .where(
                Observation.indicator_key.like("cn_industry_amount:%"),
                Observation.date >= start,
                Observation.date <= end,
            )
            .group_by(Observation.indicator_key)
        ).all()

        for k, s in rows:
            code = str(k).split(":", 1)[1] if ":" in str(k) else str(k)
            name = name_map.get(code, code)
            items.append(CnIndustryTopItemOut(code=code, name=name, value=float(s or 0.0)))

        items.sort(key=lambda x: x.value, reverse=True)
        items = items[:n]

    elif metric == "return":
        # Compute window return from close series: last/first - 1.
        rows = db.execute(
            select(Observation.indicator_key, Observation.date, Observation.value)
            .where(
                Observation.indicator_key.like("cn_industry_close:%"),
                Observation.date >= start,
                Observation.date <= end,
            )
            .order_by(Observation.indicator_key, Observation.date)
        ).all()

        cur_key = None
        first = None
        last = None
        for k, _, v in rows:
            if cur_key != k:
                if cur_key is not None and first is not None and last is not None and first != 0:
                    code = str(cur_key).split(":", 1)[1] if ":" in str(cur_key) else str(cur_key)
                    name = name_map.get(code, code)
                    items.append(CnIndustryTopItemOut(code=code, name=name, value=(float(last) / float(first) - 1.0)))
                cur_key = k
                first = v
                last = v
            else:
                last = v

        if cur_key is not None and first is not None and last is not None and first != 0:
            code = str(cur_key).split(":", 1)[1] if ":" in str(cur_key) else str(cur_key)
            name = name_map.get(code, code)
            items.append(CnIndustryTopItemOut(code=code, name=name, value=(float(last) / float(first) - 1.0)))

        items.sort(key=lambda x: x.value, reverse=True)
        items = items[:n]

    else:
        raise HTTPException(status_code=400, detail="metric must be 'return' or 'amount'")

    _cache_set(
        db,
        cache_key=cache_key,
        asof=end,
        payload={
            "asof": str(end),
            "metric": metric,
            "window_days": days,
            "items": [i.model_dump(mode="json") for i in items],
        },
    )
    return CnIndustryTopOut(asof=end, metric=metric, window_days=days, items=items)


@app.get("/api/cn/sector/overview", response_model=CnSectorOverviewOut)
def cn_sector_overview(n: int = 10, asof: dt.date | None = None, db: Session = Depends(get_db)):
    n = max(3, min(int(n), 30))

    end = asof or _latest_cn_flow_date(db)
    if end is None:
        raise HTTPException(status_code=400, detail="No CN sector flow data yet. Run ingest first.")

    cache_key = f"cn_sector_overview:v2:n={n}"
    cached = _cache_get(db, cache_key=cache_key, asof=end, max_age_s=15 * 60)
    if cached is not None:
        return CnSectorOverviewOut(
            asof=end,
            top_inflow=[CnSectorOverviewItemOut(**x) for x in cached.get("top_inflow", [])],
            top_outflow=[CnSectorOverviewItemOut(**x) for x in cached.get("top_outflow", [])],
            new_mainline=[CnSectorSignalOut(**x) for x in cached.get("new_mainline", [])],
            fading=[CnSectorSignalOut(**x) for x in cached.get("fading", [])],
        )

    name_map = {r.code: r.name for r in db.execute(select(CnIndustry)).scalars().all()}

    rows = db.execute(
        select(Observation.indicator_key, Observation.value)
        .where(
            Observation.date == end,
            Observation.indicator_key.like("cn_industry_flow_main_net:%"),
        )
    ).all()
    today_vals: list[tuple[str, float]] = []
    for k, v in rows:
        code = str(k).split(":", 1)[1] if ":" in str(k) else str(k)
        today_vals.append((code, float(v or 0.0)))

    if not today_vals:
        raise HTTPException(status_code=400, detail="No CN sector flow data yet. Run ingest first.")

    # Rank definition (tempA): higher main_net ranks better.
    today_sorted = sorted(today_vals, key=lambda x: x[1], reverse=True)
    today_rank = {code: i + 1 for i, (code, _) in enumerate(today_sorted)}

    prev = _prev_cn_flow_date(db, end)
    prev_rank: dict[str, int] = {}
    prev_main_net: dict[str, float] = {}
    if prev is not None:
        prev_rows = db.execute(
            select(Observation.indicator_key, Observation.value)
            .where(
                Observation.date == prev,
                Observation.indicator_key.like("cn_industry_flow_main_net:%"),
            )
        ).all()
        prev_vals: list[tuple[str, float]] = []
        for k, v in prev_rows:
            code = str(k).split(":", 1)[1] if ":" in str(k) else str(k)
            val = float(v or 0.0)
            prev_vals.append((code, val))
            prev_main_net[code] = val
        prev_sorted = sorted(prev_vals, key=lambda x: x[1], reverse=True)
        prev_rank = {code: i + 1 for i, (code, _) in enumerate(prev_sorted)}

    def _features_at(code: str, end_date: dt.date, main_net_hint: float | None = None) -> tuple[float | None, float | None, str, int | None]:
        flow_key = f"cn_industry_flow_main_net:{code}"
        tail = _load_tail(db, indicator_key=flow_key, end=end_date, limit=30)
        vals = [v for _, v in tail]
        _today_v = vals[-1] if vals else (main_net_hint if main_net_hint is not None else 0.0)
        flow_5d = sum(vals[-5:]) if len(vals) >= 5 else (sum(vals) if vals else None)

        close_key = f"cn_industry_close:{code}"
        close_tail = _load_tail(db, indicator_key=close_key, end=end_date, limit=12)
        closes = [v for _, v in close_tail]
        price_return_5d = None
        if len(closes) >= 6 and closes[-6] != 0:
            price_return_5d = float(closes[-1] / closes[-6] - 1.0)

        state = _compute_state(flow_5d=flow_5d, price_return_5d=price_return_5d)
        div = _divergence_score(flow_5d=flow_5d, price_return_5d=price_return_5d)
        return flow_5d, price_return_5d, state, div

    def _enrich(code: str, main_net: float) -> CnSectorOverviewItemOut:
        # Flow tails (for strength + 5/10d sums)
        flow_key = f"cn_industry_flow_main_net:{code}"
        tail = _load_tail(db, indicator_key=flow_key, end=end, limit=30)
        vals = [v for _, v in tail]
        today_v = vals[-1] if vals else main_net
        last20 = vals[-21:-1] if len(vals) >= 21 else (vals[:-1] if len(vals) >= 2 else [])
        mean_abs_20 = (sum(abs(x) for x in last20) / len(last20)) if last20 else 0.0
        flow_strength = (today_v / mean_abs_20) if mean_abs_20 > 0 else None

        flow_5d = sum(vals[-5:]) if len(vals) >= 5 else (sum(vals) if vals else None)
        flow_10d = sum(vals[-10:]) if len(vals) >= 10 else (sum(vals) if vals else None)

        # Price 5d return from close
        close_key = f"cn_industry_close:{code}"
        close_tail = _load_tail(db, indicator_key=close_key, end=end, limit=12)
        closes = [v for _, v in close_tail]
        price_return_5d = None
        if len(closes) >= 6 and closes[-6] != 0:
            price_return_5d = float(closes[-1] / closes[-6] - 1.0)

        state = _compute_state(flow_5d=flow_5d, price_return_5d=price_return_5d)
        div = _divergence_score(flow_5d=flow_5d, price_return_5d=price_return_5d)

        r = today_rank.get(code, 0)
        rc = None
        if prev_rank:
            pr = prev_rank.get(code)
            if pr is not None and r:
                # tempA: rotation speed = today's rank - yesterday's rank
                rc = r - pr

        return CnSectorOverviewItemOut(
            code=code,
            name=name_map.get(code, code),
            main_net=main_net,
            flow_strength=flow_strength,
            flow_5d=flow_5d,
            flow_10d=flow_10d,
            price_return_5d=price_return_5d,
            divergence_score=div,
            state=state,
            rank=r,
            rank_change=rc,
        )

    inflow_sorted = [(c, v) for c, v in today_sorted if v > 0]
    outflow_sorted = [(c, v) for c, v in sorted(today_vals, key=lambda x: x[1]) if v < 0]

    top_inflow_raw = inflow_sorted[:n]
    top_outflow_raw = outflow_sorted[:n]

    top_inflow = [_enrich(code, v) for code, v in top_inflow_raw]
    top_outflow = [_enrich(code, v) for code, v in top_outflow_raw]

    # Signals (tempA): new mainline / fading
    new_mainline: list[CnSectorSignalOut] = []
    fading: list[CnSectorSignalOut] = []
    if prev is not None and prev_rank:
        pool = sorted(today_vals, key=lambda x: abs(x[1]), reverse=True)[:50]
        for code, main_net in pool:
            r = today_rank.get(code)
            pr = prev_rank.get(code)
            if r is None or pr is None:
                continue
            rotation_speed = r - pr

            _, _, state_today, div_today = _features_at(code, end, main_net_hint=main_net)
            prev_net = prev_main_net.get(code, 0.0)
            _, _, state_prev, _ = _features_at(code, prev, main_net_hint=prev_net)

            if state_today == "主升" and state_prev != "主升" and main_net > 0 and rotation_speed <= -5:
                new_mainline.append(
                    CnSectorSignalOut(
                        code=code,
                        name=name_map.get(code, code),
                        main_net=main_net,
                        state=state_today,
                        prev_state=state_prev,
                        rotation_speed=rotation_speed,
                        rank=r,
                        divergence_score=div_today,
                    )
                )

            if state_today == "退潮" and state_prev != "退潮" and main_net < 0 and rotation_speed >= 5:
                fading.append(
                    CnSectorSignalOut(
                        code=code,
                        name=name_map.get(code, code),
                        main_net=main_net,
                        state=state_today,
                        prev_state=state_prev,
                        rotation_speed=rotation_speed,
                        rank=r,
                        divergence_score=div_today,
                    )
                )

        new_mainline = sorted(new_mainline, key=lambda x: (x.rotation_speed or 0, -x.main_net))[:6]
        fading = sorted(fading, key=lambda x: (-(x.rotation_speed or 0), x.main_net))[:6]

    _cache_set(
        db,
        cache_key=cache_key,
        asof=end,
        payload={
            "asof": str(end),
            "top_inflow": [x.model_dump(mode="json") for x in top_inflow],
            "top_outflow": [x.model_dump(mode="json") for x in top_outflow],
            "new_mainline": [x.model_dump(mode="json") for x in new_mainline],
            "fading": [x.model_dump(mode="json") for x in fading],
        },
    )

    return CnSectorOverviewOut(
        asof=end,
        top_inflow=top_inflow,
        top_outflow=top_outflow,
        new_mainline=new_mainline,
        fading=fading,
    )


@app.get("/api/cn/sector/matrix", response_model=CnSectorMatrixOut)
def cn_sector_matrix(
    days: int = 10,
    n: int = 20,
    direction: str = "abs",
    asof: dt.date | None = None,
    db: Session = Depends(get_db),
):
    days = max(5, min(int(days), 30))
    n = max(5, min(int(n), 50))

    direction = (direction or "abs").strip().lower()
    if direction not in {"abs", "in", "out"}:
        raise HTTPException(status_code=400, detail="direction must be 'abs', 'in', or 'out'")

    end = asof or _latest_cn_flow_date(db)
    if end is None:
        raise HTTPException(status_code=400, detail="No CN sector flow data yet. Run ingest first.")

    cache_key = f"cn_sector_matrix:v2:days={days}:n={n}:dir={direction}"
    cached = _cache_get(db, cache_key=cache_key, asof=end, max_age_s=15 * 60)
    if cached is not None:
        return CnSectorMatrixOut(
            asof=end,
            dates=[dt.date.fromisoformat(x) for x in cached.get("dates", [])],
            rows=[CnSectorMatrixRowOut(**r) for r in cached.get("rows", [])],
        )

    name_map = {r.code: r.name for r in db.execute(select(CnIndustry)).scalars().all()}

    today_rows = db.execute(
        select(Observation.indicator_key, Observation.value)
        .where(Observation.date == end, Observation.indicator_key.like("cn_industry_flow_main_net:%"))
    ).all()
    today_vals: list[tuple[str, float]] = []
    for k, v in today_rows:
        code = str(k).split(":", 1)[1] if ":" in str(k) else str(k)
        today_vals.append((code, float(v or 0.0)))

    # Pick rows by direction.
    if direction == "in":
        pool = [(c, v) for c, v in today_vals if v > 0]
        picked = sorted(pool, key=lambda x: x[1], reverse=True)[:n]
    elif direction == "out":
        pool = [(c, v) for c, v in today_vals if v < 0]
        # More negative first
        picked = sorted(pool, key=lambda x: x[1])[:n]
    else:
        picked = sorted(today_vals, key=lambda x: abs(x[1]), reverse=True)[:n]

    date_set: set[dt.date] = set()
    per_code: dict[str, list[tuple[dt.date, float]]] = {}
    for code, _ in picked:
        flow_key = f"cn_industry_flow_main_net:{code}"
        tail = _load_tail(db, indicator_key=flow_key, end=end, limit=days)
        per_code[code] = tail
        date_set.update(d for d, _ in tail)

    dates = sorted(date_set)
    if len(dates) > days:
        dates = dates[-days:]

    rows_out: list[CnSectorMatrixRowOut] = []
    for code, _ in picked:
        tail = per_code.get(code, [])
        mp = {d: v for d, v in tail}

        # Normalize by recent mean abs to make colors comparable within the row.
        vals_raw = [float(mp.get(d, 0.0)) for d in dates]
        # When user explicitly requests inflow/outflow matrix, do not mix signs.
        # For inflow: keep only >=0; for outflow: keep only <=0.
        if direction == "in":
            vals_raw = [x if x > 0 else 0.0 for x in vals_raw]
        elif direction == "out":
            vals_raw = [x if x < 0 else 0.0 for x in vals_raw]
        denom = sum(abs(x) for x in vals_raw) / len(vals_raw) if vals_raw else 0.0
        if denom <= 0:
            vals = [0.0 for _ in vals_raw]
        else:
            vals = [max(-3.0, min(3.0, x / denom)) for x in vals_raw]

        rows_out.append(CnSectorMatrixRowOut(code=code, name=name_map.get(code, code), values=vals))

    payload = {
        "asof": str(end),
        "dates": [str(d) for d in dates],
        "rows": [r.model_dump(mode="json") for r in rows_out],
    }
    _cache_set(db, cache_key=cache_key, asof=end, payload=payload)
    return CnSectorMatrixOut(asof=end, dates=dates, rows=rows_out)


@app.get("/api/cn/sector/breadth", response_model=CnSectorBreadthOut)
def cn_sector_breadth(code: str, asof: dt.date | None = None, db: Session = Depends(get_db)):
    code = (code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required")

    end = asof or _latest_cn_flow_date(db)
    if end is None:
        raise HTTPException(status_code=400, detail="No CN sector flow data yet. Run ingest first.")

    cache_key = f"cn_sector_breadth:code={code}"
    cached = _cache_get(db, cache_key=cache_key, asof=end, max_age_s=15 * 60)
    if cached is not None:
        return CnSectorBreadthOut(**cached)

    row = db.execute(select(CnIndustry).where(CnIndustry.code == code)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown industry code")

    # External call (Eastmoney) to compute breadth; cache the result.
    try:
        import akshare as ak  # type: ignore
    except ImportError as e:
        raise HTTPException(status_code=500, detail="AkShare not installed") from e

    df = ak.stock_sector_fund_flow_summary(symbol=row.name, indicator="今日")  # type: ignore[attr-defined]
    if df is None or df.empty:
        raise HTTPException(status_code=502, detail="breadth source returned empty")

    col = "今天涨跌幅" if "今天涨跌幅" in df.columns else ("涨跌幅" if "涨跌幅" in df.columns else None)
    if col is None:
        raise HTTPException(status_code=502, detail="breadth source missing pct column")

    pct = pd.to_numeric(df[col], errors="coerce")
    total = int(pct.notna().sum())
    up = int((pct > 0).sum())
    breadth = float(up / total) if total > 0 else 0.0

    payload = {
        "asof": str(end),
        "code": code,
        "name": row.name,
        "breadth": breadth,
        "up": up,
        "total": total,
    }
    _cache_set(db, cache_key=cache_key, asof=end, payload=payload)
    return CnSectorBreadthOut(**payload)


@app.get("/api/chat/explain/cached")
def chat_explain_cached(asof: dt.date | None = None, db: Session = Depends(get_db)):
    """Return cached explanation if available; never calls the LLM."""
    snapshot = get_snapshot(asof=asof, db=db)
    if not snapshot.regime:
        raise HTTPException(status_code=400, detail="No regime computed yet. Run ingest first.")

    shash = _snapshot_hash(snapshot)
    row = _get_llm_cache(db, snapshot_hash=shash)
    return {
        "asof": str(snapshot.asof),
        "cached": row is not None,
        "text": row.text if row else None,
        "snapshot_hash": shash,
        "updated_at": row.updated_at.isoformat() if row else None,
    }


@app.post("/api/telemetry/pageview")
def telemetry_pageview(payload: dict, request: Request, db: Session = Depends(get_db)):
    """Record a single page view.

    Privacy policy (MVP): store only coarse IP prefix + server-side hash.
    """
    if not settings.telemetry_enabled:
        return {"ok": False, "disabled": True}

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    path = str(payload.get("path") or "/")[:256]
    event = str(payload.get("event") or "pageview")[:32]

    asof_raw = payload.get("asof")
    asof: dt.date | None = None
    if isinstance(asof_raw, str) and asof_raw:
        try:
            asof = dt.date.fromisoformat(asof_raw)
        except ValueError:
            asof = None

    user_agent = request.headers.get("user-agent")
    if user_agent:
        user_agent = user_agent[:256]
    ref = request.headers.get("referer")
    if ref:
        ref = ref[:512]
    accept_lang = request.headers.get("accept-language")
    if accept_lang:
        accept_lang = accept_lang[:128]

    ip = _client_ip(request)
    prefix = _ip_prefix(ip) if ip else None
    vhash = _visitor_hash(salt=settings.telemetry_salt, ip_prefix=prefix, user_agent=user_agent)

    db.add(
        PageView(
            event=event,
            path=path,
            asof=asof,
            session_id=session_id,
            visitor_hash=vhash,
            ip_prefix=prefix,
            user_agent=user_agent,
            referrer=ref,
            accept_language=accept_lang,
        )
    )
    db.commit()
    return {"ok": True}


@app.get("/api/telemetry/stats")
def telemetry_stats(days: int = 30, db: Session = Depends(get_db)):
    if not settings.telemetry_enabled:
        return {"ok": False, "disabled": True}

    # days=0 means "all time".
    days = max(0, min(days, 3650))
    end = dt.datetime.utcnow()
    start = None if days == 0 else (end - dt.timedelta(days=days))

    if start is not None:
        total = db.execute(sa_text("select count(*) from page_view where ts >= :start"), {"start": start}).scalar_one()
        sessions = db.execute(
            sa_text("select count(distinct session_id) from page_view where ts >= :start"),
            {"start": start},
        ).scalar_one()
        visitors = db.execute(
            sa_text("select count(distinct visitor_hash) from page_view where ts >= :start"),
            {"start": start},
        ).scalar_one()
        per_day = db.execute(
            sa_text(
                "select date(ts) as d, count(*) as pv "
                "from page_view where ts >= :start "
                "group by 1 order by 1"
            ),
            {"start": start},
        ).all()
    else:
        total = db.execute(sa_text("select count(*) from page_view")).scalar_one()
        sessions = db.execute(sa_text("select count(distinct session_id) from page_view")).scalar_one()
        visitors = db.execute(sa_text("select count(distinct visitor_hash) from page_view")).scalar_one()
        per_day = db.execute(
            sa_text("select date(ts) as d, count(*) as pv from page_view group by 1 order by 1")
        ).all()

    return {
        "ok": True,
        "window_days": days,
        "pv": int(total),
        "sessions": int(sessions),
        "visitors": int(visitors),
        "pv_by_day": [{"date": str(r[0]), "pv": int(r[1])} for r in per_day],
    }


@app.post("/api/chat/explain")
def chat_explain(asof: dt.date | None = None, force: bool = False, db: Session = Depends(get_db)):
    snapshot = get_snapshot(asof=asof, db=db)

    if not snapshot.regime:
        raise HTTPException(status_code=400, detail="No regime computed yet. Run ingest first.")

    shash = _snapshot_hash(snapshot)
    if not force:
        cached = _get_llm_cache(db, snapshot_hash=shash)
        if cached is not None:
            return {
                "asof": str(snapshot.asof),
                "text": cached.text,
                "cached": True,
                "snapshot_hash": shash,
                "updated_at": cached.updated_at.isoformat(),
            }

    prompt = (
        "请解释今天的宏观监控快照，并给出为什么选择该仓位模板。\n"
        f"日期: {snapshot.asof}\n"
        f"Regime: {snapshot.regime.regime} (risk_score={snapshot.regime.risk_score})\n"
        f"Template: {snapshot.regime.template_name}\n"
        f"Drivers(JSON): {snapshot.regime.drivers}\n"
        f"Indicators(JSON): {[i.model_dump() for i in snapshot.indicators]}\n"
        "要求：\n"
        "- 只基于提供的数据解释\n"
        "- 输出：1)一句话结论 2)三条主要驱动 3)风险点与需要盯的指标\n"
    )

    try:
        llm_text = explain_snapshot(prompt)
        _upsert_llm_cache(db, asof=snapshot.asof, snapshot_hash=shash, text=llm_text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "asof": str(snapshot.asof),
        "text": llm_text,
        "cached": False,
        "snapshot_hash": shash,
        "updated_at": None,
    }


@app.get("/api/chat/explain/stream")
def chat_explain_stream(asof: dt.date | None = None, force: bool = False, db: Session = Depends(get_db)):
    snapshot = get_snapshot(asof=asof, db=db)
    if not snapshot.regime:
        raise HTTPException(status_code=400, detail="No regime computed yet. Run ingest first.")

    shash = _snapshot_hash(snapshot)
    if not force:
        cached = _get_llm_cache(db, snapshot_hash=shash)
        if cached is not None:
            def _iter_cached() -> Iterator[str]:
                payload = json.dumps({"delta": cached.text, "cached": True}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                yield "data: {\"done\": true}\n\n"

            return StreamingResponse(
                _iter_cached(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

    prompt = (
        "请解释今天的宏观监控快照，并给出为什么选择该仓位模板。\n"
        f"日期: {snapshot.asof}\n"
        f"Regime: {snapshot.regime.regime} (risk_score={snapshot.regime.risk_score})\n"
        f"Template: {snapshot.regime.template_name}\n"
        f"Drivers(JSON): {snapshot.regime.drivers}\n"
        f"Indicators(JSON): {[i.model_dump() for i in snapshot.indicators]}\n"
        "要求：\n"
        "- 只基于提供的数据解释\n"
        "- 输出：1)一句话结论 2)三条主要驱动 3)风险点与需要盯的指标\n"
        "- 使用 Markdown 格式输出\n"
    )

    def _iter_events() -> Iterator[str]:
        buf: list[str] = []
        try:
            for delta in explain_snapshot_stream(prompt):
                payload = json.dumps({"delta": delta}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                buf.append(delta)
            full = "".join(buf)
            if full.strip():
                _upsert_llm_cache(db, asof=snapshot.asof, snapshot_hash=shash, text=full)
            yield "data: {\"done\": true}\n\n"
        except (OpenAIError, RuntimeError, ValueError) as e:
            payload = json.dumps({"error": str(e), "done": True}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        _iter_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# If a built frontend exists (e.g., in Docker/ACA), serve it at '/'.
_frontend_dist = Path(__file__).resolve().parent / "static"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
