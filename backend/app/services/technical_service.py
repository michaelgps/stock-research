from sqlalchemy.orm import Session

from app.data_structure.technical import TechnicalLevelsResponse
from app.logic.technical import compute_technical_levels
from app.repositories import data_pull_log_repository, technical_level_repository
from app.services.market_price_service import ensure_daily_prices


def get_technical_levels(db: Session, ticker: str) -> TechnicalLevelsResponse:
    """Compute and persist daily OHLCV liquidity zones for a ticker."""
    ticker = ticker.strip().upper()
    prices = ensure_daily_prices(db, ticker, allow_recent_existing=True)
    result = compute_technical_levels(ticker, prices)
    technical_level_repository.save_response(db, result)
    data_pull_log_repository.mark(
        db,
        ticker,
        "technical_level",
        "technical_v1",
        "success",
        records_inserted=len(result.support_zones) + len(result.resistance_zones) + len(result.active_zones),
        records_updated=0,
    )
    return result
