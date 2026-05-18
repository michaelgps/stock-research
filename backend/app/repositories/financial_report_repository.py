from sqlalchemy.orm import Session

from app.db.financial import FinancialReport
from app.data_structure.financial import FinancialStatementData


def upsert_many(db: Session, ticker: str, statements: list[FinancialStatementData]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    ticker = ticker.upper()
    for statement in statements:
        source = statement.source or "unknown"
        fiscal_quarter = statement.fiscal_quarter or 0
        row = db.query(FinancialReport).filter(
            FinancialReport.ticker == ticker,
            FinancialReport.source == source,
            FinancialReport.period_type == statement.period,
            FinancialReport.fiscal_year == statement.fiscal_year,
            FinancialReport.fiscal_quarter == fiscal_quarter,
        ).first()
        values = {
            "report_date": statement.date,
            "filing_date": None,
            "revenue": statement.revenue,
            "cost_of_revenue": statement.cost_of_revenue,
            "gross_profit": statement.gross_profit,
            "operating_income": statement.operating_income,
            "net_income": statement.net_income,
            "ebitda": statement.ebitda,
            "cash_from_operations": statement.cash_from_operations,
            "capital_expenditures": statement.capital_expenditures,
            "free_cash_flow": statement.free_cash_flow,
            "total_cash": statement.total_cash,
            "total_debt": statement.total_debt,
            "total_assets": statement.total_assets,
            "total_equity": statement.total_equity,
            "diluted_shares": statement.diluted_shares,
            "raw_data_json": statement.model_dump(),
        }
        if row:
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
        else:
            db.add(FinancialReport(
                ticker=ticker,
                source=source,
                period_type=statement.period,
                fiscal_year=statement.fiscal_year,
                fiscal_quarter=fiscal_quarter,
                **values,
            ))
            inserted += 1
    db.commit()
    return inserted, updated


def get_statements(db: Session, ticker: str, period_type: str | None = None) -> list[FinancialReport]:
    query = db.query(FinancialReport).filter(FinancialReport.ticker == ticker.upper())
    if period_type:
        query = query.filter(FinancialReport.period_type == period_type)
    return query.order_by(FinancialReport.fiscal_year.desc(), FinancialReport.fiscal_quarter.desc()).all()
