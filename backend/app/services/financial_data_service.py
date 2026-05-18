import logging

from sqlalchemy.orm import Session

from app.data_structure.financial import (
    AnalystEstimateData,
    CompanyInfo,
    EarningsSurpriseData,
    FinancialDataResponse,
    FinancialStatementData,
    TextMaterial,
)
from app.logic.data_sources import fmp, finnhub_client, sec_edgar
from app.repositories import (
    company_profile_repository,
    company_repository,
    data_pull_log_repository,
    estimate_repository,
    filing_repository,
    financial_report_repository,
)

logger = logging.getLogger(__name__)


def _today() -> str:
    return data_pull_log_repository.today_str()


def _pull_status(inserted: int = 0, updated: int = 0) -> str:
    return data_pull_log_repository.status_for_records(inserted, updated)


def _merge_company(base: CompanyInfo | None, incoming: CompanyInfo | None) -> CompanyInfo | None:
    if incoming is None:
        return base
    if base is None:
        return incoming
    for field in ("name", "sector", "industry", "market_cap", "current_price", "shares_outstanding"):
        value = getattr(incoming, field)
        if value is not None:
            setattr(base, field, value)
    return base


async def ensure_company_and_profile(db: Session, ticker: str) -> None:
    ticker = ticker.upper()
    company_info: CompanyInfo | None = None
    cik = None

    if not data_pull_log_repository.has_success(db, ticker, "company_identity", "sec_edgar"):
        try:
            company_info = await sec_edgar.get_company_info(ticker)
            try:
                cik = await sec_edgar._get_cik_for_ticker(ticker)  # noqa: SLF001 - local EDGAR helper
            except Exception:
                cik = None
            if company_info:
                company_repository.upsert(db, company_info, cik=cik)
            inserted = 1 if company_info else 0
            data_pull_log_repository.mark(
                db,
                ticker,
                "company_identity",
                "sec_edgar",
                _pull_status(inserted),
                records_inserted=inserted,
            )
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "company_identity", "sec_edgar", "failed", error_message=str(exc))
            logger.warning("SEC company identity failed for %s: %s", ticker, exc)

    if not data_pull_log_repository.has_success(db, ticker, "company_profile", "fmp"):
        try:
            fmp_info = await fmp.get_company_info(ticker)
            if fmp_info:
                # API peers are only reference metadata. Manual peers are the
                # only peers allowed into valuation.
                reference_peers = await fmp.get_stock_peers(ticker, industry=fmp_info.industry)
                company_profile_repository.upsert(
                    db,
                    fmp_info,
                    "fmp",
                    peers={"manual": [], "reference": reference_peers},
                )
                company_info = _merge_company(company_info, fmp_info)
            inserted = 1 if fmp_info else 0
            data_pull_log_repository.mark(
                db,
                ticker,
                "company_profile",
                "fmp",
                _pull_status(inserted),
                records_inserted=inserted,
            )
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "company_profile", "fmp", "failed", error_message=str(exc))
            logger.warning("FMP company profile failed for %s: %s", ticker, exc)

    if not data_pull_log_repository.has_success(db, ticker, "company_profile", "finnhub"):
        try:
            finnhub_info = await finnhub_client.get_company_info(ticker)
            if finnhub_info:
                company_profile_repository.upsert(db, finnhub_info, "finnhub")
                company_info = _merge_company(company_info, finnhub_info)
            inserted = 1 if finnhub_info else 0
            data_pull_log_repository.mark(
                db,
                ticker,
                "company_profile",
                "finnhub",
                _pull_status(inserted),
                records_inserted=inserted,
            )
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "company_profile", "finnhub", "failed", error_message=str(exc))
            logger.warning("Finnhub company profile failed for %s: %s", ticker, exc)

    if company_info:
        company_repository.upsert(db, company_info, cik=cik)


async def ensure_financial_reports(db: Session, ticker: str) -> None:
    ticker = ticker.upper()
    statements: list[FinancialStatementData] = []
    if not data_pull_log_repository.has_success(db, ticker, "financial_report", "sec_edgar"):
        try:
            statements = await sec_edgar.get_financial_statements(ticker)
            inserted, updated = financial_report_repository.upsert_many(db, ticker, statements)
            data_pull_log_repository.mark(db, ticker, "financial_report", "sec_edgar", _pull_status(inserted, updated), records_inserted=inserted, records_updated=updated)
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "financial_report", "sec_edgar", "failed", error_message=str(exc))
            logger.warning("SEC financial reports failed for %s: %s", ticker, exc)

    existing = financial_report_repository.get_statements(db, ticker, period_type="annual")
    if len(existing) >= 3:
        return

    if not data_pull_log_repository.has_success(db, ticker, "financial_report", "fmp"):
        try:
            fmp_statements = await fmp.get_financial_statements(ticker)
            inserted, updated = financial_report_repository.upsert_many(db, ticker, fmp_statements)
            data_pull_log_repository.mark(db, ticker, "financial_report", "fmp", _pull_status(inserted, updated), records_inserted=inserted, records_updated=updated)
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "financial_report", "fmp", "failed", error_message=str(exc))
            logger.warning("FMP financial reports failed for %s: %s", ticker, exc)


async def ensure_estimates_and_earnings(db: Session, ticker: str) -> None:
    ticker = ticker.upper()
    if not data_pull_log_repository.has_success(db, ticker, "estimate", "fmp"):
        try:
            estimates = await fmp.get_analyst_estimates(ticker)
            inserted, updated = estimate_repository.upsert_many(db, ticker, estimates)
            data_pull_log_repository.mark(db, ticker, "estimate", "fmp", _pull_status(inserted, updated), records_inserted=inserted, records_updated=updated)
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "estimate", "fmp", "failed", error_message=str(exc))
            logger.warning("FMP estimates failed for %s: %s", ticker, exc)

    if not data_pull_log_repository.has_success(db, ticker, "estimate", "finnhub"):
        try:
            estimates = await finnhub_client.get_analyst_estimates(ticker)
            inserted, updated = estimate_repository.upsert_many(db, ticker, estimates)
            data_pull_log_repository.mark(db, ticker, "estimate", "finnhub", _pull_status(inserted, updated), records_inserted=inserted, records_updated=updated)
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "estimate", "finnhub", "failed", error_message=str(exc))
            logger.warning("Finnhub estimates failed for %s: %s", ticker, exc)

    for source, getter in (("fmp", fmp.get_earnings_surprises), ("finnhub", finnhub_client.get_earnings_surprises)):
        if data_pull_log_repository.has_success(db, ticker, "earnings_surprise", source):
            continue
        try:
            surprises = await getter(ticker)
            inserted, updated = estimate_repository.upsert_earnings_many(db, ticker, surprises)
            data_pull_log_repository.mark(db, ticker, "earnings_surprise", source, _pull_status(inserted, updated), records_inserted=inserted, records_updated=updated)
        except Exception as exc:
            data_pull_log_repository.mark(db, ticker, "earnings_surprise", source, "failed", error_message=str(exc))
            logger.warning("%s earnings surprises failed for %s: %s", source, ticker, exc)


async def ensure_filings(db: Session, ticker: str) -> None:
    ticker = ticker.upper()
    if data_pull_log_repository.has_success(db, ticker, "filing", "sec_edgar"):
        return
    try:
        materials = await sec_edgar.get_10k_text_materials(ticker)
        inserted, updated = filing_repository.upsert_many(db, ticker, materials, source="sec_edgar")
        data_pull_log_repository.mark(db, ticker, "filing", "sec_edgar", _pull_status(inserted, updated), records_inserted=inserted, records_updated=updated)
    except Exception as exc:
        data_pull_log_repository.mark(db, ticker, "filing", "sec_edgar", "failed", error_message=str(exc))
        logger.warning("SEC filings failed for %s: %s", ticker, exc)


def _row_to_company(db: Session, ticker: str) -> CompanyInfo:
    company = company_repository.get(db, ticker)
    fmp_profile = company_profile_repository.get_latest_by_source(db, ticker, "fmp")
    fallback_profile = company_profile_repository.get_latest(db, ticker)
    profile = fmp_profile or fallback_profile
    return CompanyInfo(
        ticker=ticker.upper(),
        name=company.company_name if company else None,
        sector=profile.sector if profile else None,
        industry=profile.industry if profile else None,
        market_cap=profile.market_cap if profile else None,
        current_price=profile.current_price if profile else None,
        shares_outstanding=profile.shares_outstanding if profile else None,
    )


def _row_to_statement(row) -> FinancialStatementData:
    return FinancialStatementData(
        period=row.period_type,
        fiscal_year=row.fiscal_year,
        fiscal_quarter=row.fiscal_quarter or None,
        date=row.report_date,
        revenue=row.revenue,
        cost_of_revenue=row.cost_of_revenue,
        gross_profit=row.gross_profit,
        operating_income=row.operating_income,
        net_income=row.net_income,
        ebitda=row.ebitda,
        cash_from_operations=row.cash_from_operations,
        capital_expenditures=row.capital_expenditures,
        free_cash_flow=row.free_cash_flow,
        total_cash=row.total_cash,
        total_debt=row.total_debt,
        total_assets=row.total_assets,
        total_equity=row.total_equity,
        diluted_shares=row.diluted_shares,
        source=row.source,
    )


def _row_to_estimate(row) -> AnalystEstimateData:
    return AnalystEstimateData(
        period=row.estimate_period,
        revenue_estimate=row.revenue_estimate,
        eps_estimate=row.eps_estimate,
        revenue_growth_estimate=row.revenue_growth_estimate,
        buy_count=row.buy_count,
        hold_count=row.hold_count,
        sell_count=row.sell_count,
        target_price=row.target_price,
        source=row.source,
    )


def _row_to_surprise(row) -> EarningsSurpriseData:
    raw = row.raw_data_json or {}
    return EarningsSurpriseData(
        date=raw.get("date") or row.estimate_period.replace("earnings:", ""),
        actual_eps=row.actual_eps,
        estimated_eps=row.estimated_eps,
        surprise=row.surprise,
        surprise_percent=row.surprise_percent,
        source=row.source,
    )


def build_financial_response(db: Session, ticker: str) -> FinancialDataResponse:
    ticker = ticker.upper()
    statements = financial_report_repository.get_statements(db, ticker)
    estimates = estimate_repository.get_latest(db, ticker)
    text_materials = [
        material for material in filing_repository.get_text_materials(db, ticker)
        if not material.source_type.startswith("signal_")
    ]

    return FinancialDataResponse(
        company=_row_to_company(db, ticker),
        annual_statements=[_row_to_statement(row) for row in statements if row.period_type == "annual"],
        quarterly_statements=[_row_to_statement(row) for row in statements if row.period_type == "quarterly"],
        analyst_estimates=[_row_to_estimate(row) for row in estimates if row.record_type == "analyst_estimate"],
        earnings_surprises=[_row_to_surprise(row) for row in estimates if row.record_type == "earnings_surprise"],
        text_materials=text_materials,
    )


async def collect_financial_data(db: Session, ticker: str) -> FinancialDataResponse:
    ticker = ticker.strip().upper()
    await ensure_company_and_profile(db, ticker)
    await ensure_financial_reports(db, ticker)
    await ensure_estimates_and_earnings(db, ticker)
    await ensure_filings(db, ticker)
    return build_financial_response(db, ticker)


def save_user_text(db: Session, ticker: str, material: TextMaterial) -> None:
    filing_repository.upsert_many(db, ticker, [material], source="user")


def get_user_texts(db: Session, ticker: str) -> list[TextMaterial]:
    return [m for m in filing_repository.get_text_materials(db, ticker) if m.source_type in ("earnings_transcript", "manual")]


def clear_user_texts(db: Session, ticker: str) -> None:
    filing_repository.delete_user_texts(db, ticker)
