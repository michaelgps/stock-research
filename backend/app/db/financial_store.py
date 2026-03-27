"""
PostgreSQL cache layer for financial data.
Saves fetched data so repeated queries for the same ticker skip API calls.
Uses a 24-hour TTL — data older than that is re-fetched from sources.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.financial import (
    Company,
    FinancialStatement,
    AnalystEstimate,
    EarningsSurprise,
    TextMaterialDB,
    ValuationResultDB,
    DailyPrice,
)
from app.data_structure.financial import (
    CompanyInfo,
    FinancialStatementData,
    AnalystEstimateData,
    EarningsSurpriseData,
    TextMaterial,
    FinancialDataResponse,
)

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


def _is_stale(updated_at: datetime) -> bool:
    return datetime.utcnow() - updated_at > timedelta(hours=CACHE_TTL_HOURS)


# --------------- Load from DB ---------------

def load_cached_data(db: Session, ticker: str) -> FinancialDataResponse | None:
    """Load cached financial data for a ticker. Returns None if cache miss or stale."""
    ticker = ticker.upper()

    company_row = db.query(Company).filter(Company.ticker == ticker).first()
    if not company_row or _is_stale(company_row.updated_at):
        return None

    company = CompanyInfo(
        ticker=company_row.ticker,
        name=company_row.name,
        sector=company_row.sector,
        industry=company_row.industry,
        market_cap=company_row.market_cap,
        current_price=company_row.current_price,
        shares_outstanding=company_row.shares_outstanding,
    )

    stmt_rows = db.query(FinancialStatement).filter(
        FinancialStatement.ticker == ticker
    ).order_by(FinancialStatement.fiscal_year.desc()).all()

    annual_statements = [
        FinancialStatementData(
            period=r.period,
            fiscal_year=r.fiscal_year,
            fiscal_quarter=r.fiscal_quarter,
            date=r.date,
            revenue=r.revenue,
            cost_of_revenue=r.cost_of_revenue,
            gross_profit=r.gross_profit,
            operating_income=r.operating_income,
            net_income=r.net_income,
            ebitda=r.ebitda,
            cash_from_operations=r.cash_from_operations,
            capital_expenditures=r.capital_expenditures,
            free_cash_flow=r.free_cash_flow,
            total_cash=r.total_cash,
            total_debt=r.total_debt,
            total_assets=r.total_assets,
            total_equity=r.total_equity,
            diluted_shares=r.diluted_shares,
            source=r.source,
        )
        for r in stmt_rows
    ]

    est_rows = db.query(AnalystEstimate).filter(
        AnalystEstimate.ticker == ticker
    ).all()

    analyst_estimates = [
        AnalystEstimateData(
            period=r.period,
            revenue_estimate=r.revenue_estimate,
            eps_estimate=r.eps_estimate,
            revenue_growth_estimate=r.revenue_growth_estimate,
            buy_count=r.buy_count,
            hold_count=r.hold_count,
            sell_count=r.sell_count,
            target_price=r.target_price,
            source=r.source,
        )
        for r in est_rows
    ]

    surp_rows = db.query(EarningsSurprise).filter(
        EarningsSurprise.ticker == ticker
    ).order_by(EarningsSurprise.date.desc()).all()

    earnings_surprises = [
        EarningsSurpriseData(
            date=r.date,
            actual_eps=r.actual_eps,
            estimated_eps=r.estimated_eps,
            surprise=r.surprise,
            surprise_percent=r.surprise_percent,
            source=r.source,
        )
        for r in surp_rows
    ]

    text_rows = db.query(TextMaterialDB).filter(
        TextMaterialDB.ticker == ticker
    ).all()

    text_materials = [
        TextMaterial(
            ticker=r.ticker,
            source_type=r.source_type,
            content=r.content,
            filing_date=r.filing_date,
            fiscal_year=r.fiscal_year,
        )
        for r in text_rows
    ]

    logger.info(f"Cache hit for {ticker}")
    return FinancialDataResponse(
        company=company,
        annual_statements=annual_statements,
        quarterly_statements=[],
        analyst_estimates=analyst_estimates,
        earnings_surprises=earnings_surprises,
        text_materials=text_materials,
    )


# --------------- Save to DB ---------------

def save_to_cache(db: Session, data: FinancialDataResponse) -> None:
    """Save financial data to the database, replacing any existing data for the ticker."""
    ticker = data.company.ticker.upper()
    now = datetime.utcnow()

    # --- Company ---
    # Resolve peers from industry map (no API call)
    from app.logic.data_sources.fmp import INDUSTRY_PEERS
    industry = data.company.industry
    peers_list = []
    if industry:
        all_peers = INDUSTRY_PEERS.get(industry, [])
        peers_list = [p for p in all_peers if p != ticker][:6]
    peers_str = ",".join(peers_list) if peers_list else None

    company_row = db.query(Company).filter(Company.ticker == ticker).first()
    if company_row:
        company_row.name = data.company.name
        company_row.sector = data.company.sector
        company_row.industry = data.company.industry
        company_row.market_cap = data.company.market_cap
        company_row.current_price = data.company.current_price
        company_row.shares_outstanding = data.company.shares_outstanding
        company_row.peers = peers_str
        company_row.updated_at = now
    else:
        company_row = Company(
            ticker=ticker,
            name=data.company.name,
            sector=data.company.sector,
            industry=data.company.industry,
            market_cap=data.company.market_cap,
            current_price=data.company.current_price,
            shares_outstanding=data.company.shares_outstanding,
            peers=peers_str,
            updated_at=now,
        )
        db.add(company_row)

    # --- Financial Statements (replace all for ticker) ---
    db.query(FinancialStatement).filter(FinancialStatement.ticker == ticker).delete()
    for s in data.annual_statements:
        db.add(FinancialStatement(
            ticker=ticker,
            period=s.period,
            fiscal_year=s.fiscal_year,
            fiscal_quarter=s.fiscal_quarter,
            date=s.date,
            revenue=s.revenue,
            cost_of_revenue=s.cost_of_revenue,
            gross_profit=s.gross_profit,
            operating_income=s.operating_income,
            net_income=s.net_income,
            ebitda=s.ebitda,
            cash_from_operations=s.cash_from_operations,
            capital_expenditures=s.capital_expenditures,
            free_cash_flow=s.free_cash_flow,
            total_cash=s.total_cash,
            total_debt=s.total_debt,
            total_assets=s.total_assets,
            total_equity=s.total_equity,
            diluted_shares=s.diluted_shares,
            source=s.source,
            updated_at=now,
        ))

    # --- Analyst Estimates (replace all for ticker) ---
    db.query(AnalystEstimate).filter(AnalystEstimate.ticker == ticker).delete()
    for e in data.analyst_estimates:
        db.add(AnalystEstimate(
            ticker=ticker,
            period=e.period,
            revenue_estimate=e.revenue_estimate,
            eps_estimate=e.eps_estimate,
            revenue_growth_estimate=e.revenue_growth_estimate,
            buy_count=e.buy_count,
            hold_count=e.hold_count,
            sell_count=e.sell_count,
            target_price=e.target_price,
            source=e.source,
            updated_at=now,
        ))

    # --- Earnings Surprises (replace all for ticker) ---
    db.query(EarningsSurprise).filter(EarningsSurprise.ticker == ticker).delete()
    for s in data.earnings_surprises:
        db.add(EarningsSurprise(
            ticker=ticker,
            date=s.date,
            actual_eps=s.actual_eps,
            estimated_eps=s.estimated_eps,
            surprise=s.surprise,
            surprise_percent=s.surprise_percent,
            source=s.source,
            updated_at=now,
        ))

    # --- Text Materials (replace auto-fetched, keep user-submitted) ---
    db.query(TextMaterialDB).filter(
        TextMaterialDB.ticker == ticker,
        TextMaterialDB.is_user_submitted == False,
    ).delete()
    for t in data.text_materials:
        db.add(TextMaterialDB(
            ticker=ticker,
            source_type=t.source_type,
            content=t.content,
            filing_date=t.filing_date,
            fiscal_year=t.fiscal_year,
            is_user_submitted=False,
            updated_at=now,
        ))

    db.commit()
    logger.info(f"Saved {ticker} to cache")


# --------------- User text materials (persisted to DB) ---------------

def save_user_text(db: Session, ticker: str, material: TextMaterial) -> None:
    """Save a user-submitted text material to the database."""
    ticker = ticker.upper()
    db.add(TextMaterialDB(
        ticker=ticker,
        source_type=material.source_type,
        content=material.content,
        filing_date=material.filing_date,
        fiscal_year=material.fiscal_year,
        is_user_submitted=True,
        updated_at=datetime.utcnow(),
    ))
    db.commit()


def get_user_texts(db: Session, ticker: str) -> list[TextMaterial]:
    """Get all user-submitted text materials for a ticker."""
    rows = db.query(TextMaterialDB).filter(
        TextMaterialDB.ticker == ticker.upper(),
        TextMaterialDB.is_user_submitted == True,
    ).all()
    return [
        TextMaterial(
            ticker=r.ticker,
            source_type=r.source_type,
            content=r.content,
            filing_date=r.filing_date,
            fiscal_year=r.fiscal_year,
        )
        for r in rows
    ]


def clear_user_texts(db: Session, ticker: str) -> None:
    """Delete all user-submitted text materials for a ticker."""
    db.query(TextMaterialDB).filter(
        TextMaterialDB.ticker == ticker.upper(),
        TextMaterialDB.is_user_submitted == True,
    ).delete()
    db.commit()


def save_valuation_result(db: Session, ticker: str, result_dict: dict) -> None:
    """Persist a valuation result to the database."""
    # Delete previous result for this ticker
    db.query(ValuationResultDB).filter(
        ValuationResultDB.ticker == ticker.upper()
    ).delete()

    row = ValuationResultDB(
        ticker=ticker.upper(),
        current_price=result_dict["current_price"],
        bear_blended=result_dict["bear"]["blended_per_share"],
        base_blended=result_dict["base"]["blended_per_share"],
        bull_blended=result_dict["bull"]["blended_per_share"],
        result_json=result_dict,
    )
    db.add(row)
    db.commit()
    logger.info("Saved valuation result for %s to DB", ticker.upper())


# --------------- Daily Prices Cache ---------------

def load_cached_daily_prices(db: Session, ticker: str) -> list[dict] | None:
    """
    Load cached daily prices for a ticker.
    Returns None if no data or if the most recent row is stale (>24h old).
    """
    ticker = ticker.upper()
    rows = db.query(DailyPrice).filter(
        DailyPrice.ticker == ticker
    ).order_by(DailyPrice.date.desc()).all()

    if not rows:
        return None

    # Check staleness on the most recently updated row
    if _is_stale(rows[0].updated_at):
        return None

    logger.info("Daily prices cache hit for %s (%d rows)", ticker, len(rows))
    return [
        {
            "date": r.date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        }
        for r in rows
    ]


def save_daily_prices(db: Session, ticker: str, prices: list[dict]) -> None:
    """Save daily prices to the database, replacing existing data for the ticker."""
    ticker = ticker.upper()
    if not prices:
        return

    now = datetime.utcnow()

    # Delete old data for this ticker
    db.query(DailyPrice).filter(DailyPrice.ticker == ticker).delete()

    # Bulk insert
    for p in prices:
        db.add(DailyPrice(
            ticker=ticker,
            date=p.get("date", ""),
            open=p.get("open"),
            high=p.get("high"),
            low=p.get("low"),
            close=p.get("close"),
            volume=p.get("volume"),
            source="fmp",
            updated_at=now,
        ))

    db.commit()
    logger.info("Saved %d daily prices for %s", len(prices), ticker)
