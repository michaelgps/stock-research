"""
Forward P/E valuation with triangulation.

P/E is determined by triangulating three sources:
  (a) Historical trailing P/E distribution (yearly high/low/avg from daily prices)
  (b) Peer forward P/E (median + cap-weighted from FMP peers)
  (c) Justified P/E cross-check (DCF per-share / forward EPS)

Note on denominator mismatch: historical P/E uses trailing EPS (net income /
diluted shares from filings), but we apply it to forward EPS. This is a known
limitation — ideally we'd use historical forward P/E, but that requires
I/B/E/S-style historical consensus data we don't have. The growth adjustment
partially compensates for this gap.

All math is deterministic — no LLM calls.
"""

import logging
from datetime import date as dt_date

from app.data_structure.financial import (
    FinancialDataResponse,
    FinancialStatementData,
    AnalystEstimateData,
)
from app.data_structure.valuation import MultiplesResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Compute yearly high/low/avg P/E from daily prices + annual EPS
# ---------------------------------------------------------------------------

def compute_yearly_pe_ranges(
    daily_prices: list[dict],
    statements: list[FinancialStatementData],
) -> list[dict]:
    """
    For each fiscal year with EPS data, find the stock's high/low/avg price
    during that fiscal year and compute high/low/avg P/E.

    Returns list of {"fy": int, "eps": float, "pe_low": float, "pe_high": float, "pe_avg": float}
    """
    # Build EPS per fiscal year
    annual = [s for s in statements if s.period == "annual"]
    annual.sort(key=lambda s: s.fiscal_year, reverse=True)

    fy_eps = {}
    for s in annual[:5]:
        if s.net_income and s.diluted_shares and s.diluted_shares > 0:
            eps = s.net_income / s.diluted_shares
            if eps > 0:
                fy_eps[s.fiscal_year] = {"eps": eps, "end_date": s.date}

    if not fy_eps or not daily_prices:
        return []

    # Index daily prices by date string
    price_by_date = {}
    for p in daily_prices:
        d = p.get("date", "")
        if d:
            price_by_date[d] = p

    # For each FY, find prices in the ~12 months before fiscal year end
    results = []
    for fy, info in sorted(fy_eps.items(), reverse=True):
        eps = info["eps"]
        end_str = info["end_date"]
        try:
            fy_end = dt_date.fromisoformat(end_str)
        except ValueError:
            continue
        fy_start = fy_end.replace(year=fy_end.year - 1)

        # Collect all daily prices in this fiscal year window
        year_prices = []
        for d_str, p in price_by_date.items():
            try:
                d = dt_date.fromisoformat(d_str)
            except ValueError:
                continue
            if fy_start <= d <= fy_end:
                year_prices.append(p)

        if not year_prices:
            continue

        highs = [p["high"] for p in year_prices if "high" in p]
        lows = [p["low"] for p in year_prices if "low" in p]
        closes = [p["close"] for p in year_prices if "close" in p]

        if not highs or not lows or not closes:
            continue

        pe_high = max(highs) / eps
        pe_low = min(lows) / eps
        pe_avg = (sum(closes) / len(closes)) / eps

        results.append({
            "fy": fy,
            "eps": round(eps, 2),
            "pe_low": round(pe_low, 1),
            "pe_high": round(pe_high, 1),
            "pe_avg": round(pe_avg, 1),
            "price_high": round(max(highs), 2),
            "price_low": round(min(lows), 2),
        })

    return results


# ---------------------------------------------------------------------------
# Step 2: Determine P/E multiple via triangulation
# ---------------------------------------------------------------------------

def determine_pe_multiple(
    yearly_pe_ranges: list[dict],
    forward_eps_growth: float | None,
    peer_pe_data: dict | None,
    justified_pe: float | None,
    scenario: str,
) -> tuple[float, dict]:
    """
    Determine forward P/E multiple by triangulating:
      (a) Historical trailing P/E distribution (yearly ranges)
      (b) Peer forward P/E (median from FMP peers)
      (c) Justified P/E (DCF per share / forward EPS)

    Bear = weighted low estimate
    Base = weighted central estimate
    Bull = weighted high estimate
    """
    details = {}
    estimates = []  # list of (pe_value, weight, label)

    # --- (a) Historical P/E from yearly ranges ---
    if yearly_pe_ranges and len(yearly_pe_ranges) >= 2:
        avg_pe_low = sum(r["pe_low"] for r in yearly_pe_ranges) / len(yearly_pe_ranges)
        avg_pe_high = sum(r["pe_high"] for r in yearly_pe_ranges) / len(yearly_pe_ranges)
        avg_pe_avg = sum(r["pe_avg"] for r in yearly_pe_ranges) / len(yearly_pe_ranges)

        details["hist_pe_low_avg"] = round(avg_pe_low, 1)
        details["hist_pe_high_avg"] = round(avg_pe_high, 1)
        details["hist_pe_avg"] = round(avg_pe_avg, 1)
        details["hist_years_used"] = len(yearly_pe_ranges)

        # Growth adjustment: compare forward EPS growth to historical EPS growth
        growth_adj = 0.0
        if forward_eps_growth is not None:
            sorted_by_fy = sorted(yearly_pe_ranges, key=lambda r: r["fy"])
            oldest_eps = sorted_by_fy[0]["eps"]
            newest_eps = sorted_by_fy[-1]["eps"]
            years_span = sorted_by_fy[-1]["fy"] - sorted_by_fy[0]["fy"]
            if years_span > 0 and oldest_eps > 0:
                hist_eps_growth = (newest_eps / oldest_eps) ** (1 / years_span) - 1
            else:
                hist_eps_growth = 0

            growth_diff = forward_eps_growth - hist_eps_growth
            # Each 1pp faster growth nudges P/E by ~0.5x, capped at ±15%
            growth_adj = growth_diff * 50
            max_adj = avg_pe_avg * 0.15
            growth_adj = max(-max_adj, min(growth_adj, max_adj))

            details["hist_eps_growth"] = f"{round(hist_eps_growth * 100, 1)}%"
            details["fwd_eps_growth"] = f"{round(forward_eps_growth * 100, 1)}%"
            details["growth_adjustment"] = round(growth_adj, 1)

        hist_scenario = {
            "bear": avg_pe_low + growth_adj,
            "base": avg_pe_avg + growth_adj,
            "bull": avg_pe_high + growth_adj,
        }
        estimates.append((hist_scenario[scenario], 0.5, "historical"))

    # --- (b) Peer forward P/E (growth-adjusted via PEG) ---
    if peer_pe_data and peer_pe_data.get("median_pe"):
        raw_median = peer_pe_data["median_pe"]
        details["peer_median_pe_raw"] = raw_median
        details["peer_cap_weighted_pe"] = peer_pe_data.get("cap_weighted_pe")
        details["peer_count"] = len(peer_pe_data.get("peers", []))

        # Prefer growth-adjusted P/E (median_PEG × ticker growth) over raw median
        growth_adj_pe = peer_pe_data.get("growth_adjusted_pe")
        if growth_adj_pe is not None and growth_adj_pe > 0:
            peer_base = growth_adj_pe
            details["peer_median_peg"] = peer_pe_data.get("median_peg")
            details["peer_growth_adjusted_pe"] = growth_adj_pe
            details["peer_method"] = "peg_adjusted"
        else:
            # Fallback: no growth data available, use raw median
            peer_base = raw_median
            details["peer_method"] = "raw_median (no growth data)"

        peer_spread = peer_base * 0.15
        peer_scenario = {
            "bear": peer_base - peer_spread,
            "base": peer_base,
            "bull": peer_base + peer_spread,
        }
        estimates.append((peer_scenario[scenario], 0.3, "peer"))

    # --- (c) Justified P/E (DCF / forward EPS) ---
    if justified_pe is not None and justified_pe > 0:
        details["justified_pe"] = round(justified_pe, 1)
        # Justified P/E is a single-point fundamental anchor
        # Use ±10% for bear/bull
        just_spread = justified_pe * 0.10
        just_scenario = {
            "bear": justified_pe - just_spread,
            "base": justified_pe,
            "bull": justified_pe + just_spread,
        }
        estimates.append((just_scenario[scenario], 0.2, "justified"))

    # --- Combine via weighted average ---
    if estimates:
        total_weight = sum(w for _, w, _ in estimates)
        pe = sum(v * w for v, w, _ in estimates) / total_weight
        details["triangulation_inputs"] = {
            label: round(v, 1) for v, _, label in estimates
        }
        details["triangulation_weights"] = {
            label: round(w / total_weight, 2) for _, w, label in estimates
        }
        details["method"] = "triangulation"
    else:
        # Last resort: no data at all, use a conservative default
        pe = {"bear": 15, "base": 18, "bull": 22}[scenario]
        details["method"] = "default_no_data"

    # Sanity floor: P/E should never go below 5x (avoids nonsensical values)
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
        e for e in forward_estimates
        if e.eps_estimate is not None and e.source == "fmp"
    ]
    fmp_estimates.sort(key=lambda e: e.period)

    trend = []
    for est in fmp_estimates:
        price = round(est.eps_estimate * pe_multiple, 2)
        trend.append({
            "year": est.period,
            "eps": round(est.eps_estimate, 2),
            "implied_price": price,
        })
    return trend


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------

async def fetch_daily_prices(ticker: str, db=None) -> list[dict]:
    """Fetch ~5 years of daily prices, with DB caching. Uses yfinance (free) instead of FMP."""
    # Try DB cache first
    if db is not None:
        from app.db.financial_store import load_cached_daily_prices, save_daily_prices
        cached = load_cached_daily_prices(db, ticker)
        if cached is not None:
            return cached

    from app.logic.data_sources.yfinance_client import get_daily_prices
    prices = get_daily_prices(ticker)

    # Save to DB cache
    if db is not None and prices:
        from app.db.financial_store import save_daily_prices
        save_daily_prices(db, ticker, prices)

    return prices


async def fetch_peer_pe(ticker: str, ticker_eps_growth: float | None = None, industry: str | None = None) -> dict:
    """Fetch peer forward P/E data from FMP (with growth adjustment)."""
    from app.logic.data_sources.fmp import get_peer_forward_pe
    return await get_peer_forward_pe(ticker, ticker_eps_growth=ticker_eps_growth, industry=industry)


def get_forward_eps_growth(
    estimates: list[AnalystEstimateData],
    actual_eps: float | None = None,
    fy_end_date: str | None = None,
) -> float | None:
    """
    Compute forward EPS growth anchored on latest actual EPS (2-year CAGR).

    Uses _compute_eps_growth from fmp.py which handles:
    - Anchoring on actual EPS instead of estimate-only CAGR
    - Time-window adjustment (shifts forward if <6 months to next FY end)
    - Fallback to estimate-only if no actual EPS available
    """
    from app.logic.data_sources.fmp import _compute_eps_growth

    # Build lightweight objects matching what _compute_eps_growth expects
    class _Est:
        def __init__(self, period, eps_estimate):
            self.period = period
            self.eps_estimate = eps_estimate

    fmp = [e for e in estimates if e.eps_estimate is not None and e.source == "fmp"]
    est_objects = [_Est(e.period, e.eps_estimate) for e in fmp]

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
    forward_eps_growth: float | None = None,
    peer_pe_data: dict | None = None,
    justified_pe: float | None = None,
) -> MultiplesResult:
    """
    Compute per-share value using forward P/E via triangulation.
    P/E is determined from: historical ranges, peer comparison, justified P/E.
    """
    pe_mult, details = determine_pe_multiple(
        yearly_pe_ranges or [],
        forward_eps_growth,
        peer_pe_data,
        justified_pe,
        scenario,
    )

    forward_pe_value = None
    if forward_eps is not None and forward_eps > 0:
        forward_pe_value = round(forward_eps * pe_mult, 2)

    return MultiplesResult(
        forward_pe_value=forward_pe_value,
        forward_eps=round(forward_eps, 2) if forward_eps else None,
        pe_multiple=pe_mult,
        justified_pe=round(justified_pe, 1) if justified_pe else None,
    )
