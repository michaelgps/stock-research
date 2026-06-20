from sqlalchemy.orm import Session

from app.db.financial import TechnicalLevel
from app.data_structure.technical import TechnicalLevelsResponse, TechnicalZone


def save_response(
    db: Session,
    response: TechnicalLevelsResponse,
    source: str = "technical_v1",
) -> None:
    """Replace same-day technical levels for a ticker/source with fresh rows."""
    ticker = response.ticker.upper()
    level_date = response.analysis_date
    db.query(TechnicalLevel).filter(
        TechnicalLevel.ticker == ticker,
        TechnicalLevel.level_date == level_date,
        TechnicalLevel.source == source,
    ).delete()

    groups = {
        "support": response.support_zones,
        "resistance": response.resistance_zones,
        "active": response.active_zones,
    }
    for level_type, zones in groups.items():
        for index, zone in enumerate(zones, start=1):
            db.add(TechnicalLevel(
                ticker=ticker,
                level_date=level_date,
                source=source,
                level_type=level_type,
                rank=index,
                price_low=zone.price_low,
                price_high=zone.price_high,
                center_price=zone.center_price,
                strength_score=zone.strength_score,
                relevance_score=zone.relevance_score,
                strength_label=zone.strength_label,
                evidence_json=zone.evidence,
                invalid_if=zone.invalid_if,
                breakout_confirmation=zone.breakout_confirmation,
                lookback_days=response.lookback_days,
                raw_data_json=zone.model_dump(),
            ))
    db.commit()
