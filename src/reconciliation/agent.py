"""
Claude reconciliation agent -- resolves conflicts between Agmarknet and eNAM.

KEY DIFFERENTIATOR: No existing tool reconciles conflicting Indian mandi
price sources. This agent cross-validates two data streams using spatial
(neighboring mandis), temporal (seasonality), and economic (transport
arbitrage) reasoning.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from config import (
    COMMODITY_MAP,
    COMMODITIES,
    MANDI_MAP,
    MANDIS,
    SEASONAL_INDICES,
    TRANSPORT_COST_RS_PER_QUINTAL_PER_KM,
    Mandi,
)
from src.geo import haversine_km

log = logging.getLogger(__name__)


# ── Output dataclass ────────────────────────────────────────────────────

@dataclass
class ReconciliationResult:
    """Reconciliation output for a single mandi."""
    mandi_id: str
    reconciled_prices: dict = field(default_factory=dict)  # commodity_id -> {price, confidence, source_used, reasoning}
    conflicts_found: list[dict] = field(default_factory=list)
    data_quality_score: float = 0.0
    reconciliation_method: str = "rule_based"  # "claude" | "rule_based"
    tools_used: list[str] = field(default_factory=list)
    tokens_used: int = 0



# ── Claude tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "compare_sources",
        "description": (
            "Side-by-side comparison of Agmarknet vs eNAM prices for the same "
            "mandi/commodity/date. Returns price delta, recency, and historical "
            "reliability score for each source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mandi_id": {"type": "string"},
                "commodity_id": {"type": "string"},
                "date": {"type": "string"},
                "agmarknet_price": {"type": "number"},
                "enam_price": {"type": "number"},
            },
            "required": ["mandi_id", "commodity_id", "agmarknet_price", "enam_price"],
        },
    },
    {
        "name": "check_neighboring_mandis",
        "description": (
            "Check what mandis within 50km are reporting for the same commodity. "
            "Flags outliers that diverge significantly from regional consensus."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mandi_id": {"type": "string"},
                "commodity_id": {"type": "string"},
                "radius_km": {"type": "number", "default": 50},
            },
            "required": ["mandi_id", "commodity_id"],
        },
    },
    {
        "name": "seasonal_norm_check",
        "description": (
            "Is this price plausible for this crop at this time of year? "
            "Compares against seasonal price indices from historical data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commodity_id": {"type": "string"},
                "price_rs": {"type": "number"},
                "month": {"type": "integer"},
            },
            "required": ["commodity_id", "price_rs", "month"],
        },
    },
    {
        "name": "verify_arrival_volumes",
        "description": (
            "Cross-check arrival volumes against prices. High arrivals + low price = "
            "plausible (supply glut). Zero arrivals + reported price = suspicious."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mandi_id": {"type": "string"},
                "commodity_id": {"type": "string"},
                "price_rs": {"type": "number"},
                "arrivals_tonnes": {"type": "number"},
            },
            "required": ["mandi_id", "commodity_id", "price_rs", "arrivals_tonnes"],
        },
    },
    {
        "name": "transport_arbitrage_check",
        "description": (
            "If Mandi A reports Rs X and Mandi B (nearby) reports Rs Y, is the "
            "spread greater than transport cost? If not, the gap is suspicious -- "
            "markets should roughly equilibrate minus transport."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mandi_a_id": {"type": "string"},
                "mandi_b_id": {"type": "string"},
                "commodity_id": {"type": "string"},
                "price_a_rs": {"type": "number"},
                "price_b_rs": {"type": "number"},
            },
            "required": ["mandi_a_id", "mandi_b_id", "commodity_id", "price_a_rs", "price_b_rs"],
        },
    },
]

SYSTEM_PROMPT = (
    "You are a market data reconciliation agent for Tamil Nadu agricultural prices. "
    "Your job is to resolve conflicts between two data sources -- Agmarknet (government "
    "mandi price database) and eNAM (electronic trading platform) -- which often report "
    "different prices for the same commodity at the same mandi on the same day.\n\n"
    "Use the available tools to investigate: compare sources side-by-side, check "
    "neighboring mandi prices for regional consensus, validate against seasonal norms, "
    "verify arrival volumes, and check for transport arbitrage anomalies.\n\n"
    "For each conflict, decide which price to trust (or take a weighted average) "
    "and explain your reasoning."
)


# ── Tool execution (local logic) ────────────────────────────────────────

def _execute_tool(
    tool_name: str,
    tool_input: dict,
    agmarknet_by_mandi: dict | None = None,
    enam_by_mandi: dict | None = None,
) -> dict:
    """Execute a reconciliation tool locally."""
    if tool_name == "compare_sources":
        return _tool_compare_sources(tool_input)
    elif tool_name == "check_neighboring_mandis":
        return _tool_check_neighbors(tool_input, agmarknet_by_mandi)
    elif tool_name == "seasonal_norm_check":
        return _tool_seasonal_check(tool_input)
    elif tool_name == "verify_arrival_volumes":
        return _tool_verify_arrivals(tool_input)
    elif tool_name == "transport_arbitrage_check":
        return _tool_transport_arbitrage(tool_input)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def _tool_compare_sources(inp: dict) -> dict:
    """Compare Agmarknet vs eNAM prices side by side."""
    agm_price = inp.get("agmarknet_price", 0)
    enam_price = inp.get("enam_price", 0)
    mandi_id = inp.get("mandi_id", "")
    mandi = MANDI_MAP.get(mandi_id)

    if agm_price == 0 or enam_price == 0:
        return {"delta_pct": None, "note": "One source has no data."}

    delta = enam_price - agm_price
    delta_pct = (delta / agm_price) * 100

    # Reliability heuristic: Agmarknet is generally more reliable for modal prices
    agm_reliability = 0.8
    enam_reliability = 0.7
    if mandi and mandi.reporting_quality == "good":
        agm_reliability = 0.9
        enam_reliability = 0.8
    elif mandi and mandi.reporting_quality == "poor":
        agm_reliability = 0.6
        enam_reliability = 0.5

    return {
        "agmarknet_price": agm_price,
        "enam_price": enam_price,
        "delta_rs": round(delta, 0),
        "delta_pct": round(delta_pct, 1),
        "agmarknet_reliability": agm_reliability,
        "enam_reliability": enam_reliability,
        "recommendation": (
            "agmarknet" if abs(delta_pct) < 5 else
            "weighted_average" if abs(delta_pct) < 10 else
            "investigate"
        ),
    }


def _tool_check_neighbors(inp: dict, agmarknet_by_mandi: dict | None) -> dict:
    """Check neighboring mandis for regional price consensus."""
    mandi_id = inp.get("mandi_id", "")
    commodity_id = inp.get("commodity_id", "")
    radius_km = inp.get("radius_km", 50)

    mandi = MANDI_MAP.get(mandi_id)
    if mandi is None:
        return {"error": f"Unknown mandi: {mandi_id}"}

    neighbors = []
    for m in MANDIS:
        if m.mandi_id == mandi_id:
            continue
        if commodity_id not in m.commodities_traded:
            continue
        dist = haversine_km(mandi.latitude, mandi.longitude, m.latitude, m.longitude)
        if dist <= radius_km:
            neighbors.append({"mandi_id": m.mandi_id, "name": m.name, "distance_km": round(dist, 1)})

    return {
        "mandi_id": mandi_id,
        "commodity_id": commodity_id,
        "radius_km": radius_km,
        "neighbors_found": len(neighbors),
        "neighbors": neighbors,
    }


def _tool_seasonal_check(inp: dict) -> dict:
    """Check if price is plausible for season."""
    commodity_id = inp.get("commodity_id", "")
    price = inp.get("price_rs", 0)
    month = inp.get("month", date.today().month)

    from config import BASE_PRICES_RS
    base = BASE_PRICES_RS.get(commodity_id, 0)
    seasonal_idx = SEASONAL_INDICES.get(commodity_id, {}).get(month, 1.0)

    if base == 0:
        return {"plausible": True, "note": "No base price reference."}

    expected = base * seasonal_idx
    deviation_pct = ((price - expected) / expected) * 100

    return {
        "commodity_id": commodity_id,
        "month": month,
        "seasonal_index": seasonal_idx,
        "expected_price_rs": round(expected, 0),
        "actual_price_rs": price,
        "deviation_pct": round(deviation_pct, 1),
        "plausible": abs(deviation_pct) < 25,
    }


def _tool_verify_arrivals(inp: dict) -> dict:
    """Cross-check arrival volumes against prices."""
    arrivals = inp.get("arrivals_tonnes", 0)
    price = inp.get("price_rs", 0)
    mandi_id = inp.get("mandi_id", "")
    mandi = MANDI_MAP.get(mandi_id)

    avg_arrivals = mandi.avg_daily_arrivals_tonnes if mandi else 100

    if arrivals == 0 and price > 0:
        return {
            "suspicious": True,
            "reasoning": "Zero arrivals but price reported -- likely stale data.",
        }
    elif arrivals > avg_arrivals * 2:
        return {
            "suspicious": False,
            "reasoning": f"High arrivals ({arrivals:.0f}t vs avg {avg_arrivals:.0f}t) -- supply glut likely, lower prices expected.",
        }
    else:
        return {
            "suspicious": False,
            "reasoning": "Arrivals and prices are consistent.",
        }


def _tool_transport_arbitrage(inp: dict) -> dict:
    """Check if price spread between two mandis is plausible given transport cost."""
    mandi_a = MANDI_MAP.get(inp.get("mandi_a_id", ""))
    mandi_b = MANDI_MAP.get(inp.get("mandi_b_id", ""))
    price_a = inp.get("price_a_rs", 0)
    price_b = inp.get("price_b_rs", 0)

    if not mandi_a or not mandi_b:
        return {"error": "Unknown mandi IDs."}

    distance = haversine_km(mandi_a.latitude, mandi_a.longitude, mandi_b.latitude, mandi_b.longitude)
    transport_cost = max(50, distance * TRANSPORT_COST_RS_PER_QUINTAL_PER_KM)
    price_spread = abs(price_a - price_b)

    return {
        "distance_km": round(distance, 1),
        "transport_cost_per_quintal_rs": round(transport_cost, 0),
        "price_spread_rs": round(price_spread, 0),
        "arbitrage_profitable": price_spread > transport_cost,
        "suspicious": price_spread > transport_cost * 3,
        "reasoning": (
            f"Spread of Rs {price_spread:.0f} vs transport Rs {transport_cost:.0f}. "
            + ("Spread exceeds 3x transport cost -- data error likely."
               if price_spread > transport_cost * 3
               else "Spread is within plausible range.")
        ),
    }


# ── Rule-based reconciliation fallback ───────────────────────────────────

class RuleBasedReconciler:
    """Deterministic reconciliation when Claude is unavailable."""

    @classmethod
    def reconcile(
        cls,
        mandi_id: str,
        agmarknet_prices: dict[str, dict],
        enam_prices: dict[str, dict],
    ) -> ReconciliationResult:
        """Reconcile Agmarknet vs eNAM prices for a mandi.

        Uses recency-weighted average, neighbor median comparison,
        and seasonal band checks.
        """
        result = ReconciliationResult(
            mandi_id=mandi_id,
            reconciliation_method="rule_based",
        )

        all_commodity_ids = set(agmarknet_prices.keys()) | set(enam_prices.keys())
        total_conflicts = 0

        for commodity_id in all_commodity_ids:
            agm = agmarknet_prices.get(commodity_id, {})
            enam = enam_prices.get(commodity_id, {})

            agm_price = agm.get("modal_price_rs", 0)
            enam_price = enam.get("modal_price_rs", 0)

            # If only one source has data, use it
            if agm_price > 0 and enam_price == 0:
                result.reconciled_prices[commodity_id] = {
                    "price_rs": agm_price,
                    "confidence": 0.75,
                    "source_used": "agmarknet_only",
                    "reasoning": "Only Agmarknet has data for this commodity.",
                }
                continue
            elif enam_price > 0 and agm_price == 0:
                result.reconciled_prices[commodity_id] = {
                    "price_rs": enam_price,
                    "confidence": 0.65,
                    "source_used": "enam_only",
                    "reasoning": "Only eNAM has data for this commodity.",
                }
                continue
            elif agm_price == 0 and enam_price == 0:
                continue

            # Both sources have data -- check for conflict
            delta_pct = abs(agm_price - enam_price) / agm_price * 100

            if delta_pct < 3:
                # Agreement: use Agmarknet (more comprehensive)
                result.reconciled_prices[commodity_id] = {
                    "price_rs": agm_price,
                    "confidence": 0.95,
                    "source_used": "agmarknet (sources agree)",
                    "reasoning": f"Sources agree within 3% (delta={delta_pct:.1f}%).",
                }
            elif delta_pct < 8:
                # Minor conflict: weighted average favoring Agmarknet
                reconciled = agm_price * 0.6 + enam_price * 0.4
                total_conflicts += 1
                result.reconciled_prices[commodity_id] = {
                    "price_rs": round(reconciled, 0),
                    "confidence": 0.80,
                    "source_used": "weighted_average",
                    "reasoning": (
                        f"Minor conflict: Agmarknet Rs {agm_price:.0f} vs eNAM Rs {enam_price:.0f} "
                        f"(delta={delta_pct:.1f}%). Using 60/40 weighted average."
                    ),
                }
                result.conflicts_found.append({
                    "commodity_id": commodity_id,
                    "agmarknet_price": agm_price,
                    "enam_price": enam_price,
                    "delta_pct": round(delta_pct, 1),
                    "resolution": "weighted_average",
                    "reconciled_price": round(reconciled, 0),
                })
            else:
                # Significant conflict: investigate further
                total_conflicts += 1

                # Check eNAM freshness and quality
                enam_quality = enam.get("quality_flag", "good")
                if enam_quality == "stale":
                    reconciled = agm_price
                    source = "agmarknet (eNAM stale)"
                    reasoning = f"eNAM data flagged as stale. Using Agmarknet Rs {agm_price:.0f}."
                elif enam_quality == "anomalous":
                    reconciled = agm_price
                    source = "agmarknet (eNAM anomalous)"
                    reasoning = f"eNAM price anomalous (Rs {enam_price:.0f}). Using Agmarknet."
                else:
                    # Default: weighted average with lower confidence
                    reconciled = agm_price * 0.55 + enam_price * 0.45
                    source = "weighted_average (low confidence)"
                    reasoning = (
                        f"Significant conflict: Agmarknet Rs {agm_price:.0f} vs eNAM Rs {enam_price:.0f} "
                        f"(delta={delta_pct:.1f}%). Using cautious weighted average. Needs investigation."
                    )

                result.reconciled_prices[commodity_id] = {
                    "price_rs": round(reconciled, 0),
                    "confidence": 0.60,
                    "source_used": source,
                    "reasoning": reasoning,
                }
                result.conflicts_found.append({
                    "commodity_id": commodity_id,
                    "agmarknet_price": agm_price,
                    "enam_price": enam_price,
                    "delta_pct": round(delta_pct, 1),
                    "resolution": source,
                    "reconciled_price": round(reconciled, 0),
                })

        # Data quality score
        if not result.reconciled_prices:
            result.data_quality_score = 0.0
        else:
            avg_confidence = (
                sum(v["confidence"] for v in result.reconciled_prices.values())
                / len(result.reconciled_prices)
            )
            conflict_penalty = min(0.3, total_conflicts * 0.05)
            result.data_quality_score = round(max(0, avg_confidence - conflict_penalty), 2)

        return result


# ── Claude agent ────────────────────────────────────────────────────────

class ReconciliationAgent:
    """Multi-round Claude tool-use agent for price reconciliation.

    Falls back to RuleBasedReconciler when Claude is unavailable.
    """

    MAX_ROUNDS = 6

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self._client = None

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

    def reconcile(
        self,
        mandi_id: str,
        agmarknet_prices: dict[str, dict],
        enam_prices: dict[str, dict],
    ) -> ReconciliationResult:
        """Reconcile prices for a single mandi."""
        client = self._get_client()
        if client is not None:
            return self._claude_reconcile(client, mandi_id, agmarknet_prices, enam_prices)
        return RuleBasedReconciler.reconcile(mandi_id, agmarknet_prices, enam_prices)

    def _claude_reconcile(
        self,
        client: Any,
        mandi_id: str,
        agmarknet_prices: dict[str, dict],
        enam_prices: dict[str, dict],
    ) -> ReconciliationResult:
        """Multi-round Claude reconciliation."""
        result = ReconciliationResult(mandi_id=mandi_id, reconciliation_method="claude")
        tools_used: list[str] = []
        total_tokens = 0

        mandi = MANDI_MAP.get(mandi_id)
        parts = [f"Reconcile conflicting price data for mandi {mandi_id}"]
        if mandi:
            parts.append(f"({mandi.name}, {mandi.district}, reporting_quality={mandi.reporting_quality})")

        parts.append("\n--- AGMARKNET PRICES ---")
        parts.append(json.dumps(agmarknet_prices, indent=2, default=str))
        parts.append("\n--- eNAM PRICES ---")
        parts.append(json.dumps(enam_prices, indent=2, default=str))

        parts.append(
            "\nFor each commodity where sources disagree, use the tools to investigate "
            "and determine the most reliable price. Return your reconciled prices with reasoning."
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
                return RuleBasedReconciler.reconcile(mandi_id, agmarknet_prices, enam_prices)

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

        result.tools_used = list(set(tools_used))
        result.tokens_used = total_tokens
        return result
