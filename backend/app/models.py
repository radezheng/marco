from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Observation(Base):
    __tablename__ = "observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator_key: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="fred")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("indicator_key", "date", name="uq_observation_indicator_date"),
        Index("ix_observation_indicator_date", "indicator_key", "date"),
    )


class IndicatorState(Base):
    __tablename__ = "indicator_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator_key: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(String(8), nullable=False)  # G/Y/R/U
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("indicator_key", "date", name="uq_indicator_state_indicator_date"),
        Index("ix_indicator_state_indicator_date", "indicator_key", "date"),
    )


class RegimeState(Base):
    __tablename__ = "regime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, unique=True)
    regime: Mapped[str] = mapped_column(String(8), nullable=False)  # A/B/C
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    template_name: Mapped[str] = mapped_column(String(32), nullable=False)
    drivers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)


class PageView(Base):
    __tablename__ = "page_view"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow, index=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False, default="pageview")
    path: Mapped[str] = mapped_column(String(256), nullable=False, default="/")
    asof: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    # Client-side session identifier (random UUID stored in localStorage).
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Server-side derived identifier for approximate unique visitors.
    visitor_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Privacy: store only a coarse IP prefix (e.g., IPv4 /24 or IPv6 /48), not full IP.
    ip_prefix: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    accept_language: Mapped[str | None] = mapped_column(String(128), nullable=True)


class LlmExplanation(Base):
    __tablename__ = "llm_explanation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asof: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    # Stable hash of snapshot content (regime + drivers + indicators, etc.).
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=dt.datetime.utcnow,
        onupdate=dt.datetime.utcnow,
    )


class CnIndustry(Base):
    __tablename__ = "cn_industry"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="akshare_em")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class ApiCache(Base):
    __tablename__ = "api_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    asof: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("cache_key", "asof", name="uq_api_cache_key_asof"),
        Index("ix_api_cache_key_asof", "cache_key", "asof"),
    )
