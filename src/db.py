"""
Neon PostgreSQL persistence layer.

Stores pipeline runs, forecasts, stock readings, anomaly scores, and agent
traces. Falls back gracefully when DATABASE_URL is not set — the app runs
in demo mode with in-memory data.

Tables:
    pipeline_runs     — run metadata (status, duration, cost, step results)
    forecasts         — demand forecasts per facility × drug × period
    stock_snapshots   — stock level snapshots with anomaly scores
    agent_traces      — Claude agent tool call traces
    model_metrics     — ML model evaluation metrics per run
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
    status = Column(String(20), nullable=False)  # ok, partial, failed
    duration_sec = Column(Float)
    total_cost_usd = Column(Float, default=0)
    facilities_count = Column(Integer, default=0)
    drugs_count = Column(Integer, default=0)
    step_results = Column(Text)  # JSON blob of per-step status
    errors = Column(Text)


class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    facility_id = Column(String(20), nullable=False, index=True)
    drug_id = Column(String(20), nullable=False, index=True)
    period = Column(String(20), nullable=False)  # e.g. "2026-04"
    predicted_consumption = Column(Float)
    prediction_lower = Column(Float)
    prediction_upper = Column(Float)
    actual_consumption = Column(Float)  # filled later for evaluation
    model_type = Column(String(30))  # xgboost, epidemiological, corrected
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StockSnapshot(Base):
    __tablename__ = "stock_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    facility_id = Column(String(20), nullable=False, index=True)
    drug_id = Column(String(20), nullable=False, index=True)
    stock_level = Column(Float)
    days_of_stock = Column(Float)
    consumption_rate = Column(Float)
    anomaly_score = Column(Float)
    is_anomaly = Column(Boolean, default=False)
    risk_level = Column(String(20))  # ok, low, medium, high, critical
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    agent_type = Column(String(30), nullable=False)  # extraction, reconciliation, procurement
    facility_id = Column(String(20), index=True)
    tool_calls = Column(Text)  # JSON array of tool call details
    reasoning = Column(Text)
    tokens_used = Column(Integer, default=0)
    cost_usd = Column(Float, default=0)
    duration_sec = Column(Float)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ModelMetric(Base):
    __tablename__ = "model_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    model_name = Column(String(50), nullable=False)  # primary_xgb, residual_xgb, anomaly_detector
    metric_name = Column(String(50), nullable=False)  # rmse, mae, r2, etc.
    metric_value = Column(Float, nullable=False)
    extra_data = Column(Text)  # JSON with extra details (feature importances, etc.)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            return None

        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if DATABASE_URL.startswith("sqlite"):
            # SQLite: no pooling args, no SSL
            pass
        else:
            # PostgreSQL (Neon): connection pool + SSL
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
    """Create all tables if they don't exist. Idempotent — only runs DDL once."""
    global _db_initialized
    if _db_initialized:
        return True
    engine = get_engine()
    if engine is None:
        log.info("DATABASE_URL not set — running without persistence")
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
            duration_sec=run_info.get("duration_sec", 0),
            total_cost_usd=run_info.get("total_cost_usd", 0),
            facilities_count=len(run_result.get("facilities", [])),
            drugs_count=len(set(
                s.get("drug_id") for s in run_result.get("stock_levels", [])
            )),
            step_results=json.dumps(run_info.get("steps", {})),
            errors=json.dumps(run_info.get("errors", [])),
        )
        session.add(run)

        # Save forecasts
        for fc in run_result.get("demand_forecasts", []):
            session.add(Forecast(
                run_id=run.run_id,
                facility_id=fc.get("facility_id", ""),
                drug_id=fc.get("drug_id", ""),
                period=fc.get("period", ""),
                predicted_consumption=fc.get("predicted_consumption_per_1000"),
                prediction_lower=fc.get("prediction_interval_lower"),
                prediction_upper=fc.get("prediction_interval_upper"),
                model_type=fc.get("model_type", "xgboost"),
            ))

        # Save stock snapshots
        for sl in run_result.get("stock_levels", []):
            session.add(StockSnapshot(
                run_id=run.run_id,
                facility_id=sl.get("facility_id", ""),
                drug_id=sl.get("drug_id", ""),
                stock_level=sl.get("stock_level"),
                days_of_stock=sl.get("days_of_stock"),
                consumption_rate=sl.get("avg_daily_consumption"),
                anomaly_score=sl.get("anomaly_score"),
                is_anomaly=sl.get("is_anomaly", False),
                risk_level=sl.get("risk_level", "ok"),
            ))

        # Save agent traces
        for trace in run_result.get("procurement_reasoning", []):
            session.add(AgentTrace(
                run_id=run.run_id,
                agent_type=trace.get("agent_type", "procurement"),
                facility_id=trace.get("facility_id"),
                tool_calls=json.dumps(trace.get("tool_calls", [])),
                reasoning=trace.get("reasoning", ""),
                tokens_used=trace.get("tokens_used", 0),
                cost_usd=trace.get("cost_usd", 0),
                duration_sec=trace.get("duration_sec", 0),
            ))

        # Save model metrics
        model_metrics = run_result.get("model_metrics", {})
        for metric_name, metric_value in model_metrics.items():
            if isinstance(metric_value, (int, float)):
                session.add(ModelMetric(
                    run_id=run.run_id,
                    model_name="pipeline",
                    metric_name=metric_name,
                    metric_value=float(metric_value),
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
                "facilities_count": r.facilities_count,
                "drugs_count": r.drugs_count,
            }
            for r in runs
        ]
    except Exception:
        log.exception("Failed to fetch pipeline runs")
        return []
    finally:
        session.close()


def get_forecast_history(
    facility_id: str, drug_id: str, limit: int = 30,
) -> list[dict]:
    """Fetch forecast history for a specific facility/drug pair."""
    session = get_session()
    if session is None:
        return []

    try:
        forecasts = (
            session.query(Forecast)
            .filter_by(facility_id=facility_id, drug_id=drug_id)
            .order_by(Forecast.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "run_id": f.run_id,
                "period": f.period,
                "predicted_consumption": f.predicted_consumption,
                "prediction_lower": f.prediction_lower,
                "prediction_upper": f.prediction_upper,
                "actual_consumption": f.actual_consumption,
                "model_type": f.model_type,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in forecasts
        ]
    except Exception:
        log.exception("Failed to fetch forecast history")
        return []
    finally:
        session.close()


def get_anomaly_history(facility_id: str, limit: int = 50) -> list[dict]:
    """Fetch anomaly score history for a facility."""
    session = get_session()
    if session is None:
        return []

    try:
        snapshots = (
            session.query(StockSnapshot)
            .filter_by(facility_id=facility_id, is_anomaly=True)
            .order_by(StockSnapshot.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "drug_id": s.drug_id,
                "stock_level": s.stock_level,
                "anomaly_score": s.anomaly_score,
                "risk_level": s.risk_level,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snapshots
        ]
    except Exception:
        log.exception("Failed to fetch anomaly history")
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
