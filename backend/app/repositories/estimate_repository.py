from sqlalchemy.orm import Session

from app.db.financial import Estimate
from app.data_structure.financial import AnalystEstimateData, EarningsSurpriseData
from app.repositories.data_pull_log_repository import today_str


def upsert_many(
    db: Session,
    ticker: str,
    estimates: list[AnalystEstimateData],
    estimate_date: str | None = None,
) -> tuple[int, int]:
    inserted = 0
    updated = 0
    ticker = ticker.upper()
    estimate_date = estimate_date or today_str()
    for estimate in estimates:
        source = estimate.source or "unknown"
        period = estimate.period or "unknown"
        row = db.query(Estimate).filter(
            Estimate.ticker == ticker,
            Estimate.estimate_date == estimate_date,
            Estimate.source == source,
            Estimate.estimate_period == period,
        ).first()
        values = {
            "record_type": "analyst_estimate",
            "revenue_estimate": estimate.revenue_estimate,
            "eps_estimate": estimate.eps_estimate,
            "revenue_growth_estimate": estimate.revenue_growth_estimate,
            "actual_eps": None,
            "estimated_eps": None,
            "surprise": None,
            "surprise_percent": None,
            "buy_count": estimate.buy_count,
            "hold_count": estimate.hold_count,
            "sell_count": estimate.sell_count,
            "target_price": estimate.target_price,
            "raw_data_json": estimate.model_dump(),
        }
        if row:
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
        else:
            db.add(Estimate(
                ticker=ticker,
                estimate_date=estimate_date,
                source=source,
                estimate_period=period,
                **values,
            ))
            inserted += 1
    db.commit()
    return inserted, updated


def upsert_earnings_many(
    db: Session,
    ticker: str,
    surprises: list[EarningsSurpriseData],
    estimate_date: str | None = None,
) -> tuple[int, int]:
    inserted = 0
    updated = 0
    ticker = ticker.upper()
    estimate_date = estimate_date or today_str()
    for surprise in surprises:
        source = surprise.source or "unknown"
        period = f"earnings:{surprise.date or 'unknown'}"
        row = db.query(Estimate).filter(
            Estimate.ticker == ticker,
            Estimate.estimate_date == estimate_date,
            Estimate.source == source,
            Estimate.estimate_period == period,
        ).first()
        values = {
            "record_type": "earnings_surprise",
            "revenue_estimate": None,
            "eps_estimate": None,
            "revenue_growth_estimate": None,
            "actual_eps": surprise.actual_eps,
            "estimated_eps": surprise.estimated_eps,
            "surprise": surprise.surprise,
            "surprise_percent": surprise.surprise_percent,
            "buy_count": None,
            "hold_count": None,
            "sell_count": None,
            "target_price": None,
            "raw_data_json": surprise.model_dump(),
        }
        if row:
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
        else:
            db.add(Estimate(
                ticker=ticker,
                estimate_date=estimate_date,
                source=source,
                estimate_period=period,
                **values,
            ))
            inserted += 1
    db.commit()
    return inserted, updated


def get_latest(db: Session, ticker: str) -> list[Estimate]:
    latest_date = db.query(Estimate.estimate_date).filter(
        Estimate.ticker == ticker.upper()
    ).order_by(Estimate.estimate_date.desc()).first()
    if not latest_date:
        return []
    return db.query(Estimate).filter(
        Estimate.ticker == ticker.upper(),
        Estimate.estimate_date == latest_date[0],
    ).all()
