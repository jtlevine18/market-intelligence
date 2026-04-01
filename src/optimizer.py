"""
Sell Optimizer -- computes when and where to sell for maximum net returns.

For each (mandi, timing) combination, calculates:
  net_price = market_price - transport_cost - storage_loss - mandi_fees

Recommends the optimal combination across space (which mandi) and time
(sell now vs wait 7/14/30 days).
"""

from dataclasses import dataclass, field

from config import (
    COMMODITY_MAP,
    MANDI_MAP,
    MANDIS,
    MIN_TRANSPORT_COST_RS,
    POST_HARVEST_LOSS,
    TRANSPORT_COST_RS_PER_QUINTAL_PER_KM,
    MANDI_FEE_PCT,
    Mandi,
)
from src.geo import haversine_km


@dataclass
class SellOption:
    """A single sell option: specific mandi + timing."""
    mandi_id: str
    mandi_name: str
    commodity_id: str
    sell_timing: str  # "now", "7d", "14d", "30d"
    market_price_rs: float
    transport_cost_rs: float
    storage_loss_rs: float
    storage_cost_rs: float
    mandi_fee_rs: float
    net_price_rs: float
    distance_km: float
    drive_time_min: float
    confidence: float
    price_source: str  # "current" or "forecasted"


@dataclass
class SellRecommendation:
    """Complete sell recommendation for a farmer."""
    commodity_id: str
    commodity_name: str
    quantity_quintals: float
    farmer_lat: float
    farmer_lon: float
    best_option: SellOption
    all_options: list[SellOption]
    potential_gain_rs: float
    recommendation_text: str



def _estimate_drive_time_min(distance_km: float) -> float:
    """Estimate drive time in minutes (avg 30 km/h for rural Tamil Nadu)."""
    return (distance_km / 30) * 60


def optimize_sell(
    farmer_lat: float,
    farmer_lon: float,
    commodity_id: str,
    quantity_quintals: float,
    reconciled_prices: dict[str, dict],
    forecasted_prices: dict[str, dict] | None = None,
    max_distance_km: float = 60.0,
    storage_cost_rs_per_quintal_per_month: float = 20.0,
) -> SellRecommendation:
    """Compute optimal sell strategy across mandis and time horizons.

    Parameters
    ----------
    farmer_lat, farmer_lon : float
        Farmer's location.
    commodity_id : str
        Commodity to sell.
    quantity_quintals : float
        Amount to sell.
    reconciled_prices : dict
        Mandi_id -> {commodity_id: {price_rs, ...}} -- current reconciled prices.
    forecasted_prices : dict, optional
        Mandi_id -> {commodity_id: {price_7d, price_14d, price_30d, ...}}.
    max_distance_km : float
        Maximum travel distance to consider.
    storage_cost_rs_per_quintal_per_month : float
        Warehouse storage rental cost if applicable.

    Returns
    -------
    SellRecommendation
        Best option with all alternatives ranked.
    """
    commodity = COMMODITY_MAP.get(commodity_id, {})
    commodity_name = commodity.get("name", commodity_id)
    loss_data = POST_HARVEST_LOSS.get(commodity_id, {})
    storage_loss_pct_month = loss_data.get("storage_per_month", 2.5)

    if forecasted_prices is None:
        forecasted_prices = {}

    all_options: list[SellOption] = []
    nearest_now_price = 0.0  # for potential gain calculation

    for mandi in MANDIS:
        if commodity_id not in mandi.commodities_traded:
            continue

        distance = haversine_km(farmer_lat, farmer_lon, mandi.latitude, mandi.longitude)
        if distance > max_distance_km:
            continue

        drive_time = _estimate_drive_time_min(distance)
        transport_cost = max(
            MIN_TRANSPORT_COST_RS,
            distance * TRANSPORT_COST_RS_PER_QUINTAL_PER_KM,
        )

        # Current price
        mandi_prices = reconciled_prices.get(mandi.mandi_id, {})
        commodity_price_data = mandi_prices.get(commodity_id, {})
        current_price = commodity_price_data.get("price_rs", 0)

        if current_price <= 0:
            continue

        # Track nearest mandi for potential gain
        if nearest_now_price == 0.0:
            nearest_now_price = current_price - transport_cost - (current_price * MANDI_FEE_PCT / 100)

        # Time horizons
        timings = [
            ("now", current_price, 0, "current"),
        ]

        # Add forecasted prices
        mandi_forecasts = forecasted_prices.get(mandi.mandi_id, {})
        commodity_forecast = mandi_forecasts.get(commodity_id, {})
        for label, key, months in [
            ("7d", "price_7d", 7 / 30),
            ("14d", "price_14d", 14 / 30),
            ("30d", "price_30d", 30 / 30),
        ]:
            forecast_price = commodity_forecast.get(key, 0)
            if forecast_price > 0:
                timings.append((label, forecast_price, months, "forecasted"))

        for timing_label, market_price, storage_months, price_source in timings:
            # Storage loss (% of value per month of storage)
            storage_loss_value = market_price * (storage_loss_pct_month / 100) * storage_months
            storage_cost = storage_cost_rs_per_quintal_per_month * storage_months

            # Mandi fee
            mandi_fee = market_price * (MANDI_FEE_PCT / 100)

            # Net price per quintal
            net_price = market_price - transport_cost - storage_loss_value - storage_cost - mandi_fee

            # Confidence decreases with forecast horizon
            if price_source == "current":
                confidence = commodity_price_data.get("confidence", 0.85)
            else:
                horizon_days = {"7d": 7, "14d": 14, "30d": 30}.get(timing_label, 7)
                confidence = max(0.40, 0.85 - horizon_days * 0.01)

            all_options.append(SellOption(
                mandi_id=mandi.mandi_id,
                mandi_name=mandi.name,
                commodity_id=commodity_id,
                sell_timing=timing_label,
                market_price_rs=round(market_price, 0),
                transport_cost_rs=round(transport_cost, 0),
                storage_loss_rs=round(storage_loss_value, 0),
                storage_cost_rs=round(storage_cost, 0),
                mandi_fee_rs=round(mandi_fee, 0),
                net_price_rs=round(net_price, 0),
                distance_km=round(distance, 1),
                drive_time_min=round(drive_time, 0),
                confidence=round(confidence, 2),
                price_source=price_source,
            ))

    # Sort by net price descending
    all_options.sort(key=lambda o: o.net_price_rs, reverse=True)

    if not all_options:
        # No mandis found -- return empty recommendation
        return SellRecommendation(
            commodity_id=commodity_id,
            commodity_name=commodity_name,
            quantity_quintals=quantity_quintals,
            farmer_lat=farmer_lat,
            farmer_lon=farmer_lon,
            best_option=SellOption(
                mandi_id="", mandi_name="No mandis in range",
                commodity_id=commodity_id, sell_timing="now",
                market_price_rs=0, transport_cost_rs=0, storage_loss_rs=0,
                storage_cost_rs=0, mandi_fee_rs=0, net_price_rs=0,
                distance_km=0, drive_time_min=0, confidence=0, price_source="none",
            ),
            all_options=[],
            potential_gain_rs=0,
            recommendation_text="No mandis trading this commodity within travel distance.",
        )

    best = all_options[0]

    # Nearest mandi selling now (for comparison)
    now_options = [o for o in all_options if o.sell_timing == "now"]
    if now_options:
        nearest_now = min(now_options, key=lambda o: o.distance_km)
        nearest_now_price = nearest_now.net_price_rs

    potential_gain = (best.net_price_rs - nearest_now_price) * quantity_quintals

    # Generate recommendation text
    rec_text = _generate_recommendation_text(
        best, all_options, commodity_name, quantity_quintals, potential_gain, nearest_now_price,
    )

    return SellRecommendation(
        commodity_id=commodity_id,
        commodity_name=commodity_name,
        quantity_quintals=quantity_quintals,
        farmer_lat=farmer_lat,
        farmer_lon=farmer_lon,
        best_option=best,
        all_options=all_options[:15],  # top 15 options
        potential_gain_rs=round(potential_gain, 0),
        recommendation_text=rec_text,
    )


def _generate_recommendation_text(
    best: SellOption,
    all_options: list[SellOption],
    commodity_name: str,
    quantity: float,
    potential_gain: float,
    nearest_now_price: float,
) -> str:
    """Generate plain-language sell recommendation."""
    parts = []

    if best.sell_timing == "now":
        parts.append(
            f"Sell {commodity_name} NOW at {best.mandi_name} ({best.distance_km:.0f} km). "
            f"Market price: Rs {best.market_price_rs:,.0f}/quintal. "
            f"After transport (Rs {best.transport_cost_rs:,.0f}) and fees "
            f"(Rs {best.mandi_fee_rs:,.0f}), net: Rs {best.net_price_rs:,.0f}/quintal."
        )
    else:
        parts.append(
            f"WAIT {best.sell_timing} and sell at {best.mandi_name} ({best.distance_km:.0f} km). "
            f"Forecasted price: Rs {best.market_price_rs:,.0f}/quintal. "
            f"After transport, storage loss (Rs {best.storage_loss_rs:,.0f}), and fees, "
            f"net: Rs {best.net_price_rs:,.0f}/quintal."
        )

    if potential_gain > 0:
        parts.append(
            f"Potential gain over nearest mandi: Rs {potential_gain:,.0f} "
            f"on {quantity:.0f} quintals."
        )

    # Compare best "sell now" vs best "wait"
    now_options = [o for o in all_options if o.sell_timing == "now"]
    wait_options = [o for o in all_options if o.sell_timing != "now"]

    if now_options and wait_options:
        best_now = now_options[0]
        best_wait = wait_options[0]

        if best_wait.net_price_rs > best_now.net_price_rs:
            gain_per_quintal = best_wait.net_price_rs - best_now.net_price_rs
            parts.append(
                f"Waiting advantage: Rs {gain_per_quintal:,.0f}/quintal gain by selling "
                f"{best_wait.sell_timing} at {best_wait.mandi_name} vs selling now at "
                f"{best_now.mandi_name}."
            )
        else:
            parts.append("Prices are expected to decline -- sell sooner rather than later.")

    if best.confidence < 0.6:
        parts.append("Note: forecast confidence is moderate. Monitor prices daily.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Credit readiness assessment — same data, farmer-facing view
# ---------------------------------------------------------------------------

@dataclass
class CreditReadiness:
    """Farmer-facing credit readiness assessment derived from sell optimization."""
    readiness: str            # "strong", "moderate", "not_yet"
    expected_revenue_rs: float
    min_revenue_rs: float
    max_advisable_input_loan_rs: float
    revenue_confidence: float
    loan_to_revenue_pct: float  # if farmer were to borrow max_advisable
    strengths: list[str]
    risks: list[str]
    advice_en: str
    advice_ta: str            # Tamil placeholder


def assess_credit_readiness(
    rec: SellRecommendation,
    has_storage: bool = True,
    typical_input_loan_rs: float | None = None,
) -> CreditReadiness:
    """Assess whether a farmer should seek credit, based on her sell optimization.

    This is advice FOR THE FARMER, not a score for a lender.
    """
    if not rec.all_options or rec.best_option.net_price_rs <= 0:
        return CreditReadiness(
            readiness="not_yet",
            expected_revenue_rs=0,
            min_revenue_rs=0,
            max_advisable_input_loan_rs=0,
            revenue_confidence=0,
            loan_to_revenue_pct=0,
            strengths=[],
            risks=["No market data available to estimate harvest revenue"],
            advice_en="We don't have enough market data to assess your credit readiness right now. Check back after prices are available.",
            advice_ta="",
        )

    best = rec.best_option
    quantity = rec.quantity_quintals

    # Revenue scenarios
    expected_revenue = best.net_price_rs * quantity
    now_options = [o for o in rec.all_options if o.sell_timing == "now"]
    worst_net = min(o.net_price_rs for o in rec.all_options) if rec.all_options else best.net_price_rs
    min_revenue = worst_net * quantity

    # Conservative: advisable loan is up to 40% of expected revenue
    max_advisable = expected_revenue * 0.40

    # If typical input loan provided, use it for comparison
    if typical_input_loan_rs is None:
        # Rough estimate: Rs 15,000-20,000 per hectare for most TN crops
        # Use quantity as proxy (1 quintal ≈ 0.03-0.05 ha depending on yield)
        typical_input_loan_rs = min(max_advisable, 25_000)

    loan_to_revenue = (typical_input_loan_rs / expected_revenue * 100) if expected_revenue > 0 else 999

    # Strengths and risks
    strengths = []
    risks = []

    if best.confidence >= 0.75:
        strengths.append("Strong price forecast confidence")
    elif best.confidence < 0.55:
        risks.append("Price forecast has low confidence — actual revenue may differ")

    if has_storage:
        strengths.append("Storage available — you can wait for better prices if needed")
    else:
        risks.append("No storage — you must sell quickly, limiting price flexibility")

    if expected_revenue > typical_input_loan_rs * 3:
        strengths.append(f"Expected revenue (Rs {expected_revenue:,.0f}) is well above typical input costs")
    elif expected_revenue < typical_input_loan_rs * 1.5:
        risks.append("Expected revenue is close to input costs — tight margins if prices drop")

    if rec.potential_gain_rs > 0:
        strengths.append(f"Agent found Rs {rec.potential_gain_rs:,.0f} more value by optimizing where and when you sell")

    price_spread = best.net_price_rs - worst_net if worst_net > 0 else 0
    if price_spread > best.net_price_rs * 0.15:
        risks.append("Large price variation across markets — revenue depends on selling at the right time and place")

    if len(now_options) < 2:
        risks.append("Few markets trading your commodity nearby")

    # Readiness determination
    if len(risks) == 0 and expected_revenue > typical_input_loan_rs * 2:
        readiness = "strong"
    elif len(risks) <= 1 and expected_revenue > typical_input_loan_rs * 1.5:
        readiness = "moderate"
    else:
        readiness = "not_yet"

    # Generate farmer-facing advice
    advice_en = _credit_advice_en(readiness, expected_revenue, min_revenue, max_advisable, loan_to_revenue, strengths, risks, rec)
    advice_ta = ""  # Tamil via Claude in recommendation agent

    return CreditReadiness(
        readiness=readiness,
        expected_revenue_rs=round(expected_revenue, 0),
        min_revenue_rs=round(min_revenue, 0),
        max_advisable_input_loan_rs=round(max_advisable, 0),
        revenue_confidence=best.confidence,
        loan_to_revenue_pct=round(loan_to_revenue, 1),
        strengths=strengths,
        risks=risks,
        advice_en=advice_en,
        advice_ta=advice_ta,
    )


def _credit_advice_en(
    readiness: str,
    expected: float,
    minimum: float,
    max_advisable: float,
    loan_pct: float,
    strengths: list[str],
    risks: list[str],
    rec: SellRecommendation,
) -> str:
    """Generate plain-language credit readiness advice for the farmer."""
    commodity = rec.commodity_name
    quantity = rec.quantity_quintals
    best = rec.best_option

    if readiness == "strong":
        return (
            f"Your {commodity} harvest ({quantity:.0f} quintals) is expected to earn "
            f"Rs {expected:,.0f} at {best.mandi_name}. "
            f"An input loan of up to Rs {max_advisable:,.0f} looks manageable — "
            f"that's {loan_pct:.0f}% of your expected revenue. "
            f"Consider applying through your local SACCO, FPO, or mobile platform."
        )
    elif readiness == "moderate":
        return (
            f"Your {commodity} harvest ({quantity:.0f} quintals) should earn around "
            f"Rs {expected:,.0f}, but {'prices are uncertain' if any('confidence' in r.lower() for r in risks) else 'margins are tight'}. "
            f"A smaller input loan — up to Rs {max_advisable:,.0f} — could work, "
            f"but keep the amount conservative. "
            f"{'Consider crop insurance to protect against downside.' if not any('storage' in s.lower() for s in strengths) else 'Your storage gives you flexibility to wait for better prices.'}"
        )
    else:
        main_risk = risks[0] if risks else "uncertain revenue"
        return (
            f"Based on current market conditions, applying for a large input loan "
            f"carries risk: {main_risk.lower()}. "
            f"Your expected revenue is Rs {expected:,.0f}, with a worst case of Rs {minimum:,.0f}. "
            f"Consider starting with a very small amount, or waiting until after harvest "
            f"when you have cash in hand."
        )


def credit_readiness_to_dict(cr: CreditReadiness) -> dict:
    """Convert CreditReadiness to a JSON-serializable dict."""
    return {
        "readiness": cr.readiness,
        "expected_revenue_rs": cr.expected_revenue_rs,
        "min_revenue_rs": cr.min_revenue_rs,
        "max_advisable_input_loan_rs": cr.max_advisable_input_loan_rs,
        "revenue_confidence": cr.revenue_confidence,
        "loan_to_revenue_pct": cr.loan_to_revenue_pct,
        "strengths": cr.strengths,
        "risks": cr.risks,
        "advice_en": cr.advice_en,
        "advice_ta": cr.advice_ta,
    }


def recommendation_to_dict(rec: SellRecommendation) -> dict:
    """Convert a SellRecommendation to a JSON-serializable dict."""
    return {
        "commodity_id": rec.commodity_id,
        "commodity_name": rec.commodity_name,
        "quantity_quintals": rec.quantity_quintals,
        "farmer_lat": rec.farmer_lat,
        "farmer_lon": rec.farmer_lon,
        "best_option": {
            "mandi_id": rec.best_option.mandi_id,
            "mandi_name": rec.best_option.mandi_name,
            "sell_timing": rec.best_option.sell_timing,
            "market_price_rs": rec.best_option.market_price_rs,
            "transport_cost_rs": rec.best_option.transport_cost_rs,
            "storage_loss_rs": rec.best_option.storage_loss_rs,
            "mandi_fee_rs": rec.best_option.mandi_fee_rs,
            "net_price_rs": rec.best_option.net_price_rs,
            "distance_km": rec.best_option.distance_km,
            "confidence": rec.best_option.confidence,
            "price_source": rec.best_option.price_source,
        },
        "all_options": [
            {
                "mandi_id": o.mandi_id,
                "mandi_name": o.mandi_name,
                "sell_timing": o.sell_timing,
                "market_price_rs": o.market_price_rs,
                "transport_cost_rs": o.transport_cost_rs,
                "storage_loss_rs": o.storage_loss_rs,
                "mandi_fee_rs": o.mandi_fee_rs,
                "net_price_rs": o.net_price_rs,
                "distance_km": o.distance_km,
                "confidence": o.confidence,
                "price_source": o.price_source,
            }
            for o in rec.all_options
        ],
        "potential_gain_rs": rec.potential_gain_rs,
        "recommendation_text": rec.recommendation_text,
        "farmer_id": "",
        "farmer_name": "",
        "recommendation_tamil": "",
    }
