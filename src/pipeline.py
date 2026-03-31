"""
Health Supply Chain Optimizer -- Main Pipeline Orchestrator

6-step pipeline: INGEST -> EXTRACT -> RECONCILE -> FORECAST -> OPTIMIZE -> RECOMMEND

Each step has independent fallbacks -- no cascading failures.
Follows the same StepResult/PipelineRunResult pattern as climate-risk-engine.
"""

import asyncio
import json
import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

from config import (
    FACILITIES,
    FACILITY_MAP,
    DRUG_MAP,
    ESSENTIAL_MEDICINES,
    PIPELINE_STEPS,
    DEFAULT_PARAMS,
)
from src.ingestion.nasa_power import fetch_all_facilities_nasa_power, DailyReading
from src.ingestion.lmis_simulator import simulate_all_facilities, StockReading, _get_season
from src.forecasting.demand import forecast_demand, forecast_to_dicts, DemandForecast
from src.forecasting.model import XGBoostDemandModel, FACILITY_TYPE_ENC, CATEGORY_ENC
from src.forecasting.residual_model import ResidualCorrectionModel
from src.forecasting.chronos_model import (
    ChronosBoltForecaster,
    build_series_from_training_data,
    ensemble_predictions,
)
from src.anomaly.detector import ConsumptionAnomalyDetector
from src.optimizer import optimize, plan_to_dict, ProcurementPlan
from src.procurement_agent import ProcurementAgent, ProcurementRecommendation
from src.store import store
from src import db as persistence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step / Pipeline result dataclasses
# ---------------------------------------------------------------------------

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
    facilities_processed: int
    drugs_tracked: int
    stockout_risks_found: int
    total_cost_usd: float
    duration_s: float


# ---------------------------------------------------------------------------
# Text input generators (stock reports, IDSR, CHW messages)
# ---------------------------------------------------------------------------

def _generate_stock_report(fac, stock_readings: list, rng: random.Random) -> str:
    """Generate a realistic unstructured stock report text for a facility."""
    fid = fac.facility_id
    drug_readings = {}
    for r in stock_readings:
        if isinstance(r, dict):
            did = r.get("drug_id", "")
            if r.get("reported") and did:
                drug_readings[did] = r
        else:
            did = getattr(r, "drug_id", "")
            if getattr(r, "reported", False) and did:
                drug_readings[did] = {
                    "drug_id": did,
                    "stock_level": getattr(r, "stock_level", 0),
                    "consumption_today": getattr(r, "consumption_today", 0),
                    "days_of_stock_remaining": getattr(r, "days_of_stock_remaining", 0),
                }

    lines = [
        f"MONTHLY STOCK REPORT - {fac.name}",
        f"District: {fac.district}, {fac.country}",
        f"Date: {datetime.utcnow().strftime('%d %B %Y')}",
        f"Prepared by: {fac.name} Pharmacist",
        "",
        "CURRENT STOCK STATUS:",
    ]

    for did, r in list(drug_readings.items())[:8]:
        drug = DRUG_MAP.get(did)
        if drug:
            stock = r.get("stock_level", 0) or 0
            dos = r.get("days_of_stock_remaining", 0) or 0
            status = "ADEQUATE" if dos > 30 else "LOW" if dos > 7 else "CRITICAL"
            lines.append(
                f"  {drug['name']}: {stock:.0f} {drug['unit']} on hand, "
                f"~{dos:.0f} days supply. Status: {status}"
            )

    # Add some narrative
    critical_drugs = [
        did for did, r in drug_readings.items()
        if (r.get("days_of_stock_remaining") or 999) < 14 and DRUG_MAP.get(did, {}).get("critical")
    ]
    if critical_drugs:
        names = [DRUG_MAP[d]["name"] for d in critical_drugs if d in DRUG_MAP]
        lines.append(f"\nURGENT: {', '.join(names)} at critically low levels. "
                      "Request emergency resupply.")

    if fac.reporting_quality == "poor":
        lines.append("\nNote: Some stock counts may be approximate. "
                      "Physical count delayed due to staffing shortages.")

    lines.append(f"\nTotal drugs tracked: {len(drug_readings)}")
    lines.append(f"Cold chain status: {'Functional' if fac.has_cold_chain else 'Not available'}")
    return "\n".join(lines)


def _generate_idsr_report(fac, rng: random.Random) -> str:
    """Generate a realistic IDSR (Integrated Disease Surveillance & Response) report."""
    pop = fac.population_served
    malaria_cases = rng.randint(int(pop * 0.002), int(pop * 0.008))
    diarrhoea_cases = rng.randint(int(pop * 0.001), int(pop * 0.005))
    ari_cases = rng.randint(int(pop * 0.001), int(pop * 0.004))
    measles_cases = rng.randint(0, 3)

    lines = [
        f"IDSR WEEKLY EPIDEMIOLOGICAL REPORT",
        f"Facility: {fac.name}",
        f"District: {fac.district}, {fac.country}",
        f"Week: {datetime.utcnow().strftime('W%W %Y')}",
        "",
        "REPORTABLE DISEASE CASES THIS WEEK:",
        f"  Malaria (confirmed + clinical): {malaria_cases}",
        f"  Acute watery diarrhoea: {diarrhoea_cases}",
        f"  Acute respiratory infections: {ari_cases}",
        f"  Measles (suspected): {measles_cases}",
        "",
        f"MALARIA POSITIVITY RATE: {rng.randint(25, 65)}%",
        f"TOTAL OPD ATTENDANCE: {rng.randint(int(pop * 0.005), int(pop * 0.015))}",
    ]

    if malaria_cases > pop * 0.005:
        lines.append("\nALERT: Malaria cases above epidemic threshold. "
                      "Increased ACT and RDT consumption expected.")

    if diarrhoea_cases > pop * 0.003:
        lines.append("\nALERT: Diarrhoea cluster detected. Possible contaminated water source. "
                      "ORS and Zinc demand increasing.")

    return "\n".join(lines)


def _generate_chw_messages(fac, rng: random.Random) -> list[str]:
    """Generate realistic CHW (Community Health Worker) text messages."""
    templates = [
        "ORS finished in ward {ward}. {n} children with diarrhoea this week. Pls resupply urgent",
        "Malaria cases increasing. Used {n} RDTs today, only {rem} left. Need more ACT too",
        "Paracetamol and amoxicillin running low. {n} patients turned away today",
        "Cold chain fridge broken since Monday. Oxytocin may be compromised",
        "Stock count done. ACT-20: {stock} courses, ORS: {ors} sachets. Both below minimum",
        "Community health outreach tomorrow. Need extra Zinc and ORS for under-5 program",
        "3 suspected malaria cases referred to facility. No RDTs available in community",
        "Monthly CHW report: served {n} households. Main complaints: fever, diarrhoea, cough",
    ]

    n_messages = min(fac.chw_count, rng.randint(2, 5))
    messages = []
    for i in range(n_messages):
        template = rng.choice(templates)
        msg = template.format(
            ward=rng.randint(1, 8),
            n=rng.randint(3, 25),
            rem=rng.randint(2, 15),
            stock=rng.randint(5, 50),
            ors=rng.randint(10, 80),
        )
        messages.append(f"CHW-{fac.facility_id}-{i+1}: {msg}")
    return messages


def generate_all_inputs(
    facilities=None,
    stock_by_facility: dict | None = None,
    seed: int = 42,
) -> dict:
    """Generate all text inputs (stock reports, IDSR, CHW messages) for all facilities.

    Returns a dict keyed by facility_id with sub-keys:
        stock_report, idsr_report, chw_messages
    """
    if facilities is None:
        facilities = FACILITIES
    rng = random.Random(seed)

    result = {}
    for fac in facilities:
        fid = fac.facility_id
        stock_readings = (stock_by_facility or {}).get(fid, [])
        result[fid] = {
            "stock_report": _generate_stock_report(fac, stock_readings, rng),
            "idsr_report": _generate_idsr_report(fac, rng),
            "chw_messages": _generate_chw_messages(fac, rng),
        }
    return result


# ---------------------------------------------------------------------------
# Regex-based extraction fallback
# ---------------------------------------------------------------------------

def _regex_extract(raw_inputs: dict) -> dict:
    """Regex-based extraction of structured data from text inputs.

    Extracts drug stock levels from stock reports and disease cases from IDSR.
    Used as fallback when Claude extraction agent is unavailable.
    """
    import re
    extracted = {}

    for fid, inputs in raw_inputs.items():
        fac_data = {"facility_id": fid, "drugs": {}, "disease_cases": {}, "alerts": []}

        # Parse stock report
        report = inputs.get("stock_report", "")
        for drug in ESSENTIAL_MEDICINES:
            pattern = re.escape(drug["name"]) + r":\s*([\d,.]+)\s*\w+\s*on hand.*?~([\d,.]+)\s*days"
            match = re.search(pattern, report)
            if match:
                stock_level = float(match.group(1).replace(",", ""))
                days_supply = float(match.group(2).replace(",", ""))
                fac_data["drugs"][drug["drug_id"]] = {
                    "stock_level": stock_level,
                    "days_of_stock": days_supply,
                    "source": "stock_report",
                }

        # Parse IDSR report
        idsr = inputs.get("idsr_report", "")
        malaria_match = re.search(r"Malaria.*?:\s*(\d+)", idsr)
        if malaria_match:
            fac_data["disease_cases"]["malaria"] = int(malaria_match.group(1))
        diarrhoea_match = re.search(r"diarrhoea.*?:\s*(\d+)", idsr, re.IGNORECASE)
        if diarrhoea_match:
            fac_data["disease_cases"]["diarrhoea"] = int(diarrhoea_match.group(1))
        ari_match = re.search(r"respiratory.*?:\s*(\d+)", idsr, re.IGNORECASE)
        if ari_match:
            fac_data["disease_cases"]["ari"] = int(ari_match.group(1))

        # Parse CHW messages for urgency signals
        for msg in inputs.get("chw_messages", []):
            if any(kw in msg.lower() for kw in ["urgent", "finished", "broken", "no rdt"]):
                fac_data["alerts"].append(msg)

        extracted[fid] = fac_data

    return extracted


# ---------------------------------------------------------------------------
# Simple reconciliation fallback
# ---------------------------------------------------------------------------

def _simple_reconcile(
    extracted_data: dict,
    stock_by_facility: dict,
) -> dict:
    """Rule-based reconciliation: cross-validate extracted vs. simulated stock data.

    Returns reconciled data with conflict log per facility.
    """
    reconciled = {}

    for fid, extracted in extracted_data.items():
        conflicts = []
        stock_by_drug = {}

        # Start from simulated/ingested stock data as baseline
        sim_readings = stock_by_facility.get(fid, [])
        latest_by_drug: dict[str, dict] = {}
        for r in sim_readings:
            if isinstance(r, dict):
                did = r.get("drug_id", "")
                reported = r.get("reported", False)
            else:
                did = getattr(r, "drug_id", "")
                reported = getattr(r, "reported", False)

            if not reported or not did:
                continue

            if isinstance(r, dict):
                rdata = r
            else:
                rdata = {
                    "drug_id": did,
                    "stock_level": getattr(r, "stock_level", 0),
                    "consumption_today": getattr(r, "consumption_today", 0),
                    "days_of_stock_remaining": getattr(r, "days_of_stock_remaining", 0),
                }

            if did not in latest_by_drug:
                latest_by_drug[did] = rdata
            else:
                existing_date = latest_by_drug[did].get("date", "")
                new_date = rdata.get("date", "")
                if new_date > existing_date:
                    latest_by_drug[did] = rdata

        # Reconcile with extracted values
        for did, sim_data in latest_by_drug.items():
            drug = DRUG_MAP.get(did)
            if not drug:
                continue

            sim_stock = sim_data.get("stock_level", 0) or 0
            sim_daily = sim_data.get("consumption_today", 0) or 0
            sim_dos = sim_data.get("days_of_stock_remaining", 0) or 0

            ext_drug = extracted.get("drugs", {}).get(did, {})
            ext_stock = ext_drug.get("stock_level")

            final_stock = sim_stock
            final_daily = sim_daily

            # If extracted value exists, check for conflict
            if ext_stock is not None and abs(ext_stock - sim_stock) > sim_stock * 0.20:
                conflicts.append({
                    "drug_id": did,
                    "drug_name": drug["name"],
                    "field": "stock_level",
                    "simulated_value": sim_stock,
                    "extracted_value": ext_stock,
                    "resolution": "averaged",
                    "reasoning": (
                        f"Stock report says {ext_stock:.0f} but LMIS shows {sim_stock:.0f}. "
                        f"Difference is >{20}%. Using average as reconciled value."
                    ),
                })
                final_stock = (sim_stock + ext_stock) / 2

            # Negative stock correction
            if final_stock < 0:
                conflicts.append({
                    "drug_id": did,
                    "drug_name": drug["name"],
                    "field": "stock_level",
                    "original_value": final_stock,
                    "corrected_value": 0,
                    "resolution": "corrected",
                    "reasoning": "Negative stock corrected to 0",
                })
                final_stock = 0

            final_dos = final_stock / final_daily if final_daily > 0 else 999

            stock_by_drug[did] = {
                "stock_level": round(final_stock, 1),
                "consumption_daily": round(final_daily, 1),
                "days_of_stock_remaining": round(final_dos, 1),
                "source": "reconciled",
            }

        reconciled[fid] = {
            "facility_id": fid,
            "stock_by_drug": stock_by_drug,
            "conflicts": conflicts,
            "disease_cases": extracted.get("disease_cases", {}),
            "quality_score": max(0.5, 1.0 - len(conflicts) * 0.05),
        }

    return reconciled


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class HealthSupplyChainPipeline:
    """
    End-to-end health supply chain optimization pipeline.

    Step 1 (INGEST):     Generate text inputs + fetch NASA POWER climate data
    Step 2 (EXTRACT):    Extract structured data from stock reports, IDSR, CHW messages
    Step 3 (RECONCILE):  Cross-validate and reconcile data sources
    Step 4 (FORECAST):   Climate -> disease -> drug demand prediction
    Step 5 (OPTIMIZE):   Claude cross-facility procurement agent (or greedy fallback)
    Step 6 (RECOMMEND):  Generate alerts and recommendations
    """

    def __init__(
        self,
        days_back: int = 90,
        use_claude_extraction: bool = True,
        use_claude_reconciliation: bool = True,
        use_claude_optimizer: bool = True,
        use_claude_recommender: bool = True,
        planning_months: int = 3,
    ):
        self.days_back = days_back
        self.use_claude_extraction = use_claude_extraction
        self.use_claude_reconciliation = use_claude_reconciliation
        self.use_claude_optimizer = use_claude_optimizer
        self.use_claude_recommender = use_claude_recommender
        self.planning_months = planning_months

        # Pipeline state
        self._raw_inputs: dict = {}
        self._climate: dict[str, list] = {}
        self._stock: dict[str, list] = {}
        self._extracted_data: dict = {}
        self._reconciled_data: dict = {}
        self._forecasts: dict[str, list[DemandForecast]] = {}
        self._forecast_dicts: list[dict] = []
        self._procurement: ProcurementRecommendation | None = None
        self._procurement_plans: dict[str, ProcurementPlan] = {}
        self._alerts: list[dict] = []
        self._model_metrics: dict = {}
        self._rag_retrievals: list[dict] = []

        # Token/cost tracking per step
        self._extraction_tokens: int = 0
        self._reconciliation_tokens: int = 0
        self._optimization_tokens: int = 0
        self._recommendation_tokens: int = 0

    async def run(self) -> PipelineRunResult:
        """Execute the full 6-step pipeline."""
        run_id = str(uuid.uuid4())[:8]
        started_at = datetime.utcnow()

        # Initialize database if configured
        persistence.init_db()
        steps: list[StepResult] = []
        total_cost = 0.0

        logger.info(
            "Pipeline run %s starting -- %d facilities, %d days back",
            run_id, len(FACILITIES), self.days_back,
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
        total_cost += step5.details.get("cost_usd", 0)

        # Step 6: RECOMMEND
        step6 = await self._step_recommend(run_id)
        steps.append(step6)
        total_cost += step6.details.get("cost_usd", 0)

        result = self._finalize(run_id, started_at, steps, total_cost=total_cost)

        # Push results to the store for the API
        self._update_store(result)

        logger.info(
            "Pipeline run %s complete -- status=%s, stockouts=%d, cost=$%.4f, duration=%.1fs",
            run_id, result.status, result.stockout_risks_found,
            result.total_cost_usd, result.duration_s,
        )
        return result

    # -- Step 1: INGEST -------------------------------------------------------

    async def _step_ingest(self, run_id: str) -> StepResult:
        """Ingest text data (stock reports, IDSR, CHW messages) + NASA POWER climate."""
        t0 = time.time()
        errors = []

        try:
            # Run stock simulation + NASA POWER fetch concurrently
            # (text generation depends on stock, so it goes after simulation)
            async def _ingest_stock_and_text():
                stock_results = simulate_all_facilities(FACILITIES, days_back=self.days_back)
                for fid, readings in stock_results.items():
                    self._stock[fid] = [
                        {
                            "facility_id": r.facility_id,
                            "drug_id": r.drug_id,
                            "date": r.date,
                            "stock_level": r.stock_level,
                            "consumption_today": r.consumption_today,
                            "days_of_stock_remaining": r.days_of_stock_remaining,
                            "reported": r.reported,
                            "data_quality": r.data_quality,
                        }
                        for r in readings
                    ]
                self._raw_inputs = generate_all_inputs(
                    facilities=FACILITIES,
                    stock_by_facility=self._stock,
                )

            async def _ingest_climate():
                try:
                    climate_results = await fetch_all_facilities_nasa_power(
                        FACILITIES, days_back=self.days_back,
                    )
                    for fid, readings in climate_results.items():
                        self._climate[fid] = [
                            {
                                "facility_id": r.facility_id,
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

            await asyncio.gather(_ingest_stock_and_text(), _ingest_climate())

            total_stock_readings = sum(len(v) for v in self._stock.values())
            total_climate_readings = sum(len(v) for v in self._climate.values())

            status = "ok" if not errors else "partial"
            return StepResult(
                step="ingest", status=status, duration_s=time.time() - t0,
                records_processed=total_stock_readings + total_climate_readings,
                errors=errors,
                details={
                    "facilities": len(FACILITIES),
                    "stock_readings": total_stock_readings,
                    "climate_readings": total_climate_readings,
                    "text_inputs_generated": len(self._raw_inputs),
                },
            )
        except Exception as e:
            logger.exception(f"Ingestion step failed: {e}")
            return StepResult(
                step="ingest", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # -- Step 2: EXTRACT -------------------------------------------------------

    async def _step_extract(self, run_id: str) -> StepResult:
        """Extract structured data from stock reports, IDSR, CHW messages."""
        t0 = time.time()
        errors = []

        try:
            # For now, use regex-based extraction as the primary path.
            # Claude ExtractionAgent would be plugged in here when available.
            if self.use_claude_extraction:
                try:
                    # Placeholder for Claude extraction agent
                    raise NotImplementedError("ExtractionAgent not yet implemented")
                except Exception as exc:
                    errors.append(f"Claude extraction unavailable: {exc}")
                    logger.warning("Claude extraction unavailable: %s -- using regex", exc)

            # Regex fallback
            self._extracted_data = _regex_extract(self._raw_inputs)

            total_drugs_extracted = sum(
                len(v.get("drugs", {})) for v in self._extracted_data.values()
            )

            est_cost = self._extraction_tokens * 0.005 / 1000

            return StepResult(
                step="extract", status="ok" if not errors else "partial",
                duration_s=time.time() - t0,
                records_processed=len(self._extracted_data),
                errors=errors,
                details={
                    "extractor": "regex_fallback" if errors else "claude",
                    "facilities_extracted": len(self._extracted_data),
                    "total_drugs_extracted": total_drugs_extracted,
                    "total_tokens": self._extraction_tokens,
                    "cost_usd": est_cost,
                },
            )
        except Exception as e:
            logger.exception(f"Extraction step failed: {e}")
            return StepResult(
                step="extract", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # -- Step 3: RECONCILE -----------------------------------------------------

    async def _step_reconcile(self, run_id: str) -> StepResult:
        """Cross-validate and reconcile extracted data with LMIS + climate."""
        t0 = time.time()
        errors = []

        try:
            if self.use_claude_reconciliation:
                try:
                    raise NotImplementedError("ReconciliationAgent not yet implemented")
                except Exception as exc:
                    errors.append(f"Claude reconciliation unavailable: {exc}")
                    logger.warning("Claude reconciliation unavailable: %s -- using rules", exc)

            # Rule-based fallback
            self._reconciled_data = _simple_reconcile(
                self._extracted_data,
                self._stock,
            )

            total_conflicts = sum(
                len(v.get("conflicts", [])) for v in self._reconciled_data.values()
            )
            avg_quality = sum(
                v.get("quality_score", 0) for v in self._reconciled_data.values()
            ) / max(1, len(self._reconciled_data))

            est_cost = self._reconciliation_tokens * 0.005 / 1000

            return StepResult(
                step="reconcile", status="ok" if not errors else "partial",
                duration_s=time.time() - t0,
                records_processed=len(self._reconciled_data),
                errors=errors,
                details={
                    "reconciler": "rule_based" if errors else "claude",
                    "facilities_reconciled": len(self._reconciled_data),
                    "total_conflicts": total_conflicts,
                    "avg_quality_score": round(avg_quality, 3),
                    "total_tokens": self._reconciliation_tokens,
                    "cost_usd": est_cost,
                },
            )
        except Exception as e:
            logger.exception(f"Reconciliation step failed: {e}")
            return StepResult(
                step="reconcile", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # -- Step 4: FORECAST ------------------------------------------------------

    async def _step_forecast(self, run_id: str) -> StepResult:
        """Demand forecasting: epidemiological formulas + XGBoost + residual correction."""
        t0 = time.time()

        try:
            # Layer 1: Epidemiological formulas (climate -> disease -> demand)
            climate_data = self._climate if self._climate else {}
            self._forecasts = forecast_demand(
                climate_by_facility=climate_data,
                stock_by_facility=self._stock,
                planning_months=self.planning_months,
            )
            self._forecast_dicts = forecast_to_dicts(self._forecasts)

            total_forecasts = sum(len(v) for v in self._forecasts.values())
            climate_driven = sum(
                sum(1 for f in v if f.climate_driven)
                for v in self._forecasts.values()
            )

            # Layer 2: XGBoost model (load pre-trained or train on the fly)
            model_type = "epidemiological_formulas"
            xgb_model = XGBoostDemandModel()
            residual_model = ResidualCorrectionModel()
            training_df = None  # cached for reuse by residual model

            try:
                xgb_model.load()
                model_type = "xgboost"
                logger.info("Loaded pre-trained XGBoost model")
            except FileNotFoundError:
                logger.info("No pre-trained XGBoost model — training on the fly")
                training_df = xgb_model.build_training_data(months_back=6, seed=42)
                xgb_model.train(training_df)
                xgb_model.save()
                model_type = "xgboost"

            # Layer 2.5: Chronos-Bolt neural foundation model (zero-shot)
            chronos = ChronosBoltForecaster()
            chronos_preds: dict = {}
            if chronos.is_available:
                if training_df is None:
                    training_df = xgb_model.build_training_data(months_back=6, seed=42)
                series = build_series_from_training_data(training_df)
                chronos_preds = chronos.predict_batch(series, prediction_length=1)
                if chronos_preds:
                    model_type += "+chronos_bolt"
                    logger.info("Chronos-Bolt predictions: %d series", len(chronos_preds))

            # Layer 3: Residual correction (MOS pattern)
            try:
                residual_model.load()
                model_type = model_type.replace("xgboost", "xgboost+residual_correction", 1)
                logger.info("Loaded pre-trained residual correction model")
            except FileNotFoundError:
                if xgb_model.is_trained():
                    try:
                        if training_df is None:
                            training_df = xgb_model.build_training_data(months_back=6, seed=42)
                        res_df = residual_model.build_residual_data(xgb_model, training_df)
                        residual_model.train(res_df)
                        residual_model.save()
                        model_type = model_type.replace("xgboost", "xgboost+residual_correction", 1)
                    except Exception:
                        logger.warning("Residual model training failed — continuing with primary only")

            # Ensemble Chronos predictions into forecast dicts
            if chronos_preds and xgb_model.is_trained():
                for fc in self._forecast_dicts:
                    key = f"{fc['facility_id']}|{fc['drug_id']}"
                    cp = chronos_preds.get(key)
                    if not cp:
                        continue
                    # Get XGBoost prediction for this item
                    xgb_pred = fc.get("predicted_demand_monthly", fc.get("baseline_demand_monthly", 0))
                    pi = fc.get("prediction_interval", {})
                    xgb_lower = pi.get("lower", xgb_pred * 0.8)
                    xgb_upper = pi.get("upper", xgb_pred * 1.2)
                    ens = ensemble_predictions(
                        xgb_pred, xgb_lower, xgb_upper,
                        cp["median"], cp["lower_10"], cp["upper_90"],
                    )
                    fc["ensemble"] = ens
                    fc["prediction_interval"] = {
                        "lower": ens["ensemble_lower"],
                        "upper": ens["ensemble_upper"],
                    }

            # Model metrics from trained models
            self._model_metrics = {
                "model_type": model_type,
                "primary_model": xgb_model.metrics if xgb_model.is_trained() else {},
                "residual_model": residual_model.metrics if residual_model.is_trained() else {},
                "chronos_model": chronos.model_info,
                "features": list(xgb_model.feature_importances.keys()) if xgb_model.is_trained() else [],
                "feature_importances": xgb_model.feature_importances if xgb_model.is_trained() else {},
            }

            return StepResult(
                step="forecast", status="ok", duration_s=time.time() - t0,
                records_processed=total_forecasts,
                details={
                    "total_forecasts": total_forecasts,
                    "climate_driven": climate_driven,
                    "facilities": len(self._forecasts),
                    "model_type": model_type,
                },
            )
        except Exception as e:
            logger.exception(f"Forecasting step failed: {e}")
            return StepResult(
                step="forecast", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # -- Step 5: OPTIMIZE ------------------------------------------------------

    async def _step_optimize(self, run_id: str) -> StepResult:
        """Claude cross-facility procurement agent (or greedy fallback)."""
        t0 = time.time()
        errors = []

        try:
            # Build demand forecast dicts keyed by facility for the agent
            forecast_by_fac: dict[str, list] = {}
            for fc_dict in self._forecast_dicts:
                fid = fc_dict.get("facility_id")
                if fid:
                    forecast_by_fac.setdefault(fid, []).append(fc_dict)

            if self.use_claude_optimizer:
                try:
                    agent = ProcurementAgent(
                        reconciled_data=self._reconciled_data,
                        demand_forecasts=forecast_by_fac,
                    )
                    self._procurement = await agent.optimize()
                    self._optimization_tokens = self._procurement.tokens_used
                except Exception as exc:
                    errors.append(f"Claude optimizer failed: {exc}")
                    logger.warning("Claude optimizer failed: %s -- using greedy", exc)
                    agent = ProcurementAgent(
                        reconciled_data=self._reconciled_data,
                        demand_forecasts=forecast_by_fac,
                    )
                    self._procurement = agent._greedy_fallback(reason=str(exc))
            else:
                agent = ProcurementAgent(
                    reconciled_data=self._reconciled_data,
                    demand_forecasts=forecast_by_fac,
                )
                self._procurement = agent._greedy_fallback(reason="Claude optimizer disabled")

            # Also run per-facility greedy for the existing API shape
            for fac in FACILITIES:
                fid = fac.facility_id
                fac_forecasts = self._forecasts.get(fid, [])

                season = "rainy"
                for fc in fac_forecasts:
                    if fc.category == "Antimalarials" and fc.demand_multiplier > 1.0:
                        season = "rainy"
                        break
                    elif fc.category == "Antimalarials" and fc.demand_multiplier < 0.8:
                        season = "dry"
                        break

                plan = optimize(
                    population=fac.population_served,
                    budget_usd=fac.budget_usd_quarterly,
                    planning_months=self.planning_months,
                    season=season,
                    supply_source="regional_depot",
                    wastage_pct=8,
                    prioritize_critical=True,
                )
                self._procurement_plans[fid] = plan

            total_orders = sum(
                len(p.orders) for p in self._procurement_plans.values()
            )
            stockout_risks = sum(
                sum(1 for o in p.orders if o.stockout_risk in ("high", "critical"))
                for p in self._procurement_plans.values()
            )

            est_cost = self._optimization_tokens * 0.005 / 1000

            return StepResult(
                step="optimize", status="ok" if not errors else "partial",
                duration_s=time.time() - t0,
                records_processed=total_orders,
                errors=errors,
                details={
                    "optimization_method": self._procurement.optimization_method if self._procurement else "greedy_fallback",
                    "facilities_optimized": len(self._procurement_plans),
                    "total_orders": total_orders,
                    "stockout_risks": stockout_risks,
                    "redistributions": len(self._procurement.redistributions) if self._procurement else 0,
                    "total_tokens": self._optimization_tokens,
                    "cost_usd": est_cost,
                },
            )
        except Exception as e:
            logger.exception(f"Optimization step failed: {e}")
            return StepResult(
                step="optimize", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    # -- Step 6: RECOMMEND -----------------------------------------------------

    async def _step_recommend(self, run_id: str) -> StepResult:
        """Generate alerts and recommendations."""
        t0 = time.time()

        try:
            for fac in FACILITIES:
                fid = fac.facility_id
                plan = self._procurement_plans.get(fid)
                if not plan:
                    continue

                for order in plan.orders:
                    if order.stockout_risk in ("high", "critical"):
                        forecasts = self._forecasts.get(fid, [])
                        drug_forecast = next(
                            (f for f in forecasts if f.drug_id == order.drug_id),
                            None,
                        )

                        alert = {
                            "facility_id": fid,
                            "facility_name": fac.name,
                            "district": fac.district,
                            "drug_id": order.drug_id,
                            "drug_name": order.name,
                            "category": order.category,
                            "critical": order.critical,
                            "stockout_risk": order.stockout_risk,
                            "coverage_pct": order.coverage_pct,
                            "days_of_stock": order.days_of_stock,
                            "demand_qty": order.demand_qty,
                            "ordered_qty": order.ordered_qty,
                            "shortfall_qty": order.total_need - order.ordered_qty,
                            "shortfall_cost_usd": round(
                                (order.total_need - order.ordered_qty) * order.unit_cost_usd, 2,
                            ),
                            "climate_driven": drug_forecast.climate_driven if drug_forecast else False,
                            "demand_multiplier": drug_forecast.demand_multiplier if drug_forecast else 1.0,
                            "recommendation": self._generate_recommendation(
                                fac, order, drug_forecast,
                            ),
                        }
                        self._alerts.append(alert)

            est_cost = self._recommendation_tokens * 0.005 / 1000

            return StepResult(
                step="recommend", status="ok" if self._alerts else "skipped",
                duration_s=time.time() - t0,
                records_processed=len(self._alerts),
                details={
                    "alerts_generated": len(self._alerts),
                    "critical_alerts": sum(
                        1 for a in self._alerts if a["stockout_risk"] == "critical"
                    ),
                    "total_tokens": self._recommendation_tokens,
                    "cost_usd": est_cost,
                },
            )
        except Exception as e:
            logger.exception(f"Recommendation step failed: {e}")
            return StepResult(
                step="recommend", status="failed", duration_s=time.time() - t0,
                errors=[str(e)],
            )

    def _generate_recommendation(self, fac, order, forecast) -> str:
        """Generate a procurement recommendation string."""
        parts = []

        if order.stockout_risk == "critical":
            parts.append(f"URGENT: {order.name} at critically low stock.")
        else:
            parts.append(f"{order.name} at risk of stockout within {order.days_of_stock} days.")

        if forecast and forecast.climate_driven and forecast.demand_multiplier > 1.3:
            parts.append(
                f"Climate-driven demand increase ({forecast.demand_multiplier:.1f}x baseline) "
                f"due to {forecast.contributing_factors[0].get('factor', 'seasonal')} conditions."
            )

        shortfall = order.total_need - order.ordered_qty
        if shortfall > 0:
            parts.append(
                f"Budget shortfall: need {shortfall} {order.unit} "
                f"(${shortfall * order.unit_cost_usd:.2f}) beyond current allocation."
            )

        if order.critical:
            parts.append("This is a critical/essential medicine -- prioritize procurement.")

        # Add redistribution note if procurement agent found one
        if self._procurement and self._procurement.redistributions:
            for redist in self._procurement.redistributions:
                if redist.get("drug_id") == order.drug_id:
                    parts.append(
                        f"Redistribution available: {redist.get('quantity', 0)} units "
                        f"from {redist.get('from_facility', '?')} "
                        f"(transit: {redist.get('transit_days', '?')} days)."
                    )
                    break

        return " ".join(parts)

    # -- Finalize --------------------------------------------------------------

    def _finalize(
        self, run_id: str, started_at: datetime,
        steps: list[StepResult], status: str | None = None,
        total_cost: float = 0,
    ) -> PipelineRunResult:
        ended_at = datetime.utcnow()
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

        stockout_risks = sum(
            sum(1 for o in p.orders if o.stockout_risk in ("high", "critical"))
            for p in self._procurement_plans.values()
        )

        return PipelineRunResult(
            run_id=run_id,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            status=status,
            steps=steps,
            facilities_processed=len(self._reconciled_data) or len(FACILITIES),
            drugs_tracked=len(ESSENTIAL_MEDICINES),
            stockout_risks_found=stockout_risks,
            total_cost_usd=total_cost,
            duration_s=duration,
        )

    def _update_store(self, result: PipelineRunResult):
        """Push pipeline results to the shared store for the API."""
        try:
            # Build facility summaries
            facilities = []
            for fac in FACILITIES:
                fid = fac.facility_id
                rec = self._reconciled_data.get(fid, {})
                plan = self._procurement_plans.get(fid)

                facilities.append({
                    "facility_id": fid,
                    "name": fac.name,
                    "district": fac.district,
                    "country": fac.country,
                    "latitude": fac.latitude,
                    "longitude": fac.longitude,
                    "facility_type": fac.facility_type,
                    "population_served": fac.population_served,
                    "reporting_quality": fac.reporting_quality,
                    "data_quality_score": rec.get("quality_score", 0.0),
                    "budget_usd": fac.budget_usd_quarterly,
                    "budget_used_usd": plan.budget_used_usd if plan else 0,
                    "stockout_risks": (
                        sum(1 for o in plan.orders if o.stockout_risk in ("high", "critical"))
                        if plan else 0
                    ),
                })

            # Build stock levels
            stock_levels = []
            for fid, readings in self._stock.items():
                fac = FACILITY_MAP.get(fid)
                latest: dict[str, dict] = {}
                for r in readings:
                    if r.get("reported") and r.get("drug_id"):
                        did = r["drug_id"]
                        if did not in latest or r.get("date", "") > latest[did].get("date", ""):
                            latest[did] = r

                for drug_id, r in latest.items():
                    drug = DRUG_MAP.get(drug_id, {})
                    stock_levels.append({
                        "facility_id": fid,
                        "facility_name": fac.name if fac else fid,
                        "drug_id": drug_id,
                        "drug_name": drug.get("name", drug_id),
                        "category": drug.get("category", ""),
                        "stock_level": r.get("stock_level"),
                        "consumption_daily": r.get("consumption_today"),
                        "days_of_stock": r.get("days_of_stock_remaining"),
                        "date": r.get("date"),
                    })

            # Build demand forecasts
            demand_forecasts = self._forecast_dicts

            # Build procurement plans
            procurement_plans = []
            for fid, plan in self._procurement_plans.items():
                fac = FACILITY_MAP.get(fid)
                plan_dict = plan_to_dict(plan)
                plan_dict["facility_id"] = fid
                plan_dict["facility_name"] = fac.name if fac else fid
                procurement_plans.append(plan_dict)

            # Build stockout risks
            stockout_risks = []
            for fid, plan in self._procurement_plans.items():
                fac = FACILITY_MAP.get(fid)
                for order in plan.orders:
                    if order.stockout_risk in ("high", "critical", "moderate"):
                        stockout_risks.append({
                            "facility_id": fid,
                            "facility_name": fac.name if fac else fid,
                            "drug_id": order.drug_id,
                            "drug_name": order.name,
                            "category": order.category,
                            "critical": order.critical,
                            "risk_level": order.stockout_risk,
                            "coverage_pct": order.coverage_pct,
                            "days_of_stock": order.days_of_stock,
                            "shortfall_qty": order.total_need - order.ordered_qty,
                            "shortfall_cost_usd": round(
                                (order.total_need - order.ordered_qty) * order.unit_cost_usd, 2,
                            ),
                        })

            run_info = {
                "run_id": result.run_id,
                "started_at": result.started_at,
                "ended_at": result.ended_at,
                "status": result.status,
                "duration_s": round(result.duration_s, 1),
                "facilities_processed": result.facilities_processed,
                "drugs_tracked": result.drugs_tracked,
                "stockout_risks_found": result.stockout_risks_found,
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

            # Build procurement reasoning from agent
            procurement_reasoning = []
            if self._procurement:
                procurement_reasoning = self._procurement.reasoning_trace

            # Run anomaly detection on stock levels (batch scoring)
            try:
                detector = ConsumptionAnomalyDetector()
                detector.load()
                import pandas as _pd
                from datetime import date as _date
                now = datetime.utcnow()
                rows = []
                for sl in stock_levels:
                    fac = FACILITY_MAP.get(sl["facility_id"], FACILITIES[0])
                    drug = DRUG_MAP.get(sl.get("drug_id", ""), {})
                    season = _get_season(_date(now.year, now.month, 15), fac.latitude)
                    rows.append({
                        "consumption_rate_per_1000": sl.get("consumption_daily", 0) * 30,
                        "consumption_last_month": sl.get("consumption_daily", 0) * 30,
                        "consumption_trend": 1.0,
                        "population_served": fac.population_served,
                        "facility_type_encoded": FACILITY_TYPE_ENC.get(fac.facility_type, 1),
                        "drug_category_encoded": CATEGORY_ENC.get(drug.get("category", ""), 0),
                        "month": now.month,
                        "is_rainy_season": 1 if season == "rainy" else 0,
                    })
                if rows:
                    scored = detector.score_batch(_pd.DataFrame(rows))
                    for i, sl in enumerate(stock_levels):
                        sl["anomaly_score"] = float(scored["anomaly_score"].iloc[i])
                        sl["is_anomaly"] = bool(scored["is_anomaly"].iloc[i])
            except Exception:
                logger.debug("Anomaly detector not available — skipping scoring")

            run_data = {
                "facilities": facilities,
                "stock_levels": stock_levels,
                "demand_forecasts": demand_forecasts,
                "procurement_plan": procurement_plans,
                "stockout_risks": stockout_risks,
                "alerts": self._alerts,
                "run_info": run_info,
                "raw_inputs": self._raw_inputs,
                "extracted_data": self._extracted_data,
                "reconciliation_results": self._reconciled_data,
                "model_metrics": self._model_metrics,
                "procurement_reasoning": procurement_reasoning,
                "rag_retrievals": self._rag_retrievals,
            }

            store.update(run_data)

            # Persist to database if configured
            persistence.save_pipeline_run(run_data)

        except Exception:
            logger.exception("Failed to update store from pipeline")


def run_pipeline_sync(**kwargs) -> PipelineRunResult:
    """Synchronous wrapper for the pipeline."""
    pipeline = HealthSupplyChainPipeline(**kwargs)
    return asyncio.run(pipeline.run())
