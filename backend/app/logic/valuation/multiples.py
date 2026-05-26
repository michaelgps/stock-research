"""
Forward P/E valuation from the ticker's historical P/E distribution.

P/E is determined from the last ~5 fiscal years of daily trailing P/E:
  bear = P25
  base = P50 / median
  bull = P75

Note on denominator mismatch: historical P/E uses trailing EPS (net income /
diluted shares from filings), but we apply it to forward EPS. This is a known
limitation: ideally we'd use historical forward P/E, but that requires
I/B/E/S-style historical consensus data we don't have.

All math is deterministic; no LLM calls.
"""

from datetime import date as dt_date

from app.data_structure.financial import (
    AnalystEstimateData,
    EarningsSurpriseData,
    FinancialDataResponse,
    FinancialStatementData,
)
from app.data_structure.valuation import MultiplesResult


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

        price_eps_rows = []
        adjusted_count = 0
        has_adjusted_coverage = any(
            fy_start <= report_date <= fy_end for report_date, _ in adjusted_ttm_points
        )
        for price in year_prices:
            close = price.get("close")
            if close is None or close <= 0:
                continue
            try:
                price_date = dt_date.fromisoformat(price.get("date", ""))
            except ValueError:
                continue
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
        elif adjusted_count:
            eps_basis = "mixed_adjusted_ttm_and_gaap"
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
# Step 2: Determine P/E multiple from historical percentiles
# ---------------------------------------------------------------------------

def determine_pe_multiple(
    yearly_pe_ranges: list[dict],
    peer_pe_data: dict | None,
    scenario: str,
) -> tuple[float, dict]:
    """
    Determine forward P/E multiple from the ticker's own 5-year historical P/E.

    Bear = 25th percentile, Base = median, Bull = 75th percentile.
    """
    details = {}
    pe_values: list[float] = []
    for row in yearly_pe_ranges or []:
        pe_values.extend(row.get("pe_daily_values") or [])

    if pe_values and len(yearly_pe_ranges) >= 2:
        p25 = _percentile(pe_values, 0.25)
        p50 = _percentile(pe_values, 0.50)
        p75 = _percentile(pe_values, 0.75)
        pe = {"bear": p25, "base": p50, "bull": p75}[scenario]
        details.update({
            "method": "historical_pe_percentiles",
            "hist_pe_p25": round(p25, 1),
            "hist_pe_p50": round(p50, 1),
            "hist_pe_p75": round(p75, 1),
            "hist_years_used": len(yearly_pe_ranges),
            "hist_daily_observations": len(pe_values),
        })
    else:
        pe = {"bear": 15, "base": 18, "bull": 22}[scenario]
        details["method"] = "default_no_data"

    if peer_pe_data and peer_pe_data.get("median_pe"):
        details["peer_reference_only"] = True
        details["peer_median_pe_raw"] = peer_pe_data.get("median_pe")
        details["peer_count"] = len(peer_pe_data.get("peers", []))

    pe = max(pe, 5.0)
    details["applied_pe"] = round(pe, 1)
    return round(pe, 1), details


# ---------------------------------------------------------------------------
# Step 3: 5-year forward valuation trend
# ---------------------------------------------------------------------------

def compute_forward_trend(
    forward_estimates: list[AnalystEstimateData],
    pe_multiple: float,
) -> list[dict]:
    """
    Apply the base P/E multiple to each year's forward EPS.
    Returns list of {"year": str, "eps": float, "implied_price": float}.
    """
    fmp_estimates = [
        estimate for estimate in forward_estimates
        if estimate.eps_estimate is not None and estimate.source == "fmp"
    ]
    fmp_estimates.sort(key=lambda estimate: estimate.period)

    trend = []
    for estimate in fmp_estimates:
        price = round(estimate.eps_estimate * pe_multiple, 2)
        trend.append({
            "year": estimate.period,
            "eps": round(estimate.eps_estimate, 2),
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
) -> MultiplesResult:
    """
    Compute per-share value using forward EPS and a historical-percentile P/E.
    DCF-derived justified P/E is reported only as a cross-check, not as an input.
    """
    pe_mult, details = determine_pe_multiple(
        yearly_pe_ranges or [],
        peer_pe_data,
        scenario,
    )

    forward_pe_value = None
    if forward_eps is not None and forward_eps > 0:
        forward_pe_value = round(forward_eps * pe_mult, 2)

    return MultiplesResult(
        forward_pe_value=forward_pe_value,
        forward_eps=round(forward_eps, 2) if forward_eps else None,
        pe_multiple=pe_mult,
        justified_pe=None,
        details=details,
    )
