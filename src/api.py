"""
Health Supply Chain Optimizer -- FastAPI Application

Serves synthetic demo data for the dashboard when the pipeline hasn't run.
When the real pipeline has been run, serves pipeline results instead.

Endpoints:
- GET  /health                  -- Health check
- GET  /api/facilities          -- Facility list with current stock status
- GET  /api/stock-levels        -- Stock by drug x facility with stockout risk
- GET  /api/demand-forecast     -- Predicted demand with climate factors
- GET  /api/procurement-plan    -- Optimized plan with per-drug orders
- GET  /api/stockout-risks      -- Drugs/facilities at risk
- GET  /api/raw-inputs          -- Raw unstructured text (stock reports, IDSR, CHW)
- GET  /api/extracted-data      -- What Claude extracted from each input
- GET  /api/reconciled-data     -- Reconciled data with conflict resolution reasoning
- GET  /api/model-info          -- XGBoost metrics, feature importances
- GET  /api/pipeline/runs       -- Run history
- GET  /api/pipeline/stats      -- Aggregate stats
- POST /api/pipeline/trigger    -- Manual pipeline run
"""

import logging
import random
import threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import (
    ESSENTIAL_MEDICINES,
    DRUG_MAP,
    CATEGORIES,
    FACILITIES,
    FACILITY_MAP,
    LEAD_TIMES,
    DEFAULT_PARAMS,
    PIPELINE_STEPS,
)
from src.optimizer import optimize, plan_to_dict
from src.store import store
from src.scheduler import scheduler
from src.pipeline import generate_all_inputs
from src.ingestion.lmis_simulator import simulate_all_facilities

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Health Supply Chain Optimizer",
    description="Agentic supply chain monitoring + procurement optimization for district health officers",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://jtlevine-health-supply-optimizer.hf.space",
        "https://health-supply-optimizer.vercel.app",
        "https://frontend-five-ruby-79.vercel.app",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

SEED = 42


# ---------------------------------------------------------------------------
# Demo data generation (deterministic, seed=42)
# ---------------------------------------------------------------------------

def _generate_demo_data() -> dict:
    """Deterministic synthetic data that tells a coherent story.

    Story:
    - It's rainy season: malaria drug demand is 2x normal
    - Ajeromi PHC and Ungogo Health Post have poor reporting (missing data)
    - ACT-20 is running low at 3 facilities (stockout risk: high)
    - ORS demand spiking due to recent heavy rainfall
    - Budget covers 80% of critical drugs but only 50% of non-critical
    """
    rng = random.Random(SEED)
    now = datetime(2026, 3, 29, 10, 0, 0)

    # -- Run optimizer once per facility (reused for facilities + procurement) --
    facility_plans: dict = {}
    for fac in FACILITIES:
        facility_plans[fac.facility_id] = optimize(
            population=fac.population_served,
            budget_usd=fac.budget_usd_quarterly,
            planning_months=3,
            season="rainy",
            supply_source="regional_depot",
            wastage_pct=8,
            prioritize_critical=True,
        )

    # -- Simulate stock for text input generation --
    stock_sim = simulate_all_facilities(FACILITIES, days_back=90, seed=SEED)
    stock_dict = {}
    for fid, readings in stock_sim.items():
        stock_dict[fid] = [
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

    # -- Generate raw text inputs --
    raw_inputs = generate_all_inputs(
        facilities=FACILITIES,
        stock_by_facility=stock_dict,
        seed=SEED,
    )

    # -- Demo extracted data --
    extracted_data = {}
    for fac in FACILITIES:
        fid = fac.facility_id
        drugs_extracted = {}
        pop_factor = fac.population_served / 1000

        for drug in ESSENTIAL_MEDICINES[:8]:  # top 8 drugs
            monthly = drug["consumption_per_1000_month"] * pop_factor
            seasonal_mult = drug["seasonal_multiplier"].get("rainy", 1.0)
            daily = monthly * seasonal_mult / 30
            stock = daily * rng.uniform(10, 50)
            dos = stock / daily if daily > 0 else 999

            drugs_extracted[drug["drug_id"]] = {
                "stock_level": round(stock, 0),
                "days_of_stock": round(dos, 1),
                "source": "stock_report",
            }

        disease_cases = {
            "malaria": rng.randint(int(fac.population_served * 0.002), int(fac.population_served * 0.008)),
            "diarrhoea": rng.randint(int(fac.population_served * 0.001), int(fac.population_served * 0.005)),
            "ari": rng.randint(int(fac.population_served * 0.001), int(fac.population_served * 0.004)),
        }

        alerts = []
        if fac.reporting_quality == "poor":
            alerts.append(f"CHW-{fid}-1: ORS finished in ward {rng.randint(1,5)}. Pls resupply urgent")

        extracted_data[fid] = {
            "facility_id": fid,
            "drugs": drugs_extracted,
            "disease_cases": disease_cases,
            "alerts": alerts,
        }

    # -- Demo reconciliation results --
    reconciliation_results = {}
    for fac in FACILITIES:
        fid = fac.facility_id
        conflicts = []
        stock_by_drug = {}
        pop_factor = fac.population_served / 1000

        for drug in ESSENTIAL_MEDICINES:
            monthly = drug["consumption_per_1000_month"] * pop_factor
            seasonal_mult = drug["seasonal_multiplier"].get("rainy", 1.0)
            daily = monthly * seasonal_mult / 30

            # ACT-20 deliberately low at certain facilities
            if drug["drug_id"] == "ACT-20" and fid in ("FAC-AJE", "FAC-UNG", "FAC-EPE"):
                stock = rng.uniform(2, 8) * daily
            elif drug["drug_id"] == "ORS-1L" and fid in ("FAC-AJE", "FAC-GMA"):
                stock = rng.uniform(5, 12) * daily
            else:
                stock = rng.uniform(15, 60) * daily

            dos = stock / daily if daily > 0 else 999

            stock_by_drug[drug["drug_id"]] = {
                "stock_level": round(stock, 1),
                "consumption_daily": round(daily, 1),
                "days_of_stock_remaining": round(dos, 1),
                "source": "reconciled",
            }

        # Add a sample conflict for poor-reporting facilities
        if fac.reporting_quality == "poor":
            conflicts.append({
                "drug_id": "ACT-20",
                "drug_name": "Artemether-Lumefantrine (AL) 20/120mg",
                "field": "stock_level",
                "simulated_value": 245,
                "extracted_value": 180,
                "resolution": "averaged",
                "reasoning": (
                    "Stock report says 180 but LMIS shows 245. "
                    "Difference is >20%. Using average (212) as reconciled value. "
                    "Facility has poor reporting quality -- manual count recommended."
                ),
            })

        quality_score = {"good": 0.92, "moderate": 0.78, "poor": 0.55}.get(fac.reporting_quality, 0.7)

        reconciliation_results[fid] = {
            "facility_id": fid,
            "stock_by_drug": stock_by_drug,
            "conflicts": conflicts,
            "disease_cases": extracted_data.get(fid, {}).get("disease_cases", {}),
            "quality_score": quality_score,
        }

    # -- Demo model metrics --
    model_metrics = {
        "model_type": "epidemiological_formulas",
        "model_source": "mordecai_et_al_2013",
        "features": [
            "avg_precip_mm", "avg_temp_c", "avg_humidity_pct",
            "population_served", "seasonal_multiplier",
        ],
        "rmse": 142.3,
        "mae": 98.7,
        "r_squared": 0.84,
        "feature_importances": {
            "avg_precip_mm": 0.32,
            "avg_temp_c": 0.25,
            "seasonal_multiplier": 0.22,
            "population_served": 0.15,
            "avg_humidity_pct": 0.06,
        },
        "note": (
            "Epidemiological formula model calibrated against historical disease "
            "surveillance data. Climate features dominate for malaria and diarrhoeal "
            "drug categories. R-squared of 0.84 across 10 facilities."
        ),
    }

    # -- Demo procurement reasoning --
    procurement_reasoning = [
        {
            "round": 1,
            "tool": "get_facility_stock",
            "input": {"facility_id": "FAC-AJE"},
            "result_summary": "15 drugs, facility=Ajeromi PHC. ACT-20 at 5 days, ORS at 8 days.",
        },
        {
            "round": 1,
            "tool": "get_facility_stock",
            "input": {"facility_id": "FAC-UNG"},
            "result_summary": "15 drugs, facility=Ungogo Health Post. ACT-20 at 3 days, critical.",
        },
        {
            "round": 2,
            "tool": "estimate_stockout_impact",
            "input": {"facility_id": "FAC-UNG", "drug_id": "ACT-20", "days_without_stock": 14},
            "result_summary": "severity=critical, deaths=0.45 estimated if 14-day stockout",
        },
        {
            "round": 2,
            "tool": "check_redistribution",
            "input": {"source_facility_id": "FAC-KMC", "target_facility_id": "FAC-UNG", "drug_id": "ACT-20"},
            "result_summary": "can_redistribute=True, available=2400 courses, transit 1 day (same district)",
        },
        {
            "round": 3,
            "tool": "get_demand_forecast",
            "input": {"facility_id": "FAC-AJE", "drug_id": "ORS-1L"},
            "result_summary": "1 forecast. Demand 1.7x baseline due to diarrhoea risk from heavy rainfall.",
        },
        {
            "round": 3,
            "tool": "get_supplier_options",
            "input": {"drug_id": "ACT-20"},
            "result_summary": "4 supplier options: central(7d), regional(14d), intl(45d), emergency(5d)",
        },
        {
            "round": 4,
            "tool": "check_redistribution",
            "input": {"source_facility_id": "FAC-IKJ", "target_facility_id": "FAC-AJE", "drug_id": "ORS-1L"},
            "result_summary": "can_redistribute=True, available=850 sachets, transit 1 day (Lagos district)",
        },
    ]

    # -- Demo RAG retrievals --
    rag_retrievals = [
        {
            "query": "ACT stockout management protocol",
            "chunk": "WHO recommends emergency procurement of ACTs when stock falls below 2 weeks supply...",
            "source": "WHO Essential Medicines Guidelines 2023",
            "relevance_score": 0.92,
        },
        {
            "query": "ORS diarrhoea outbreak response",
            "chunk": "During diarrhoea outbreaks, ORS consumption may increase 2-3x. Pre-position stocks at community level...",
            "source": "UNICEF WASH Response Protocol",
            "relevance_score": 0.88,
        },
    ]

    # -- Facilities with status --
    facilities = []
    for fac in FACILITIES:
        plan = facility_plans[fac.facility_id]
        high_risk_count = sum(
            1 for o in plan.orders if o.stockout_risk in ("high", "critical")
        )

        # Data quality score based on reporting quality
        quality_scores = {"good": rng.uniform(0.88, 0.96), "moderate": rng.uniform(0.65, 0.82), "poor": rng.uniform(0.35, 0.55)}
        dq = quality_scores.get(fac.reporting_quality, 0.7)

        facilities.append({
            "facility_id": fac.facility_id,
            "name": fac.name,
            "district": fac.district,
            "country": fac.country,
            "latitude": fac.latitude,
            "longitude": fac.longitude,
            "facility_type": fac.facility_type,
            "population_served": fac.population_served,
            "reporting_quality": fac.reporting_quality,
            "data_quality_score": round(dq, 2),
            "budget_usd": fac.budget_usd_quarterly,
            "budget_used_usd": plan.budget_used_usd,
            "stockout_risks": high_risk_count,
            "last_updated": now.isoformat(),
        })

    # -- Stock levels (latest per drug x facility) --
    stock_levels = []
    for fac in FACILITIES:
        pop_factor = fac.population_served / 1000
        for drug in ESSENTIAL_MEDICINES:
            monthly_consumption = drug["consumption_per_1000_month"] * pop_factor
            seasonal_mult = drug["seasonal_multiplier"].get("rainy", 1.0)
            daily_consumption = monthly_consumption * seasonal_mult / 30

            # Simulate current stock level
            # ACT-20 deliberately low at several facilities
            if drug["drug_id"] == "ACT-20" and fac.facility_id in ("FAC-AJE", "FAC-UNG", "FAC-EPE"):
                stock = rng.uniform(2, 8) * daily_consumption  # 2-8 days
            elif drug["drug_id"] == "ORS-1L" and fac.facility_id in ("FAC-AJE", "FAC-GMA"):
                stock = rng.uniform(5, 12) * daily_consumption  # spiking demand
            elif drug["storage"] == "cold_chain" and not fac.has_cold_chain:
                stock = rng.uniform(0, 3) * daily_consumption
            else:
                stock = rng.uniform(15, 60) * daily_consumption

            dos = stock / daily_consumption if daily_consumption > 0 else 999

            if dos < 7:
                risk = "critical"
            elif dos < 14:
                risk = "high"
            elif dos < 30:
                risk = "moderate"
            else:
                risk = "low"

            stock_levels.append({
                "facility_id": fac.facility_id,
                "facility_name": fac.name,
                "drug_id": drug["drug_id"],
                "drug_name": drug["name"],
                "category": drug["category"],
                "critical": drug["critical"],
                "stock_level": round(stock, 0),
                "consumption_daily": round(daily_consumption, 1),
                "days_of_stock": round(dos, 1),
                "stockout_risk": risk,
                "date": now.strftime("%Y-%m-%d"),
            })

    # -- Demand forecasts --
    demand_forecasts = []
    for fac in FACILITIES:
        pop_factor = fac.population_served / 1000
        # Simulate climate conditions: rainy season
        avg_precip = rng.uniform(6, 14)  # mm/day
        avg_temp = rng.uniform(24, 29)

        for drug in ESSENTIAL_MEDICINES:
            base_monthly = drug["consumption_per_1000_month"] * pop_factor
            category = drug["category"]

            if category in ("Antimalarials", "Diagnostics"):
                # Malaria temp suitability
                temp_suit = max(0, -0.015 * (avg_temp - 25) ** 2 + 1.0)
                rain_risk = min(1.8, avg_precip / 8)
                multiplier = max(0.3, temp_suit * rain_risk)
                climate_driven = True
                risk_level = "high" if multiplier > 1.2 else "moderate" if multiplier > 0.8 else "low"
                factors = [{
                    "factor": "malaria_risk",
                    "temp_suitability": round(temp_suit, 2),
                    "rainfall_risk": round(rain_risk, 2),
                    "combined": round(multiplier, 2),
                    "avg_temp_c": round(avg_temp, 1),
                    "avg_precip_mm": round(avg_precip, 1),
                }]
            elif category == "Diarrhoeal":
                multiplier = 1.4 + rng.uniform(0, 0.5)
                climate_driven = True
                risk_level = "high"
                factors = [{
                    "factor": "diarrhoea_risk",
                    "rainfall_flooding": round(avg_precip, 1),
                    "combined": round(multiplier, 2),
                }]
            elif category == "Antibiotics":
                multiplier = 1.1 + rng.uniform(0, 0.25)
                climate_driven = True
                risk_level = "moderate"
                factors = [{"factor": "respiratory_risk", "combined": round(multiplier, 2)}]
            else:
                multiplier = 1.0
                climate_driven = False
                risk_level = "low"
                factors = [{"factor": "baseline", "note": "No climate-disease correlation"}]

            predicted = round(base_monthly * multiplier, 0)
            baseline = round(base_monthly, 0)

            demand_forecasts.append({
                "facility_id": fac.facility_id,
                "facility_name": fac.name,
                "drug_id": drug["drug_id"],
                "drug_name": drug["name"],
                "category": category,
                "predicted_demand_monthly": predicted,
                "baseline_demand_monthly": baseline,
                "demand_multiplier": round(multiplier, 2),
                "confidence": round(rng.uniform(0.7, 0.95), 2),
                "contributing_factors": factors,
                "climate_driven": climate_driven,
                "risk_level": risk_level,
                # New fields
                "model_source": "epidemiological_formulas",
                "prediction_interval": {
                    "lower": round(predicted * 0.8, 0),
                    "upper": round(predicted * 1.25, 0),
                },
                "model_metrics": {
                    "rmse": 142.3,
                    "r_squared": 0.84,
                },
            })

    # -- Procurement plans (reuse cached optimizer results) --
    procurement_plans = []
    for fac in FACILITIES:
        plan = facility_plans[fac.facility_id]
        plan_dict = plan_to_dict(plan)
        plan_dict["facility_id"] = fac.facility_id
        plan_dict["facility_name"] = fac.name

        # Add agent reasoning
        critical_covered = plan.critical_drugs_covered
        critical_total = plan.critical_drugs_total
        if critical_covered == critical_total:
            reasoning = (
                f"Budget of ${fac.budget_usd_quarterly:,.0f} fully covers all "
                f"{critical_total} critical drugs. "
            )
        else:
            reasoning = (
                f"Budget of ${fac.budget_usd_quarterly:,.0f} covers {critical_covered}/"
                f"{critical_total} critical drugs. "
            )

        if plan.stockout_risks > 0:
            reasoning += (
                f"{plan.stockout_risks} drugs at high/critical stockout risk. "
                "Recommend emergency procurement or reallocation from other facilities."
            )
        else:
            reasoning += "All drugs adequately stocked for the planning period."

        plan_dict["agent_reasoning"] = reasoning

        # New fields
        plan_dict["optimization_method"] = "greedy_fallback"
        plan_dict["reasoning_trace"] = procurement_reasoning
        plan_dict["redistributions"] = [
            r for r in [
                {
                    "from_facility": "FAC-KMC",
                    "to_facility": "FAC-UNG",
                    "drug_id": "ACT-20",
                    "quantity": 500,
                    "transit_days": 1,
                    "reason": "Murtala Muhammad has 2400 surplus ACT courses after safety buffer",
                },
                {
                    "from_facility": "FAC-IKJ",
                    "to_facility": "FAC-AJE",
                    "drug_id": "ORS-1L",
                    "quantity": 850,
                    "transit_days": 1,
                    "reason": "Ikeja General has surplus ORS; Ajeromi has diarrhoea spike",
                },
            ] if fac.facility_id in (r.get("to_facility"), r.get("from_facility"))
        ]

        procurement_plans.append(plan_dict)

    # -- Stockout risks --
    stockout_risks = [
        sl for sl in stock_levels
        if sl["stockout_risk"] in ("high", "critical", "moderate")
    ]
    stockout_risks.sort(key=lambda x: (
        {"critical": 0, "high": 1, "moderate": 2}.get(x["stockout_risk"], 3),
        0 if x.get("critical") else 1,
    ))

    # -- Pipeline runs (historical) --
    pipeline_runs = []
    for i in range(15):
        run_date = now - timedelta(days=i * 2)
        duration = rng.uniform(40, 150)
        cost = rng.uniform(0.04, 0.15)
        status = "ok" if rng.random() > 0.12 else "partial"
        pipeline_runs.append({
            "run_id": f"run-{2000 + i}",
            "started_at": run_date.isoformat(),
            "ended_at": (run_date + timedelta(seconds=duration)).isoformat(),
            "status": status,
            "duration_s": round(duration, 1),
            "facilities_processed": len(FACILITIES),
            "drugs_tracked": len(ESSENTIAL_MEDICINES),
            "stockout_risks_found": rng.randint(3, 12),
            "total_cost_usd": round(cost, 4),
            "steps": [
                {"step": s, "status": "ok", "duration_s": round(duration / 6, 1)}
                for s in PIPELINE_STEPS
            ],
        })

    # -- Stats --
    stats = {
        "total_runs": len(pipeline_runs),
        "successful_runs": sum(1 for r in pipeline_runs if r["status"] == "ok"),
        "success_rate": round(
            sum(1 for r in pipeline_runs if r["status"] == "ok") / len(pipeline_runs), 2,
        ),
        "facilities_monitored": len(FACILITIES),
        "drugs_tracked": len(ESSENTIAL_MEDICINES),
        "high_risk_stockouts": sum(
            1 for sl in stock_levels if sl["stockout_risk"] in ("high", "critical")
        ),
        "total_cost_usd": round(sum(r["total_cost_usd"] for r in pipeline_runs), 2),
        "avg_cost_per_run_usd": round(
            sum(r["total_cost_usd"] for r in pipeline_runs) / len(pipeline_runs), 4,
        ),
        "last_run": pipeline_runs[0]["started_at"],
        "data_sources": ["NASA POWER", "LMIS (simulated)"],
        # New token tracking
        "extraction_tokens": 0,
        "reconciliation_tokens": 0,
        "optimization_tokens": 0,
    }

    return {
        "facilities": facilities,
        "stock_levels": stock_levels,
        "demand_forecasts": demand_forecasts,
        "procurement_plans": procurement_plans,
        "stockout_risks": stockout_risks,
        "pipeline_runs": pipeline_runs,
        "stats": stats,
        # New demo data
        "raw_inputs": raw_inputs,
        "extracted_data": extracted_data,
        "reconciliation_results": reconciliation_results,
        "model_metrics": model_metrics,
        "procurement_reasoning": procurement_reasoning,
        "rag_retrievals": rag_retrievals,
    }


_demo_cache: dict | None = None
_demo_lock = threading.Lock()


def _get_demo() -> dict:
    global _demo_cache
    if _demo_cache is None:
        with _demo_lock:
            if _demo_cache is None:
                _demo_cache = _generate_demo_data()
    return _demo_cache


# ---------------------------------------------------------------------------
# Helper: get from store or demo
# ---------------------------------------------------------------------------

def _get(key: str, default=None):
    """Return store data if pipeline has run, otherwise demo data."""
    if default is None:
        default = []
    if store.has_real_data:
        val = getattr(store, key, None)
        if val:
            return val
    return _get_demo().get(key, default)


def _source() -> str:
    return "pipeline" if store.has_real_data else "demo"


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "health-supply-chain-optimizer",
        "version": "2.0.0",
        "pipeline_data": store.has_real_data,
    }


@app.get("/api/facilities")
def get_facilities():
    """Facility list with current stock status."""
    facilities = _get("facilities")
    return {
        "facilities": facilities,
        "total": len(facilities),
        "countries": sorted(set(f["country"] for f in facilities)),
        "source": _source(),
    }


@app.get("/api/stock-levels")
def get_stock_levels(
    facility_id: str | None = Query(default=None),
    drug_id: str | None = Query(default=None),
    risk_only: bool = Query(default=False),
):
    """Stock by drug x facility with stockout risk."""
    levels = _get("stock_levels")

    if facility_id:
        levels = [sl for sl in levels if sl["facility_id"] == facility_id]
    if drug_id:
        levels = [sl for sl in levels if sl["drug_id"] == drug_id]
    if risk_only:
        levels = [sl for sl in levels if sl.get("stockout_risk") in ("high", "critical")]

    return {
        "stock_levels": levels,
        "total": len(levels),
        "source": _source(),
    }


@app.get("/api/demand-forecast")
def get_demand_forecast(
    facility_id: str | None = Query(default=None),
    drug_id: str | None = Query(default=None),
    climate_driven_only: bool = Query(default=False),
):
    """Predicted demand with climate factors, model source, and prediction intervals."""
    forecasts = _get("demand_forecasts")

    if facility_id:
        forecasts = [f for f in forecasts if f["facility_id"] == facility_id]
    if drug_id:
        forecasts = [f for f in forecasts if f["drug_id"] == drug_id]
    if climate_driven_only:
        forecasts = [f for f in forecasts if f.get("climate_driven")]

    return {
        "forecasts": forecasts,
        "total": len(forecasts),
        "source": _source(),
    }


@app.get("/api/procurement-plan")
def get_procurement_plan(
    facility_id: str | None = Query(default=None),
):
    """Optimized procurement plan with per-drug orders, agent reasoning, and redistributions."""
    plans = _get("procurement_plans")

    if facility_id:
        plans = [p for p in plans if p.get("facility_id") == facility_id]

    return {
        "plans": plans,
        "total": len(plans),
        "source": _source(),
    }


@app.get("/api/stockout-risks")
def get_stockout_risks(
    risk_level: str | None = Query(default=None),
    critical_only: bool = Query(default=False),
):
    """Drugs/facilities at risk of stockout."""
    risks = _get("stockout_risks")

    if risk_level:
        risks = [r for r in risks if r.get("stockout_risk", r.get("risk_level")) == risk_level]
    if critical_only:
        risks = [r for r in risks if r.get("critical")]

    high = sum(1 for r in risks if r.get("stockout_risk", r.get("risk_level")) == "high")
    critical = sum(1 for r in risks if r.get("stockout_risk", r.get("risk_level")) == "critical")

    return {
        "risks": risks,
        "total": len(risks),
        "high": high,
        "critical": critical,
        "source": _source(),
    }


# ---------------------------------------------------------------------------
# New endpoints
# ---------------------------------------------------------------------------

@app.get("/api/raw-inputs")
def get_raw_inputs(
    facility_id: str | None = Query(default=None),
):
    """Raw unstructured text: stock reports, IDSR, CHW messages."""
    inputs = _get("raw_inputs")

    if facility_id:
        if isinstance(inputs, dict):
            fac_input = inputs.get(facility_id)
            if fac_input:
                inputs = {facility_id: fac_input}
            else:
                inputs = {}

    return {
        "raw_inputs": inputs,
        "total_facilities": len(inputs) if isinstance(inputs, dict) else 0,
        "source": _source(),
    }


@app.get("/api/extracted-data")
def get_extracted_data(
    facility_id: str | None = Query(default=None),
):
    """What Claude extracted from each input."""
    data = _get("extracted_data")

    if facility_id:
        if isinstance(data, dict):
            fac_data = data.get(facility_id)
            if fac_data:
                data = {facility_id: fac_data}
            else:
                data = {}

    return {
        "extracted_data": data,
        "total_facilities": len(data) if isinstance(data, dict) else 0,
        "source": _source(),
    }


@app.get("/api/reconciled-data")
def get_reconciled_data(
    facility_id: str | None = Query(default=None),
):
    """Reconciled data with conflict resolution reasoning."""
    data = _get("reconciliation_results")

    if facility_id:
        if isinstance(data, dict):
            fac_data = data.get(facility_id)
            if fac_data:
                data = {facility_id: fac_data}
            else:
                data = {}

    # Compute total conflicts
    total_conflicts = 0
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, dict):
                total_conflicts += len(v.get("conflicts", []))

    return {
        "reconciled_data": data,
        "total_facilities": len(data) if isinstance(data, dict) else 0,
        "total_conflicts": total_conflicts,
        "source": _source(),
    }


@app.get("/api/model-info")
def get_model_info():
    """XGBoost / forecasting model metrics and feature importances."""
    return {
        "model_metrics": _get("model_metrics", default={}),
        "source": _source(),
    }


# ---------------------------------------------------------------------------
# Existing endpoints (kept + enhanced)
# ---------------------------------------------------------------------------

@app.get("/api/pipeline/runs")
def get_pipeline_runs():
    """Run history."""
    runs = _get("pipeline_runs")
    return {"runs": runs, "total": len(runs)}


@app.get("/api/pipeline/stats")
def get_pipeline_stats():
    """Aggregate pipeline stats with per-step token usage."""
    stats = _get("stats", default={})
    return stats


@app.post("/api/pipeline/trigger")
def trigger_pipeline():
    """Trigger a manual pipeline run."""
    result = scheduler.trigger()
    return result


# -- Legacy endpoints (kept for backward compatibility) --

@app.get("/api/drugs")
def list_drugs():
    """List all available drugs with metadata."""
    return {
        "drugs": ESSENTIAL_MEDICINES,
        "total": len(ESSENTIAL_MEDICINES),
        "categories": CATEGORIES,
    }


@app.get("/api/defaults")
def get_defaults():
    """Return default planning parameters."""
    return {
        "defaults": DEFAULT_PARAMS,
        "lead_times": LEAD_TIMES,
        "seasons": ["rainy", "dry"],
        "supply_sources": list(LEAD_TIMES.keys()),
    }


@app.get("/api/optimize")
def run_optimization(
    population: int = Query(default=50000, ge=1000, le=10_000_000),
    budget_usd: float = Query(default=5000, ge=100, le=1_000_000),
    planning_months: int = Query(default=3, ge=1, le=12),
    season: str = Query(default="rainy"),
    supply_source: str = Query(default="regional_depot"),
    wastage_pct: float = Query(default=8, ge=0, le=50),
    prioritize_critical: bool = Query(default=True),
):
    """Compute optimal procurement plan given constraints."""
    plan = optimize(
        population=population,
        budget_usd=budget_usd,
        planning_months=planning_months,
        season=season,
        supply_source=supply_source,
        wastage_pct=wastage_pct,
        prioritize_critical=prioritize_critical,
    )
    return plan_to_dict(plan)


# -- Static file serving -----------------------------------------------------

dist_path = Path(__file__).parent.parent / "frontend" / "dist"
if dist_path.exists():
    app.mount("/assets", StaticFiles(directory=str(dist_path / "assets")), name="static")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        file_path = dist_path / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(dist_path / "index.html"))
