"""
Financial Modeling Prep (FMP) data source.
Convenience layer for normalized financial statements, company profile, and market data.
Uses the /stable/ API endpoints.
Requires API key from financialmodelingprep.com.
"""

import logging
import httpx
from app.config.config import get_settings

logger = logging.getLogger(__name__)
from app.data_structure.financial import (
    CompanyInfo,
    FinancialStatementData,
    AnalystEstimateData,
    EarningsSurpriseData,
)

FMP_BASE = "https://financialmodelingprep.com/stable"


def _is_configured() -> bool:
    key = get_settings().fmp_api_key
    return bool(key) and key != "your_fmp_api_key_here"


async def _get(endpoint: str, params: dict | None = None) -> dict | list | None:
    if not _is_configured():
        return None

    settings = get_settings()
    url = f"{FMP_BASE}/{endpoint}"
    query = {"apikey": settings.fmp_api_key}
    if params:
        query.update(params)

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=query)
        if resp.status_code != 200:
            return None
        return resp.json()


async def get_company_info(ticker: str) -> CompanyInfo | None:
    data = await _get("profile", {"symbol": ticker.upper()})
    if not data or not isinstance(data, list) or len(data) == 0:
        return None

    profile = data[0]
    return CompanyInfo(
        ticker=ticker.upper(),
        name=profile.get("companyName"),
        sector=profile.get("sector"),
        industry=profile.get("industry"),
        market_cap=profile.get("marketCap"),
        current_price=profile.get("price"),
    )


async def get_financial_statements(ticker: str) -> list[FinancialStatementData]:
    """Fetch annual income statements, balance sheets, and cash flows from FMP."""
    symbol = ticker.upper()
    # FMP free plan allows max 5 years; paid plans can increase this
    limit = 5
    income = await _get("income-statement", {"symbol": symbol, "limit": limit})
    balance = await _get("balance-sheet-statement", {"symbol": symbol, "limit": limit})
    cashflow = await _get("cash-flow-statement", {"symbol": symbol, "limit": limit})

    if not income:
        return []

    # Index balance sheet and cash flow by date for joining
    balance_by_date = {b["date"]: b for b in (balance or [])}
    cashflow_by_date = {c["date"]: c for c in (cashflow or [])}

    statements = []
    for inc in income:
        date = inc["date"]
        bal = balance_by_date.get(date, {})
        cf = cashflow_by_date.get(date, {})

        statements.append(
            FinancialStatementData(
                period="annual",
                fiscal_year=int(inc.get("fiscalYear", date[:4])),
                date=date,
                revenue=inc.get("revenue"),
                cost_of_revenue=inc.get("costOfRevenue"),
                gross_profit=inc.get("grossProfit"),
                operating_income=inc.get("operatingIncome"),
                net_income=inc.get("netIncome"),
                ebitda=inc.get("ebitda"),
                cash_from_operations=cf.get("operatingCashFlow"),
                capital_expenditures=cf.get("capitalExpenditure"),
                free_cash_flow=cf.get("freeCashFlow"),
                total_cash=bal.get("cashAndCashEquivalents"),
                total_debt=bal.get("totalDebt"),
                total_assets=bal.get("totalAssets"),
                total_equity=bal.get("totalStockholdersEquity"),
                diluted_shares=inc.get("weightedAverageShsOutDil"),
                source="fmp",
            )
        )

    return statements


async def get_analyst_estimates(ticker: str) -> list[AnalystEstimateData]:
    data = await _get("analyst-estimates", {"symbol": ticker.upper(), "period": "annual", "limit": 5})
    if not data:
        return []

    estimates = []
    for entry in data:
        estimates.append(
            AnalystEstimateData(
                period=entry.get("date", "")[:4],
                revenue_estimate=entry.get("revenueAvg"),
                eps_estimate=entry.get("epsAvg"),
                source="fmp",
            )
        )

    return estimates


async def get_historical_ratios(ticker: str) -> list[dict]:
    """Fetch annual valuation ratios (P/E, PEG, P/S, etc.) from FMP."""
    data = await _get("ratios", {"symbol": ticker.upper(), "period": "annual", "limit": 5})
    if not data or not isinstance(data, list):
        return []
    return data


async def get_daily_prices(ticker: str) -> list[dict]:
    """Fetch ~5 years of daily OHLCV prices from FMP."""
    data = await _get("historical-price-eod/full", {"symbol": ticker.upper()})
    if not data:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("historical", [])
    return []


# ---------------------------------------------------------------------------
# Industry peer map — curated peers by industry for accurate P/E comparison.
# FMP's /stock-peers endpoint returns same-sector companies (e.g. AAPL for NVDA)
# which is useless. This map provides actual business competitors.
# ---------------------------------------------------------------------------
INDUSTRY_PEERS: dict[str, list[str]] = {
    "Semiconductors": ["NVDA", "AMD", "AVGO", "QCOM", "INTC", "MU", "TXN", "MRVL", "LRCX", "KLAC"],
    "Consumer Electronics": ["AAPL", "SONY", "SAMSUNG", "HPQ", "DELL"],
    "Software - Infrastructure": ["MSFT", "ORCL", "CRM", "NOW", "INTU", "ADBE", "PLTR"],
    "Software - Application": ["CRM", "ADBE", "INTU", "NOW", "WDAY", "SNPS", "CDNS"],
    "Internet Content & Information": ["GOOGL", "META", "SNAP", "PINS", "RDDT"],
    "Internet Retail": ["AMZN", "BABA", "JD", "PDD", "MELI", "SE"],
    "Auto - Manufacturers": ["TSLA", "TM", "F", "GM", "STLA", "RIVN", "HMC", "NIO"],
    "Biotechnology": ["AMGN", "GILD", "VRTX", "REGN", "BIIB", "MRNA", "ABBV"],
    "Drug Manufacturers": ["LLY", "JNJ", "PFE", "MRK", "NVO", "AZN", "BMY"],
    "Banks - Diversified": ["JPM", "BAC", "WFC", "C", "GS", "MS"],
    "Aerospace & Defense": ["LMT", "RTX", "BA", "NOC", "GD", "LHX"],
    "Oil & Gas Integrated": ["XOM", "CVX", "COP", "EOG", "SLB", "OXY"],
    "Restaurants": ["MCD", "SBUX", "CMG", "YUM", "DRI", "QSR"],
    "Discount Stores": ["WMT", "COST", "TGT", "DG", "DLTR"],
    "Specialty Retail": ["HD", "LOW", "TJX", "ROST", "BBY"],
}


async def get_stock_peers(ticker: str, industry: str | None = None) -> list[str]:
    """
    Get peer tickers for a stock. Uses curated industry peer map first,
    falls back to FMP /stock-peers endpoint if industry not in map.
    """
    ticker = ticker.upper()

    # Try industry peer map first
    if industry:
        peers = INDUSTRY_PEERS.get(industry, [])
        if peers:
            result = [p for p in peers if p != ticker][:6]
            if result:
                logger.info("Peers for %s from industry map (%s): %s", ticker, industry, result)
                return result

    # Fallback to FMP API
    data = await _get("stock-peers", {"symbol": ticker})
    if not data or not isinstance(data, list) or len(data) == 0:
        return []
    peers = [p["symbol"] for p in data if isinstance(p, dict) and "symbol" in p]
    peers = [p for p in peers if p.upper() != ticker][:6]
    return peers


async def _get_latest_actual_eps(ticker: str) -> tuple[float | None, str | None]:
    """
    Fetch the latest actual diluted EPS and FY end date from income statement.
    Returns (eps, fy_end_date_str) e.g. (4.93, "2026-01-25").
    """
    data = await _get("income-statement", {"symbol": ticker.upper(), "period": "annual"})
    if not data or not isinstance(data, list) or len(data) == 0:
        return None, None
    latest = data[0]
    eps = latest.get("eps")
    fy_end = latest.get("date")
    if eps is not None and eps > 0:
        return eps, fy_end
    return None, fy_end


def _compute_eps_growth(
    actual_eps: float | None,
    fy_end_date: str | None,
    estimates: list,
) -> float | None:
    """
    Compute forward EPS growth rate anchored on latest actual EPS.

    Uses 2-year forward CAGR from actual EPS to smooth single-year spikes.
    Time-window adjustment: if < 6 months to next FY end, the market is already
    looking through, so shift the window forward by 1 year.

    E.g. NVDA actual FY2026 EPS=$4.93, estimates FY2027=$8.25, FY2028=$10.89:
      Normal (>6mo to FY2027): CAGR = (10.89/4.93)^(1/2) - 1 = 48.6%
      Near FY end (<6mo):      CAGR = (12.60/8.25)^(1/1) - 1 = 52.7% (shift to FY2027->FY2029)
    """
    from datetime import datetime, date

    fmp = [e for e in estimates if e.eps_estimate is not None and e.eps_estimate > 0]
    fmp.sort(key=lambda e: e.period)
    if not fmp:
        return None

    # Determine if we need to shift the window
    shift = 0
    if fy_end_date:
        try:
            fy_end = datetime.strptime(fy_end_date[:10], "%Y-%m-%d").date()
            today = date.today()
            # Next FY end is ~1 year after latest actual FY end
            next_fy_end = fy_end.replace(year=fy_end.year + 1)
            months_to_next_fy = (next_fy_end - today).days / 30.0
            if months_to_next_fy < 6:
                shift = 1
        except (ValueError, TypeError):
            pass

    if actual_eps is not None and actual_eps > 0:
        # Anchor on actual EPS, compute 2-year forward CAGR
        start_eps = actual_eps
        try:
            first_est_year = int(fmp[0].period)
            if fy_end_date:
                actual_year = int(fy_end_date[:4])
            else:
                actual_year = first_est_year - 1
        except (ValueError, TypeError):
            return None

        target_idx = shift + 1  # default: 2nd forward year (2-year CAGR from actual)
        if target_idx < len(fmp):
            target_eps = fmp[target_idx].eps_estimate
            try:
                target_year = int(fmp[target_idx].period)
            except (ValueError, TypeError):
                return None
            years = target_year - actual_year
            if years > 0 and target_eps > 0:
                return (target_eps / start_eps) ** (1 / years) - 1

        # Fallback: use 1st forward year (1-year growth from actual)
        fallback_idx = shift
        if fallback_idx < len(fmp):
            target_eps = fmp[fallback_idx].eps_estimate
            try:
                target_year = int(fmp[fallback_idx].period)
            except (ValueError, TypeError):
                return None
            years = target_year - actual_year
            if years > 0 and target_eps > 0:
                return (target_eps / start_eps) ** (1 / years) - 1

    # Fallback: estimate-only CAGR (2-year window, no actual EPS available)
    if len(fmp) >= 2 + shift:
        first = fmp[shift]
        last = fmp[min(shift + 2, len(fmp) - 1)]
        try:
            years = int(last.period) - int(first.period)
        except (ValueError, TypeError):
            return None
        if years > 0 and first.eps_estimate > 0 and last.eps_estimate > 0:
            return (last.eps_estimate / first.eps_estimate) ** (1 / years) - 1

    return None


def _median(values: list[float]) -> float:
    """Simple median."""
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


async def get_peer_forward_pe(
    ticker: str,
    ticker_eps_growth: float | None = None,
    industry: str | None = None,
) -> dict:
    """
    Fetch peer forward P/E data with growth adjustment.

    For each peer, computes forward P/E and EPS growth (CAGR from analyst estimates).
    Then computes PEG ratios and a growth-adjusted P/E for the ticker:
      growth_adjusted_pe = median_PEG × ticker_eps_growth × 100

    This ensures peers growing at 20% don't inflate the P/E for a ticker growing at 10%.
    """
    peers = await get_stock_peers(ticker, industry=industry)
    if not peers:
        return {"peers": [], "median_pe": None, "cap_weighted_pe": None,
                "median_peg": None, "growth_adjusted_pe": None}

    peer_data = []
    for sym in peers:
        try:
            # Get profile (price + market cap), analyst estimates, and actual EPS
            profile = await get_company_info(sym)
            estimates = await get_analyst_estimates(sym)
            actual_eps, fy_end_date = await _get_latest_actual_eps(sym)

            if not profile or not profile.current_price:
                continue

            # Get next FY EPS (same logic as our get_forward_eps)
            fmp_eps = [e for e in estimates if e.eps_estimate is not None]
            fmp_eps.sort(key=lambda e: e.period)
            if not fmp_eps or fmp_eps[0].eps_estimate <= 0:
                continue

            fwd_eps = fmp_eps[0].eps_estimate
            fwd_pe = profile.current_price / fwd_eps

            # Compute peer's forward EPS growth (anchored on actual EPS, 2-year CAGR)
            eps_growth = _compute_eps_growth(actual_eps, fy_end_date, estimates)

            peer_data.append({
                "ticker": sym,
                "price": round(profile.current_price, 2),
                "forward_eps": round(fwd_eps, 2),
                "forward_pe": round(fwd_pe, 1),
                "market_cap": profile.market_cap,
                "eps_growth": round(eps_growth, 3) if eps_growth is not None else None,
            })
        except Exception as e:
            logger.warning("Skipping peer %s: %s", sym, e)
            continue

    if not peer_data:
        return {"peers": [], "median_pe": None, "cap_weighted_pe": None,
                "median_peg": None, "growth_adjusted_pe": None}

    # Median forward P/E (raw, before growth adjustment)
    pes = sorted([p["forward_pe"] for p in peer_data])
    median_pe = _median(pes)

    # Cap-weighted forward P/E
    total_cap = sum(p["market_cap"] for p in peer_data if p["market_cap"])
    if total_cap > 0:
        cap_weighted_pe = sum(
            p["forward_pe"] * (p["market_cap"] or 0) / total_cap
            for p in peer_data
        )
    else:
        cap_weighted_pe = median_pe

    # PEG-based growth adjustment
    # PEG = forward_pe / (eps_growth * 100)  — growth expressed as whole number (e.g. 15 for 15%)
    peg_ratios = []
    for p in peer_data:
        if p["eps_growth"] is not None and p["eps_growth"] > 0.01:  # need meaningful growth
            peg = p["forward_pe"] / (p["eps_growth"] * 100)
            peg_ratios.append(peg)

    median_peg = None
    growth_adjusted_pe = None
    if peg_ratios and ticker_eps_growth is not None and ticker_eps_growth > 0.01:
        median_peg = round(_median(peg_ratios), 2)
        # What P/E would this ticker deserve given the peer PEG and its own growth?
        growth_adjusted_pe = round(median_peg * (ticker_eps_growth * 100), 1)

    return {
        "peers": peer_data,
        "median_pe": round(median_pe, 1),
        "cap_weighted_pe": round(cap_weighted_pe, 1),
        "median_peg": median_peg,
        "growth_adjusted_pe": growth_adjusted_pe,
    }


async def get_earnings_surprises(ticker: str) -> list[EarningsSurpriseData]:
    """Fetch historical earnings surprises (actual vs estimated EPS)."""
    data = await _get("earnings-surprises", {"symbol": ticker.upper()})
    if not data or not isinstance(data, list):
        return []

    surprises = []
    for entry in data[:12]:  # Last 12 quarters
        actual = entry.get("actualEarningResult")
        estimated = entry.get("estimatedEarning")
        surprise = None
        surprise_pct = None
        if actual is not None and estimated is not None:
            surprise = actual - estimated
            if estimated != 0:
                surprise_pct = (surprise / abs(estimated)) * 100

        surprises.append(
            EarningsSurpriseData(
                date=entry.get("date", ""),
                actual_eps=actual,
                estimated_eps=estimated,
                surprise=surprise,
                surprise_percent=surprise_pct,
                source="fmp",
            )
        )

    return surprises
