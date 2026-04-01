"""
Post-Harvest Market Intelligence -- Main Pipeline Orchestrator

6-step pipeline: INGEST -> EXTRACT -> RECONCILE -> FORECAST -> OPTIMIZE -> RECOMMEND

Each step has independent fallbacks -- no cascading failures.
Follows a common StepResult/PipelineRunResult pattern.
"""

import asyncio
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone

from config import (
    COMMODITIES,
    COMMODITY_MAP,
    MANDIS,
    MANDI_MAP,
    PIPELINE_STEPS,
    SAMPLE_FARMERS,
    SEASONAL_INDICES,
    BASE_PRICES_RS,
)
from src.ingestion.agmarknet import fetch_mandi_prices, PriceRecord
from src.ingestion.enam_scraper import fetch_enam_prices
from src.ingestion.nasa_power import fetch_all_mandis_nasa_power, DailyReading
from src.extraction.agent import ExtractionAgent, RuleBasedExtractor
from src.reconciliation.agent import ReconciliationAgent, RuleBasedReconciler
from src.forecasting.price_model import (
    XGBoostPriceModel,
    PriceForecast,
    generate_training_data,
)
from src.optimizer import optimize_sell, recommendation_to_dict, SellRecommendation, assess_credit_readiness, credit_readiness_to_dict
from src.recommendation_agent import RecommendationAgent, FarmerRecommendation
from src.store import store
from src import db as persistence

logger = logging.getLogger(__name__)


# ── Step / Pipeline result dataclasses ───────────────────────────────────

@dataclass
class StepResult:
    step: str
    status: str  # ok, partial, failed, skipped
    duration_s: float
    records_processed: int = 0
    errors: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class PipelineRunResult:
    run_id: str
    started_at: str
    ended_at: str
    status: str  # ok, partial, failed
    steps: list[StepResult]
    mandis_processed: int
    commodities_tracked: int
    price_conflicts_found: int
    total_cost_usd: float
    duration_s: float


# ── Pipeline class ───────────────────────────────────────────────────────

class MarketIntelligencePipeline:
    """
    End-to-end post-harvest market intelligence pipeline.

    Step 1 (INGEST):     Fetch Agmarknet API prices + eNAM prices + NASA POWER weather
    Step 2 (EXTRACT):    Normalize, deduplicate, flag stale/anomalous entries
    Step 3 (RECONCILE):  Resolve Agmarknet vs eNAM conflicts into trusted prices
    Step 4 (FORECAST):   Predict prices at 7/14/30 day horizons
    Step 5 (OPTIMIZE):   Compute sell options for sample farmer locations
    Step 6 (RECOMMEND):  Generate Claude-powered sell recommendations in English + Tamil
    """

    def __init__(
        self,
        days_back: int = 30,
        use_claude_extraction: bool = True,
        use_claude_reconciliation: bool = True,
        use_claude_recommender: bool = True,
    ):
        self.days_back = days_back
        self.use_claude_extraction = use_claude_extraction
        self.use_claude_reconciliation = use_claude_reconciliation
        self.use_claude_recommender = use_claude_recommender

        # Pipeline state
        self._agmarknet_prices: dict[str, list[PriceRecord]] = {}
        self._enam_prices: dict[str, list[PriceRecord]] = {}
        self._climate: dict[str, list] = {}
        self._extracted_data: dict = {}
        self._reconciled_data: dict = {}  # mandi_id -> {commodity_id -> {price, conf, ...}}
        self._forecasts: list[PriceForecast] = []
        self._forecast_by_mandi: dict[str, dict] = {}
        self._sell_recommendations: dict[str, dict] = {}
        self._farmer_recommendations: list[FarmerRecommendation] = []
        self._model_metrics: dict = {}
        self._price_conflicts: list[dict] = []

        # Token tracking
        self._extraction_tokens: int = 0
        self._reconciliation_tokens: int = 0
        self._recommendation_tokens: int = 0

    async def run(self) -> PipelineRunResult:
        """Execute the full 6-step pipeline."""
        run_id = str(uuid.uuid4())[:8]
        started_at = datetime.now(timezone.utc)

        persistence.init_db()
        steps: list[StepResult] = []
        total_cost = 0.0

        logger.info(
            "Pipeline run %s starting -- %d mandis, %d commodities, %d days back",
            run_id, len(MANDIS), len(COMMODITIES), self.days_back,
        )

        # Step 1: INGEST
        step1 = await self._step_ingest(run_id)
        steps.append(step1)
        if step1.status == "failed":
            logger.error("Ingestion failed completely -- aborting pipeline")
            return self._finalize(run_id, started_at, steps, "failed")

        # Step 2: EXTRACT
        step2 = await self._step_extract(run_id)
        steps.append(step2)
        total_cost += step2.details.get("cost_usd", 0)

        # Step 3: RECONCILE
        step3 = await self._step_reconcile(run_id)
        steps.append(step3)
        total_cost += step3.details.get("cost_usd", 0)

        # Step 4: FORECAST
        step4 = await self._step_forecast(run_id)
        steps.append(step4)

        # Step 5: OPTIMIZE
        step5 = await self._step_optimize(run_id)
        steps.append(step5)

        # Step 6: RECOMMEND
        step6 = await self._step_recommend(run_id)
        steps.append(step6)
        total_cost += step6.details.get("cost_usd", 0)

        result = self._finalize(run_id, started_at, steps, total_cost=total_cost)

        # Push to store
        self._update_store(result)

        logger.info(
            "Pipeline run %s complete -- status=%s, conflicts=%d, cost=$%.4f, duration=%.1fs",
            run_id, result.status, result.price_conflicts_found,
            result.total_cost_usd, result.duration_s,
        )
        return result

    # ── Step 1: INGEST ───────────────────────────────────────────────────

    async def _step_ingest(self, run_id: str) -> StepResult:
        """Fetch Agmarknet + eNAM + NASA POWER data."""
        t0 = time.time()
        errors = []

        try:
            async def _ingest_agmarknet():
                try:
                    self._agmarknet_prices = await fetch_mandi_prices(
                        MANDIS, COMMODITIES, days_back=self.days_back,
                    )
                except Exception as e:
                    errors.append(f"Agmarknet fetch failed: {e}")

            async def _ingest_enam():
                try:
                    self._enam_prices = await fetch_enam_prices(
                        MANDIS, COMMODITIES, days_back=min(14, self.days_back),
                    )
                except Exception as e:
                    errors.append(f"eNAM fetch failed: {e}")

            async def _ingest_climate():
                try:
                    climate_results = await fetch_all_mandis_nasa_power(
                        MANDIS, days_back=self.days_back,
                    )
                    for mid, readings in climate_results.items():
                        self._climate[mid] = [
                            {
                                "mandi_id": r.mandi_id,
                                "date": r.date,
                                "precip_mm": r.precip_mm,
                                "temp_mean_c": r.temp_mean_c,
                                "temp_max_c": r.temp_max_c,
                                "temp_min_c": r.temp_min_c,
                                "humidity_pct": r.humidity_pct,
                                "data_quality": r.data_quality,
                            }
                            for r in readings
                        ]
                except Exception as e:
                    errors.append(f"NASA POWER fetch failed: {e}")

            await asyncio.gather(
                _ingest_agmarknet(), _ingest_enam(), _ingest_climate(),
            )

            total_agm = sum(len(v) for v in self._agmarknet_prices.values())
            total_enam = sum(len(v) for v in self._enam_prices.values())
            total_climate = sum(len(v) for v in self._climate.values())

            status = "ok" if not errors else "partial"
            return StepResult(
                step="ingest", status=status, duration_s=time.time() - t0,
                records_processed=total_agm + total_enam + total_climate,
                errors=errors,
                details={
                    "mandis": len(MANDIS),
                    "agmarknet_records": total_agm,
                    "enam_records": total_enam,
                    "climate_readings": total_climate,
                },
            )
        except Exception as e:
            logger.exception("Ingestion step failed: %s", e)
            return StepResult(
                step="ingest", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # ── Step 2: EXTRACT ──────────────────────────────────────────────────

    async def _step_extract(self, run_id: str) -> StepResult:
        """Normalize and validate price data."""
        t0 = time.time()
        errors = []

        try:
            extractor = RuleBasedExtractor()

            for mandi in MANDIS:
                mid = mandi.mandi_id
                agm_records = [
                    {
                        "commodity_id": r.commodity_id,
                        "commodity_name": COMMODITY_MAP.get(r.commodity_id, {}).get("agmarknet_name", ""),
                        "date": r.date,
                        "min_price_rs": r.min_price_rs,
                        "max_price_rs": r.max_price_rs,
                        "modal_price_rs": r.modal_price_rs,
                        "arrivals_tonnes": r.arrivals_tonnes,
                        "source": r.source,
                        "quality_flag": r.quality_flag,
                    }
                    for r in self._agmarknet_prices.get(mid, [])
                ]
                enam_records = [
                    {
                        "commodity_id": r.commodity_id,
                        "commodity_name": COMMODITY_MAP.get(r.commodity_id, {}).get("agmarknet_name", ""),
                        "date": r.date,
                        "min_price_rs": r.min_price_rs,
                        "max_price_rs": r.max_price_rs,
                        "modal_price_rs": r.modal_price_rs,
                        "arrivals_tonnes": r.arrivals_tonnes,
                        "source": r.source,
                        "quality_flag": r.quality_flag,
                    }
                    for r in self._enam_prices.get(mid, [])
                ]

                all_records = agm_records + enam_records
                if all_records:
                    result = extractor.extract_prices(all_records, mid)
                    self._extracted_data[mid] = {
                        "mandi_id": mid,
                        "normalized_count": len(result.normalized_prices),
                        "stale_count": len(result.stale_entries),
                        "anomaly_count": len(result.anomalies),
                        "confidence": result.confidence,
                        "method": result.extraction_method,
                    }

            total_extracted = sum(
                v.get("normalized_count", 0) for v in self._extracted_data.values()
            )

            est_cost = self._extraction_tokens * 0.005 / 1000

            return StepResult(
                step="extract", status="ok" if not errors else "partial",
                duration_s=time.time() - t0,
                records_processed=total_extracted,
                errors=errors,
                details={
                    "extractor": "rule_based",
                    "mandis_extracted": len(self._extracted_data),
                    "total_records": total_extracted,
                    "total_tokens": self._extraction_tokens,
                    "cost_usd": est_cost,
                },
            )
        except Exception as e:
            logger.exception("Extraction step failed: %s", e)
            return StepResult(
                step="extract", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # ── Step 3: RECONCILE ────────────────────────────────────────────────

    async def _step_reconcile(self, run_id: str) -> StepResult:
        """Resolve Agmarknet vs eNAM price conflicts."""
        t0 = time.time()
        errors = []

        try:
            reconciler = RuleBasedReconciler()

            for mandi in MANDIS:
                mid = mandi.mandi_id

                # Build latest prices by commodity from each source
                agm_latest = self._latest_prices_by_commodity(
                    self._agmarknet_prices.get(mid, []),
                )
                enam_latest = self._latest_prices_by_commodity(
                    self._enam_prices.get(mid, []),
                )

                result = reconciler.reconcile(mid, agm_latest, enam_latest)
                self._reconciled_data[mid] = result.reconciled_prices

                for conflict in result.conflicts_found:
                    conflict["mandi_id"] = mid
                    conflict["mandi_name"] = mandi.name
                    self._price_conflicts.append(conflict)

            total_conflicts = len(self._price_conflicts)
            est_cost = self._reconciliation_tokens * 0.005 / 1000

            return StepResult(
                step="reconcile", status="ok" if not errors else "partial",
                duration_s=time.time() - t0,
                records_processed=len(self._reconciled_data),
                errors=errors,
                details={
                    "reconciler": "rule_based",
                    "mandis_reconciled": len(self._reconciled_data),
                    "total_conflicts": total_conflicts,
                    "total_tokens": self._reconciliation_tokens,
                    "cost_usd": est_cost,
                },
            )
        except Exception as e:
            logger.exception("Reconciliation step failed: %s", e)
            return StepResult(
                step="reconcile", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    def _latest_prices_by_commodity(
        self, records: list[PriceRecord],
    ) -> dict[str, dict]:
        """Get the latest price for each commodity from a list of PriceRecords."""
        latest: dict[str, dict] = {}
        for r in records:
            existing = latest.get(r.commodity_id)
            if existing is None or r.date > existing.get("date", ""):
                latest[r.commodity_id] = {
                    "commodity_id": r.commodity_id,
                    "date": r.date,
                    "min_price_rs": r.min_price_rs,
                    "max_price_rs": r.max_price_rs,
                    "modal_price_rs": r.modal_price_rs,
                    "arrivals_tonnes": r.arrivals_tonnes,
                    "source": r.source,
                    "quality_flag": r.quality_flag,
                }
        return latest

    # ── Step 4: FORECAST ─────────────────────────────────────────────────

    async def _step_forecast(self, run_id: str) -> StepResult:
        """Price forecasting at 7/14/30 day horizons."""
        t0 = time.time()

        try:
            import pandas as pd
            import numpy as np
            from src.forecasting.price_model import _days_since_harvest, _days_until_harvest, MARKET_TYPE_ENC, CATEGORY_ENC

            # Build feature DataFrame from reconciled prices
            rows = []
            today = date.today()

            for mandi in MANDIS:
                mid = mandi.mandi_id
                mandi_prices = self._reconciled_data.get(mid, {})

                for commodity in COMMODITIES:
                    cid = commodity["id"]
                    if cid not in mandi.commodities_traded:
                        continue

                    price_data = mandi_prices.get(cid, {})
                    current_price = price_data.get("price_rs", 0)
                    if current_price <= 0:
                        current_price = BASE_PRICES_RS.get(cid, 0) * SEASONAL_INDICES.get(cid, {}).get(today.month, 1.0)

                    # Compute features from historical data
                    agm_records = [r for r in self._agmarknet_prices.get(mid, []) if r.commodity_id == cid]
                    prices = [r.modal_price_rs for r in sorted(agm_records, key=lambda x: x.date)]

                    trend_7 = float(np.polyfit(range(len(prices[-7:])), prices[-7:], 1)[0]) if len(prices) >= 7 else 0
                    trend_14 = float(np.polyfit(range(len(prices[-14:])), prices[-14:], 1)[0]) if len(prices) >= 14 else 0
                    trend_30 = float(np.polyfit(range(len(prices[-30:])), prices[-30:], 1)[0]) if len(prices) >= 30 else 0

                    vol_30 = float(np.std(prices[-30:]) / np.mean(prices[-30:])) if len(prices) >= 30 and np.mean(prices[-30:]) > 0 else 0.05

                    harvest_months = []
                    for hw in commodity.get("harvest_windows", []):
                        harvest_months.extend(hw.get("months", []))

                    # Average arrivals over recent records
                    arrivals = [r.arrivals_tonnes for r in agm_records[-7:]]
                    avg_arrivals = sum(arrivals) / len(arrivals) if arrivals else mandi.avg_daily_arrivals_tonnes * 0.5

                    # Climate averages
                    climate_records = self._climate.get(mid, [])
                    recent_climate = climate_records[-7:] if climate_records else []
                    avg_rainfall = sum(c.get("precip_mm", 0) or 0 for c in recent_climate) / max(1, len(recent_climate))
                    avg_temp = sum(c.get("temp_mean_c", 28) or 28 for c in recent_climate) / max(1, len(recent_climate))

                    rows.append({
                        "mandi_id": mid,
                        "commodity_id": cid,
                        "current_reconciled_price": current_price,
                        "price_trend_7d": round(trend_7, 2),
                        "price_trend_14d": round(trend_14, 2),
                        "price_trend_30d": round(trend_30, 2),
                        "price_volatility_30d": round(vol_30, 4),
                        "seasonal_index": SEASONAL_INDICES.get(cid, {}).get(today.month, 1.0),
                        "days_since_harvest": _days_since_harvest(today, harvest_months),
                        "days_until_next_harvest": _days_until_harvest(today, harvest_months),
                        "mandi_arrival_volume_7d_avg": round(avg_arrivals, 1),
                        "rainfall_7d": round(avg_rainfall, 1),
                        "temperature_7d_avg": round(avg_temp, 1),
                        "month_sin": round(math.sin(2 * math.pi * today.month / 12), 4),
                        "month_cos": round(math.cos(2 * math.pi * today.month / 12), 4),
                        "commodity_category_encoded": CATEGORY_ENC.get(commodity["category"], 0),
                        "mandi_market_type_encoded": MARKET_TYPE_ENC.get(mandi.market_type, 0),
                    })

            if not rows:
                return StepResult(
                    step="forecast", status="skipped", duration_s=time.time() - t0,
                    errors=["No price data to forecast"],
                )

            features_df = pd.DataFrame(rows)

            # Train or load model
            model = XGBoostPriceModel()
            model_type = "seasonal_baseline"

            try:
                model.load()
                model_type = "xgboost"
                logger.info("Loaded pre-trained XGBoost price model")
            except (FileNotFoundError, Exception):
                logger.info("No pre-trained model -- training on synthetic data")
                try:
                    training_df = generate_training_data(months_back=6, seed=42)
                    model.train(training_df)
                    model.save()
                    model_type = "xgboost"
                except Exception as exc:
                    logger.warning("XGBoost training failed: %s -- using seasonal baseline", exc)

            self._forecasts = model.predict(features_df)
            self._model_metrics = {
                "model_type": model_type,
                **model.metrics,
                "features": model.FEATURES,
                "feature_importances": model.feature_importances,
            }

            # Build forecast lookup: mandi_id -> {commodity_id -> forecast_dict}
            for fc in self._forecasts:
                mid = fc.mandi_id
                cid = fc.commodity_id
                if mid not in self._forecast_by_mandi:
                    self._forecast_by_mandi[mid] = {}
                self._forecast_by_mandi[mid][cid] = {
                    "price_7d": fc.price_7d,
                    "price_14d": fc.price_14d,
                    "price_30d": fc.price_30d,
                    "ci_lower_7d": fc.ci_lower_7d,
                    "ci_upper_7d": fc.ci_upper_7d,
                    "direction": fc.direction,
                    "confidence": fc.confidence,
                }

            return StepResult(
                step="forecast", status="ok", duration_s=time.time() - t0,
                records_processed=len(self._forecasts),
                details={
                    "total_forecasts": len(self._forecasts),
                    "model_type": model_type,
                    "mandis": len(set(fc.mandi_id for fc in self._forecasts)),
                },
            )
        except Exception as e:
            logger.exception("Forecasting step failed: %s", e)
            return StepResult(
                step="forecast", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # ── Step 5: OPTIMIZE ─────────────────────────────────────────────────

    async def _step_optimize(self, run_id: str) -> StepResult:
        """Compute sell options for sample farmer locations."""
        t0 = time.time()

        try:
            for farmer in SAMPLE_FARMERS:
                rec = optimize_sell(
                    farmer_lat=farmer.latitude,
                    farmer_lon=farmer.longitude,
                    commodity_id=farmer.primary_commodity,
                    quantity_quintals=farmer.quantity_quintals,
                    reconciled_prices=self._reconciled_data,
                    forecasted_prices=self._forecast_by_mandi,
                )
                rec_dict = recommendation_to_dict(rec)

                # Credit readiness — farmer-facing assessment
                credit = assess_credit_readiness(
                    rec,
                    has_storage=farmer.has_storage,
                )
                rec_dict["credit_readiness"] = credit_readiness_to_dict(credit)

                self._sell_recommendations[farmer.farmer_id] = rec_dict
                self._sell_recommendations[farmer.farmer_id]["farmer_id"] = farmer.farmer_id
                self._sell_recommendations[farmer.farmer_id]["farmer_name"] = farmer.name

            total_options = sum(
                len(v.get("all_options", []))
                for v in self._sell_recommendations.values()
            )

            return StepResult(
                step="optimize", status="ok", duration_s=time.time() - t0,
                records_processed=len(self._sell_recommendations),
                details={
                    "farmers_optimized": len(self._sell_recommendations),
                    "total_options_computed": total_options,
                },
            )
        except Exception as e:
            logger.exception("Optimization step failed: %s", e)
            return StepResult(
                step="optimize", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # ── Step 6: RECOMMEND ────────────────────────────────────────────────

    async def _step_recommend(self, run_id: str) -> StepResult:
        """Generate Claude-powered sell recommendations."""
        t0 = time.time()
        errors = []

        try:
            agent = RecommendationAgent()

            for farmer in SAMPLE_FARMERS:
                try:
                    sell_rec = self._sell_recommendations.get(farmer.farmer_id, {})
                    rec = agent.recommend(
                        farmer=farmer,
                        reconciled_prices=self._reconciled_data,
                        forecasted_prices=self._forecast_by_mandi,
                        sell_recommendation=sell_rec,
                        climate_data=self._climate,
                    )
                    self._farmer_recommendations.append(rec)
                    self._recommendation_tokens += rec.tokens_used
                except Exception as exc:
                    errors.append(f"Recommendation for {farmer.name} failed: {exc}")

            est_cost = self._recommendation_tokens * 0.005 / 1000

            return StepResult(
                step="recommend", status="ok" if not errors else "partial",
                duration_s=time.time() - t0,
                records_processed=len(self._farmer_recommendations),
                errors=errors,
                details={
                    "recommendations_generated": len(self._farmer_recommendations),
                    "total_tokens": self._recommendation_tokens,
                    "cost_usd": est_cost,
                },
            )
        except Exception as e:
            logger.exception("Recommendation step failed: %s", e)
            return StepResult(
                step="recommend", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # ── Finalize ─────────────────────────────────────────────────────────

    def _finalize(
        self, run_id: str, started_at: datetime,
        steps: list[StepResult], status: str | None = None,
        total_cost: float = 0,
    ) -> PipelineRunResult:
        ended_at = datetime.now(timezone.utc)
        duration = (ended_at - started_at).total_seconds()

        if status is None:
            failed = sum(1 for s in steps if s.status == "failed")
            partial = sum(1 for s in steps if s.status == "partial")
            if failed > 1:
                status = "failed"
            elif failed > 0 or partial > 0:
                status = "partial"
            else:
                status = "ok"

        return PipelineRunResult(
            run_id=run_id,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            status=status,
            steps=steps,
            mandis_processed=len(self._reconciled_data) or len(MANDIS),
            commodities_tracked=len(COMMODITIES),
            price_conflicts_found=len(self._price_conflicts),
            total_cost_usd=total_cost,
            duration_s=duration,
        )

    def _update_store(self, result: PipelineRunResult):
        """Push pipeline results to the shared store for the API."""
        try:
            mandis = []
            for m in MANDIS:
                rec = self._reconciled_data.get(m.mandi_id, {})
                mandis.append({
                    "mandi_id": m.mandi_id,
                    "name": m.name,
                    "district": m.district,
                    "state": m.state,
                    "latitude": m.latitude,
                    "longitude": m.longitude,
                    "market_type": m.market_type,
                    "enam_integrated": m.enam_integrated,
                    "reporting_quality": m.reporting_quality,
                    "commodities_traded": m.commodities_traded,
                    "commodities_with_prices": len(rec),
                })

            # Market prices (reconciled)
            market_prices = []
            today_str = date.today().isoformat()
            for mid, commodities in self._reconciled_data.items():
                mandi = MANDI_MAP.get(mid)
                for cid, price_data in commodities.items():
                    commodity = COMMODITY_MAP.get(cid, {})
                    reconciled = price_data.get("price_rs", 0)
                    market_prices.append({
                        "mandi_id": mid,
                        "mandi_name": mandi.name if mandi else mid,
                        "commodity_id": cid,
                        "commodity_name": commodity.get("name", cid),
                        "category": commodity.get("category", ""),
                        "price_rs": reconciled,
                        "agmarknet_price_rs": price_data.get("agmarknet_price"),
                        "enam_price_rs": price_data.get("enam_price"),
                        "reconciled_price_rs": reconciled,
                        "confidence": price_data.get("confidence", 0),
                        "price_trend": "flat",
                        "date": today_str,
                        "source_used": price_data.get("source_used", ""),
                        "reasoning": price_data.get("reasoning", ""),
                    })

            # Build forecast direction lookup for price_trend
            forecast_dir = {}
            for fc in self._forecasts:
                forecast_dir[(fc.mandi_id, fc.commodity_id)] = fc.direction
            # Back-fill price_trend on market_prices
            for mp in market_prices:
                mp["price_trend"] = forecast_dir.get(
                    (mp["mandi_id"], mp["commodity_id"]), "flat"
                )

            # Price forecasts
            price_forecasts = []
            for fc in self._forecasts:
                commodity = COMMODITY_MAP.get(fc.commodity_id, {})
                mandi = MANDI_MAP.get(fc.mandi_id)
                price_forecasts.append({
                    "mandi_id": fc.mandi_id,
                    "mandi_name": mandi.name if mandi else fc.mandi_id,
                    "commodity_id": fc.commodity_id,
                    "commodity_name": commodity.get("name", fc.commodity_id),
                    "current_price_rs": fc.current_price,
                    "price_7d": fc.price_7d,
                    "price_14d": fc.price_14d,
                    "price_30d": fc.price_30d,
                    "ci_lower_7d": fc.ci_lower_7d,
                    "ci_upper_7d": fc.ci_upper_7d,
                    "direction": fc.direction,
                    "confidence": fc.confidence,
                })

            # Sell recommendations
            sell_recs = list(self._sell_recommendations.values())

            # Recommendation reasoning
            rec_reasoning = []
            for rec in self._farmer_recommendations:
                rec_reasoning.append({
                    "farmer_id": rec.farmer_id,
                    "farmer_name": rec.farmer_name,
                    "recommendation_en": rec.recommendation_en,
                    "reasoning_trace": rec.reasoning_trace,
                    "tokens_used": rec.tokens_used,
                })

            run_info = {
                "run_id": result.run_id,
                "started_at": result.started_at,
                "ended_at": result.ended_at,
                "status": result.status,
                "duration_s": round(result.duration_s, 1),
                "mandis_processed": result.mandis_processed,
                "commodities_tracked": result.commodities_tracked,
                "price_conflicts_found": result.price_conflicts_found,
                "total_cost_usd": round(result.total_cost_usd, 4),
                "steps": [
                    {
                        "step": s.step,
                        "status": s.status,
                        "duration_s": round(s.duration_s, 1),
                    }
                    for s in result.steps
                ],
            }

            run_data = {
                "mandis": mandis,
                "market_prices": market_prices,
                "price_forecasts": price_forecasts,
                "sell_recommendations": sell_recs,
                "price_conflicts": self._price_conflicts,
                "run_info": run_info,
                "raw_inputs": {
                    "agmarknet_mandis": len(self._agmarknet_prices),
                    "enam_mandis": len(self._enam_prices),
                    "climate_mandis": len(self._climate),
                },
                "extracted_data": self._extracted_data,
                "reconciliation_results": self._reconciled_data,
                "model_metrics": self._model_metrics,
                "recommendation_reasoning": rec_reasoning,
            }

            store.update(run_data)
            persistence.save_pipeline_run(run_data)

        except Exception:
            logger.exception("Failed to update store from pipeline")


def run_pipeline_sync(**kwargs) -> PipelineRunResult:
    """Synchronous wrapper for the pipeline."""
    pipeline = MarketIntelligencePipeline(**kwargs)
    return asyncio.run(pipeline.run())
