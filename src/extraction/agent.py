"""
Claude extraction agent for the Market Intelligence pipeline.

Normalizes heterogeneous price data from Agmarknet and eNAM into
canonical commodity IDs, standardized units, and validated dates.
Flags stale entries and anomalies. Falls back to rule-based regex
extraction when the Anthropic API is unavailable.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any

from config import COMMODITY_MAP, COMMODITIES, MANDI_MAP, MANDIS

log = logging.getLogger(__name__)


# ── Output dataclass ────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    """Structured extraction output for a single mandi."""
    mandi_id: str
    normalized_prices: list[dict] = field(default_factory=list)
    stale_entries: list[dict] = field(default_factory=list)
    anomalies: list[dict] = field(default_factory=list)
    commodity_mappings: dict = field(default_factory=dict)
    extraction_method: str = "rule_based"  # "claude" | "rule_based"
    confidence: float = 0.0
    tokens_used: int = 0


# ── Commodity name mapping (canonical aliases) ──────────────────────────

COMMODITY_ALIASES: dict[str, str] = {
    # Rice variants
    "paddy(samba)": "RICE-SAMBA",
    "paddy samba": "RICE-SAMBA",
    "samba paddy": "RICE-SAMBA",
    "rice(paddy)": "RICE-SAMBA",
    "rice paddy": "RICE-SAMBA",
    "paddy": "RICE-SAMBA",
    "rice": "RICE-SAMBA",
    "samba": "RICE-SAMBA",
    # Groundnut variants
    "groundnut": "GNUT-POD",
    "groundnut pods": "GNUT-POD",
    "groundnut pods (raw)": "GNUT-POD",
    "moongphali": "GNUT-POD",
    "peanut": "GNUT-POD",
    "groundnut(pods)": "GNUT-POD",
    # Turmeric
    "turmeric": "TUR-FIN",
    "turmeric(finger)": "TUR-FIN",
    "haldi": "TUR-FIN",
    "turmeric finger": "TUR-FIN",
    # Cotton
    "cotton": "COT-MCU",
    "cotton(kapas)": "COT-MCU",
    "kapas": "COT-MCU",
    "cotton kapas": "COT-MCU",
    # Onion
    "onion": "ONI-RED",
    "onion red": "ONI-RED",
    "vengayam": "ONI-RED",
    # Coconut/Copra
    "copra": "COP-DRY",
    "coconut": "COP-DRY",
    "coconut(copra)": "COP-DRY",
    "copra(dry)": "COP-DRY",
    # Maize
    "maize": "MZE-YEL",
    "maize(yellow)": "MZE-YEL",
    "corn": "MZE-YEL",
    "makka": "MZE-YEL",
    # Black gram
    "urad": "URD-BLK",
    "urad dal": "URD-BLK",
    "urad (black gram)": "URD-BLK",
    "black gram": "URD-BLK",
    "blackgram": "URD-BLK",
    # Green gram
    "moong": "MNG-GRN",
    "moong(green gram)": "MNG-GRN",
    "green gram": "MNG-GRN",
    "greengram": "MNG-GRN",
    "moong dal": "MNG-GRN",
    # Banana
    "banana": "BAN-ROB",
    "banana(robusta)": "BAN-ROB",
    "vazhai": "BAN-ROB",
}


# ── Claude tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "parse_agmarknet_entry",
        "description": (
            "Normalize an Agmarknet price record: map commodity name variants to "
            "canonical ID, standardize units to per-quintal, validate date format. "
            "Returns normalized record with canonical commodity_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_commodity_name": {"type": "string"},
                "price_rs": {"type": "number"},
                "unit": {"type": "string"},
                "date_str": {"type": "string"},
                "mandi_name": {"type": "string"},
            },
            "required": ["raw_commodity_name", "price_rs"],
        },
    },
    {
        "name": "parse_enam_listing",
        "description": (
            "Parse eNAM scraped data, handling the difference between "
            "last traded price (eNAM) vs modal price (Agmarknet). "
            "Returns normalized record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_commodity_name": {"type": "string"},
                "last_traded_price_rs": {"type": "number"},
                "lot_size_quintals": {"type": "number"},
                "trade_date": {"type": "string"},
                "mandi_name": {"type": "string"},
            },
            "required": ["raw_commodity_name", "last_traded_price_rs"],
        },
    },
    {
        "name": "detect_stale_data",
        "description": (
            "Flag entries where price hasn't changed in 3+ consecutive days. "
            "This is a common copy-paste artifact in mandi price reporting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "price_series": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Array of {date, price} objects sorted by date.",
                },
                "commodity_id": {"type": "string"},
                "mandi_id": {"type": "string"},
            },
            "required": ["price_series"],
        },
    },
    {
        "name": "normalize_commodity",
        "description": (
            "Map a variant commodity name to the canonical taxonomy. "
            "Handle: 'Groundnut' vs 'Groundnut Pods' vs 'Moongphali', "
            "'Paddy' vs 'Paddy(Samba)' vs 'Rice(Paddy)', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_name": {"type": "string"},
            },
            "required": ["raw_name"],
        },
    },
    {
        "name": "flag_anomalies",
        "description": (
            "Identify prices >3 standard deviations from 30-day rolling mean "
            "for same mandi/commodity pair. Returns flagged anomalies."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "price_series": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "commodity_id": {"type": "string"},
                "mandi_id": {"type": "string"},
            },
            "required": ["price_series"],
        },
    },
]

SYSTEM_PROMPT = (
    "You are a market data extraction agent for Tamil Nadu agricultural prices. "
    "Normalize heterogeneous price records from Agmarknet (government mandi data) "
    "and eNAM (electronic trading platform) into canonical commodity IDs and "
    "standardized units. Flag stale or anomalous entries.\n\n"
    "Commodity taxonomy:\n"
    + "\n".join(f"  {c['id']}: {c['name']} ({c['agmarknet_name']})" for c in COMMODITIES)
    + "\n\nWhen normalizing commodity names, always map to the closest canonical ID. "
    "Common variants: 'Paddy(Samba)' -> RICE-SAMBA, 'Groundnut pods' -> GNUT-POD, "
    "'Cotton(Kapas)' -> COT-MCU, 'Urad' -> URD-BLK."
)


# ── Tool execution (local logic) ────────────────────────────────────────

def _execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool call locally, returning structured results."""
    if tool_name == "parse_agmarknet_entry":
        return _tool_parse_agmarknet(tool_input)
    elif tool_name == "parse_enam_listing":
        return _tool_parse_enam(tool_input)
    elif tool_name == "detect_stale_data":
        return _tool_detect_stale(tool_input)
    elif tool_name == "normalize_commodity":
        return _tool_normalize_commodity(tool_input)
    elif tool_name == "flag_anomalies":
        return _tool_flag_anomalies(tool_input)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def _tool_parse_agmarknet(inp: dict) -> dict:
    """Normalize an Agmarknet price entry."""
    raw_name = inp.get("raw_commodity_name", "")
    commodity_id = _match_commodity(raw_name)
    price = inp.get("price_rs", 0)
    unit = inp.get("unit", "quintal").lower()

    # Unit conversion
    if unit == "tonne" or unit == "mt":
        price = price / 10  # convert tonne to quintal

    return {
        "commodity_id": commodity_id,
        "original_name": raw_name,
        "price_rs_per_quintal": price,
        "unit_standardized": "quintal",
        "valid": commodity_id is not None,
    }


def _tool_parse_enam(inp: dict) -> dict:
    """Normalize an eNAM listing."""
    raw_name = inp.get("raw_commodity_name", "")
    commodity_id = _match_commodity(raw_name)
    last_traded = inp.get("last_traded_price_rs", 0)

    return {
        "commodity_id": commodity_id,
        "original_name": raw_name,
        "price_rs_per_quintal": last_traded,
        "price_type": "last_traded",
        "note": "eNAM reports last traded price, not modal. May be higher than Agmarknet modal.",
        "valid": commodity_id is not None,
    }


def _tool_detect_stale(inp: dict) -> dict:
    """Detect stale (unchanged) prices in a series."""
    series = inp.get("price_series", [])
    stale_runs = []
    if len(series) < 3:
        return {"stale_entries": [], "note": "Series too short to detect staleness."}

    # Sort by date
    sorted_series = sorted(series, key=lambda x: x.get("date", ""))
    current_run = [sorted_series[0]]

    for i in range(1, len(sorted_series)):
        if sorted_series[i].get("price") == sorted_series[i - 1].get("price"):
            current_run.append(sorted_series[i])
        else:
            if len(current_run) >= 3:
                stale_runs.append({
                    "start_date": current_run[0].get("date"),
                    "end_date": current_run[-1].get("date"),
                    "consecutive_days": len(current_run),
                    "price": current_run[0].get("price"),
                })
            current_run = [sorted_series[i]]

    if len(current_run) >= 3:
        stale_runs.append({
            "start_date": current_run[0].get("date"),
            "end_date": current_run[-1].get("date"),
            "consecutive_days": len(current_run),
            "price": current_run[0].get("price"),
        })

    return {"stale_entries": stale_runs, "total_stale_runs": len(stale_runs)}


def _tool_normalize_commodity(inp: dict) -> dict:
    """Map a variant name to canonical commodity ID."""
    raw_name = inp.get("raw_name", "")
    commodity_id = _match_commodity(raw_name)
    commodity = COMMODITY_MAP.get(commodity_id) if commodity_id else None

    return {
        "raw_name": raw_name,
        "commodity_id": commodity_id,
        "canonical_name": commodity["name"] if commodity else None,
        "category": commodity["category"] if commodity else None,
        "match_confidence": 0.95 if commodity_id else 0.0,
    }


def _tool_flag_anomalies(inp: dict) -> dict:
    """Flag prices >3 sigma from rolling mean."""
    series = inp.get("price_series", [])
    if len(series) < 10:
        return {"anomalies": [], "note": "Series too short for anomaly detection."}

    prices = [s.get("price", 0) for s in sorted(series, key=lambda x: x.get("date", ""))]
    anomalies = []

    window = 30
    for i in range(window, len(prices)):
        window_prices = prices[max(0, i - window):i]
        mean = sum(window_prices) / len(window_prices)
        variance = sum((p - mean) ** 2 for p in window_prices) / len(window_prices)
        std = math.sqrt(variance) if variance > 0 else 1

        if abs(prices[i] - mean) > 3 * std:
            anomalies.append({
                "index": i,
                "date": series[i].get("date") if i < len(series) else None,
                "price": prices[i],
                "rolling_mean": round(mean, 0),
                "rolling_std": round(std, 0),
                "z_score": round((prices[i] - mean) / std, 2),
            })

    return {"anomalies": anomalies, "total_anomalies": len(anomalies)}


# ── Commodity matching ───────────────────────────────────────────────────

def _match_commodity(raw_name: str) -> str | None:
    """Match a raw commodity name to canonical ID."""
    if not raw_name:
        return None

    name_lower = raw_name.lower().strip()

    # Direct alias match
    if name_lower in COMMODITY_ALIASES:
        return COMMODITY_ALIASES[name_lower]

    # Substring match (longest alias first)
    sorted_aliases = sorted(COMMODITY_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        if alias in name_lower:
            return COMMODITY_ALIASES[alias]

    # Try matching against canonical names
    for c in COMMODITIES:
        if c["name"].lower() in name_lower or name_lower in c["name"].lower():
            return c["id"]
        if c["agmarknet_name"].lower() in name_lower or name_lower in c["agmarknet_name"].lower():
            return c["id"]

    return None


# ── Rule-based fallback ─────────────────────────────────────────────────

class RuleBasedExtractor:
    """Regex-based extraction when Claude is unavailable."""

    @classmethod
    def extract_prices(cls, price_records: list[dict], mandi_id: str) -> ExtractionResult:
        """Normalize and validate a list of price records for a mandi."""
        result = ExtractionResult(mandi_id=mandi_id, extraction_method="rule_based")
        mappings: dict[str, str] = {}

        for rec in price_records:
            # Normalize commodity name
            raw_name = rec.get("commodity_name", rec.get("commodity_id", ""))
            commodity_id = rec.get("commodity_id")
            if commodity_id not in COMMODITY_MAP:
                commodity_id = _match_commodity(raw_name)
                if commodity_id:
                    mappings[raw_name] = commodity_id

            if commodity_id is None:
                continue

            normalized = {
                "mandi_id": mandi_id,
                "commodity_id": commodity_id,
                "date": rec.get("date"),
                "min_price_rs": rec.get("min_price_rs", 0),
                "max_price_rs": rec.get("max_price_rs", 0),
                "modal_price_rs": rec.get("modal_price_rs", 0),
                "arrivals_tonnes": rec.get("arrivals_tonnes", 0),
                "source": rec.get("source", "unknown"),
                "quality_flag": rec.get("quality_flag", "good"),
            }
            result.normalized_prices.append(normalized)

        # Detect stale entries
        cls._detect_stale_entries(result)

        # Detect anomalies
        cls._detect_anomalies(result)

        result.commodity_mappings = mappings
        result.confidence = 0.75 if result.normalized_prices else 0.3
        return result

    @classmethod
    def _detect_stale_entries(cls, result: ExtractionResult):
        """Flag entries where price hasn't changed for 3+ days."""
        from collections import defaultdict
        by_commodity: dict[str, list[dict]] = defaultdict(list)

        for p in result.normalized_prices:
            by_commodity[p["commodity_id"]].append(p)

        for commodity_id, prices in by_commodity.items():
            sorted_prices = sorted(prices, key=lambda x: x.get("date", ""))
            current_run = [sorted_prices[0]] if sorted_prices else []

            for i in range(1, len(sorted_prices)):
                if sorted_prices[i]["modal_price_rs"] == sorted_prices[i - 1]["modal_price_rs"]:
                    current_run.append(sorted_prices[i])
                else:
                    if len(current_run) >= 3:
                        for entry in current_run:
                            entry["quality_flag"] = "stale"
                            result.stale_entries.append(entry)
                    current_run = [sorted_prices[i]]

            if len(current_run) >= 3:
                for entry in current_run:
                    entry["quality_flag"] = "stale"
                    result.stale_entries.append(entry)

    @classmethod
    def _detect_anomalies(cls, result: ExtractionResult):
        """Flag prices >3 sigma from rolling mean."""
        from collections import defaultdict
        by_commodity: dict[str, list[dict]] = defaultdict(list)

        for p in result.normalized_prices:
            by_commodity[p["commodity_id"]].append(p)

        for commodity_id, prices in by_commodity.items():
            sorted_prices = sorted(prices, key=lambda x: x.get("date", ""))
            modal_prices = [p["modal_price_rs"] for p in sorted_prices]

            if len(modal_prices) < 10:
                continue

            mean = sum(modal_prices) / len(modal_prices)
            variance = sum((p - mean) ** 2 for p in modal_prices) / len(modal_prices)
            std = math.sqrt(variance) if variance > 0 else 1

            for i, p in enumerate(sorted_prices):
                z_score = (p["modal_price_rs"] - mean) / std
                if abs(z_score) > 3:
                    p["quality_flag"] = "anomalous"
                    result.anomalies.append({
                        **p,
                        "z_score": round(z_score, 2),
                        "rolling_mean": round(mean, 0),
                    })


# ── Claude agent ────────────────────────────────────────────────────────

class ExtractionAgent:
    """Multi-round Claude tool-use agent for market data extraction.

    Falls back to RuleBasedExtractor when the Anthropic API is unavailable
    or ANTHROPIC_API_KEY is not set.
    """

    MAX_ROUNDS = 6

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self._client = None
        self._fallback = RuleBasedExtractor()

    def _get_client(self):
        """Lazy-init the Anthropic client."""
        if self._client is not None:
            return self._client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log.warning("ANTHROPIC_API_KEY not set -- using rule-based fallback")
            return None
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
            return self._client
        except ImportError:
            log.warning("anthropic package not installed -- using rule-based fallback")
            return None

    def extract(
        self,
        mandi_id: str,
        agmarknet_records: list[dict] | None = None,
        enam_records: list[dict] | None = None,
    ) -> ExtractionResult:
        """Run extraction for a single mandi.

        Attempts Claude agent loop first; falls back to regex if unavailable.
        """
        client = self._get_client()
        if client is not None:
            return self._claude_extract(client, mandi_id, agmarknet_records, enam_records)
        return self._rule_based_extract(mandi_id, agmarknet_records, enam_records)

    def _claude_extract(
        self,
        client: Any,
        mandi_id: str,
        agmarknet_records: list[dict] | None,
        enam_records: list[dict] | None,
    ) -> ExtractionResult:
        """Multi-round tool-use loop with Claude."""
        result = ExtractionResult(mandi_id=mandi_id, extraction_method="claude")
        tools_used: list[str] = []
        total_tokens = 0

        mandi = MANDI_MAP.get(mandi_id)
        parts = [f"Extract and normalize price data for mandi {mandi_id}"]
        if mandi:
            parts.append(f"({mandi.name}, {mandi.district}, type={mandi.market_type})")

        if agmarknet_records:
            parts.append(f"\n--- AGMARKNET RECORDS ({len(agmarknet_records)} entries) ---")
            for rec in agmarknet_records[:20]:
                parts.append(json.dumps(rec, default=str))

        if enam_records:
            parts.append(f"\n--- eNAM RECORDS ({len(enam_records)} entries) ---")
            for rec in enam_records[:20]:
                parts.append(json.dumps(rec, default=str))

        parts.append(
            "\nUse the available tools to normalize commodity names, detect stale data, "
            "and flag anomalies. Return normalized prices in JSON."
        )

        messages: list[dict] = [{"role": "user", "content": "\n".join(parts)}]

        for round_num in range(self.MAX_ROUNDS):
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                )
            except Exception as e:
                log.error("Claude API error on round %d: %s", round_num, e)
                return self._rule_based_extract(mandi_id, agmarknet_records, enam_records)

            if hasattr(response, "usage"):
                total_tokens += getattr(response.usage, "input_tokens", 0)
                total_tokens += getattr(response.usage, "output_tokens", 0)

            tool_calls = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls.append(block)
                    tools_used.append(block.name)

            if response.stop_reason == "end_turn" or not tool_calls:
                break

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tc in tool_calls:
                tool_result = _execute_tool(tc.name, tc.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(tool_result),
                })

            messages.append({"role": "user", "content": tool_results})

        result.tokens_used = total_tokens
        result.confidence = 0.85 if result.normalized_prices else 0.5
        return result

    def _rule_based_extract(
        self,
        mandi_id: str,
        agmarknet_records: list[dict] | None,
        enam_records: list[dict] | None,
    ) -> ExtractionResult:
        """Fallback extraction using regex-based approach."""
        all_records = []
        if agmarknet_records:
            all_records.extend(agmarknet_records)
        if enam_records:
            all_records.extend(enam_records)

        return self._fallback.extract_prices(all_records, mandi_id)
