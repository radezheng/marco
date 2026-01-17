from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from ipaddress import ip_address

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import OpenAIError
from sqlalchemy import func, text as sa_text
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, init_db
from .ingest import ingest_and_compute
from .llm import explain_snapshot, explain_snapshot_stream
from .models import Observation, PageView
from .snapshot_logic import build_snapshot, synthetic_liquidity_delta_points
from .schemas import SeriesPoint, SnapshotOut

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
def chat_explain(asof: dt.date | None = None, db: Session = Depends(get_db)):
    snapshot = get_snapshot(asof=asof, db=db)

    if not snapshot.regime:
        raise HTTPException(status_code=400, detail="No regime computed yet. Run ingest first.")

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
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"asof": str(snapshot.asof), "text": llm_text}


@app.get("/api/chat/explain/stream")
def chat_explain_stream(asof: dt.date | None = None, db: Session = Depends(get_db)):
    snapshot = get_snapshot(asof=asof, db=db)
    if not snapshot.regime:
        raise HTTPException(status_code=400, detail="No regime computed yet. Run ingest first.")

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
        try:
            for delta in explain_snapshot_stream(prompt):
                payload = json.dumps({"delta": delta}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
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
