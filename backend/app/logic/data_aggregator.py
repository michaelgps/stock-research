"""
Data aggregator service.
Orchestrates data collection from multiple sources, merges, and normalizes.
Priority: SEC EDGAR (ground truth) > FMP (convenience) > Finnhub (estimates/metadata)
"""

import logging

from sqlalchemy.orm import Session

from app.data_structure.financial import (
    CompanyInfo,
    FinancialStatementData,
    AnalystEstimateData,
    EarningsSurpriseData,
    TextMaterial,
    FinancialDataResponse,
)
from app.logic.data_sources import sec_edgar, fmp, finnhub_client
from app.db.financial_store import load_cached_data, save_to_cache, get_user_texts

logger = logging.getLogger(__name__)


async def _get_company_info(ticker: str) -> CompanyInfo:
    """Get company info, preferring SEC EDGAR, falling back to FMP/Finnhub."""
    info = await sec_edgar.get_company_info(ticker)

    fmp_info = await fmp.get_company_info(ticker)
    if fmp_info:
        if info is None:
            info = fmp_info
        else:
            if fmp_info.sector:
                info.sector = fmp_info.sector
            if fmp_info.industry:
                info.industry = fmp_info.industry
            if fmp_info.market_cap:
                info.market_cap = fmp_info.market_cap
            if fmp_info.current_price:
                info.current_price = fmp_info.current_price
            if fmp_info.shares_outstanding:
                info.shares_outstanding = fmp_info.shares_outstanding

    if info is None or not info.name:
        finnhub_info = await finnhub_client.get_company_info(ticker)
        if finnhub_info:
            if info is None:
                info = finnhub_info
            else:
                if not info.name:
                    info.name = finnhub_info.name
                if not info.shares_outstanding:
                    info.shares_outstanding = finnhub_info.shares_outstanding

    if info is None:
        info = CompanyInfo(ticker=ticker.upper())

    return info


async def _get_financial_statements(ticker: str) -> list[FinancialStatementData]:
    """Get annual financial statements. SEC EDGAR is primary, FMP as fallback."""
    annual = await sec_edgar.get_financial_statements(ticker)

    if len(annual) < 3:
        fmp_annual = await fmp.get_financial_statements(ticker)
        if len(fmp_annual) > len(annual):
            annual = fmp_annual

    return annual


async def _get_analyst_estimates(ticker: str) -> list[AnalystEstimateData]:
    """Get analyst estimates from FMP and Finnhub."""
    estimates: list[AnalystEstimateData] = []

    fmp_estimates = await fmp.get_analyst_estimates(ticker)
    if fmp_estimates:
        estimates.extend(fmp_estimates)

    finnhub_estimates = await finnhub_client.get_analyst_estimates(ticker)
    if finnhub_estimates:
        estimates.extend(finnhub_estimates)

    return estimates


async def _get_earnings_surprises(ticker: str) -> list[EarningsSurpriseData]:
    """
    Get earnings surprises by merging Finnhub and FMP data.
    Deduplicates by date, preferring Finnhub (more complete surprise data).
    """
    finnhub_surprises = await finnhub_client.get_earnings_surprises(ticker)
    fmp_surprises = await fmp.get_earnings_surprises(ticker)

    by_date: dict[str, EarningsSurpriseData] = {}
    for s in fmp_surprises:
        if s.date:
            by_date[s.date] = s
    for s in finnhub_surprises:
        if s.date:
            by_date[s.date] = s

    merged = sorted(by_date.values(), key=lambda x: x.date, reverse=True)
    return merged


async def _get_text_materials(ticker: str, db: Session) -> list[TextMaterial]:
    """
    Collect text materials from all sources:
    1. SEC EDGAR 10-K (MD&A + Risk Factors) — auto-fetched
    2. User-submitted texts from database
    """
    materials: list[TextMaterial] = []

    edgar_texts = await sec_edgar.get_10k_text_materials(ticker)
    materials.extend(edgar_texts)

    user_texts = get_user_texts(db, ticker)
    materials.extend(user_texts)

    return materials


async def collect_financial_data(ticker: str, db: Session) -> FinancialDataResponse:
    """
    Main entry point. Checks PostgreSQL cache first (24h TTL).
    If cache miss or stale, fetches from APIs and saves to DB.
    """
    ticker = ticker.strip().upper()

    # Check cache
    cached = load_cached_data(db, ticker)
    if cached:
        # Still include any new user-submitted texts
        user_texts = get_user_texts(db, ticker)
        if user_texts:
            existing_user = [t for t in cached.text_materials if t.source_type in ("earnings_transcript", "manual")]
            if len(user_texts) != len(existing_user):
                cached.text_materials = [
                    t for t in cached.text_materials
                    if t.source_type not in ("earnings_transcript", "manual")
                ] + user_texts
        return cached

    # Cache miss — fetch from APIs
    logger.info(f"Cache miss for {ticker}, fetching from APIs")

    company = await _get_company_info(ticker)
    annual = await _get_financial_statements(ticker)
    estimates = await _get_analyst_estimates(ticker)
    surprises = await _get_earnings_surprises(ticker)
    text_materials = await _get_text_materials(ticker, db)

    result = FinancialDataResponse(
        company=company,
        annual_statements=annual,
        quarterly_statements=[],
        analyst_estimates=estimates,
        earnings_surprises=surprises,
        text_materials=text_materials,
    )

    # Save to cache
    save_to_cache(db, result)

    return result
