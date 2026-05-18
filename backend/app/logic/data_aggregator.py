"""
Data aggregation facade.

The old implementation used 24-hour destructive cache replacement. The new
implementation writes historical records into the tb_* tables and uses
tb_data_pull_log to avoid duplicate third-party calls on the same day.
"""

from sqlalchemy.orm import Session

from app.data_structure.financial import FinancialDataResponse
from app.services.financial_data_service import collect_financial_data as _collect_financial_data


async def collect_financial_data(ticker: str, db: Session) -> FinancialDataResponse:
    return await _collect_financial_data(db, ticker)
