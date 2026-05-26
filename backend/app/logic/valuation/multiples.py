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


# ---------------------------------------------------------------------------
# Step 1: Compute yearly P/E distribution from daily prices + annual EPS
# ---------------------------------------------------------------------------

def compute_yearly_pe_ranges(
    daily_prices: list[dict],
    statements: list[FinancialStatementData],
) -> list[dict]:
    """
    For each fiscal year with EPS data, compute daily trailing P/E values.

    Each row includes a private pe_daily_values list so aggregate 5-year
    P25/P50/P75 can be computed internally. The API response strips that list.
    """
    annual = [s for s in statements if s.period == "annual"]
    annual.sort(key=lambda s: s.fiscal_year, reverse=True)

    fy_eps = {}
    for statement in annual[:5]:
        if statement.net_income and statement.diluted_shares and statement.diluted_shares > 0:
            eps = statement.net_income / statement.diluted_shares
            if eps > 0:
                fy_eps[statement.fiscal_year] = {"eps": eps, "end_date": statement.date}

    if not fy_eps or not daily_prices:
        return []

    price_by_date = {}
    for price in daily_prices:
        date_text = price.get("date", "")
        if date_text:
            price_by_date[date_text] = price

    results = []
    for fy, info in sorted(fy_eps.items(), reverse=True):
        eps = info["eps"]
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

        highs = [p["high"] for p in year_prices if "high" in p]
        lows = [p["low"] for p in year_prices if "low" in p]
        closes = [p["close"] for p in year_prices if "close" in p]

        if not highs or not lows or not closes:
            continue

        pe_daily_values = [close / eps for close in closes if close > 0]
        if not pe_daily_values:
            continue

        results.append({
            "fy": fy,
            "eps": round(eps, 2),
            "pe_low": round(min(lows) / eps, 1),
            "pe_high": round(max(highs) / eps, 1),
            "pe_avg": round((sum(closes) / len(closes)) / eps, 1),
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
