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
        self.mandis: list[dict] = []
        self.market_prices: list[dict] = []
        self.price_forecasts: list[dict] = []
        self.sell_recommendations: list[dict] = []
        self.price_conflicts: list[dict] = []
        self.pipeline_runs: list[dict] = []
        self.stats: dict[str, Any] = {}

        # Pipeline stage outputs
        self.raw_inputs: dict = {}
        self.extracted_data: dict = {}
        self.reconciliation_results: dict = {}
        self.model_metrics: dict = {}
        self.recommendation_reasoning: list[dict] = []
        self.rag_retrievals: list[dict] = []

        self._lock = threading.Lock()

    def update(self, run_result: dict):
        """Update the store with results from a pipeline run.

        Args:
            run_result: dict with keys matching the store attributes.
        """
        with self._lock:
            try:
                self.mandis = run_result.get("mandis", [])
                self.market_prices = run_result.get("market_prices", [])
                self.price_forecasts = run_result.get("price_forecasts", [])
                sell_recs = run_result.get("sell_recommendations", [])
                if isinstance(sell_recs, dict):
                    sell_recs = [sell_recs]
                self.sell_recommendations = sell_recs
                self.price_conflicts = run_result.get("price_conflicts", [])

                # Pipeline stage data
                self.raw_inputs = run_result.get("raw_inputs", {})
                self.extracted_data = run_result.get("extracted_data", {})
                self.reconciliation_results = run_result.get("reconciliation_results", {})
                self.model_metrics = run_result.get("model_metrics", {})
                self.recommendation_reasoning = run_result.get("recommendation_reasoning", [])
                self.rag_retrievals = run_result.get("rag_retrievals", [])

                run_info = run_result.get("run_info", {})
                if run_info:
                    self.pipeline_runs.insert(0, run_info)
                    self.pipeline_runs = self.pipeline_runs[:50]

                self.stats = self._build_stats(run_result)
                self.has_real_data = True

                logger.info(
                    "Store updated: %d mandis, %d prices, %d forecasts",
                    len(self.mandis),
                    len(self.market_prices),
                    len(self.price_forecasts),
                )
            except Exception:
                logger.exception("Failed to update store from pipeline")

    def _build_stats(self, run_result: dict) -> dict:
        """Build aggregate stats from run result."""
        runs = self.pipeline_runs
        total_runs = len(runs)
        successful = sum(1 for r in runs if r.get("status") == "ok")
        total_cost = sum(r.get("total_cost_usd", 0) for r in runs)

        price_conflicts = run_result.get("price_conflicts", [])
        unresolved = sum(
            1 for c in price_conflicts
            if c.get("resolution") == "unresolved"
        )

        return {
            "total_runs": total_runs,
            "successful_runs": successful,
            "success_rate": round(successful / max(1, total_runs), 2),
            "mandis_monitored": len(run_result.get("mandis", [])),
            "commodities_tracked": len(set(
                p.get("commodity_id") for p in run_result.get("market_prices", [])
            )),
            "price_conflicts_found": len(price_conflicts),
            "unresolved_conflicts": unresolved,
            "total_cost_usd": round(total_cost, 2),
            "avg_cost_per_run_usd": round(total_cost / max(1, total_runs), 4),
            "last_run": runs[0].get("started_at") if runs else None,
            "data_sources": ["Agmarknet (data.gov.in)", "eNAM", "NASA POWER"],
        }


# Module-level singleton
store = PipelineStore()
