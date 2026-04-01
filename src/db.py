"""
Neon PostgreSQL persistence layer for Market Intelligence.

Stores pipeline runs, market prices, price forecasts, sell recommendations,
and agent traces. Falls back gracefully when DATABASE_URL is not set --
the app runs in demo mode with in-memory data.

Tables:
    pipeline_runs        -- run metadata (status, duration, cost, step results)
    market_prices        -- reconciled mandi prices by commodity
    price_forecasts      -- 7/14/30d price predictions with confidence intervals
    sell_recommendations -- optimal sell options per farmer
    agent_traces         -- Claude agent tool call traces
    model_metrics        -- ML model evaluation metrics per run
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Boolean,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False)
    duration_sec = Column(Float)
    total_cost_usd = Column(Float, default=0)
    mandis_count = Column(Integer, default=0)
    commodities_count = Column(Integer, default=0)
    step_results = Column(Text)
    errors = Column(Text)


class MarketPrice(Base):
    __tablename__ = "market_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    mandi_id = Column(String(20), nullable=False, index=True)
    commodity_id = Column(String(20), nullable=False, index=True)
    date = Column(String(10))
    source = Column(String(20))
    price_rs = Column(Float)
    arrivals_tonnes = Column(Float)
    quality_flag = Column(String(20))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PriceForecast(Base):
    __tablename__ = "price_forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    mandi_id = Column(String(20), nullable=False, index=True)
    commodity_id = Column(String(20), nullable=False, index=True)
    forecast_date = Column(String(10))
    horizon_days = Column(Integer)
    predicted_price = Column(Float)
    ci_lower = Column(Float)
    ci_upper = Column(Float)
    model_type = Column(String(30))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SellRecommendation(Base):
    __tablename__ = "sell_recommendations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    farmer_id = Column(String(20), nullable=False, index=True)
    commodity_id = Column(String(20), nullable=False)
    best_mandi_id = Column(String(20))
    best_timing = Column(String(10))
    net_price_rs = Column(Float)
    potential_gain_rs = Column(Float)
    recommendation_text = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    agent_type = Column(String(30), nullable=False)  # extraction, reconciliation, recommendation
    mandi_id = Column(String(20), index=True)
    tool_calls = Column(Text)
    reasoning = Column(Text)
    tokens_used = Column(Integer, default=0)
    cost_usd = Column(Float, default=0)
    duration_sec = Column(Float)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ModelMetric(Base):
    __tablename__ = "model_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    model_name = Column(String(50), nullable=False)
    metric_name = Column(String(50), nullable=False)
    metric_value = Column(Float, nullable=False)
    extra_data = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            return None

        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if DATABASE_URL.startswith("sqlite"):
            pass
        else:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
            connect_args: dict[str, Any] = {}
            if "sslmode" not in DATABASE_URL:
                connect_args["sslmode"] = "require"
            kwargs["connect_args"] = connect_args

        _engine = create_engine(DATABASE_URL, **kwargs)
    return _engine


def get_session() -> Session | None:
    """Get a database session. Returns None if DB not configured."""
    global _SessionLocal
    engine = get_engine()
    if engine is None:
        return None
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal()


_db_initialized = False


def init_db() -> bool:
    """Create all tables if they don't exist. Idempotent."""
    global _db_initialized
    if _db_initialized:
        return True
    engine = get_engine()
    if engine is None:
        log.info("DATABASE_URL not set -- running without persistence")
        return False
    try:
        Base.metadata.create_all(engine)
        _db_initialized = True
        log.info("Database tables initialized")
        return True
    except Exception:
        log.exception("Failed to initialize database")
        return False


def save_pipeline_run(run_result: dict) -> bool:
    """Persist a pipeline run result to the database."""
    session = get_session()
    if session is None:
        return False

    try:
        run_info = run_result.get("run_info", {})
        run = PipelineRun(
            run_id=run_info.get("run_id", f"run-{datetime.now(timezone.utc).isoformat()}"),
            started_at=datetime.fromisoformat(run_info["started_at"])
            if "started_at" in run_info else datetime.now(timezone.utc),
            finished_at=datetime.fromisoformat(run_info["finished_at"])
            if "finished_at" in run_info else datetime.now(timezone.utc),
            status=run_info.get("status", "ok"),
            duration_sec=run_info.get("duration_s", 0),
            total_cost_usd=run_info.get("total_cost_usd", 0),
            mandis_count=len(run_result.get("mandis", [])),
            commodities_count=len(set(
                p.get("commodity_id") for p in run_result.get("market_prices", [])
            )),
            step_results=json.dumps(run_info.get("steps", {})),
            errors=json.dumps(run_info.get("errors", [])),
        )
        session.add(run)

        # Save market prices
        for mp in run_result.get("market_prices", []):
            session.add(MarketPrice(
                run_id=run.run_id,
                mandi_id=mp.get("mandi_id", ""),
                commodity_id=mp.get("commodity_id", ""),
                date=mp.get("date", ""),
                source=mp.get("source_used", ""),
                price_rs=mp.get("price_rs"),
                arrivals_tonnes=mp.get("arrivals_tonnes"),
                quality_flag=mp.get("quality_flag", ""),
            ))

        # Save price forecasts
        for fc in run_result.get("price_forecasts", []):
            for horizon, key in [(7, "price_7d"), (14, "price_14d"), (30, "price_30d")]:
                predicted = fc.get(key)
                if predicted:
                    session.add(PriceForecast(
                        run_id=run.run_id,
                        mandi_id=fc.get("mandi_id", ""),
                        commodity_id=fc.get("commodity_id", ""),
                        forecast_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        horizon_days=horizon,
                        predicted_price=predicted,
                        ci_lower=fc.get(f"ci_lower_{horizon}d"),
                        ci_upper=fc.get(f"ci_upper_{horizon}d"),
                        model_type=run_result.get("model_metrics", {}).get("model_type", ""),
                    ))

        # Save sell recommendations
        for rec in run_result.get("sell_recommendations", []):
            best = rec.get("best_option", {})
            session.add(SellRecommendation(
                run_id=run.run_id,
                farmer_id=rec.get("farmer_id", ""),
                commodity_id=rec.get("commodity_id", ""),
                best_mandi_id=best.get("mandi_id", ""),
                best_timing=best.get("sell_timing", ""),
                net_price_rs=best.get("net_price_rs"),
                potential_gain_rs=rec.get("potential_gain_rs"),
                recommendation_text=rec.get("recommendation_text", ""),
            ))

        # Save agent traces
        for trace in run_result.get("recommendation_reasoning", []):
            session.add(AgentTrace(
                run_id=run.run_id,
                agent_type="recommendation",
                tool_calls=json.dumps(trace.get("reasoning_trace", [])),
                reasoning=trace.get("recommendation_en", ""),
                tokens_used=trace.get("tokens_used", 0),
            ))

        session.commit()
        log.info("Pipeline run %s persisted to database", run.run_id)
        return True
    except Exception:
        session.rollback()
        log.exception("Failed to persist pipeline run")
        return False
    finally:
        session.close()


def get_recent_runs(limit: int = 20) -> list[dict]:
    """Fetch recent pipeline runs from the database."""
    session = get_session()
    if session is None:
        return []

    try:
        runs = (
            session.query(PipelineRun)
            .order_by(PipelineRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "run_id": r.run_id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "status": r.status,
                "duration_sec": r.duration_sec,
                "total_cost_usd": r.total_cost_usd,
                "mandis_count": r.mandis_count,
                "commodities_count": r.commodities_count,
            }
            for r in runs
        ]
    except Exception:
        log.exception("Failed to fetch pipeline runs")
        return []
    finally:
        session.close()


def health_check() -> dict:
    """Check database connectivity."""
    engine = get_engine()
    if engine is None:
        return {"status": "not_configured", "message": "DATABASE_URL not set"}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "message": "Connected to database"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
