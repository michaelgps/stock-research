"""
Compatibility facade for older callers.

The project now stores historical data in tb_* tables through repositories and
services. This module keeps the previous function names so valuation/routes can
be migrated gradually without reintroducing destructive cache replacement.
"""

from sqlalchemy.orm import Session

from app.data_structure.financial import FinancialDataResponse, TextMaterial
from app.repositories import market_price_repository
from app.services import financial_data_service, market_price_service, valuation_service


def load_cached_data(db: Session, ticker: str) -> FinancialDataResponse | None:
    data = financial_data_service.build_financial_response(db, ticker)
    if not data.annual_statements and not data.analyst_estimates and not data.company.name:
        return None
    return data


def save_to_cache(db: Session, data: FinancialDataResponse) -> None:
    # Historical writes now happen inside services as data is fetched.
    return None


def save_user_text(db: Session, ticker: str, material: TextMaterial) -> None:
    financial_data_service.save_user_text(db, ticker, material)


def get_user_texts(db: Session, ticker: str) -> list[TextMaterial]:
    return financial_data_service.get_user_texts(db, ticker)


def clear_user_texts(db: Session, ticker: str) -> None:
    financial_data_service.clear_user_texts(db, ticker)


def save_valuation_result(db: Session, ticker: str, result_dict: dict) -> None:
    valuation_service.save_valuation_result(db, ticker, result_dict)


def load_cached_daily_prices(db: Session, ticker: str) -> list[dict] | None:
    prices = market_price_repository.get_prices(db, ticker)
    return prices or None


def save_daily_prices(db: Session, ticker: str, prices: list[dict]) -> None:
    market_price_repository.upsert_many(db, ticker, prices, source="yfinance")


def ensure_daily_prices(db: Session, ticker: str) -> list[dict]:
    return market_price_service.ensure_daily_prices(db, ticker)
