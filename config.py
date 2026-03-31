"""
Health Supply Chain Optimizer — Configuration

Agentic supply chain monitoring + procurement optimization for district health officers.
Scheduled pipeline ingests real climate data (NASA POWER), simulated facility stock levels,
and uses Claude agents to forecast disease-driven demand and optimize procurement under
budget constraints.
"""

from dataclasses import dataclass, field

# WHO Essential Medicines — subset most relevant for district-level procurement
# Consumption rates are per 1000 population per month (WHO/MSH reference)
ESSENTIAL_MEDICINES = [
    {
        "drug_id": "AMX-500",
        "name": "Amoxicillin 500mg",
        "category": "Antibiotics",
        "unit": "capsules",
        "unit_cost_usd": 0.04,
        "consumption_per_1000_month": 180,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.3, "dry": 0.9},  # respiratory infections spike in rains
        "critical": True,
    },
    {
        "drug_id": "ORS-1L",
        "name": "ORS sachets (1L)",
        "category": "Diarrhoeal",
        "unit": "sachets",
        "unit_cost_usd": 0.08,
        "consumption_per_1000_month": 120,
        "shelf_life_months": 36,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.8, "dry": 0.7},  # cholera/diarrhoea spikes
        "critical": True,
    },
    {
        "drug_id": "ZNC-20",
        "name": "Zinc 20mg dispersible",
        "category": "Diarrhoeal",
        "unit": "tablets",
        "unit_cost_usd": 0.02,
        "consumption_per_1000_month": 90,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.6, "dry": 0.8},
        "critical": True,
    },
    {
        "drug_id": "ACT-20",
        "name": "Artemether-Lumefantrine (AL) 20/120mg",
        "category": "Antimalarials",
        "unit": "courses",
        "unit_cost_usd": 0.50,
        "consumption_per_1000_month": 65,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 2.2, "dry": 0.5},  # strong malaria seasonality
        "critical": True,
    },
    {
        "drug_id": "RDT-MAL",
        "name": "Malaria RDT (Pf/Pan)",
        "category": "Diagnostics",
        "unit": "tests",
        "unit_cost_usd": 0.45,
        "consumption_per_1000_month": 55,
        "shelf_life_months": 18,
        "storage": "cool_dry",
        "seasonal_multiplier": {"rainy": 2.0, "dry": 0.6},
        "critical": True,
    },
    {
        "drug_id": "PCT-500",
        "name": "Paracetamol 500mg",
        "category": "Analgesics",
        "unit": "tablets",
        "unit_cost_usd": 0.01,
        "consumption_per_1000_month": 300,
        "shelf_life_months": 36,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.1, "dry": 1.0},
        "critical": False,
    },
    {
        "drug_id": "MET-500",
        "name": "Metformin 500mg",
        "category": "Diabetes",
        "unit": "tablets",
        "unit_cost_usd": 0.02,
        "consumption_per_1000_month": 45,
        "shelf_life_months": 36,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.0, "dry": 1.0},  # no seasonality
        "critical": False,
    },
    {
        "drug_id": "AML-5",
        "name": "Amlodipine 5mg",
        "category": "Cardiovascular",
        "unit": "tablets",
        "unit_cost_usd": 0.03,
        "consumption_per_1000_month": 40,
        "shelf_life_months": 36,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.0, "dry": 1.0},
        "critical": False,
    },
    {
        "drug_id": "CTX-480",
        "name": "Cotrimoxazole 480mg",
        "category": "Antibiotics",
        "unit": "tablets",
        "unit_cost_usd": 0.02,
        "consumption_per_1000_month": 110,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.2, "dry": 0.9},
        "critical": True,
    },
    {
        "drug_id": "IB-200",
        "name": "Ibuprofen 200mg",
        "category": "Analgesics",
        "unit": "tablets",
        "unit_cost_usd": 0.01,
        "consumption_per_1000_month": 200,
        "shelf_life_months": 36,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.0, "dry": 1.0},
        "critical": False,
    },
    {
        "drug_id": "FER-200",
        "name": "Ferrous Sulphate 200mg",
        "category": "Nutrition",
        "unit": "tablets",
        "unit_cost_usd": 0.01,
        "consumption_per_1000_month": 80,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.0, "dry": 1.0},
        "critical": False,
    },
    {
        "drug_id": "FA-5",
        "name": "Folic Acid 5mg",
        "category": "Nutrition",
        "unit": "tablets",
        "unit_cost_usd": 0.01,
        "consumption_per_1000_month": 60,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.0, "dry": 1.0},
        "critical": False,
    },
    {
        "drug_id": "CPX-500",
        "name": "Ciprofloxacin 500mg",
        "category": "Antibiotics",
        "unit": "tablets",
        "unit_cost_usd": 0.05,
        "consumption_per_1000_month": 50,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.4, "dry": 0.8},
        "critical": False,
    },
    {
        "drug_id": "DOX-100",
        "name": "Doxycycline 100mg",
        "category": "Antibiotics",
        "unit": "capsules",
        "unit_cost_usd": 0.03,
        "consumption_per_1000_month": 35,
        "shelf_life_months": 24,
        "storage": "room_temp",
        "seasonal_multiplier": {"rainy": 1.1, "dry": 1.0},
        "critical": False,
    },
    {
        "drug_id": "OXY-5",
        "name": "Oxytocin 5 IU/mL injection",
        "category": "Maternal Health",
        "unit": "ampoules",
        "unit_cost_usd": 0.30,
        "consumption_per_1000_month": 8,
        "shelf_life_months": 18,
        "storage": "cold_chain",
        "seasonal_multiplier": {"rainy": 1.0, "dry": 1.0},
        "critical": True,
    },
]

DRUG_MAP = {d["drug_id"]: d for d in ESSENTIAL_MEDICINES}
CATEGORIES = sorted(set(d["category"] for d in ESSENTIAL_MEDICINES))

# Lead time assumptions (days from order to delivery)
# Lagos State Central Medical Store (Oshodi) → facilities
LEAD_TIMES = {
    "central_warehouse": 5,   # LSMOH Central Medical Store, Oshodi
    "regional_depot": 10,     # Zonal medical stores
    "international": 60,      # UNICEF / Global Fund procurement
}

# Safety stock multiplier (months of buffer stock to keep)
SAFETY_STOCK_MONTHS = 1.5

# Default planning parameters
DEFAULT_PARAMS = {
    "population": 50000,
    "budget_usd": 5000,
    "planning_months": 3,
    "season": "rainy",
    "supply_source": "regional_depot",
    "wastage_pct": 8,
    "prioritize_critical": True,
}

# NASA POWER configuration
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_POWER_PARAMS = ["PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN", "RH2M"]

# Pipeline
PIPELINE_STEPS = ["ingest", "extract", "reconcile", "forecast", "optimize", "recommend"]


@dataclass
class HealthFacility:
    facility_id: str
    name: str
    district: str
    country: str
    latitude: float
    longitude: float
    facility_type: str  # hospital, health_center, health_post
    population_served: int
    chw_count: int
    storage_capacity_m3: float
    has_cold_chain: bool
    reporting_quality: str  # good, moderate, poor
    budget_usd_quarterly: float
    notes: str = ""


FACILITIES: list[HealthFacility] = [
    # ── Lagos State, Nigeria ──
    # Mix of General Hospitals, PHCs, and Health Centres across urban,
    # peri-urban, and semi-rural LGAs.  Coordinates, populations, and
    # budgets calibrated to Lagos State MOH / HEFAMAA data.

    # ── Urban (Lagos Mainland / Island) ──
    HealthFacility("FAC-IKJ", "General Hospital Ikeja", "Ikeja", "Nigeria",
                   6.6018, 3.3515, "hospital", 185000, 48, 120, True, "good", 14000,
                   "State referral hospital on Opebi road. Strong eLMIS reporting. Full cold chain."),
    HealthFacility("FAC-SUR", "Randle General Hospital", "Surulere", "Nigeria",
                   6.5000, 3.3500, "hospital", 165000, 40, 100, True, "good", 12000,
                   "Serves dense mainland corridor. Reliable reporting and cold chain."),
    HealthFacility("FAC-ISL", "General Hospital Lagos Island", "Lagos Island", "Nigeria",
                   6.4540, 3.4080, "hospital", 210000, 52, 140, True, "good", 16000,
                   "Oldest public hospital in Lagos (est. 1893). High patient load. Strong data quality."),

    # ── Urban fringe / High-density ──
    HealthFacility("FAC-AJE", "Ajeromi PHC", "Ajeromi-Ifelodun", "Nigeria",
                   6.4500, 3.3333, "health_center", 95000, 28, 35, False, "poor", 4500,
                   "Informal settlement along Lagos Lagoon. Chronic stockouts. Reports often late."),
    HealthFacility("FAC-MUS", "Mushin General Hospital", "Mushin", "Nigeria",
                   6.5380, 3.3540, "hospital", 195000, 42, 110, True, "moderate", 11000,
                   "High-density urban. Frequent ACT stockouts during rainy season peaks."),
    HealthFacility("FAC-ALI", "Alimosho General Hospital", "Alimosho", "Nigeria",
                   6.6100, 3.2700, "hospital", 220000, 55, 130, True, "moderate", 13000,
                   "Largest LGA by population (~2M). High OPD load. Moderate reporting consistency."),

    # ── Peri-urban / Transitional ──
    HealthFacility("FAC-IJL", "Ibeju-Lekki PHC", "Ibeju-Lekki", "Nigeria",
                   6.4500, 3.6333, "health_center", 55000, 15, 30, False, "poor", 3500,
                   "Rapid urbanisation zone. New settlements outpacing health infrastructure."),
    HealthFacility("FAC-BAD", "Badagry General Hospital", "Badagry", "Nigeria",
                   6.4167, 2.8833, "hospital", 75000, 22, 60, True, "moderate", 6000,
                   "Border town (Nigeria-Benin). Cross-border population dynamics. Malaria endemic."),

    # ── Semi-rural / Coastal ──
    HealthFacility("FAC-EPE", "Epe General Hospital", "Epe", "Nigeria",
                   6.5833, 3.9833, "hospital", 60000, 18, 50, True, "moderate", 5500,
                   "Lagoon-side town. Fishing community. Cholera risk in rainy season."),
    HealthFacility("FAC-IKR", "Ikorodu PHC", "Ikorodu", "Nigeria",
                   6.6167, 3.5000, "health_center", 85000, 24, 40, False, "moderate", 5000,
                   "Growing peri-urban centre. Market town serving rural hinterland."),
]

FACILITY_MAP: dict[str, HealthFacility] = {f.facility_id: f for f in FACILITIES}
COUNTRIES = ["Nigeria"]
