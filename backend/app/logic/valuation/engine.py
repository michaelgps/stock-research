"""
Valuation engine orchestrator.
Runs DCF + forward P/E (with triangulation) for bear/base/bull, blends results.
Includes 5-year forward trend, historical P/E context, and peer comparison.
"""

import logging

from app.data_structure.financial import FinancialDataResponse
from app.data_structure.signals import ExtractionResult
from app.data_structure.valuation import (
    ValuationResponse,
    ScenarioResult,
    ForwardYearEstimate,
    PeerComparison,
    PeerPEData,
    ReverseDCF,
    MarginOfSafety,
)
from app.logic.valuation.assumptions import build_scenarios, get_forward_eps
from app.logic.valuation.dcf import run_dcf
from app.logic.valuation.multiples import (
    run_multiples,
    fetch_daily_prices,
    fetch_peer_pe,
    compute_yearly_pe_ranges,
    compute_forward_trend,
    compute_justified_pe,
    get_forward_eps_growth,
)

logger = logging.getLogger(__name__)

# DCF vs forward P/E blend weights
DCF_WEIGHT = 0.50
MULTIPLES_WEIGHT = 0.50


async def run_valuation(
    data: FinancialDataResponse,
    signals: ExtractionResult | None = None,
    db=None,
) -> ValuationResponse:
    """
    Run full valuation: DCF + forward P/E (triangulated) × 3 scenarios.
    Returns a ValuationResponse with bear/base/bull price targets.
    """
    # --- Extract key inputs ---
    latest_revenue = _get_latest_revenue(data)
    net_debt = _get_net_debt(data)
    shares = _get_shares(data)
    current_price = data.company.current_price or 0
    forward_eps = get_forward_eps(data.analyst_estimates)

    if latest_revenue <= 0:
        raise ValueError("Cannot run valuation: no revenue data available")
    if shares <= 0:
        raise ValueError("Cannot run valuation: no share count available")

    # --- Build DCF assumptions ---
    bear_a, base_a, bull_a, signal_adj, data_quality, analyst_revenues = await build_scenarios(data, signals)
    if analyst_revenues:
        data_quality["dcf_revenue_source"] = f"analyst_consensus_{len(analyst_revenues)}_years"
    else:
        data_quality["dcf_revenue_source"] = "flat_growth_rate"

    # --- Compute yearly P/E ranges from daily prices + EPS ---
    daily_prices = await fetch_daily_prices(data.company.ticker, db=db)
    yearly_pe_ranges = compute_yearly_pe_ranges(daily_prices, data.annual_statements)
    if yearly_pe_ranges:
        data_quality["pe_range_years"] = len(yearly_pe_ranges)
    else:
        data_quality["pe_range_years"] = "not_available"

    # --- Forward EPS growth (anchored on actual EPS, 2-year CAGR) ---
    actual_eps, fy_end_date = _get_latest_actual_eps(data)
    fwd_eps_growth = get_forward_eps_growth(
        data.analyst_estimates,
        actual_eps=actual_eps,
        fy_end_date=fy_end_date,
    )
    if fwd_eps_growth is not None:
        data_quality["forward_eps_growth"] = f"{round(fwd_eps_growth * 100, 1)}%"
        if actual_eps is not None:
            data_quality["actual_eps_anchor"] = round(actual_eps, 2)
            data_quality["fy_end_date"] = fy_end_date
    else:
        data_quality["forward_eps_growth"] = "not_available"

    # Record forward EPS
    if forward_eps is not None:
        data_quality["forward_eps"] = round(forward_eps, 2)
        data_quality["forward_eps_source"] = "analyst_consensus_next_fy"
    else:
        data_quality["forward_eps"] = "not_available"

    # Denominator mismatch note
    data_quality["pe_denominator_note"] = (
        "Historical P/E uses trailing EPS; applied to forward EPS. "
        "Peer and justified P/E use forward EPS for consistency."
    )

    # --- Cross-validate FMP EPS with Yahoo Finance ---
    try:
        from app.logic.data_sources.yfinance_client import cross_validate_eps
        yf_validation = cross_validate_eps(forward_eps, data.company.ticker)
        data_quality["yf_cross_validation"] = yf_validation
        if yf_validation.get("warning"):
            logger.warning(
                "%s EPS divergence: FMP=%.2f vs YF=%.2f (%.1f%%)",
                data.company.ticker,
                forward_eps or 0,
                yf_validation.get("yf_current_fy_eps") or 0,
                (yf_validation.get("divergence") or 0) * 100,
            )
    except Exception as e:
        logger.warning("Yahoo Finance cross-validation failed: %s", e)
        data_quality["yf_cross_validation"] = "error"

    # --- Fetch peer forward P/E (with growth adjustment) ---
    peer_pe_data = await fetch_peer_pe(data.company.ticker, ticker_eps_growth=fwd_eps_growth, industry=data.company.industry)
    peer_comparison = None
    if peer_pe_data and peer_pe_data.get("peers"):
        peer_comparison = PeerComparison(
            peers=[PeerPEData(**p) for p in peer_pe_data["peers"]],
            median_pe=peer_pe_data.get("median_pe"),
            cap_weighted_pe=peer_pe_data.get("cap_weighted_pe"),
            median_peg=peer_pe_data.get("median_peg"),
            growth_adjusted_pe=peer_pe_data.get("growth_adjusted_pe"),
        )
        data_quality["peer_count"] = len(peer_pe_data["peers"])
        data_quality["peer_median_pe"] = peer_pe_data.get("median_pe")
        if peer_pe_data.get("growth_adjusted_pe"):
            data_quality["peer_growth_adjusted_pe"] = peer_pe_data["growth_adjusted_pe"]
            data_quality["peer_median_peg"] = peer_pe_data.get("median_peg")
    else:
        data_quality["peer_comparison"] = "not_available"

    # --- Run base DCF first to compute justified P/E ---
    base_dcf = run_dcf(base_a, latest_revenue, net_debt, shares, analyst_revenues=analyst_revenues or None)
    justified_pe = compute_justified_pe(base_dcf.per_share_value, forward_eps)
    if justified_pe is not None:
        data_quality["justified_pe"] = round(justified_pe, 1)

    # --- Run models for each scenario ---
    scenarios = {}
    base_pe_mult = None
    for label, assumptions in [("bear", bear_a), ("base", base_a), ("bull", bull_a)]:
        dcf_result = run_dcf(assumptions, latest_revenue, net_debt, shares, analyst_revenues=analyst_revenues or None)
        mult_result = run_multiples(
            data, label, forward_eps,
            yearly_pe_ranges=yearly_pe_ranges,
            forward_eps_growth=fwd_eps_growth,
            peer_pe_data=peer_pe_data,
            justified_pe=justified_pe,
        )

        if label == "base":
            base_pe_mult = mult_result.pe_multiple

        # Blend DCF and forward P/E
        dcf_price = dcf_result.per_share_value
        pe_price = mult_result.forward_pe_value or 0

        if pe_price > 0 and dcf_price > 0:
            blended = DCF_WEIGHT * dcf_price + MULTIPLES_WEIGHT * pe_price
        elif dcf_price > 0:
            blended = dcf_price
            data_quality[f"{label}_blend"] = "dcf_only (no forward EPS)"
        elif pe_price > 0:
            blended = pe_price
            data_quality[f"{label}_blend"] = "forward_pe_only (dcf failed)"
        else:
            blended = 0

        scenarios[label] = ScenarioResult(
            label=label,
            dcf=dcf_result,
            multiples=mult_result,
            blended_per_share=round(blended, 2),
        )

    # --- 5-year forward trend (using base P/E multiple) ---
    trend_raw = compute_forward_trend(
        data.analyst_estimates,
        base_pe_mult or 20,
    )
    forward_trend = [
        ForwardYearEstimate(year=t["year"], eps=t["eps"], implied_price=t["implied_price"])
        for t in trend_raw
    ]

    # --- Terminal Value Warning ---
    tv_warning = None
    base_dcf_result = scenarios["base"].dcf
    if base_dcf_result.enterprise_value > 0:
        tv_pct = base_dcf_result.present_value_terminal / base_dcf_result.enterprise_value
        data_quality["terminal_value_pct_of_ev"] = round(tv_pct * 100, 1)
        if tv_pct > 0.75:
            tv_warning = (
                f"Terminal value accounts for {round(tv_pct * 100, 1)}% of enterprise value. "
                f"This means >75% of the valuation depends on long-term assumptions "
                f"(perpetual growth of {round(base_a.terminal_growth_rate * 100, 1)}%). "
                f"The result is highly sensitive to the terminal growth rate and WACC."
            )

    # --- Margin of Safety ---
    margin_of_safety = None
    if current_price > 0:
        base_val = scenarios["base"].blended_per_share
        bear_val = scenarios["bear"].blended_per_share
        bull_val = scenarios["bull"].blended_per_share
        upside_pct = (base_val - current_price) / current_price
        if upside_pct > 0.15:
            verdict = "undervalued"
        elif upside_pct < -0.15:
            verdict = "overvalued"
        else:
            verdict = "fairly_valued"
        margin_of_safety = MarginOfSafety(
            current_price=round(current_price, 2),
            base_intrinsic=round(base_val, 2),
            bear_intrinsic=round(bear_val, 2),
            bull_intrinsic=round(bull_val, 2),
            upside_pct=round(upside_pct, 4),
            verdict=verdict,
        )

    # --- Reverse DCF ---
    reverse_dcf = _compute_reverse_dcf(
        current_price=current_price,
        latest_revenue=latest_revenue,
        net_debt=net_debt,
        shares=shares,
        fcf_margin=base_a.fcf_margin,
        wacc=base_a.discount_rate,
        terminal_growth=base_a.terminal_growth_rate,
        projection_years=base_a.projection_years,
    )

    return ValuationResponse(
        ticker=data.company.ticker,
        current_price=round(current_price, 2),
        bear=scenarios["bear"],
        base=scenarios["base"],
        bull=scenarios["bull"],
        forward_trend=forward_trend,
        historical_pe_ranges=yearly_pe_ranges,
        peer_comparison=peer_comparison,
        signal_adjustments=signal_adj,
        data_quality=data_quality,
        reverse_dcf=reverse_dcf,
        margin_of_safety=margin_of_safety,
        terminal_value_warning=tv_warning,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_reverse_dcf(
    current_price: float,
    latest_revenue: float,
    net_debt: float,
    shares: float,
    fcf_margin: float,
    wacc: float,
    terminal_growth: float,
    projection_years: int = 5,
) -> ReverseDCF | None:
    """
    Reverse DCF: back-solve for the implied annual revenue growth rate
    that justifies the current market price.

    Uses bisection search to find the growth rate where
    DCF per-share value = current market price.
    """
    if current_price <= 0 or shares <= 0 or latest_revenue <= 0:
        return None

    target_equity = current_price * shares + net_debt  # target EV

    def _ev_at_growth(g: float) -> float:
        """Compute enterprise value at a given revenue growth rate."""
        revenue = latest_revenue
        projected_fcf = []
        for _ in range(projection_years):
            revenue = revenue * (1 + g)
            projected_fcf.append(revenue * fcf_margin)

        pv_fcfs = sum(
            fcf / (1 + wacc) ** (i + 1)
            for i, fcf in enumerate(projected_fcf)
        )

        last_fcf = projected_fcf[-1]
        if wacc <= terminal_growth:
            tv = last_fcf * 20
        else:
            tv = last_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
        pv_tv = tv / (1 + wacc) ** projection_years

        return pv_fcfs + pv_tv

    # Bisection search: find g where _ev_at_growth(g) ≈ target_equity
    lo, hi = -0.20, 0.50  # search range: -20% to +50% growth
    for _ in range(50):
        mid = (lo + hi) / 2
        ev = _ev_at_growth(mid)
        if ev < target_equity:
            lo = mid
        else:
            hi = mid

    implied_growth = (lo + hi) / 2

    # Interpretation
    if implied_growth > 0.25:
        interp = f"Market implies {round(implied_growth*100,1)}% annual revenue growth — very aggressive expectations."
    elif implied_growth > 0.15:
        interp = f"Market implies {round(implied_growth*100,1)}% annual revenue growth — above-average growth expectations."
    elif implied_growth > 0.05:
        interp = f"Market implies {round(implied_growth*100,1)}% annual revenue growth — moderate expectations."
    elif implied_growth > 0:
        interp = f"Market implies {round(implied_growth*100,1)}% annual revenue growth — low growth expectations."
    else:
        interp = f"Market implies {round(implied_growth*100,1)}% annual revenue growth — pricing in decline."

    return ReverseDCF(
        implied_growth_rate=round(implied_growth, 4),
        terminal_growth_rate=terminal_growth,
        discount_rate=wacc,
        fcf_margin=fcf_margin,
        interpretation=interp,
    )


def _get_latest_actual_eps(data: FinancialDataResponse) -> tuple[float | None, str | None]:
    """
    Get the latest actual diluted EPS and FY end date from financial statements.
    EPS = net_income / diluted_shares.
    Returns (eps, fy_end_date_str) e.g. (7.49, "2025-09-27").
    """
    annual = [s for s in data.annual_statements if s.period == "annual"]
    if not annual:
        return None, None
    annual.sort(key=lambda s: s.fiscal_year, reverse=True)
    latest = annual[0]
    if latest.net_income and latest.diluted_shares and latest.diluted_shares > 0:
        eps = latest.net_income / latest.diluted_shares
        return round(eps, 4), latest.date
    return None, latest.date


def _get_latest_revenue(data: FinancialDataResponse) -> float:
    """Latest annual revenue."""
    annual = [s for s in data.annual_statements if s.period == "annual" and s.revenue]
    if not annual:
        return 0
    annual.sort(key=lambda s: s.fiscal_year, reverse=True)
    return annual[0].revenue


def _get_net_debt(data: FinancialDataResponse) -> float:
    """Net debt = total_debt - total_cash. Positive means net debtor."""
    annual = [s for s in data.annual_statements if s.period == "annual"]
    if not annual:
        return 0
    annual.sort(key=lambda s: s.fiscal_year, reverse=True)
    latest = annual[0]
    debt = latest.total_debt or 0
    cash = latest.total_cash or 0
    return debt - cash


def _get_shares(data: FinancialDataResponse) -> float:
    """Best available diluted share count."""
    annual = [s for s in data.annual_statements if s.period == "annual"]
    if annual:
        annual.sort(key=lambda s: s.fiscal_year, reverse=True)
        if annual[0].diluted_shares and annual[0].diluted_shares > 0:
            return annual[0].diluted_shares
    if data.company.shares_outstanding and data.company.shares_outstanding > 0:
        return data.company.shares_outstanding
    return 0
