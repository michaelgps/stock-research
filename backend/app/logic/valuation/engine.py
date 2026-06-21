"""
Valuation engine orchestrator.
Runs base DCF as a reference and forward P/E as fiscal-year case windows.
Includes forward EPS validation, historical P/E context, and peer comparison.
"""

import logging
from datetime import date as dt_date

from app.data_structure.financial import FinancialDataResponse, AnalystEstimateData
from app.data_structure.signals import ExtractionResult
from app.data_structure.valuation import (
    ValuationResponse,
    ScenarioResult,
    ForwardYearEstimate,
    PeerComparison,
    PeerPEData,
    ReverseDCF,
    MarginOfSafety,
    ValuationView,
    ForwardEpsMetadata,
    FiscalYearValuationWindow,
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
    compute_auto_pe_cases,
    get_forward_eps_growth,
)

logger = logging.getLogger(__name__)

# Upside band (±) around current price within which a verdict is "fairly_valued".
_VERDICT_BAND = 0.15
_MAX_FORWARD_VALUATION_YEARS = 3


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
    forward_eps_estimate = _get_forward_eps_estimate(data)
    valuation_analyst_estimates = list(data.analyst_estimates)
    forward_eps = forward_eps_estimate.eps_estimate if forward_eps_estimate else get_forward_eps(valuation_analyst_estimates)

    if latest_revenue <= 0:
        raise ValueError("Cannot run valuation: no revenue data available")
    if shares <= 0:
        raise ValueError("Cannot run valuation: no share count available")

    # --- Build DCF assumptions ---
    bear_a, base_a, bull_a, signal_adj, data_quality, analyst_revenues = await build_scenarios(data, signals, db=db)
    if analyst_revenues:
        data_quality["dcf_revenue_source"] = f"analyst_consensus_{len(analyst_revenues)}_years"
    else:
        data_quality["dcf_revenue_source"] = "flat_growth_rate"

    # --- Compute yearly P/E ranges from daily prices + EPS ---
    daily_prices = await fetch_daily_prices(data.company.ticker, db=db)
    yearly_pe_ranges = compute_yearly_pe_ranges(
        daily_prices,
        data.annual_statements,
        data.earnings_surprises,
    )
    if yearly_pe_ranges:
        data_quality["pe_range_years"] = len(yearly_pe_ranges)
        data_quality["historical_pe_eps_basis"] = _summarize_pe_eps_basis(yearly_pe_ranges)
    else:
        data_quality["pe_range_years"] = "not_available"

    actual_eps, fy_end_date = _get_latest_actual_eps(data)

    # Denominator mismatch note
    data_quality["pe_denominator_note"] = (
        "Forward P/E uses an automatic range based on EPS growth, company quality, "
        "growth deceleration, estimate uncertainty, and historical P/E guardrails. "
        "DCF-implied P/E and manual peers are cross-checks only, not P/E inputs."
    )

    # --- Cross-validate FMP EPS with Yahoo Finance ---
    try:
        yf_validation = None
        if db is not None:
            from app.db.financial import Estimate
            from app.repositories import data_pull_log_repository

            today = data_pull_log_repository.today_str()
            cached_yf = db.query(Estimate).filter(
                Estimate.ticker == data.company.ticker,
                Estimate.estimate_date == today,
                Estimate.source == "yfinance",
                Estimate.estimate_period == "eps_validation",
            ).first()
            if cached_yf and cached_yf.raw_data_json and data_pull_log_repository.has_success(
                db, data.company.ticker, "eps_validation", "yfinance", today
            ):
                yf_validation = cached_yf.raw_data_json

        if yf_validation is None:
            from app.logic.data_sources.yfinance_client import cross_validate_eps
            yf_validation = cross_validate_eps(forward_eps, data.company.ticker)
            if db is not None:
                from app.db.financial import Estimate
                from app.repositories import data_pull_log_repository

                today = data_pull_log_repository.today_str()
                row = db.query(Estimate).filter(
                    Estimate.ticker == data.company.ticker,
                    Estimate.estimate_date == today,
                    Estimate.source == "yfinance",
                    Estimate.estimate_period == "eps_validation",
                ).first()
                values = {
                    "record_type": "eps_validation",
                    "revenue_estimate": None,
                    "eps_estimate": yf_validation.get("yf_current_fy_eps"),
                    "revenue_growth_estimate": None,
                    "actual_eps": None,
                    "estimated_eps": None,
                    "surprise": None,
                    "surprise_percent": None,
                    "buy_count": None,
                    "hold_count": None,
                    "sell_count": None,
                    "target_price": None,
                    "raw_data_json": yf_validation,
                }
                if row:
                    for key, value in values.items():
                        setattr(row, key, value)
                else:
                    db.add(Estimate(
                        ticker=data.company.ticker,
                        estimate_date=today,
                        source="yfinance",
                        estimate_period="eps_validation",
                        **values,
                    ))
                db.commit()
                data_pull_log_repository.mark(
                    db, data.company.ticker, "eps_validation", "yfinance", "success", records_inserted=1
                )

        data_quality["yf_cross_validation"] = yf_validation
        fallback_estimates = _build_yfinance_forward_eps_estimates(data, yf_validation)
        if forward_eps is None and fallback_estimates:
            valuation_analyst_estimates.extend(fallback_estimates)
            forward_eps_estimate = fallback_estimates[0]
            forward_eps = forward_eps_estimate.eps_estimate
            data_quality["forward_eps_fallback_warning"] = (
                "FMP annual analyst EPS is unavailable for this ticker under the current data plan; "
                "Yahoo Finance current-FY consensus EPS is used as a fallback."
            )
        elif forward_eps is None:
            unavailable_reason = _forward_eps_unavailable_reason(db, data.company.ticker)
            if unavailable_reason:
                data_quality["forward_eps_unavailable_reason"] = unavailable_reason

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

    try:
        alpha_validation = None
        if db is not None:
            from app.db.financial import Estimate
            from app.repositories import data_pull_log_repository

            today = data_pull_log_repository.today_str()
            cached_alpha = db.query(Estimate).filter(
                Estimate.ticker == data.company.ticker,
                Estimate.estimate_date == today,
                Estimate.source == "alpha_vantage",
                Estimate.estimate_period == "eps_validation",
            ).first()
            if cached_alpha and cached_alpha.raw_data_json and data_pull_log_repository.has_success(
                db, data.company.ticker, "eps_validation", "alpha_vantage", today
            ):
                alpha_validation = cached_alpha.raw_data_json

        if alpha_validation is None:
            alpha_validation = await _cross_validate_alpha_vantage_eps(data)
            if db is not None:
                from app.db.financial import Estimate
                from app.repositories import data_pull_log_repository

                today = data_pull_log_repository.today_str()
                row = db.query(Estimate).filter(
                    Estimate.ticker == data.company.ticker,
                    Estimate.estimate_date == today,
                    Estimate.source == "alpha_vantage",
                    Estimate.estimate_period == "eps_validation",
                ).first()
                values = {
                    "record_type": "eps_validation",
                    "revenue_estimate": None,
                    "eps_estimate": None,
                    "revenue_growth_estimate": None,
                    "actual_eps": None,
                    "estimated_eps": None,
                    "surprise": None,
                    "surprise_percent": None,
                    "buy_count": None,
                    "hold_count": None,
                    "sell_count": None,
                    "target_price": None,
                    "raw_data_json": alpha_validation,
                }
                if row:
                    for key, value in values.items():
                        setattr(row, key, value)
                else:
                    db.add(Estimate(
                        ticker=data.company.ticker,
                        estimate_date=today,
                        source="alpha_vantage",
                        estimate_period="eps_validation",
                        **values,
                    ))
                db.commit()
                status = "success" if alpha_validation.get("configured") else "empty"
                data_pull_log_repository.mark(
                    db,
                    data.company.ticker,
                    "eps_validation",
                    "alpha_vantage",
                    status,
                    records_inserted=1 if status == "success" else 0,
                )

        data_quality["alpha_vantage_eps_validation"] = alpha_validation
    except Exception as e:
        logger.warning("Alpha Vantage EPS validation failed: %s", e)
        data_quality["alpha_vantage_eps_validation"] = "error"

    data_quality["forward_eps_validation_policy"] = (
        "Primary valuation uses only the first 3 forward fiscal-year EPS estimates. "
        "FMP is preferred; Yahoo Finance may be used as a fallback when FMP forward EPS is unavailable. "
        "Optional Alpha Vantage is a cross-check to catch obvious estimate errors."
    )

    valuation_data = _with_analyst_estimates(data, valuation_analyst_estimates)

    # --- Forward EPS growth (anchored on actual EPS, 2-year CAGR) ---
    fwd_eps_growth = get_forward_eps_growth(
        valuation_data.analyst_estimates,
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
        data_quality["forward_eps_basis"] = "next_fiscal_year"
        data_quality["forward_eps_period"] = forward_eps_estimate.period if forward_eps_estimate else "unknown"
        data_quality["forward_eps_source"] = _forward_eps_source_label(forward_eps_estimate)
    else:
        data_quality["forward_eps"] = "not_available"
        unavailable_reason = _forward_eps_unavailable_reason(db, data.company.ticker)
        if unavailable_reason:
            data_quality["forward_eps_unavailable_reason"] = unavailable_reason

    # --- Fetch peer forward P/E (with growth adjustment) ---
    peer_pe_data = await fetch_peer_pe(
        data.company.ticker,
        ticker_eps_growth=fwd_eps_growth,
        industry=data.company.industry,
        db=db,
    )
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
        method = peer_pe_data.get("method") if peer_pe_data else None
        if method == "manual_peers_required":
            data_quality["peer_comparison"] = "skipped_no_manual_peers"
        else:
            data_quality["peer_comparison"] = "not_available"

    # --- Run base DCF first to compute the DCF-implied P/E cross-check ---
    base_dcf = run_dcf(base_a, latest_revenue, net_debt, shares, analyst_revenues=analyst_revenues or None)
    justified_pe = compute_justified_pe(base_dcf.per_share_value, forward_eps)
    if justified_pe is not None:
        data_quality["dcf_implied_pe_cross_check"] = round(justified_pe, 1)

    # --- Run models for each scenario (reuse the already-computed base DCF) ---
    scenarios = {}
    base_pe_mult = None
    for label, assumptions in [("bear", bear_a), ("base", base_a), ("bull", bull_a)]:
        dcf_result = base_dcf if label == "base" else run_dcf(
            assumptions, latest_revenue, net_debt, shares, analyst_revenues=analyst_revenues or None
        )
        mult_result = run_multiples(
            valuation_data, label, forward_eps,
            yearly_pe_ranges=yearly_pe_ranges,
            peer_pe_data=peer_pe_data,
            target_period=forward_eps_estimate.period if forward_eps_estimate else None,
            latest_fiscal_year_end=fy_end_date,
            latest_actual_eps=actual_eps,
        )

        if label == "base":
            base_pe_mult = mult_result.pe_multiple

        scenarios[label] = ScenarioResult(
            label=label,
            dcf=dcf_result,
            multiples=mult_result,
            blended_per_share=None,
        )

    # --- 5-year forward trend (using period-specific base P/E multiples) ---
    pe_case_details_by_period = _build_pe_case_details_by_period(
        data=valuation_data,
        yearly_pe_ranges=yearly_pe_ranges,
        current_price=current_price,
        latest_fiscal_year_end=fy_end_date,
        latest_actual_eps=actual_eps,
    )
    base_pe_by_period = {
        period: cases[0]["pe_mid"]
        for period, cases in pe_case_details_by_period.items()
        if cases
    }
    trend_raw = compute_forward_trend(
        valuation_data.analyst_estimates,
        base_pe_mult or 20,
        pe_by_period=base_pe_by_period,
    )
    forward_trend = [
        ForwardYearEstimate(
            year=t["year"],
            eps=t["eps"],
            pe_multiple=t.get("pe_multiple"),
            implied_price=t["implied_price"],
        )
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

    # --- Standalone valuation views ---
    dcf_view = _build_view(
        label="DCF Intrinsic Value",
        methodology="discounted_cash_flow",
        current_price=current_price,
        bear_value=scenarios["bear"].dcf.per_share_value,
        base_value=scenarios["base"].dcf.per_share_value,
        bull_value=scenarios["bull"].dcf.per_share_value,
        notes=[
            "Standalone intrinsic value view based on projected free cash flow and WACC.",
            "Not averaged with market multiple valuation.",
        ],
    )
    pe_view = _build_view(
        label="Forward P/E Market Multiple",
        methodology="forward_pe_next_fiscal_year",
        current_price=current_price,
        bear_value=scenarios["bear"].multiples.forward_pe_value,
        base_value=scenarios["base"].multiples.forward_pe_value,
        bull_value=scenarios["bull"].multiples.forward_pe_value,
        notes=[
            "Standalone market multiple view: next fiscal year EPS multiplied by the automatic P/E midpoint.",
            "The main UI shows the full automatic P/E low/mid/high range and any multi-case output.",
        ],
    )

    # --- Margin of Safety (compatibility field; mirrors the standalone DCF view) ---
    margin_of_safety = None
    if current_price > 0 and dcf_view.verdict is not None:
        margin_of_safety = MarginOfSafety(
            current_price=round(current_price, 2),
            base_intrinsic=dcf_view.base_value or 0,
            bear_intrinsic=dcf_view.bear_value or 0,
            bull_intrinsic=dcf_view.bull_value or 0,
            upside_pct=dcf_view.upside_pct,
            verdict=dcf_view.verdict,
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

    forward_eps_metadata = _build_forward_eps_metadata(
        forward_eps_estimate,
        latest_fiscal_year_end=fy_end_date,
    )
    fiscal_year_valuation_windows = _build_fiscal_year_valuation_windows(
        forward_trend=forward_trend,
        latest_fiscal_year_end=fy_end_date,
        dcf_present_value=dcf_view.base_value,
        discount_rate=base_a.discount_rate,
        pe_multiple=base_pe_mult,
        current_price=current_price,
        scenario_results=scenarios,
        pe_case_details_by_period=pe_case_details_by_period,
    )

    return ValuationResponse(
        ticker=data.company.ticker,
        current_price=round(current_price, 2),
        bear=scenarios["bear"],
        base=scenarios["base"],
        bull=scenarios["bull"],
        dcf_view=dcf_view,
        pe_view=pe_view,
        forward_eps_metadata=forward_eps_metadata,
        fiscal_year_valuation_windows=fiscal_year_valuation_windows,
        forward_trend=forward_trend,
        historical_pe_ranges=_public_historical_pe_ranges(yearly_pe_ranges),
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

def _get_forward_eps_estimate(data: FinancialDataResponse) -> AnalystEstimateData | None:
    """Return the next fiscal year FMP annual EPS estimate used by P/E valuation."""
    estimates = [
        e for e in data.analyst_estimates
        if e.eps_estimate is not None and e.source == "fmp" and e.period and e.period.isdigit()
    ]
    estimates.sort(key=lambda e: e.period)
    return estimates[0] if estimates else None


def _with_analyst_estimates(
    data: FinancialDataResponse,
    estimates: list[AnalystEstimateData],
) -> FinancialDataResponse:
    """Return a shallow copy with valuation-specific estimate fallbacks included."""
    if hasattr(data, "model_copy"):
        return data.model_copy(update={"analyst_estimates": estimates})
    return data.copy(update={"analyst_estimates": estimates})


def _build_yfinance_forward_eps_estimates(
    data: FinancialDataResponse,
    yf_validation: dict | None,
) -> list[AnalystEstimateData]:
    """Convert Yahoo EPS validation output into explicit fiscal-year estimates."""
    if not isinstance(yf_validation, dict):
        return []

    current_fy = _infer_current_forward_fiscal_year(data)
    if current_fy is None:
        return []

    estimates: list[AnalystEstimateData] = []
    current_eps = _positive_number(yf_validation.get("yf_current_fy_eps"))
    next_eps = _positive_number(yf_validation.get("yf_next_fy_eps"))

    if current_eps is not None:
        estimates.append(AnalystEstimateData(
            period=str(current_fy),
            eps_estimate=current_eps,
            source="yfinance",
        ))
    if next_eps is not None:
        estimates.append(AnalystEstimateData(
            period=str(current_fy + 1),
            eps_estimate=next_eps,
            source="yfinance",
        ))
    return estimates


def _infer_current_forward_fiscal_year(data: FinancialDataResponse) -> int | None:
    """Infer the current forward fiscal year when Yahoo labels estimates as 0y/+1y."""
    latest_reported_fy = max(
        (row.fiscal_year for row in data.annual_statements if row.fiscal_year),
        default=None,
    )
    today_year = dt_date.today().year
    if latest_reported_fy is None:
        return today_year
    return max(today_year, latest_reported_fy + 1)


def _positive_number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _forward_eps_source_label(estimate: AnalystEstimateData | None) -> str:
    if estimate and estimate.source == "yfinance":
        return "yfinance_fallback_current_fy_consensus"
    if estimate and estimate.source == "fmp":
        return "fmp_annual_analyst_estimates"
    return "unknown"


def _forward_eps_unavailable_reason(db, ticker: str) -> str | None:
    if db is None:
        return None
    try:
        from app.db.financial import DataPullLog
        from app.repositories import data_pull_log_repository

        today = data_pull_log_repository.today_str()
        row = db.query(DataPullLog).filter(
            DataPullLog.ticker == ticker,
            DataPullLog.data_type == "estimate",
            DataPullLog.source == "fmp",
            DataPullLog.pull_date == today,
        ).order_by(DataPullLog.id.desc()).first()
        message = row.error_message if row else None
        if message and ("402" in message or "Payment Required" in message):
            return "FMP analyst estimates are unavailable for this ticker under the current subscription (402 Payment Required)."
        if row and row.status in {"empty", "failed"}:
            return f"FMP analyst estimates unavailable: {row.status}."
    except Exception as exc:
        logger.debug("Could not read forward EPS pull log for %s: %s", ticker, exc)
    return None


def _build_forward_eps_metadata(
    estimate: AnalystEstimateData | None,
    latest_fiscal_year_end: str | None,
) -> ForwardEpsMetadata | None:
    if estimate is None or estimate.eps_estimate is None:
        return None
    from app.repositories import data_pull_log_repository
    fiscal_year = int(estimate.period) if estimate.period and estimate.period.isdigit() else None
    fiscal_year_end = None
    if fiscal_year and latest_fiscal_year_end:
        fiscal_year_end = _infer_fiscal_year_end(latest_fiscal_year_end, fiscal_year)
    return ForwardEpsMetadata(
        basis="next_fiscal_year",
        period=f"FY{estimate.period}" if estimate.period else None,
        fiscal_year=fiscal_year,
        fiscal_year_end=fiscal_year_end,
        eps=round(estimate.eps_estimate, 2),
        source=_forward_eps_source_label(estimate),
        as_of_date=data_pull_log_repository.today_str(),
    )


def _public_historical_pe_ranges(yearly_pe_ranges: list[dict]) -> list[dict]:
    """Remove internal daily P/E observations before serializing API output."""
    return [
        {key: value for key, value in row.items() if key != "pe_daily_values"}
        for row in yearly_pe_ranges
    ]


def _summarize_pe_eps_basis(yearly_pe_ranges: list[dict]) -> str:
    bases = {row.get("eps_basis") for row in yearly_pe_ranges if row.get("eps_basis")}
    if "adjusted_ttm_eps" in bases:
        return "adjusted_ttm_eps_preferred"
    if bases:
        return "gaap_annual_eps"
    return "unknown"


async def _cross_validate_alpha_vantage_eps(
    data: FinancialDataResponse,
    threshold: float = 0.15,
) -> dict:
    """Cross-check FMP forward EPS estimates against optional Alpha Vantage data."""
    from app.logic.data_sources import alpha_vantage

    if not alpha_vantage._is_configured():
        return {
            "configured": False,
            "source": "alpha_vantage",
            "matches": [],
            "warning": False,
            "note": "ALPHA_VANTAGE_API_KEY is not configured.",
        }

    fmp_estimates = [
        estimate for estimate in data.analyst_estimates
        if (
            estimate.source == "fmp"
            and estimate.period
            and str(estimate.period).isdigit()
            and estimate.eps_estimate is not None
            and estimate.eps_estimate > 0
        )
    ]
    fmp_estimates.sort(key=lambda estimate: int(estimate.period))
    fmp_estimates = fmp_estimates[:_MAX_FORWARD_VALUATION_YEARS]

    alpha_estimates = await alpha_vantage.get_annual_eps_estimates(
        data.company.ticker,
        limit=_MAX_FORWARD_VALUATION_YEARS,
    )
    alpha_by_period = {item["period"]: item for item in alpha_estimates}

    matches = []
    warning = False
    for estimate in fmp_estimates:
        period = str(estimate.period)
        alpha = alpha_by_period.get(period)
        alpha_eps = alpha.get("eps_estimate") if alpha else None
        divergence = None
        period_warning = False
        if alpha_eps and estimate.eps_estimate and estimate.eps_estimate > 0:
            divergence = abs(alpha_eps - estimate.eps_estimate) / estimate.eps_estimate
            period_warning = divergence > threshold
            warning = warning or period_warning
        matches.append({
            "period": period,
            "fmp_eps": round(estimate.eps_estimate, 4),
            "alpha_vantage_eps": round(alpha_eps, 4) if alpha_eps is not None else None,
            "divergence": round(divergence, 3) if divergence is not None else None,
            "warning": period_warning,
        })

    return {
        "configured": True,
        "source": "alpha_vantage",
        "matches": matches,
        "warning": warning,
    }


def _build_pe_case_details_by_period(
    data: FinancialDataResponse,
    yearly_pe_ranges: list[dict],
    current_price: float,
    latest_fiscal_year_end: str | None,
    latest_actual_eps: float | None,
) -> dict[str, list[dict]]:
    """Precompute automatic P/E range cases for every forward fiscal year."""
    periods = sorted({
        str(estimate.period)
        for estimate in data.analyst_estimates
        if (
            estimate.period
            and str(estimate.period).isdigit()
            and estimate.eps_estimate is not None
            and estimate.eps_estimate > 0
            and estimate.source in {"fmp", "yfinance"}
        )
    }, key=int)[:_MAX_FORWARD_VALUATION_YEARS]
    eps_by_period = {
        str(estimate.period): estimate.eps_estimate
        for estimate in data.analyst_estimates
        if estimate.period and str(estimate.period).isdigit() and estimate.eps_estimate is not None
    }
    result: dict[str, list[dict]] = {}
    for period in periods:
        result[period] = compute_auto_pe_cases(
            data=data,
            yearly_pe_ranges=yearly_pe_ranges,
            target_period=period,
            forward_eps=eps_by_period.get(period),
            current_price=current_price,
            latest_fiscal_year_end=latest_fiscal_year_end,
            latest_actual_eps=latest_actual_eps,
        )
    return result


def _build_fiscal_year_valuation_windows(
    forward_trend: list[ForwardYearEstimate],
    latest_fiscal_year_end: str | None,
    dcf_present_value: float | None,
    discount_rate: float | None,
    pe_multiple: float | None,
    current_price: float,
    scenario_results: dict,
    pe_case_details_by_period: dict[str, list[dict]] | None = None,
) -> list[FiscalYearValuationWindow]:
    """Align Forward P/E targets and rolled-forward DCF values by fiscal-year end."""
    from app.repositories import data_pull_log_repository

    valuation_date = data_pull_log_repository.today_str()
    windows: list[FiscalYearValuationWindow] = []
    for estimate in forward_trend:
        if not estimate.year or not str(estimate.year).isdigit():
            continue
        fiscal_year = int(estimate.year)
        fiscal_year_end = (
            _infer_fiscal_year_end(latest_fiscal_year_end, fiscal_year)
            if latest_fiscal_year_end
            else None
        )
        years_from_valuation_date = _years_between(valuation_date, fiscal_year_end)
        dcf_rolled_forward_value = None
        if (
            dcf_present_value is not None
            and discount_rate is not None
            and years_from_valuation_date is not None
        ):
            roll_years = max(years_from_valuation_date, 0)
            dcf_rolled_forward_value = round(dcf_present_value * (1 + discount_rate) ** roll_years, 2)
        forward_pe_upside = _compute_upside(estimate.implied_price, current_price)
        dcf_rolled_forward_upside = _compute_upside(dcf_rolled_forward_value, current_price)
        pe_cases = _build_fiscal_year_pe_cases(
            period=str(estimate.year),
            pe_case_details_by_period=pe_case_details_by_period,
        )

        windows.append(FiscalYearValuationWindow(
            fiscal_year=fiscal_year,
            fiscal_year_end=fiscal_year_end,
            valuation_date=valuation_date,
            years_from_valuation_date=(
                round(years_from_valuation_date, 4)
                if years_from_valuation_date is not None
                else None
            ),
            time_distance_label=_format_time_distance(valuation_date, fiscal_year_end),
            forward_eps=round(estimate.eps, 2),
            pe_multiple=round(estimate.pe_multiple or pe_multiple, 1) if (estimate.pe_multiple or pe_multiple) is not None else None,
            forward_pe_value=round(estimate.implied_price, 2),
            forward_pe_upside_pct=forward_pe_upside,
            forward_pe_verdict=_classify_verdict(forward_pe_upside) if forward_pe_upside is not None else None,
            pe_cases=pe_cases,
            dcf_present_value=round(dcf_present_value, 2) if dcf_present_value is not None else None,
            dcf_rolled_forward_value=dcf_rolled_forward_value,
            dcf_rolled_forward_upside_pct=dcf_rolled_forward_upside,
            dcf_rolled_forward_verdict=(
                _classify_verdict(dcf_rolled_forward_upside)
                if dcf_rolled_forward_upside is not None
                else None
            ),
            discount_rate_used=round(discount_rate, 4) if discount_rate is not None else None,
            discount_rate_source="base_dcf_wacc",
        ))
    return windows


def _build_fiscal_year_pe_cases(
    period: str,
    pe_case_details_by_period: dict[str, list[dict]] | None,
) -> list:
    from app.data_structure.valuation import FiscalYearPECase

    cases = []
    for case in (pe_case_details_by_period or {}).get(period, []):
        cases.append(FiscalYearPECase(
            label=case["label"],
            method=case["method"],
            pe_low=case["pe_low"],
            pe_mid=case["pe_mid"],
            pe_high=case["pe_high"],
            value_low=case["value_low"],
            value_mid=case["value_mid"],
            value_high=case["value_high"],
            upside_low_pct=case.get("upside_low_pct"),
            upside_mid_pct=case.get("upside_mid_pct"),
            upside_high_pct=case.get("upside_high_pct"),
            verdict=_classify_verdict(case["upside_mid_pct"]) if case.get("upside_mid_pct") is not None else None,
            weighted_eps_growth=case.get("weighted_eps_growth"),
            growth_curve=case.get("growth_curve"),
            quality_adjustment=case.get("quality_adjustment", 0),
            deceleration_adjustment=case.get("deceleration_adjustment", 0),
            uncertainty_adjustment=case.get("uncertainty_adjustment", 0),
            uncertainty_reasons=case.get("uncertainty_reasons", []),
            historical_guardrail_pe=case.get("historical_guardrail_pe"),
            explanation=case.get("explanation", ""),
        ))
    return cases


def _compute_upside(value: float | None, current_price: float) -> float | None:
    if value is None or current_price <= 0:
        return None
    return round((value - current_price) / current_price, 4)


def _years_between(start_date: str, end_date: str | None) -> float | None:
    if not end_date:
        return None
    try:
        start = dt_date.fromisoformat(start_date)
        end = dt_date.fromisoformat(end_date)
    except ValueError:
        return None
    return (end - start).days / 365.25


def _format_time_distance(start_date: str, end_date: str | None) -> str:
    years = _years_between(start_date, end_date)
    if years is None:
        return "date unknown"
    days = round(years * 365.25)
    if days == 0:
        return "today"

    abs_days = abs(days)
    whole_years = abs_days // 365
    months = round((abs_days % 365) / 30)
    parts = []
    if whole_years:
        parts.append(f"{whole_years}y")
    if months or not parts:
        parts.append(f"{months}m")
    distance = " ".join(parts)
    return f"in {distance}" if days > 0 else f"{distance} ago"


def _infer_fiscal_year_end(latest_fiscal_year_end: str, fiscal_year: int) -> str | None:
    """Infer future FY end by reusing the latest reported fiscal year month/day."""
    if len(latest_fiscal_year_end) < 4:
        return None
    return f"{fiscal_year:04d}{latest_fiscal_year_end[4:]}"


def _classify_verdict(upside_pct: float) -> str:
    """Map base-case upside to a valuation verdict (±15% band)."""
    if upside_pct > _VERDICT_BAND:
        return "undervalued"
    if upside_pct < -_VERDICT_BAND:
        return "overvalued"
    return "fairly_valued"


def _build_view(
    label: str,
    methodology: str,
    current_price: float,
    bear_value: float | None,
    base_value: float | None,
    bull_value: float | None,
    notes: list[str],
) -> ValuationView:
    upside_pct = None
    verdict = None
    if current_price > 0 and base_value is not None:
        upside_pct = round((base_value - current_price) / current_price, 4)
        verdict = _classify_verdict(upside_pct)
    return ValuationView(
        label=label,
        methodology=methodology,
        bear_value=round(bear_value, 2) if bear_value is not None else None,
        base_value=round(base_value, 2) if base_value is not None else None,
        bull_value=round(bull_value, 2) if bull_value is not None else None,
        upside_pct=upside_pct,
        verdict=verdict,
        notes=notes,
    )


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
