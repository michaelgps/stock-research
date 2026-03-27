"""
Derive valuation assumptions from historical financials + LLM signals.
Produces bear/base/bull scenarios for DCF and multiples models.
"""

import logging

import httpx

from app.data_structure.financial import (
    FinancialDataResponse,
    FinancialStatementData,
    AnalystEstimateData,
)
from app.data_structure.signals import ExtractionResult
from app.data_structure.valuation import ScenarioAssumptions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults & bounds
# ---------------------------------------------------------------------------
DEFAULT_RISK_FREE_RATE = 0.043  # fallback ~10Y US Treasury
DEFAULT_EQUITY_RISK_PREMIUM = 0.05
DEFAULT_TERMINAL_GROWTH = 0.03
PROJECTION_YEARS = 5

# Sector-level debt-to-equity ratios (median, used for unlevering beta)
SECTOR_DEBT_TO_EQUITY = {
    "Technology": 0.30,
    "Healthcare": 0.40,
    "Financial Services": 0.80,
    "Consumer Cyclical": 0.50,
    "Consumer Defensive": 0.45,
    "Industrials": 0.55,
    "Energy": 0.40,
    "Utilities": 1.00,
    "Real Estate": 0.70,
    "Communication Services": 0.50,
    "Basic Materials": 0.35,
}


# ---------------------------------------------------------------------------
# FRED API: dynamic risk-free rate
# ---------------------------------------------------------------------------
_cached_risk_free_rate: float | None = None


async def _fetch_risk_free_rate() -> float:
    """
    Fetch the latest 10-Year US Treasury yield from FRED (series DGS10).
    Falls back to DEFAULT_RISK_FREE_RATE on any error.
    Uses a module-level cache so we only call FRED once per process lifetime.
    """
    global _cached_risk_free_rate
    if _cached_risk_free_rate is not None:
        return _cached_risk_free_rate

    from app.config.config import get_settings
    api_key = get_settings().fred_api_key or "DEMO_KEY"
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=DGS10&sort_order=desc&limit=5"
        f"&file_type=json&api_key={api_key}"
    )
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            for obs in data.get("observations", []):
                val = obs.get("value", ".")
                if val != ".":
                    rate = float(val) / 100  # FRED returns e.g. 4.30 for 4.30%
                    _cached_risk_free_rate = rate
                    logger.info("FRED 10Y Treasury yield: %.2f%%", rate * 100)
                    return rate
    except Exception as e:
        logger.warning("FRED API failed, using default risk-free rate: %s", e)

    return DEFAULT_RISK_FREE_RATE

# Scenario spread (applied symmetrically around base)
GROWTH_SPREAD = 0.015  # ±1.5pp for bear/bull
MARGIN_SPREAD = 0.015  # ±1.5pp
DISCOUNT_SPREAD = 0.0075  # ±0.75pp


def _recent_statements(
    statements: list[FinancialStatementData], n: int = 5
) -> list[FinancialStatementData]:
    """Return up to n most recent annual statements sorted newest-first."""
    annual = [s for s in statements if s.period == "annual"]
    annual.sort(key=lambda s: s.fiscal_year, reverse=True)
    return annual[:n]


def _compute_revenue_cagr(statements: list[FinancialStatementData]) -> float | None:
    """Compute revenue CAGR over the given (newest-first) statements."""
    # Need at least 2 years with revenue
    with_rev = [s for s in statements if s.revenue and s.revenue > 0]
    if len(with_rev) < 2:
        return None
    newest = with_rev[0]
    oldest = with_rev[-1]
    years = newest.fiscal_year - oldest.fiscal_year
    if years <= 0:
        return None
    cagr = (newest.revenue / oldest.revenue) ** (1 / years) - 1
    return cagr


def _compute_avg_fcf_margin(statements: list[FinancialStatementData]) -> float | None:
    """Average FCF margin over recent statements."""
    margins = []
    for s in statements:
        if s.free_cash_flow is not None and s.revenue and s.revenue > 0:
            margins.append(s.free_cash_flow / s.revenue)
    if not margins:
        return None
    return sum(margins) / len(margins)


def _get_latest_annual_revenue(statements: list[FinancialStatementData]) -> float | None:
    """Get the most recent annual revenue from statements (already sorted newest-first)."""
    for s in statements:
        if s.revenue and s.revenue > 0:
            return s.revenue
    return None


def _get_analyst_revenue_estimates(
    estimates: list[AnalystEstimateData],
) -> list[float]:
    """
    Extract year-by-year analyst consensus revenue estimates, sorted by period ascending.
    Returns list of revenue values e.g. [FY2026_rev, FY2027_rev, FY2028_rev, ...].
    """
    rev_ests = [
        e for e in estimates
        if e.revenue_estimate is not None and e.revenue_estimate > 0
        and e.source == "fmp"
        and e.period and e.period.isdigit()  # annual periods like "2026", "2027"
    ]
    rev_ests.sort(key=lambda e: e.period)
    return [e.revenue_estimate for e in rev_ests]


def _get_sector_beta(sector: str | None) -> float:
    """Raw sector (levered) beta. Used as starting point for unlevering."""
    sector_betas = {
        "Technology": 1.2,
        "Healthcare": 1.0,
        "Financial Services": 1.1,
        "Consumer Cyclical": 1.15,
        "Consumer Defensive": 0.7,
        "Industrials": 1.0,
        "Energy": 1.3,
        "Utilities": 0.6,
        "Real Estate": 0.8,
        "Communication Services": 1.0,
        "Basic Materials": 1.1,
    }
    return sector_betas.get(sector or "", 1.0)


def _compute_levered_beta(
    sector: str | None,
    total_debt: float,
    market_cap: float,
    tax_rate: float = 0.21,
) -> tuple[float, dict]:
    """
    Compute company-specific levered beta using Hamada's equation.

    Step 1: Unlever sector beta to get pure business risk (asset beta).
        Beta_asset = Sector_Beta / (1 + (1 - tax) × Sector_D/E)

    Step 2: Relever using company's market-value D/E.
        Beta_levered = Beta_asset × (1 + (1 - tax) × Company_D/E)

    Returns (levered_beta, details_dict).
    """
    sector_beta = _get_sector_beta(sector)
    sector_de = SECTOR_DEBT_TO_EQUITY.get(sector or "", 0.40)

    # Step 1: Unlever
    beta_asset = sector_beta / (1 + (1 - tax_rate) * sector_de)

    # Step 2: Relever with company-specific D/E (market value)
    if market_cap > 0:
        company_de = total_debt / market_cap
    else:
        company_de = sector_de  # fallback

    beta_levered = beta_asset * (1 + (1 - tax_rate) * company_de)

    details = {
        "sector_beta": round(sector_beta, 3),
        "sector_de": round(sector_de, 3),
        "beta_asset": round(beta_asset, 3),
        "company_de_market": round(company_de, 4),
        "beta_levered": round(beta_levered, 3),
    }
    return beta_levered, details


async def _estimate_wacc(
    statements: list[FinancialStatementData],
    sector: str | None,
    market_cap: float | None = None,
) -> tuple[float, dict]:
    """
    Estimate WACC using:
    - FRED 10Y Treasury for risk-free rate (with fallback)
    - Levered beta (Hamada equation) for cost of equity via CAPM
    - Market cap (not book equity) for capital structure weights

    Returns (wacc, wacc_details).
    """
    risk_free_rate = await _fetch_risk_free_rate()
    tax_rate = 0.21  # US corporate
    cost_of_debt_pretax = 0.05  # assume ~5%
    cost_of_debt = cost_of_debt_pretax * (1 - tax_rate)

    latest = statements[0] if statements else None
    total_debt = (latest.total_debt or 0) if latest else 0

    # Use market cap for equity value (not book equity)
    equity_value = market_cap if market_cap and market_cap > 0 else None

    # Compute levered beta
    if equity_value and equity_value > 0:
        beta, beta_details = _compute_levered_beta(sector, total_debt, equity_value, tax_rate)
    else:
        beta = _get_sector_beta(sector)
        beta_details = {"method": "sector_beta_fallback", "beta": round(beta, 3)}

    cost_of_equity = risk_free_rate + beta * DEFAULT_EQUITY_RISK_PREMIUM

    # Capital structure weights using market values
    wacc_details = {
        "risk_free_rate": round(risk_free_rate, 4),
        "risk_free_source": "FRED_DGS10" if risk_free_rate != DEFAULT_RISK_FREE_RATE else "default",
        "equity_risk_premium": DEFAULT_EQUITY_RISK_PREMIUM,
        "beta_details": beta_details,
        "cost_of_equity": round(cost_of_equity, 4),
        "cost_of_debt_after_tax": round(cost_of_debt, 4),
    }

    if equity_value and equity_value > 0 and total_debt >= 0:
        total_capital = equity_value + total_debt
        equity_weight = equity_value / total_capital
        debt_weight = total_debt / total_capital
        wacc = equity_weight * cost_of_equity + debt_weight * cost_of_debt
        wacc_details["equity_weight"] = round(equity_weight, 4)
        wacc_details["debt_weight"] = round(debt_weight, 4)
        wacc_details["equity_value_source"] = "market_cap"
    else:
        # Fallback: all-equity
        wacc = cost_of_equity
        wacc_details["equity_weight"] = 1.0
        wacc_details["debt_weight"] = 0.0
        wacc_details["equity_value_source"] = "all_equity_fallback"

    # Clamp to reasonable range (no artificial 8% floor now that we use market cap)
    wacc = max(0.06, min(wacc, 0.15))
    wacc_details["wacc_raw"] = round(wacc, 4)
    wacc_details["wacc_clamped"] = round(wacc, 4)

    return wacc, wacc_details


# ---------------------------------------------------------------------------
# Signal adjustments
# ---------------------------------------------------------------------------

def _apply_signal_adjustments(
    base_growth: float,
    base_fcf_margin: float,
    base_wacc: float,
    signals: ExtractionResult | None,
) -> tuple[float, float, float, dict]:
    """
    Nudge base assumptions using LLM signals.
    Returns (adjusted_growth, adjusted_margin, adjusted_wacc, adjustment_log).
    """
    adj_growth = base_growth
    adj_margin = base_fcf_margin
    adj_wacc = base_wacc
    log = {}

    if not signals:
        return adj_growth, adj_margin, adj_wacc, log

    # --- MD&A signals ---
    mda = signals.mda_signals
    if mda:
        # Revenue outlook
        if mda.revenue_outlook == "positive":
            adj_growth += 0.01
            log["mda_revenue_outlook"] = "+1pp growth (positive)"
        elif mda.revenue_outlook == "negative":
            adj_growth -= 0.01
            log["mda_revenue_outlook"] = "-1pp growth (negative)"

        # Margin trend
        if mda.margin_trend == "expanding":
            adj_margin += 0.01
            log["mda_margin_trend"] = "+1pp FCF margin (expanding)"
        elif mda.margin_trend == "contracting":
            adj_margin -= 0.01
            log["mda_margin_trend"] = "-1pp FCF margin (contracting)"

        # Management tone → discount rate
        if mda.management_tone == "defensive":
            adj_wacc += 0.005
            log["mda_tone"] = "+0.5pp WACC (defensive tone)"
        elif mda.management_tone == "confident":
            adj_wacc -= 0.005
            log["mda_tone"] = "-0.5pp WACC (confident tone)"

    # --- Risk signals ---
    risk = signals.risk_signals
    if risk:
        if risk.overall_risk_level == "high":
            adj_wacc += 0.01
            log["risk_level"] = "+1pp WACC (high risk)"
        elif risk.overall_risk_level == "low":
            adj_wacc -= 0.005
            log["risk_level"] = "-0.5pp WACC (low risk)"

    # --- Transcript signals ---
    transcript = signals.transcript_signals
    if transcript:
        if transcript.guidance_tone == "positive":
            adj_growth += 0.005
            log["guidance_tone"] = "+0.5pp growth (positive guidance)"
        elif transcript.guidance_tone == "negative":
            adj_growth -= 0.005
            log["guidance_tone"] = "-0.5pp growth (negative guidance)"

        if transcript.management_confidence == "low":
            adj_wacc += 0.005
            log["mgmt_confidence"] = "+0.5pp WACC (low confidence)"

    return adj_growth, adj_margin, adj_wacc, log


# ---------------------------------------------------------------------------
# Forward EPS from analyst estimates
# ---------------------------------------------------------------------------

def get_forward_eps(estimates: list[AnalystEstimateData]) -> float | None:
    """
    Get forward EPS (next ~12 months) from analyst estimates.
    Looks for the nearest forward period with an EPS estimate.
    """
    # FMP estimates have periods like "2026", "2027" etc.
    eps_estimates = [
        e for e in estimates
        if e.eps_estimate is not None and e.source == "fmp"
    ]
    if not eps_estimates:
        return None
    # Sort by period (ascending) and take the first (nearest forward year)
    eps_estimates.sort(key=lambda e: e.period)
    return eps_estimates[0].eps_estimate


# ---------------------------------------------------------------------------
# Main entry: build scenarios
# ---------------------------------------------------------------------------

async def build_scenarios(
    data: FinancialDataResponse,
    signals: ExtractionResult | None,
) -> tuple[ScenarioAssumptions, ScenarioAssumptions, ScenarioAssumptions, dict, dict]:
    """
    Build bear/base/bull ScenarioAssumptions from financial data + signals.
    Returns (bear, base, bull, signal_adjustments, data_quality).
    """
    recent = _recent_statements(data.annual_statements)
    data_quality = {}

    # --- Base revenue growth ---
    latest_rev = _get_latest_annual_revenue(recent)
    analyst_revs = _get_analyst_revenue_estimates(data.analyst_estimates)
    analyst_growth = None
    if latest_rev and latest_rev > 0 and analyst_revs:
        next_fy_rev = analyst_revs[0]
        analyst_growth = (next_fy_rev / latest_rev) - 1
        data_quality["analyst_next_fy_revenue"] = round(next_fy_rev / 1e9, 1)
        data_quality["latest_actual_revenue"] = round(latest_rev / 1e9, 1)

    hist_cagr = _compute_revenue_cagr(recent)

    if analyst_growth is not None:
        base_growth = analyst_growth
        data_quality["revenue_growth_source"] = f"analyst_next_fy ({round(analyst_growth*100,1)}%)"
    elif hist_cagr is not None:
        base_growth = hist_cagr
        data_quality["revenue_growth_source"] = "historical_5y_cagr"
    else:
        base_growth = 0.05
        data_quality["revenue_growth_source"] = "default_5%"

    # --- Base FCF margin ---
    avg_fcf_margin = _compute_avg_fcf_margin(recent)
    if avg_fcf_margin is not None:
        base_fcf_margin = avg_fcf_margin
        data_quality["fcf_margin_source"] = "historical_average"
    else:
        base_fcf_margin = 0.15
        data_quality["fcf_margin_source"] = "default_15%"

    # --- Base WACC (now uses market cap + levered beta + FRED rate) ---
    base_wacc, wacc_details = await _estimate_wacc(
        recent, data.company.sector, data.company.market_cap
    )
    data_quality["wacc_method"] = "capm_levered_beta_market_cap"
    data_quality["wacc_details"] = wacc_details

    # --- Apply LLM signal adjustments ---
    adj_growth, adj_margin, adj_wacc, signal_log = _apply_signal_adjustments(
        base_growth, base_fcf_margin, base_wacc, signals
    )

    # --- Build 3 scenarios ---
    # Ensure terminal growth is always at least 2pp below discount rate
    def _safe_terminal_g(g: float, wacc: float) -> float:
        return min(g, wacc - 0.02)

    bear_wacc = min(adj_wacc + DISCOUNT_SPREAD, 0.15)
    base_wacc_final = adj_wacc
    bull_wacc = max(adj_wacc - DISCOUNT_SPREAD, 0.06)

    bear = ScenarioAssumptions(
        revenue_growth_rate=max(adj_growth - GROWTH_SPREAD, -0.05),
        fcf_margin=max(adj_margin - MARGIN_SPREAD, 0.05),
        terminal_growth_rate=_safe_terminal_g(DEFAULT_TERMINAL_GROWTH - 0.005, bear_wacc),
        discount_rate=bear_wacc,
        projection_years=PROJECTION_YEARS,
    )

    base = ScenarioAssumptions(
        revenue_growth_rate=adj_growth,
        fcf_margin=adj_margin,
        terminal_growth_rate=_safe_terminal_g(DEFAULT_TERMINAL_GROWTH, base_wacc_final),
        discount_rate=base_wacc_final,
        projection_years=PROJECTION_YEARS,
    )

    bull = ScenarioAssumptions(
        revenue_growth_rate=adj_growth + GROWTH_SPREAD,
        fcf_margin=min(adj_margin + MARGIN_SPREAD, 0.50),
        terminal_growth_rate=_safe_terminal_g(DEFAULT_TERMINAL_GROWTH + 0.005, bull_wacc),
        discount_rate=bull_wacc,
        projection_years=PROJECTION_YEARS,
    )

    # --- Extract analyst year-by-year revenues for DCF ---
    analyst_revenues = _get_analyst_revenue_estimates(data.analyst_estimates)

    return bear, base, bull, signal_log, data_quality, analyst_revenues
