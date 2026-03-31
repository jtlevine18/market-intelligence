"""
Shared singleton store that bridges pipeline output to API responses.

After a pipeline run completes, call ``store.update(run_result)`` to populate
the store with real data. The API checks ``store.has_real_data`` and serves
from the store when True, falling back to synthetic demo data when False.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class PipelineStore:
    """Thread-safe singleton that holds the latest pipeline run results."""

    def __init__(self):
        self.has_real_data = False
        self.facilities: list[dict] = []
        self.stock_levels: list[dict] = []
        self.demand_forecasts: list[dict] = []
        self.procurement_plans: list[dict] = []
        self.stockout_risks: list[dict] = []
        self.alerts: list[dict] = []
        self.pipeline_runs: list[dict] = []
        self.stats: dict[str, Any] = {}

        # New fields for extraction/reconciliation/agent pipeline
        self.raw_inputs: dict = {}                    # stock report texts, IDSR texts, CHW messages
        self.extracted_data: dict = {}                # per-facility extracted structured data
        self.reconciliation_results: dict = {}        # per-facility reconciled data + conflicts
        self.model_metrics: dict = {}                 # XGBoost RMSE, MAE, R2, feature importances
        self.procurement_reasoning: list[dict] = []   # agent tool call traces
        self.rag_retrievals: list[dict] = []          # which knowledge base chunks were used

        self._lock = threading.Lock()

    def update(self, run_result: dict):
        """Update the store with results from a pipeline run.

        Args:
            run_result: dict with keys matching the store attributes:
                facilities, stock_levels, demand_forecasts, procurement_plan,
                stockout_risks, alerts, run_info, raw_inputs, extracted_data,
                reconciliation_results, model_metrics, procurement_reasoning,
                rag_retrievals.
        """
        with self._lock:
            try:
                self.facilities = run_result.get("facilities", [])
                self.stock_levels = run_result.get("stock_levels", [])
                self.demand_forecasts = run_result.get("demand_forecasts", [])
                procurement = run_result.get("procurement_plans", run_result.get("procurement_plan", []))
                if isinstance(procurement, dict):
                    procurement = [procurement]
                self.procurement_plans = procurement
                self.stockout_risks = run_result.get("stockout_risks", [])
                self.alerts = run_result.get("alerts", [])

                # New fields
                self.raw_inputs = run_result.get("raw_inputs", {})
                self.extracted_data = run_result.get("extracted_data", {})
                self.reconciliation_results = run_result.get("reconciliation_results", {})
                self.model_metrics = run_result.get("model_metrics", {})
                self.procurement_reasoning = run_result.get("procurement_reasoning", [])
                self.rag_retrievals = run_result.get("rag_retrievals", [])

                run_info = run_result.get("run_info", {})
                if run_info:
                    self.pipeline_runs.insert(0, run_info)
                    self.pipeline_runs = self.pipeline_runs[:50]

                self.stats = self._build_stats(run_result)
                self.has_real_data = True

                logger.info(
                    "Store updated: %d facilities, %d stock levels, %d forecasts",
                    len(self.facilities),
                    len(self.stock_levels),
                    len(self.demand_forecasts),
                )
            except Exception:
                logger.exception("Failed to update store from pipeline")

    def _build_stats(self, run_result: dict) -> dict:
        """Build aggregate stats from run result."""
        runs = self.pipeline_runs
        total_runs = len(runs)
        successful = sum(1 for r in runs if r.get("status") == "ok")
        total_cost = sum(r.get("total_cost_usd", 0) for r in runs)

        stockout_risks = run_result.get("stockout_risks", [])
        high_risk = sum(
            1 for r in stockout_risks
            if r.get("risk_level") in ("high", "critical")
        )

        return {
            "total_runs": total_runs,
            "successful_runs": successful,
            "success_rate": round(successful / max(1, total_runs), 2),
            "facilities_monitored": len(run_result.get("facilities", [])),
            "drugs_tracked": len(set(
                r.get("drug_id") for r in run_result.get("stock_levels", [])
            )),
            "high_risk_stockouts": high_risk,
            "total_cost_usd": round(total_cost, 2),
            "avg_cost_per_run_usd": round(total_cost / max(1, total_runs), 4),
            "last_run": runs[0].get("started_at") if runs else None,
            "data_sources": ["NASA POWER", "LMIS (simulated)"],
        }


# Module-level singleton
store = PipelineStore()
