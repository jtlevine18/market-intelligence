"""
Pipeline scheduler -- daily automated runs via APScheduler.

Runs the market intelligence pipeline daily at 06:00 UTC.
Persists scheduler state to scheduler_state.json.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.pipeline import MarketIntelligencePipeline

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent.parent / "scheduler_state.json"


class PipelineScheduler:
    """Manages scheduled and manual pipeline runs."""

    def __init__(self):
        self._scheduler: BackgroundScheduler | None = None
        self._running = False
        self._lock = threading.Lock()
        self._state = self._load_state()
        # Live progress tracking
        self._current_step: str | None = None
        self._step_started_at: str | None = None
        self._completed_steps: list[dict] = []
        self._run_started_at: str | None = None

    def _load_state(self) -> dict:
        """Load persisted scheduler state."""
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "total_runs": 0,
            "last_run_at": None,
            "last_status": None,
            "enabled": False,
        }

    def _save_state(self):
        """Persist scheduler state to disk."""
        try:
            STATE_FILE.write_text(json.dumps(self._state, indent=2, default=str))
        except OSError as e:
            logger.warning("Failed to save scheduler state: %s", e)

    def start(self):
        """Start the background scheduler with daily 06:00 UTC runs."""
        with self._lock:
            if self._scheduler is not None:
                return

            self._scheduler = BackgroundScheduler()
            self._scheduler.add_job(
                self._run_pipeline,
                trigger=CronTrigger(hour=6, minute=0),
                id="daily_pipeline",
                name="Daily Market Intelligence Pipeline",
                replace_existing=True,
            )
            self._scheduler.start()
            self._state["enabled"] = True
            self._save_state()
            logger.info("Pipeline scheduler started -- daily run at 06:00 UTC")

    def stop(self):
        """Stop the background scheduler."""
        with self._lock:
            if self._scheduler is not None:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None
            self._state["enabled"] = False
            self._save_state()
            logger.info("Pipeline scheduler stopped")

    def trigger(self) -> dict:
        """Trigger an immediate pipeline run (non-blocking)."""
        with self._lock:
            if self._running:
                return {"status": "already_running", "message": "A pipeline run is already in progress"}
            self._running = True

        thread = threading.Thread(target=self._run_pipeline, daemon=True)
        thread.start()
        return {"status": "triggered", "message": "Pipeline run started"}

    def _run_pipeline(self):
        """Execute a pipeline run (called by scheduler or manual trigger)."""
        self._completed_steps = []
        self._current_step = "initializing"
        self._run_started_at = datetime.now(timezone.utc).isoformat()

        try:
            import asyncio
            import os
            import time
            print("[PIPELINE] Starting pipeline run", flush=True)
            has_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
            print(f"[PIPELINE] Claude API: {'enabled' if has_claude else 'disabled'}", flush=True)
            pipeline = MarketIntelligencePipeline(
                days_back=30,
                use_claude_extraction=has_claude,
                use_claude_reconciliation=has_claude,
                use_claude_recommender=has_claude,
            )
            # Attach progress callback
            pipeline._progress_cb = self._on_step_progress
            result = asyncio.run(pipeline.run())

            self._state["total_runs"] = self._state.get("total_runs", 0) + 1
            self._state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            self._state["last_status"] = result.status
            self._save_state()

            self._current_step = None
            print(f"[PIPELINE] Complete -- status={result.status}, duration={result.duration_s:.1f}s, cost=${result.total_cost_usd:.4f}", flush=True)
            for s in result.steps:
                print(f"[PIPELINE]   {s.step}: {s.status} ({s.duration_s:.1f}s) {s.errors or ''}", flush=True)
        except Exception as exc:
            print(f"[PIPELINE] FAILED: {exc}", flush=True)
            import traceback
            traceback.print_exc()
            self._current_step = None
            self._state["last_status"] = "failed"
            self._save_state()
        finally:
            self._running = False

    def _on_step_progress(self, step: str, status: str, duration_s: float = 0):
        """Callback from pipeline to track step progress."""
        if status == "started":
            self._current_step = step
            self._step_started_at = datetime.now(timezone.utc).isoformat()
            print(f"[PIPELINE] Step: {step} -- started", flush=True)
        elif status in ("ok", "skipped", "failed"):
            self._completed_steps.append({
                "step": step, "status": status, "duration_s": round(duration_s, 1),
            })
            self._current_step = None
            print(f"[PIPELINE] Step: {step} -- {status} ({duration_s:.1f}s)", flush=True)

    @property
    def progress(self) -> dict:
        """Current pipeline progress for the status page."""
        return {
            "running": self._running,
            "current_step": self._current_step,
            "step_started_at": self._step_started_at,
            "completed_steps": self._completed_steps,
            "run_started_at": self._run_started_at,
            **self._state,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def state(self) -> dict:
        return {**self._state, "currently_running": self._running}


# Module-level singleton
scheduler = PipelineScheduler()
