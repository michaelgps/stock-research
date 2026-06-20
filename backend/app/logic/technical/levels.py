from __future__ import annotations

import math

from app.data_structure.technical import TechnicalLevelsResponse, TechnicalReferenceLevel, TechnicalZone


_LOOKBACK_DAYS = 252
_MAX_ZONES_PER_SIDE = 3
_MEDIUM_PERCENTILE = 0.60  # top 40% of this ticker's own price-volume bins
_STRONG_PERCENTILE = 0.80  # top 20%
_MAX_MAIN_DISTANCE_PCT = 0.15
_MA_CONFLUENCE_ATR = 0.25


def compute_technical_levels(ticker: str, daily_prices: list[dict]) -> TechnicalLevelsResponse:
    """Compute support/resistance zones from direct price-by-volume clusters."""
    prices = _clean_prices(daily_prices)[-_LOOKBACK_DAYS:]
    if len(prices) < 60:
        raise ValueError(f"Not enough daily prices for {ticker}; need at least 60 trading days.")

    current_price = prices[-1]["close"]
    analysis_date = prices[-1]["date"]
    atr20 = _average_true_range(prices, 20) or max(current_price * 0.02, 0.01)
    atr20_pct = atr20 / current_price

    profile = _build_volume_profile(prices, current_price)
    if not profile:
        raise ValueError(f"Not enough valid volume data for {ticker}.")

    volumes = [item["volume"] for item in profile]
    medium_threshold = _percentile(volumes, _MEDIUM_PERCENTILE)
    strong_threshold = _percentile(volumes, _STRONG_PERCENTILE)
    min_width = max(0.5 * atr20, profile[0]["width"] * 2)

    strong_zones = _zones_from_threshold(
        profile=profile,
        threshold=strong_threshold,
        current_price=current_price,
        min_width=min_width,
        tier="strong",
    )
    medium_zones = _zones_from_threshold(
        profile=profile,
        threshold=medium_threshold,
        current_price=current_price,
        min_width=min_width,
        tier="medium",
    )
    medium_zones = [
        zone for zone in medium_zones
        if not any(_overlap_ratio(zone, strong) >= 0.20 for strong in strong_zones)
    ]

    zones = [
        zone for zone in sorted(strong_zones + medium_zones, key=lambda zone: zone["low"])
        if _distance_to_zone(current_price, zone["low"], zone["high"]) / current_price <= _MAX_MAIN_DISTANCE_PCT
    ]
    moving_averages = _moving_average_levels(prices, current_price)
    _apply_moving_average_confluence(zones, moving_averages, atr20)
    support, resistance, active = _split_and_rank(zones, current_price)
    reference_levels = _reference_levels(prices, current_price, atr20, moving_averages)

    notes = [
        "Daily OHLCV volume-by-price model; not a short-term price prediction.",
        "Each day distributes volume toward typical price instead of evenly across high-low.",
        "Strong zones are continuous price ranges in the top 20% of this ticker's own volume bins.",
        "Medium zones are continuous price ranges in the top 40%, excluding areas already covered by strong zones.",
        "A zone is discarded if it is too narrow versus the stock's normal daily swing.",
        "Main zones only show areas within 15% of the current price.",
        "Moving averages, gaps, and prior highs/lows are references, not volume-confirmed zones.",
    ]
    if not resistance:
        notes.append("No qualified resistance zone above current price from the volume profile.")
    if not support:
        notes.append("No qualified support zone below current price from the volume profile.")

    return TechnicalLevelsResponse(
        ticker=ticker.upper(),
        current_price=round(current_price, 2),
        analysis_date=analysis_date,
        lookback_days=len(prices),
        atr20=round(atr20, 2),
        atr20_pct=round(atr20_pct, 4),
        support_zones=[_to_response_zone(zone, current_price, atr20) for zone in support],
        resistance_zones=[_to_response_zone(zone, current_price, atr20) for zone in resistance],
        active_zones=[_to_response_zone(zone, current_price, atr20) for zone in active],
        reference_levels=reference_levels,
        notes=notes,
    )


def _clean_prices(daily_prices: list[dict]) -> list[dict]:
    rows = []
    for price in daily_prices or []:
        try:
            row = {
                "date": str(price["date"]),
                "open": float(price.get("open") or price.get("close")),
                "high": float(price["high"]),
                "low": float(price["low"]),
                "close": float(price["close"]),
                "volume": float(price.get("volume") or 0),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if row["high"] <= 0 or row["low"] <= 0 or row["close"] <= 0 or row["high"] < row["low"]:
            continue
        rows.append(row)
    rows.sort(key=lambda item: item["date"])
    return rows


def _build_volume_profile(prices: list[dict], current_price: float) -> list[dict]:
    bin_width = _price_bin_width(current_price)
    min_price = math.floor(min(row["low"] for row in prices) / bin_width) * bin_width
    max_price = math.ceil(max(row["high"] for row in prices) / bin_width) * bin_width
    bin_count = int(round((max_price - min_price) / bin_width)) + 1
    bins = [
        {
            "low": min_price + index * bin_width,
            "high": min_price + (index + 1) * bin_width,
            "center": min_price + (index + 0.5) * bin_width,
            "width": bin_width,
            "volume": 0.0,
            "days": set(),
        }
        for index in range(bin_count)
    ]

    for row in prices:
        low_index = max(0, int(math.floor((row["low"] - min_price) / bin_width)))
        high_index = min(bin_count - 1, int(math.floor((row["high"] - min_price) / bin_width)))
        if high_index < low_index:
            continue
        indexes = list(range(low_index, high_index + 1))
        weights = _triangular_volume_weights(row, [bins[index]["center"] for index in indexes])
        weight_total = sum(weights)
        if weight_total <= 0:
            weights = [1.0 for _ in indexes]
            weight_total = len(weights)
        for index in range(low_index, high_index + 1):
            weight = weights[index - low_index] / weight_total
            bins[index]["volume"] += row["volume"] * weight
            bins[index]["days"].add(row["date"])
    return [item for item in bins if item["volume"] > 0]


def _triangular_volume_weights(row: dict, centers: list[float]) -> list[float]:
    typical_price = (row["high"] + row["low"] + row["close"]) / 3
    half_range = max((row["high"] - row["low"]) / 2, 0.01)
    # Keep a small floor so the daily high/low still receive some volume, just less.
    return [max(0.08, 1 - abs(center - typical_price) / half_range) for center in centers]


def _zones_from_threshold(
    profile: list[dict],
    threshold: float,
    current_price: float,
    min_width: float,
    tier: str,
) -> list[dict]:
    max_volume = max(item["volume"] for item in profile) or 1
    zones = []
    run: list[dict] = []
    for item in profile:
        if item["volume"] >= threshold:
            run.append(item)
            continue
        if run:
            zone = _zone_from_run(run, threshold, max_volume, current_price, min_width, tier)
            if zone:
                zones.append(zone)
            run = []
    if run:
        zone = _zone_from_run(run, threshold, max_volume, current_price, min_width, tier)
        if zone:
            zones.append(zone)
    return zones


def _zone_from_run(
    run: list[dict],
    threshold: float,
    max_volume: float,
    current_price: float,
    min_width: float,
    tier: str,
) -> dict | None:
    low = run[0]["low"]
    high = run[-1]["high"]
    width = high - low
    if width < min_width:
        return None

    volumes = [item["volume"] for item in run]
    avg_volume = _average(volumes)
    total_volume = sum(volumes)
    volume_power = min(avg_volume / max_volume, 1.0)
    width_power = min(width / max(current_price * 0.04, min_width), 1.0)
    if tier == "strong":
        score = 80 + 20 * (0.75 * volume_power + 0.25 * width_power)
        evidence = ["volume_cluster", "top_20_volume", "continuous_volume_area"]
    else:
        score = 65 + 14 * (0.75 * volume_power + 0.25 * width_power)
        evidence = ["volume_cluster", "top_40_volume", "continuous_volume_area"]

    center = sum(item["center"] * item["volume"] for item in run) / total_volume if total_volume else (low + high) / 2
    level_type = _classify_zone(current_price, low, high)
    contribution_days = len(set().union(*(item["days"] for item in run))) if run else 0
    score_parts = {
        "volume_density": min(60, 60 * volume_power),
        "zone_width": min(20, 20 * width_power),
        "continuity": 20,
        "ma_confluence": 0,
    }
    tier_floor_key = "strong_tier_floor" if tier == "strong" else "medium_tier_floor"
    tier_floor = 80 if tier == "strong" else 65
    score_parts[tier_floor_key] = max(0, tier_floor - sum(score_parts.values()))
    score_parts = {key: round(value, 1) for key, value in score_parts.items()}
    score = min(100, sum(score_parts.values()))
    return {
        "level_type": level_type,
        "low": low,
        "high": high,
        "center": center,
        "strength_score": round(score, 1),
        "strength_label": "strong" if tier == "strong" else "medium",
        "evidence": evidence,
        "score_parts": score_parts,
        "details": {
            "tier": tier,
            "bin_width": run[0]["width"],
            "bin_count": len(run),
            "volume_threshold": round(threshold, 2),
            "avg_bin_volume": round(avg_volume, 2),
            "total_zone_volume": round(total_volume, 2),
            "contribution_days": contribution_days,
        },
        "dates": sorted(set().union(*(item["days"] for item in run))) if run else [],
    }


def _moving_average_levels(prices: list[dict], current_price: float) -> list[dict]:
    levels = []
    for period, label in ((50, "50D MA"), (200, "200D MA")):
        if len(prices) < period:
            continue
        value = _average([row["close"] for row in prices[-period:]])
        if value <= 0:
            continue
        slope = None
        if len(prices) >= period + 20:
            previous = _average([row["close"] for row in prices[-period - 20:-20]])
            if previous > 0:
                slope = (value - previous) / previous
        levels.append({
            "reference_type": "moving_average",
            "label": label,
            "price": value,
            "level_type": _classify_reference(current_price, value),
            "slope_pct": slope,
        })
    return levels


def _apply_moving_average_confluence(zones: list[dict], moving_averages: list[dict], atr: float) -> None:
    for zone in zones:
        for ma in moving_averages:
            price = ma["price"]
            if zone["low"] <= price <= zone["high"]:
                bonus = 8
            elif _distance_to_zone(price, zone["low"], zone["high"]) <= _MA_CONFLUENCE_ATR * atr:
                bonus = 4
            else:
                continue
            score_parts = zone["score_parts"]
            available_bonus = max(0, 100 - sum(score_parts.values()))
            applied_bonus = min(bonus, available_bonus)
            score_parts["ma_confluence"] = round(score_parts.get("ma_confluence", 0) + applied_bonus, 1)
            zone["strength_score"] = round(min(100, sum(score_parts.values())), 1)
            zone["evidence"].append(ma["label"].replace(" ", "_"))
            if zone["strength_score"] >= 80:
                zone["strength_label"] = "strong"


def _reference_levels(
    prices: list[dict],
    current_price: float,
    atr: float,
    moving_averages: list[dict],
) -> list[TechnicalReferenceLevel]:
    references = []
    for ma in moving_averages:
        references.append(_to_reference_level(
            reference_type=ma["reference_type"],
            level_type=ma["level_type"],
            label=ma["label"],
            current_price=current_price,
            price=ma["price"],
            evidence=["moving_average"],
            raw_details={"slope_pct": ma["slope_pct"]},
        ))
    references.extend(_gap_reference_levels(prices, current_price, atr))
    references.extend(_prior_high_low_references(prices, current_price))
    references = [
        ref for ref in references
        if ref.distance_to_current_pct is None or abs(ref.distance_to_current_pct) <= _MAX_MAIN_DISTANCE_PCT
    ]
    references.sort(key=lambda ref: abs(ref.distance_to_current_pct or 0))
    return references[:8]


def _gap_reference_levels(prices: list[dict], current_price: float, atr: float) -> list[TechnicalReferenceLevel]:
    references = []
    min_gap = max(0.5 * atr, current_price * 0.005)
    for index in range(1, len(prices)):
        prev = prices[index - 1]
        row = prices[index]
        if row["low"] > prev["high"]:
            gap_low = prev["high"]
            gap_high = row["low"]
            if gap_high - gap_low >= min_gap:
                references.append(_to_reference_level(
                    reference_type="gap",
                    level_type=_classify_reference_range(current_price, gap_low, gap_high),
                    label="Gap edge",
                    current_price=current_price,
                    price_low=gap_low,
                    price_high=gap_high,
                    evidence=["gap_up_edge"],
                    raw_details={"date": row["date"], "previous_date": prev["date"]},
                ))
        elif row["high"] < prev["low"]:
            gap_low = row["high"]
            gap_high = prev["low"]
            if gap_high - gap_low >= min_gap:
                references.append(_to_reference_level(
                    reference_type="gap",
                    level_type=_classify_reference_range(current_price, gap_low, gap_high),
                    label="Gap edge",
                    current_price=current_price,
                    price_low=gap_low,
                    price_high=gap_high,
                    evidence=["gap_down_edge"],
                    raw_details={"date": row["date"], "previous_date": prev["date"]},
                ))
    references.sort(key=lambda ref: abs(ref.distance_to_current_pct or 0))
    return references[:4]


def _prior_high_low_references(prices: list[dict], current_price: float) -> list[TechnicalReferenceLevel]:
    high = max(prices[:-1], key=lambda row: row["high"]) if len(prices) > 1 else prices[-1]
    low = min(prices[:-1], key=lambda row: row["low"]) if len(prices) > 1 else prices[-1]
    return [
        _to_reference_level(
            reference_type="prior_high",
            level_type=_classify_reference(current_price, high["high"]),
            label="1Y prior high",
            current_price=current_price,
            price=high["high"],
            evidence=["prior_high_reference"],
            raw_details={"date": high["date"]},
        ),
        _to_reference_level(
            reference_type="prior_low",
            level_type=_classify_reference(current_price, low["low"]),
            label="1Y prior low",
            current_price=current_price,
            price=low["low"],
            evidence=["prior_low_reference"],
            raw_details={"date": low["date"]},
        ),
    ]


def _to_reference_level(
    reference_type: str,
    level_type: str,
    label: str,
    current_price: float,
    evidence: list[str],
    raw_details: dict,
    price: float | None = None,
    price_low: float | None = None,
    price_high: float | None = None,
) -> TechnicalReferenceLevel:
    distance_pct = _reference_distance_to_current_pct(current_price, price, price_low, price_high)
    return TechnicalReferenceLevel(
        reference_type=reference_type,
        level_type=level_type,
        price=round(price, 2) if price is not None else None,
        price_low=round(price_low, 2) if price_low is not None else None,
        price_high=round(price_high, 2) if price_high is not None else None,
        label=label,
        evidence=evidence,
        distance_to_current_pct=distance_pct,
        raw_details=raw_details,
    )


def _split_and_rank(zones: list[dict], current_price: float) -> tuple[list[dict], list[dict], list[dict]]:
    support = [zone for zone in zones if zone["level_type"] == "support"]
    resistance = [zone for zone in zones if zone["level_type"] == "resistance"]
    active = [zone for zone in zones if zone["level_type"] == "active"]

    support.sort(key=lambda zone: (abs(current_price - zone["high"]), -zone["strength_score"]))
    resistance.sort(key=lambda zone: (abs(zone["low"] - current_price), -zone["strength_score"]))
    active.sort(key=lambda zone: zone["strength_score"], reverse=True)
    return support[:_MAX_ZONES_PER_SIDE], resistance[:_MAX_ZONES_PER_SIDE], active[:1]


def _to_response_zone(zone: dict, current_price: float, atr: float) -> TechnicalZone:
    distance = _distance_to_zone(current_price, zone["low"], zone["high"])
    relevance = max(0, 100 - (distance / max(current_price * 0.10, atr, 0.01)) * 100)
    return TechnicalZone(
        level_type=zone["level_type"],
        price_low=round(zone["low"], 2),
        price_high=round(zone["high"], 2),
        center_price=round(zone["center"], 2),
        strength_score=zone["strength_score"],
        relevance_score=round(relevance, 1),
        strength_label=zone["strength_label"],
        evidence=zone["evidence"],
        invalid_if=_invalid_if(zone["level_type"], zone, atr),
        breakout_confirmation=_breakout_confirmation(zone["level_type"], zone, atr),
        distance_to_current_pct=round(distance / current_price, 4) if current_price > 0 else None,
        raw_details={
            "score_parts": zone["score_parts"],
            "kinds": ["volume_profile"],
            "latest_evidence_date": max(zone["dates"]) if zone["dates"] else None,
            "details": zone["details"],
        },
    )


def _classify_zone(current_price: float, low: float, high: float) -> str:
    if high < current_price:
        return "support"
    if low > current_price:
        return "resistance"
    return "active"


def _classify_reference(current_price: float, price: float) -> str:
    if price < current_price:
        return "support"
    if price > current_price:
        return "resistance"
    return "active"


def _classify_reference_range(current_price: float, low: float, high: float) -> str:
    if high < current_price:
        return "support"
    if low > current_price:
        return "resistance"
    return "active"


def _reference_distance_to_current_pct(
    current_price: float,
    price: float | None,
    price_low: float | None,
    price_high: float | None,
) -> float | None:
    if current_price <= 0:
        return None
    if price is not None:
        reference_price = price
    elif price_low is not None and price_high is not None:
        if price_low <= current_price <= price_high:
            return 0
        reference_price = price_low if abs(price_low - current_price) <= abs(price_high - current_price) else price_high
    else:
        return None
    return round((reference_price - current_price) / current_price, 4)


def _invalid_if(level_type: str, zone: dict, atr: float) -> str | None:
    if level_type == "support":
        return f"Daily close below {zone['low'] - 0.25 * atr:.2f}."
    if level_type == "resistance":
        return f"Daily close above {zone['high'] + 0.25 * atr:.2f}."
    return f"Daily close outside {zone['low'] - 0.25 * atr:.2f}-{zone['high'] + 0.25 * atr:.2f}."


def _breakout_confirmation(level_type: str, zone: dict, atr: float) -> str | None:
    if level_type == "resistance":
        return f"Breakout confirmation: close above {zone['high'] + 0.25 * atr:.2f}."
    if level_type == "support":
        return f"Support reclaim: close back above {zone['high']:.2f} after testing the zone."
    return None


def _overlap_ratio(left: dict, right: dict) -> float:
    overlap = max(0.0, min(left["high"], right["high"]) - max(left["low"], right["low"]))
    width = max(left["high"] - left["low"], 0.01)
    return overlap / width


def _distance_to_zone(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0
    return min(abs(price - low), abs(price - high))


def _average_true_range(prices: list[dict], period: int = 20) -> float:
    if len(prices) < 2:
        return 0
    true_ranges = []
    for index in range(1, len(prices)):
        high = prices[index]["high"]
        low = prices[index]["low"]
        prev_close = prices[index - 1]["close"]
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    values = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(values) / len(values) if values else 0


def _price_bin_width(current_price: float) -> float:
    raw = current_price * 0.0035
    if current_price < 30:
        return max(0.1, round(raw, 2))
    if current_price < 100:
        return max(0.5, round(raw * 2) / 2)
    if current_price < 500:
        return max(1.0, round(raw))
    return max(2.0, round(raw))


def _percentile(values: list[float], percentile: float) -> float:
    clean = sorted(values)
    if not clean:
        return 0
    index = min(len(clean) - 1, max(0, int(len(clean) * percentile)))
    return clean[index]


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0
