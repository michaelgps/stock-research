from datetime import date

from sqlalchemy.orm import Session

from app.logic.data_sources.yfinance_client import get_daily_prices
from app.repositories import data_pull_log_repository, market_price_repository


def ensure_daily_prices(db: Session, ticker: str, allow_recent_existing: bool = False) -> list[dict]:
    ticker = ticker.upper()
    existing = market_price_repository.get_prices(db, ticker)
    if existing and data_pull_log_repository.has_success(db, ticker, "market_price", "yfinance"):
        return existing
    if allow_recent_existing and _has_recent_prices(existing):
        return existing

    prices = get_daily_prices(ticker)
    inserted, updated = market_price_repository.upsert_many(db, ticker, prices, source="yfinance")
    data_pull_log_repository.mark(
        db,
        ticker,
        "market_price",
        "yfinance",
        "success" if prices else "partial",
        records_inserted=inserted,
        records_updated=updated,
    )
    return market_price_repository.get_prices(db, ticker)


def _has_recent_prices(prices: list[dict], max_staleness_days: int = 7) -> bool:
    if not prices:
        return False
    latest = prices[0].get("date")
    if not latest:
        return False
    try:
        latest_date = date.fromisoformat(latest)
    except ValueError:
        return False
    return (date.today() - latest_date).days <= max_staleness_days
