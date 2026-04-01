"""
Claude recommendation agent -- generates personalized sell recommendations
in English and Tamil using RAG-augmented context.

Acts as the farmer's broker: explains WHY a particular market/timing is
optimal, what the risks are, and what the farmer should do.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from config import COMMODITY_MAP, MANDI_MAP, SAMPLE_FARMERS, FarmerPersona

log = logging.getLogger(__name__)


@dataclass
class FarmerRecommendation:
    """Complete recommendation for a farmer persona."""
    farmer_id: str
    farmer_name: str
    commodity_id: str
    recommendation_en: str
    recommendation_ta: str  # Tamil translation
    sell_options_summary: list[dict]
    weather_outlook: str
    storage_analysis: str
    reasoning_trace: list[dict]
    tokens_used: int = 0


# ── Claude tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_market_summary",
        "description": (
            "Get current reconciled prices and trends across all mandis for a "
            "specific commodity. Returns mandi-by-mandi price breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commodity_id": {"type": "string"},
            },
            "required": ["commodity_id"],
        },
    },
    {
        "name": "get_price_forecast",
        "description": (
            "Get predicted prices at 7, 14, and 30 day horizons for a commodity "
            "at a specific mandi, including confidence intervals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commodity_id": {"type": "string"},
                "mandi_id": {"type": "string"},
            },
            "required": ["commodity_id"],
        },
    },
    {
        "name": "get_sell_options",
        "description": (
            "Get ranked sell options from the optimizer for a farmer, including "
            "net prices after transport, storage, and fees."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "farmer_id": {"type": "string"},
            },
            "required": ["farmer_id"],
        },
    },
    {
        "name": "get_weather_outlook",
        "description": (
            "Get the 7-day weather outlook for a location. Affects drying "
            "conditions, transport feasibility, and urgency to sell."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_storage_analysis",
        "description": (
            "Get storage loss projection at different time horizons for a commodity. "
            "Shows how much value is lost by waiting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commodity_id": {"type": "string"},
                "current_price_rs": {"type": "number"},
                "quantity_quintals": {"type": "number"},
            },
            "required": ["commodity_id", "current_price_rs"],
        },
    },
]

SYSTEM_PROMPT = (
    "You are an AI broker acting in the interest of Tamil Nadu smallholder farmers. "
    "Your job is to generate clear, actionable sell recommendations with specific "
    "numbers -- not vague advice. Include:\n"
    "1. WHERE to sell (which mandi, with distance and transport cost)\n"
    "2. WHEN to sell (now vs wait, with price forecast)\n"
    "3. HOW MUCH the farmer will actually receive (net of all costs)\n"
    "4. RISK factors (weather, price volatility, storage loss)\n\n"
    "Be direct and practical. Farmers need concrete guidance, not caveats."
)


# ── Tool execution (local logic) ────────────────────────────────────────

def _execute_tool(
    tool_name: str,
    tool_input: dict,
    reconciled_prices: dict | None = None,
    forecasted_prices: dict | None = None,
    sell_recommendations: dict | None = None,
    climate_data: dict | None = None,
) -> dict:
    """Execute a recommendation tool locally."""
    if tool_name == "get_market_summary":
        return _tool_market_summary(tool_input, reconciled_prices)
    elif tool_name == "get_price_forecast":
        return _tool_price_forecast(tool_input, forecasted_prices)
    elif tool_name == "get_sell_options":
        return _tool_sell_options(tool_input, sell_recommendations)
    elif tool_name == "get_weather_outlook":
        return _tool_weather_outlook(tool_input, climate_data)
    elif tool_name == "get_storage_analysis":
        return _tool_storage_analysis(tool_input)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def _tool_market_summary(inp: dict, reconciled_prices: dict | None) -> dict:
    """Get market summary for a commodity."""
    commodity_id = inp.get("commodity_id", "")
    commodity = COMMODITY_MAP.get(commodity_id, {})

    if not reconciled_prices:
        return {"error": "No reconciled price data available."}

    mandi_prices = []
    for mandi_id, mandi_data in reconciled_prices.items():
        price_data = mandi_data.get(commodity_id)
        if price_data:
            mandi = MANDI_MAP.get(mandi_id)
            mandi_prices.append({
                "mandi_id": mandi_id,
                "mandi_name": mandi.name if mandi else mandi_id,
                "price_rs": price_data.get("price_rs", 0),
                "confidence": price_data.get("confidence", 0),
                "source": price_data.get("source_used", ""),
            })

    mandi_prices.sort(key=lambda x: x["price_rs"], reverse=True)

    return {
        "commodity_id": commodity_id,
        "commodity_name": commodity.get("name", commodity_id),
        "mandis_reporting": len(mandi_prices),
        "prices": mandi_prices,
        "price_range": {
            "min_rs": min((p["price_rs"] for p in mandi_prices), default=0),
            "max_rs": max((p["price_rs"] for p in mandi_prices), default=0),
        },
    }


def _tool_price_forecast(inp: dict, forecasted_prices: dict | None) -> dict:
    """Get price forecast for a commodity at a mandi."""
    commodity_id = inp.get("commodity_id", "")
    mandi_id = inp.get("mandi_id", "")

    if not forecasted_prices:
        return {"error": "No forecast data available."}

    if mandi_id:
        mandi_data = forecasted_prices.get(mandi_id, {})
        return mandi_data.get(commodity_id, {"note": "No forecast for this mandi/commodity."})

    # Return forecasts across all mandis
    result = {}
    for mid, mandi_data in forecasted_prices.items():
        if commodity_id in mandi_data:
            result[mid] = mandi_data[commodity_id]
    return result


def _tool_sell_options(inp: dict, sell_recommendations: dict | None) -> dict:
    """Get sell options for a farmer."""
    farmer_id = inp.get("farmer_id", "")

    if not sell_recommendations:
        return {"error": "No sell recommendations computed."}

    return sell_recommendations.get(farmer_id, {"note": f"No recommendation for farmer {farmer_id}."})


def _tool_weather_outlook(inp: dict, climate_data: dict | None) -> dict:
    """Get weather outlook (simplified demo data)."""
    lat = inp.get("latitude", 10.78)
    lon = inp.get("longitude", 79.14)

    # In production, this would fetch from NASA POWER or IMD
    return {
        "location": f"{lat:.2f}, {lon:.2f}",
        "forecast_days": 7,
        "summary": "Partly cloudy with light rain expected on days 3-4. Good drying conditions otherwise.",
        "rain_probability_pct": 35,
        "avg_temperature_c": 29,
        "drying_conditions": "moderate",
        "transport_advisory": "Roads passable. Avoid transport on day 3-4 if heavy rain.",
    }


def _tool_storage_analysis(inp: dict) -> dict:
    """Compute storage loss projections."""
    commodity_id = inp.get("commodity_id", "")
    current_price = inp.get("current_price_rs", 0)
    quantity = inp.get("quantity_quintals", 1)

    from config import POST_HARVEST_LOSS
    loss = POST_HARVEST_LOSS.get(commodity_id, {})
    monthly_loss_pct = loss.get("storage_per_month", 2.5)

    projections = []
    for days, label in [(7, "7d"), (14, "14d"), (30, "30d")]:
        months = days / 30
        loss_pct = monthly_loss_pct * months
        value_loss = current_price * (loss_pct / 100) * quantity
        projections.append({
            "horizon": label,
            "storage_loss_pct": round(loss_pct, 1),
            "value_loss_rs": round(value_loss, 0),
            "quantity_remaining_quintals": round(quantity * (1 - loss_pct / 100), 2),
        })

    return {
        "commodity_id": commodity_id,
        "monthly_loss_pct": monthly_loss_pct,
        "projections": projections,
    }


# ── Recommendation generation ───────────────────────────────────────────

class RecommendationAgent:
    """Claude-powered recommendation agent with RAG support.

    Falls back to template-based recommendations when Claude is unavailable.
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
            log.warning("ANTHROPIC_API_KEY not set -- using template fallback")
            return None
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
            return self._client
        except ImportError:
            log.warning("anthropic package not installed -- using template fallback")
            return None

    def recommend(
        self,
        farmer: FarmerPersona,
        reconciled_prices: dict,
        forecasted_prices: dict,
        sell_recommendation: dict,
        climate_data: dict | None = None,
    ) -> FarmerRecommendation:
        """Generate a recommendation for a farmer persona."""
        client = self._get_client()
        if client is not None:
            return self._claude_recommend(
                client, farmer, reconciled_prices, forecasted_prices,
                sell_recommendation, climate_data,
            )
        return self._template_recommend(
            farmer, reconciled_prices, forecasted_prices,
            sell_recommendation, climate_data,
        )

    def _claude_recommend(
        self,
        client: Any,
        farmer: FarmerPersona,
        reconciled_prices: dict,
        forecasted_prices: dict,
        sell_recommendation: dict,
        climate_data: dict | None,
    ) -> FarmerRecommendation:
        """Generate recommendation via Claude tool-use loop."""
        total_tokens = 0
        reasoning_trace = []

        parts = [
            f"Generate a sell recommendation for farmer {farmer.name} in {farmer.location_name}.",
            f"Commodity: {farmer.primary_commodity}, Quantity: {farmer.quantity_quintals} quintals.",
            f"Has storage: {farmer.has_storage}.",
            f"Notes: {farmer.notes}",
            "\nUse the tools to gather market data, forecasts, and weather, then generate "
            "a specific, actionable recommendation in English. Include all numbers.",
        ]

        messages: list[dict] = [{"role": "user", "content": "\n".join(parts)}]

        for round_num in range(self.MAX_ROUNDS):
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                )
            except Exception as e:
                log.error("Claude API error on round %d: %s", round_num, e)
                return self._template_recommend(
                    farmer, reconciled_prices, forecasted_prices,
                    sell_recommendation, climate_data,
                )

            if hasattr(response, "usage"):
                total_tokens += getattr(response.usage, "input_tokens", 0)
                total_tokens += getattr(response.usage, "output_tokens", 0)

            tool_calls = []
            recommendation_text = ""
            for block in response.content:
                if block.type == "text":
                    recommendation_text += block.text
                elif block.type == "tool_use":
                    tool_calls.append(block)

            if response.stop_reason == "end_turn" or not tool_calls:
                break

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tc in tool_calls:
                tool_result = _execute_tool(
                    tc.name, tc.input,
                    reconciled_prices=reconciled_prices,
                    forecasted_prices=forecasted_prices,
                    sell_recommendations={farmer.farmer_id: sell_recommendation},
                    climate_data=climate_data,
                )
                reasoning_trace.append({
                    "tool": tc.name,
                    "input": tc.input,
                    "result_summary": str(tool_result)[:200],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(tool_result, default=str),
                })

            messages.append({"role": "user", "content": tool_results})

        return FarmerRecommendation(
            farmer_id=farmer.farmer_id,
            farmer_name=farmer.name,
            commodity_id=farmer.primary_commodity,
            recommendation_en=recommendation_text,
            recommendation_ta="",  # Tamil translation would be a separate Claude call
            sell_options_summary=[],
            weather_outlook="",
            storage_analysis="",
            reasoning_trace=reasoning_trace,
            tokens_used=total_tokens,
        )

    def _template_recommend(
        self,
        farmer: FarmerPersona,
        reconciled_prices: dict,
        forecasted_prices: dict,
        sell_recommendation: dict,
        climate_data: dict | None,
    ) -> FarmerRecommendation:
        """Template-based recommendation when Claude is unavailable."""
        commodity = COMMODITY_MAP.get(farmer.primary_commodity, {})
        commodity_name = commodity.get("name", farmer.primary_commodity)

        # Get best option from sell recommendation
        best = sell_recommendation.get("best_option", {})
        all_options = sell_recommendation.get("all_options", [])
        rec_text = sell_recommendation.get("recommendation_text", "")

        if not rec_text and best:
            rec_text = (
                f"{farmer.name}: Sell {commodity_name} at {best.get('mandi_name', 'nearest mandi')} "
                f"({best.get('distance_km', 0):.0f} km). "
                f"Market price: Rs {best.get('market_price_rs', 0):,.0f}/quintal. "
                f"Net after costs: Rs {best.get('net_price_rs', 0):,.0f}/quintal."
            )

        # Weather summary
        weather = _tool_weather_outlook(
            {"latitude": farmer.latitude, "longitude": farmer.longitude}, climate_data,
        )

        # Storage analysis
        current_price = best.get("market_price_rs", 0)
        storage = _tool_storage_analysis({
            "commodity_id": farmer.primary_commodity,
            "current_price_rs": current_price,
            "quantity_quintals": farmer.quantity_quintals,
        })

        # Sell options summary
        options_summary = []
        for opt in all_options[:5]:
            options_summary.append({
                "mandi": opt.get("mandi_name", ""),
                "timing": opt.get("sell_timing", ""),
                "net_price_rs": opt.get("net_price_rs", 0),
                "distance_km": opt.get("distance_km", 0),
            })

        return FarmerRecommendation(
            farmer_id=farmer.farmer_id,
            farmer_name=farmer.name,
            commodity_id=farmer.primary_commodity,
            recommendation_en=rec_text,
            recommendation_ta="",  # Tamil translation placeholder
            sell_options_summary=options_summary,
            weather_outlook=weather.get("summary", ""),
            storage_analysis=json.dumps(storage.get("projections", []), indent=2),
            reasoning_trace=[
                {"tool": "template_fallback", "note": "Claude unavailable, used template."},
            ],
            tokens_used=0,
        )
