"""
Forward P/E valuation using automatic strategy ranges.

The model maps weighted forward EPS growth into a starting P/E range, then
adjusts that range for company quality, growth deceleration, estimate
uncertainty, and historical P/E guardrails. It can emit multiple cases for
high-growth companies with clear deceleration risk. All math is deterministic;
no LLM calls.
"""

from datetime import date as dt_date

from app.data_structure.financial import (
    AnalystEstimateData,
    EarningsSurpriseData,
    FinancialDataResponse,
    FinancialStatementData,
)
from app.data_structure.valuation import MultiplesResult


_DEFAULT_PE_BY_SCENARIO = {"bear": 15.0, "base": 18.0, "bull": 22.0}
_MAX_FORWARD_VALUATION_YEARS = 3
_SCENARIO_POSITION = {"bear": "low", "base": "mid", "bull": "high"}
_GROWTH_PE_ANCHORS = [
    # (weighted EPS growth, midpoint P/E, half-width, display label)
    (0.025, 12.5, 2.5, "<5%"),
    (0.075, 18.5, 3.5, "5-10%"),
    (0.125, 23.0, 5.0, "10-15%"),
    (0.200, 28.5, 6.5, "15-25%"),
    (0.325, 36.5, 8.5, "25-40%"),
    (0.450, 40.0, 10.0, ">40%"),
]


def _percentile(values: list[float], percentile: float) -> float:
    """Linear-interpolated percentile for deterministic valuation math."""
    clean = sorted(v for v in values if v is not None and v > 0)
    if not clean:
        return 0
    if len(clean) == 1:
        return clean[0]
    rank = (len(clean) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(clean) - 1)
    weight = rank - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def _nearest_split_factor(share_ratio: float) -> float | None:
    """Detect common stock split factors from large diluted-share jumps."""
    if share_ratio <= 0:
        return None

    common_factors = [
        1 / 20, 1 / 10, 1 / 8, 1 / 7, 1 / 6, 1 / 5, 1 / 4, 1 / 3, 1 / 2, 2 / 3,
        1.5, 2, 3, 4, 5, 6, 7, 8, 10, 20,
    ]
    nearest = min(common_factors, key=lambda factor: abs(share_ratio - factor) / share_ratio)
    relative_error = abs(share_ratio - nearest) / share_ratio

    # Keep the heuristic conservative: small split ratios are easier to confuse
    # with stock issuance or buybacks than large 10-for-1 style changes.
    tolerance = 0.03 if 0.5 <= nearest <= 2 else 0.08
    if relative_error <= tolerance:
        return nearest
    return None


def _share_adjustment_factors(annual_statements: list[FinancialStatementData]) -> dict[int, float]:
    """
    Return per-fiscal-year share multipliers to align EPS with split-adjusted prices.

    Yahoo prices are adjusted to the current share basis. SEC diluted shares are
    often stored from each original filing, so pre-split fiscal years need their
    share count multiplied by later split factors before EPS is compared to
    split-adjusted prices.
    """
    annual = [
        statement for statement in annual_statements
        if statement.diluted_shares and statement.diluted_shares > 0
    ]
    annual.sort(key=lambda statement: statement.fiscal_year)
    factors = {statement.fiscal_year: 1.0 for statement in annual}

    for index in range(1, len(annual)):
        previous = annual[index - 1]
        current = annual[index]
        ratio = current.diluted_shares / previous.diluted_shares
        split_factor = _nearest_split_factor(ratio)
        if split_factor is None:
            continue
        for fiscal_year in factors:
            if fiscal_year <= previous.fiscal_year:
                factors[fiscal_year] *= split_factor

    return factors


def _build_adjusted_ttm_eps_points(
    earnings_surprises: list[EarningsSurpriseData] | None,
) -> list[tuple[dt_date, float]]:
    """
    Build market/adjusted TTM EPS points from quarterly earnings actuals.

    FMP stable/earnings uses earnings announcement dates, so each point becomes
    available on its report date. Finnhub stock/earnings stores fiscal period
    end dates in our model, so it is intentionally not used here to avoid
    look-ahead bias.
    """
    if not earnings_surprises:
        return []

    by_source: dict[str, list[EarningsSurpriseData]] = {}
    for item in earnings_surprises:
        if item.actual_eps is None:
            continue
        if not item.date:
            continue
        by_source.setdefault(item.source or "unknown", []).append(item)

    if len(by_source.get("fmp", [])) < 4:
        return []

    quarters = []
    for item in by_source["fmp"]:
        try:
            report_date = dt_date.fromisoformat(item.date)
        except ValueError:
            continue
        quarters.append((report_date, item.actual_eps))
    quarters.sort(key=lambda row: row[0])
    quarters = quarters[-32:]

    ttm_points = []
    for index in range(3, len(quarters)):
        report_date = quarters[index][0]
        window = quarters[index - 3:index + 1]
        span_days = (window[-1][0] - window[0][0]).days
        if not 240 <= span_days <= 460:
            continue
        ttm_eps = sum(eps for _, eps in window)
        if ttm_eps > 0:
            ttm_points.append((report_date, ttm_eps))
    return ttm_points


def _adjusted_ttm_eps_for_date(
    price_date: dt_date,
    ttm_points: list[tuple[dt_date, float]],
) -> float | None:
    eps = None
    for report_date, ttm_eps in ttm_points:
        if report_date <= price_date:
            eps = ttm_eps
        else:
            break
    return eps


# ---------------------------------------------------------------------------
# Step 1: Compute yearly P/E distribution from daily prices + annual EPS
# ---------------------------------------------------------------------------

def compute_yearly_pe_ranges(
    daily_prices: list[dict],
    statements: list[FinancialStatementData],
    earnings_surprises: list[EarningsSurpriseData] | None = None,
) -> list[dict]:
    """
    For each fiscal year, compute daily trailing P/E values.

    Each row includes a private pe_daily_values list so aggregate 5-year
    P25/P50/P75 can be computed internally. The API response strips that list.
    Adjusted/non-GAAP TTM EPS is preferred when available; annual GAAP EPS is
    the fallback.
    """
    annual = [s for s in statements if s.period == "annual"]
    annual.sort(key=lambda s: s.fiscal_year, reverse=True)
    share_adjustment_factors = _share_adjustment_factors(annual)
    adjusted_ttm_points = _build_adjusted_ttm_eps_points(earnings_surprises)

    fy_eps = {}
    for statement in annual[:5]:
        if statement.net_income and statement.diluted_shares and statement.diluted_shares > 0:
            share_factor = share_adjustment_factors.get(statement.fiscal_year, 1.0)
            adjusted_shares = statement.diluted_shares * share_factor
            eps = statement.net_income / adjusted_shares
            if eps > 0:
                fy_eps[statement.fiscal_year] = {
                    "eps": eps,
                    "end_date": statement.date,
                    "share_adjustment_factor": share_factor,
                }

    if not fy_eps or not daily_prices:
        return []

    price_by_date = {}
    for price in daily_prices:
        date_text = price.get("date", "")
        if date_text:
            price_by_date[date_text] = price

    results = []
    for fy, info in sorted(fy_eps.items(), reverse=True):
        annual_eps = info["eps"]
        end_str = info["end_date"]
        try:
            fy_end = dt_date.fromisoformat(end_str)
        except ValueError:
            continue
        fy_start = fy_end.replace(year=fy_end.year - 1)

        year_prices = []
        for date_text, price in price_by_date.items():
            try:
                price_date = dt_date.fromisoformat(date_text)
            except ValueError:
                continue
            if fy_start <= price_date <= fy_end:
                year_prices.append(price)

        if not year_prices:
            continue

        valid_price_rows = []
        for price in year_prices:
            close = price.get("close")
            if close is None or close <= 0:
                continue
            try:
                price_date = dt_date.fromisoformat(price.get("date", ""))
            except ValueError:
                continue
            valid_price_rows.append((price, price_date, close))

        has_adjusted_coverage = any(
            _adjusted_ttm_eps_for_date(price_date, adjusted_ttm_points) is not None
            for _, price_date, _ in valid_price_rows
        )

        price_eps_rows = []
        adjusted_count = 0
        for price, price_date, close in valid_price_rows:
            adjusted_eps = _adjusted_ttm_eps_for_date(price_date, adjusted_ttm_points)
            if adjusted_eps is None and has_adjusted_coverage:
                continue
            eps = adjusted_eps if adjusted_eps is not None else annual_eps
            if eps <= 0:
                continue
            if adjusted_eps is not None:
                adjusted_count += 1
            price_eps_rows.append((price, eps, close / eps))

        if not price_eps_rows:
            continue

        highs = [price["high"] for price, _, _ in price_eps_rows if "high" in price]
        lows = [price["low"] for price, _, _ in price_eps_rows if "low" in price]
        closes = [price["close"] for price, _, _ in price_eps_rows if "close" in price]
        eps_values = [eps for _, eps, _ in price_eps_rows]
        pe_daily_values = [pe for _, _, pe in price_eps_rows]

        if not highs or not lows or not closes or not eps_values:
            continue

        if not pe_daily_values:
            continue
        if adjusted_count == len(price_eps_rows):
            eps_basis = "adjusted_ttm_eps"
        else:
            eps_basis = "gaap_annual_eps"

        results.append({
            "fy": fy,
            "eps": round(_percentile(eps_values, 0.50), 2),
            "eps_basis": eps_basis,
            "adjusted_eps_observations": adjusted_count,
            "share_adjustment_factor": round(info.get("share_adjustment_factor", 1.0), 4),
            "pe_low": round(min(pe_daily_values), 1),
            "pe_high": round(max(pe_daily_values), 1),
            "pe_avg": round(sum(pe_daily_values) / len(pe_daily_values), 1),
            "pe_p25": round(_percentile(pe_daily_values, 0.25), 1),
            "pe_p50": round(_percentile(pe_daily_values, 0.50), 1),
            "pe_p75": round(_percentile(pe_daily_values, 0.75), 1),
            "price_high": round(max(highs), 2),
            "price_low": round(min(lows), 2),
            "pe_daily_values": [round(value, 2) for value in pe_daily_values],
        })

    return results


# ---------------------------------------------------------------------------
# Step 2: Determine automatic P/E range cases
# ---------------------------------------------------------------------------

def _fmp_forward_estimates(estimates: list[AnalystEstimateData] | None) -> list[AnalystEstimateData]:
    rows = [
        estimate for estimate in estimates or []
        if (
            estimate.eps_estimate is not None
            and estimate.eps_estimate > 0
            and estimate.source in {"fmp", "yfinance"}
            and estimate.period
            and str(estimate.period).isdigit()
        )
    ]
    rows.sort(key=lambda estimate: int(estimate.period))
    return rows[:_MAX_FORWARD_VALUATION_YEARS]


def _weighted_future_growth(
    estimates: list[AnalystEstimateData] | None,
    target_period: str | None,
    earnings_surprises: list[EarningsSurpriseData] | None = None,
    latest_fiscal_year_end: str | None = None,
    latest_actual_eps: float | None = None,
) -> tuple[float | None, list[dict]]:
    """
    Estimate the growth that should support the P/E on a target fiscal-year EPS.

    For a fiscal-year target with a prior estimate available, the target year's
    own EPS growth is the main driver: 70% on prior FY -> target FY, and 30% on
    target FY -> next FY. This avoids assigning an FY2028 valuation multiple
    from FY2029 -> FY2030 growth while skipping FY2027 -> FY2028 growth.

    If the target is the first forward estimate, there is no prior estimate in
    the estimate set, so we fall back to the next two forward segments.
    """
    rows = _fmp_forward_estimates(estimates)
    if not rows or not target_period:
        return None, []

    target = str(target_period)
    target_index = next((idx for idx, row in enumerate(rows) if str(row.period) == target), None)
    if target_index is None:
        return None, []

    weighted_pairs = []
    segments = []
    if target_index > 0:
        weighted_pairs = [
            (target_index - 1, target_index, 0.70),
            (target_index, target_index + 1, 0.30),
        ]
    else:
        partial_growth = _partial_year_remaining_growth(
            estimates=rows,
            target_index=target_index,
            earnings_surprises=earnings_surprises,
            latest_fiscal_year_end=latest_fiscal_year_end,
            latest_actual_eps=latest_actual_eps,
        )
        if partial_growth is not None:
            segments.append(partial_growth)
            weighted_pairs = [(target_index, target_index + 1, 0.30)]
        else:
            weighted_pairs = [
                (target_index, target_index + 1, 0.70),
                (target_index + 1, target_index + 2, 0.30),
            ]

    if not weighted_pairs and not segments:
        weighted_pairs = [
            (target_index, target_index + 1, 0.70),
            (target_index + 1, target_index + 2, 0.30),
        ]

    for start_index, end_index, weight in weighted_pairs:
        if start_index < 0 or end_index >= len(rows):
            continue
        start = rows[start_index]
        end = rows[end_index]
        if not start.eps_estimate or start.eps_estimate <= 0 or not end.eps_estimate:
            continue
        growth = (end.eps_estimate / start.eps_estimate) - 1
        segments.append({
            "from_period": str(start.period),
            "to_period": str(end.period),
            "growth": growth,
            "weight": weight,
        })

    if not segments:
        return None, []

    total_weight = sum(segment["weight"] for segment in segments)
    weighted_growth = sum(segment["growth"] * segment["weight"] for segment in segments) / total_weight
    return weighted_growth, segments


def _partial_year_remaining_growth(
    estimates: list[AnalystEstimateData],
    target_index: int,
    earnings_surprises: list[EarningsSurpriseData] | None,
    latest_fiscal_year_end: str | None,
    latest_actual_eps: float | None,
) -> dict | None:
    """
    Compute first-forward-year growth using already-reported quarters.

    Example for NVDA after Q1 FY2027 is reported:
      remaining_growth = (FY2027 estimate - FY2027 Q1 actual)
                       / (FY2026 full actual - FY2026 Q1 actual) - 1
    """
    if target_index != 0 or not estimates or not latest_fiscal_year_end:
        return None
    target = estimates[target_index]
    if not target.eps_estimate or target.eps_estimate <= 0:
        return None

    quarters = []
    for item in earnings_surprises or []:
        if item.source != "fmp" or item.actual_eps is None or not item.date:
            continue
        try:
            report_date = dt_date.fromisoformat(item.date)
        except ValueError:
            continue
        quarters.append((report_date, item.actual_eps))
    quarters.sort(key=lambda row: row[0])
    if len(quarters) < 5:
        return None

    try:
        fy_end = dt_date.fromisoformat(latest_fiscal_year_end)
    except ValueError:
        return None

    q4_index = next((idx for idx, row in enumerate(quarters) if row[0] > fy_end), None)
    if q4_index is None or q4_index < 3:
        return None

    reported_target_quarters = quarters[q4_index + 1:q4_index + 4]
    if not reported_target_quarters:
        return None

    reported_count = min(len(reported_target_quarters), 3)
    target_reported_eps = sum(eps for _, eps in reported_target_quarters[:reported_count])

    prior_same_quarters = quarters[q4_index - 3:q4_index - 3 + reported_count]
    prior_full_quarters = quarters[q4_index - 3:q4_index + 1]
    if len(prior_same_quarters) != reported_count or len(prior_full_quarters) != 4:
        return None

    prior_same_eps = sum(eps for _, eps in prior_same_quarters)
    prior_full_eps = sum(eps for _, eps in prior_full_quarters)
    if prior_full_eps <= 0 and latest_actual_eps:
        prior_full_eps = latest_actual_eps

    target_remaining_eps = target.eps_estimate - target_reported_eps
    prior_remaining_eps = prior_full_eps - prior_same_eps
    if target_remaining_eps <= 0 or prior_remaining_eps <= 0:
        return None

    growth = (target_remaining_eps / prior_remaining_eps) - 1
    if growth <= -0.95 or growth > 3.0:
        return None

    previous_period = str(int(target.period) - 1) if str(target.period).isdigit() else "prior_fy"
    return {
        "from_period": f"{previous_period}_remaining_after_{reported_count}q",
        "to_period": f"{target.period}_remaining_after_{reported_count}q",
        "growth": growth,
        "weight": 0.70,
        "basis": "partial_year_remaining_eps",
        "reported_quarters": reported_count,
        "target_reported_eps": round(target_reported_eps, 4),
        "target_remaining_eps": round(target_remaining_eps, 4),
        "prior_same_period_eps": round(prior_same_eps, 4),
        "prior_remaining_eps": round(prior_remaining_eps, 4),
    }


def _historical_pe_stats(yearly_pe_ranges: list[dict]) -> dict:
    pe_values: list[float] = []
    for row in yearly_pe_ranges or []:
        pe_values.extend(row.get("pe_daily_values") or [])
    if not pe_values:
        return {}
    latest = max(yearly_pe_ranges or [], key=lambda row: row.get("fy", 0), default={})
    return {
        "p25": round(_percentile(pe_values, 0.25), 1),
        "p50": round(_percentile(pe_values, 0.50), 1),
        "p75": round(_percentile(pe_values, 0.75), 1),
        "p90": round(_percentile(pe_values, 0.90), 1),
        "recent_p50": latest.get("pe_p50"),
        "recent_p75": latest.get("pe_p75"),
        "years_used": len(yearly_pe_ranges or []),
        "daily_observations": len(pe_values),
    }


def _growth_curve(weighted_growth: float | None) -> tuple[str, float, float]:
    """Map forward growth to a smooth P/E range so small input changes do not jump buckets."""
    if weighted_growth is None:
        return "unknown", 18.0, 28.0

    growth_pct = weighted_growth * 100
    if growth_pct < 5:
        label = "<5%"
    elif growth_pct < 10:
        label = "5-10%"
    elif growth_pct < 15:
        label = "10-15%"
    elif growth_pct < 25:
        label = "15-25%"
    elif growth_pct < 40:
        label = "25-40%"
    else:
        label = ">40%"

    growth = max(0.0, min(weighted_growth, _GROWTH_PE_ANCHORS[-1][0]))
    previous = _GROWTH_PE_ANCHORS[0]
    if growth <= previous[0]:
        center, half_width = previous[1], previous[2]
        return label, round(center - half_width, 1), round(center + half_width, 1)

    for current in _GROWTH_PE_ANCHORS[1:]:
        if growth <= current[0]:
            span = current[0] - previous[0]
            weight = (growth - previous[0]) / span if span > 0 else 0
            center = previous[1] + (current[1] - previous[1]) * weight
            half_width = previous[2] + (current[2] - previous[2]) * weight
            return label, round(max(8.0, center - half_width), 1), round(center + half_width, 1)
        previous = current

    center, half_width = _GROWTH_PE_ANCHORS[-1][1], _GROWTH_PE_ANCHORS[-1][2]
    return label, round(center - half_width, 1), round(center + half_width, 1)


def _company_quality_adjustment(data: FinancialDataResponse) -> float:
    market_cap = data.company.market_cap or 0
    sector = (data.company.sector or "").lower()
    industry = (data.company.industry or "").lower()
    adjustment = 0.0
    if market_cap >= 1_000_000_000_000:
        adjustment += 3.0
    elif market_cap >= 300_000_000_000:
        adjustment += 1.5
    if "technology" in sector or "communication" in sector:
        adjustment += 1.0
    if "semiconductor" in industry:
        adjustment -= 1.0
    if "auto" in industry or "vehicle" in industry:
        adjustment -= 4.0
    return adjustment


def _growth_deceleration(segments: list[dict]) -> float | None:
    clean = [segment for segment in segments if segment.get("growth") is not None]
    if len(clean) < 2:
        return None
    return clean[0]["growth"] - clean[1]["growth"]


def _deceleration_adjustment(deceleration: float | None) -> float:
    if deceleration is None:
        return 0.0
    decel_pct = deceleration * 100
    if decel_pct > 30:
        return -9.0
    if decel_pct > 15:
        return -5.0
    if decel_pct > 5:
        return -2.0
    return 0.0


def _uncertainty_adjustment(data: FinancialDataResponse, weighted_growth: float | None, segments: list[dict]) -> tuple[float, list[str]]:
    industry = (data.company.industry or "").lower()
    sector = (data.company.sector or "").lower()
    adjustment = 0.0
    reasons: list[str] = []
    if "semiconductor" in industry:
        adjustment -= 3.0
        reasons.append("semiconductor_cycle_risk:-3.0")
    if any(term in industry for term in ["entertainment", "streaming", "media"]):
        adjustment -= 2.0
        reasons.append("media_or_streaming_uncertainty:-2.0")
    if "communication" in sector and any(term in industry for term in ["internet", "content", "advertising"]):
        adjustment -= 1.0
        reasons.append("internet_content_advertising_uncertainty:-1.0")
    if weighted_growth is not None and weighted_growth > 0.45:
        adjustment -= 2.0
        reasons.append("very_high_growth_visibility_risk:-2.0")
    if len(segments) < 2:
        adjustment -= 2.0
        reasons.append("insufficient_forward_growth_segments:-2.0")
    if any(segment.get("growth", 0) < 0 for segment in segments):
        adjustment -= 5.0
        reasons.append("negative_forward_growth_segment:-5.0")
    return adjustment, reasons


def _shift_range(low: float, high: float, adjustment: float) -> tuple[float, float]:
    return max(5.0, low + adjustment), max(7.0, high + adjustment)


def _apply_historical_guardrail(low: float, high: float, hist: dict) -> tuple[float, float]:
    """Use history as a soft anchor, not a hard ceiling."""
    guardrail = hist.get("recent_p75") or hist.get("p75")
    if guardrail:
        high = guardrail + (high - guardrail) * 0.5 if high > guardrail else high
    p90 = hist.get("p90")
    if p90 and high > p90:
        high = p90 + (high - p90) * 0.25
    if high < low + 5:
        high = low + 5
    return round(low, 1), round(high, 1)


def _case(label: str, low: float, high: float, eps: float | None, current_price: float | None, details: dict) -> dict:
    mid = (low + high) / 2
    value_low = round((eps or 0) * low, 2) if eps else None
    value_mid = round((eps or 0) * mid, 2) if eps else None
    value_high = round((eps or 0) * high, 2) if eps else None
    current = current_price or 0
    return {
        "label": label,
        "method": "auto_pe_range",
        "pe_low": round(low, 1),
        "pe_mid": round(mid, 1),
        "pe_high": round(high, 1),
        "value_low": value_low,
        "value_mid": value_mid,
        "value_high": value_high,
        "upside_low_pct": round((value_low - current) / current, 4) if value_low is not None and current > 0 else None,
        "upside_mid_pct": round((value_mid - current) / current, 4) if value_mid is not None and current > 0 else None,
        "upside_high_pct": round((value_high - current) / current, 4) if value_high is not None and current > 0 else None,
        **details,
    }


def compute_auto_pe_cases(
    data: FinancialDataResponse,
    yearly_pe_ranges: list[dict],
    target_period: str | None,
    forward_eps: float | None,
    current_price: float | None,
    latest_fiscal_year_end: str | None = None,
    latest_actual_eps: float | None = None,
) -> list[dict]:
    """Build automatic strategy P/E range cases from growth, quality, risk, and history."""
    weighted_growth, segments = _weighted_future_growth(
        data.analyst_estimates,
        target_period,
        earnings_surprises=data.earnings_surprises,
        latest_fiscal_year_end=latest_fiscal_year_end,
        latest_actual_eps=latest_actual_eps,
    )
    growth_curve, initial_low, initial_high = _growth_curve(weighted_growth)
    hist = _historical_pe_stats(yearly_pe_ranges)
    quality_adj = _company_quality_adjustment(data)
    deceleration = _growth_deceleration(segments)
    decel_adj = _deceleration_adjustment(deceleration)
    uncertainty_adj, uncertainty_reasons = _uncertainty_adjustment(data, weighted_growth, segments)
    industry = (data.company.industry or "").lower()
    is_semiconductor = "semiconductor" in industry

    adjusted_low, adjusted_high = _shift_range(
        initial_low,
        initial_high,
        quality_adj + decel_adj + uncertainty_adj,
    )
    adjusted_low, adjusted_high = _apply_historical_guardrail(adjusted_low, adjusted_high, hist)

    common_details = {
        "weighted_eps_growth": round(weighted_growth, 4) if weighted_growth is not None else None,
        "growth_curve": growth_curve,
        "quality_adjustment": round(quality_adj, 1),
        "deceleration_adjustment": round(decel_adj, 1),
        "uncertainty_adjustment": round(uncertainty_adj, 1),
        "uncertainty_reasons": uncertainty_reasons,
        "historical_guardrail_pe": hist.get("recent_p75") or hist.get("p75"),
        "growth_segments": [
            {
                **segment,
                "growth": round(segment["growth"], 4),
                "weight": round(segment["weight"], 2),
            }
            for segment in segments
        ],
        "explanation": (
            f"Growth curve {growth_curve}; adjusted for company quality, growth deceleration, "
            "estimate uncertainty, and a soft historical P/E guardrail."
        ),
    }

    cases = [_case("auto_base", adjusted_low, adjusted_high, forward_eps, current_price, common_details)]

    if weighted_growth is not None and weighted_growth > 0.35 and deceleration is not None and deceleration > 0.20:
        high_low, high_high = _apply_historical_guardrail(30.0, 42.0, hist)
        decel_low, decel_high = _apply_historical_guardrail(22.0, 32.0, hist)
        cases = [
            _case(
                "high_growth",
                high_low,
                high_high,
                forward_eps,
                current_price,
                {**common_details, "explanation": "High-growth case: near-term growth remains strong enough to support a premium P/E range."},
            ),
            _case(
                "deceleration",
                decel_low,
                decel_high,
                forward_eps,
                current_price,
                {**common_details, "explanation": "Deceleration case: high FY1 growth is discounted because forward growth steps down materially."},
            ),
        ]
    elif weighted_growth is not None and weighted_growth > 0.40 and is_semiconductor:
        base_low, base_high = _apply_historical_guardrail(30.0, 40.0, hist)
        visibility_low, visibility_high = _apply_historical_guardrail(40.0, 50.0, hist)
        cases = [
            _case(
                "base_visibility",
                base_low,
                base_high,
                forward_eps,
                current_price,
                {**common_details, "explanation": "Base visibility case: strong semiconductor growth is valued at a premium, but without assuming the most optimistic cycle multiple."},
            ),
            _case(
                "high_visibility",
                visibility_low,
                visibility_high,
                forward_eps,
                current_price,
                {**common_details, "explanation": "High-visibility case: stronger confidence in the AI/compute cycle supports the upper premium range."},
            ),
        ]

    return cases

# ---------------------------------------------------------------------------
# Step 3: 5-year forward valuation trend
# ---------------------------------------------------------------------------

def compute_forward_trend(
    forward_estimates: list[AnalystEstimateData],
    pe_multiple: float | None = None,
    pe_by_period: dict[str, float] | None = None,
) -> list[dict]:
    """
    Apply the period-specific base P/E multiple to each year's forward EPS.
    Returns list of {"year": str, "eps": float, "implied_price": float}.
    """
    fmp_estimates = _fmp_forward_estimates(forward_estimates)

    trend = []
    for estimate in fmp_estimates:
        period_pe = (pe_by_period or {}).get(str(estimate.period), pe_multiple)
        if period_pe is None:
            continue
        price = round(estimate.eps_estimate * period_pe, 2)
        trend.append({
            "year": estimate.period,
            "eps": round(estimate.eps_estimate, 2),
            "pe_multiple": round(period_pe, 1),
            "implied_price": price,
        })
    return trend


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------

async def fetch_daily_prices(ticker: str, db=None) -> list[dict]:
    """Fetch ~5 years of daily prices. Uses tb_market_price + yfinance."""
    if db is not None:
        from app.services.market_price_service import ensure_daily_prices
        return ensure_daily_prices(db, ticker)

    from app.logic.data_sources.yfinance_client import get_daily_prices
    return get_daily_prices(ticker)


async def fetch_peer_pe(
    ticker: str,
    ticker_eps_growth: float | None = None,
    industry: str | None = None,
    db=None,
) -> dict:
    """Fetch peer forward P/E data for manually supplied peers only."""
    ticker = ticker.upper()
    manual_peers: list[str] = []
    if db is not None:
        from app.db.financial import CompanyProfile
        from app.repositories import data_pull_log_repository

        today = data_pull_log_repository.today_str()
        profile = db.query(CompanyProfile).filter(
            CompanyProfile.ticker == ticker,
            CompanyProfile.source == "manual",
        ).order_by(CompanyProfile.profile_date.desc(), CompanyProfile.id.desc()).first()
        if profile is None:
            profile = db.query(CompanyProfile).filter(
                CompanyProfile.ticker == ticker,
                CompanyProfile.source == "fmp",
            ).order_by(CompanyProfile.profile_date.desc(), CompanyProfile.id.desc()).first()
        peers_json = profile.peers_json if profile else None
        if isinstance(peers_json, dict):
            manual_peers = [p.upper() for p in peers_json.get("manual", []) if p]
        elif isinstance(peers_json, list):
            manual_peers = []

        if not manual_peers:
            return {
                "peers": [],
                "median_pe": None,
                "cap_weighted_pe": None,
                "median_peg": None,
                "growth_adjusted_pe": None,
                "method": "manual_peers_required",
            }

        cached = db.query(CompanyProfile).filter(
            CompanyProfile.ticker == ticker,
            CompanyProfile.profile_date == today,
            CompanyProfile.source == "manual_peer_fmp",
        ).first()
        if cached and cached.raw_data_json and data_pull_log_repository.has_success(
            db, ticker, "peer_comparison", "fmp", today
        ):
            return cached.raw_data_json

    from app.logic.data_sources.fmp import get_peer_forward_pe
    data = await get_peer_forward_pe(
        ticker,
        ticker_eps_growth=ticker_eps_growth,
        industry=industry,
        peers=manual_peers,
    )

    if db is not None:
        from app.db.financial import CompanyProfile
        from app.repositories import data_pull_log_repository

        today = data_pull_log_repository.today_str()
        row = db.query(CompanyProfile).filter(
            CompanyProfile.ticker == ticker,
            CompanyProfile.profile_date == today,
            CompanyProfile.source == "manual_peer_fmp",
        ).first()
        if row:
            row.raw_data_json = data
        else:
            db.add(CompanyProfile(
                ticker=ticker,
                profile_date=today,
                source="manual_peer_fmp",
                sector=None,
                industry=industry,
                market_cap=None,
                current_price=None,
                shares_outstanding=None,
                peers_json=data.get("peers", []) if isinstance(data, dict) else [],
                raw_data_json=data,
            ))
        db.commit()
        data_pull_log_repository.mark(
            db,
            ticker,
            "peer_comparison",
            "fmp",
            "success",
            records_inserted=1 if data else 0,
        )

    return data


def get_forward_eps_growth(
    estimates: list[AnalystEstimateData],
    actual_eps: float | None = None,
    fy_end_date: str | None = None,
) -> float | None:
    """
    Compute forward EPS growth anchored on latest actual EPS (2-year CAGR).

    Used for data quality and optional peer reference calculations, not for
    setting the final historical-percentile P/E multiple.
    """
    from app.logic.data_sources.fmp import _compute_eps_growth

    class _Est:
        def __init__(self, period, eps_estimate):
            self.period = period
            self.eps_estimate = eps_estimate

    fmp_estimates = [
        estimate for estimate in estimates
        if estimate.eps_estimate is not None and estimate.source == "fmp"
    ]
    est_objects = [_Est(estimate.period, estimate.eps_estimate) for estimate in fmp_estimates]

    return _compute_eps_growth(actual_eps, fy_end_date, est_objects)


def compute_justified_pe(dcf_per_share: float, forward_eps: float | None) -> float | None:
    """
    Compute justified P/E = DCF intrinsic value / forward EPS.
    This shows what P/E the market would need to assign to match our DCF valuation.
    """
    if forward_eps is None or forward_eps <= 0 or dcf_per_share <= 0:
        return None
    return dcf_per_share / forward_eps


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_multiples(
    data: FinancialDataResponse,
    scenario: str,
    forward_eps: float | None,
    yearly_pe_ranges: list[dict] | None = None,
    peer_pe_data: dict | None = None,
    target_period: str | None = None,
    latest_fiscal_year_end: str | None = None,
    latest_actual_eps: float | None = None,
) -> MultiplesResult:
    """
    Compute per-share value using the midpoint of the automatic P/E range.
    DCF-derived justified P/E is reported only as a cross-check, not as an input.
    """
    cases = compute_auto_pe_cases(
        data=data,
        yearly_pe_ranges=yearly_pe_ranges or [],
        target_period=target_period,
        forward_eps=forward_eps,
        current_price=data.company.current_price,
        latest_fiscal_year_end=latest_fiscal_year_end,
        latest_actual_eps=latest_actual_eps,
    )
    selected = cases[0] if cases else {}
    position = _SCENARIO_POSITION.get(scenario, "mid")
    pe_mult = selected.get(f"pe_{position}") or _DEFAULT_PE_BY_SCENARIO[scenario]
    details = {
        "method": "auto_pe_range",
        "cases": cases,
        "selected_case": selected.get("label"),
        "selected_position": position,
    }

    forward_pe_value = None
    if forward_eps is not None and forward_eps > 0:
        forward_pe_value = round(forward_eps * pe_mult, 2)

    return MultiplesResult(
        forward_pe_value=forward_pe_value,
        forward_eps=round(forward_eps, 2) if forward_eps else None,
        pe_multiple=pe_mult,
        pe_low=selected.get("pe_low"),
        pe_high=selected.get("pe_high"),
        justified_pe=None,
        details=details,
    )
