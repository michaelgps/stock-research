from datetime import date

from sqlalchemy.orm import Session

from app.db.financial import DataPullLog


def today_str() -> str:
    return date.today().isoformat()


def has_success(db: Session, ticker: str, data_type: str, source: str, pull_date: str | None = None) -> bool:
    row = db.query(DataPullLog).filter(
        DataPullLog.ticker == ticker.upper(),
        DataPullLog.data_type == data_type,
        DataPullLog.source == source,
        DataPullLog.pull_date == (pull_date or today_str()),
        DataPullLog.status == "success",
    ).first()
    return row is not None


def status_for_records(records_inserted: int = 0, records_updated: int = 0) -> str:
    """Only non-empty parsed data should block another pull on the same day."""
    return "success" if records_inserted > 0 or records_updated > 0 else "empty"


def mark(
    db: Session,
    ticker: str,
    data_type: str,
    source: str,
    status: str,
    error_message: str | None = None,
    records_inserted: int = 0,
    records_updated: int = 0,
    pull_date: str | None = None,
) -> None:
    ticker = ticker.upper()
    pull_date = pull_date or today_str()
    row = db.query(DataPullLog).filter(
        DataPullLog.ticker == ticker,
        DataPullLog.data_type == data_type,
        DataPullLog.source == source,
        DataPullLog.pull_date == pull_date,
    ).first()
    values = {
        "status": status,
        "error_message": error_message,
        "records_inserted": records_inserted,
        "records_updated": records_updated,
    }
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        db.add(DataPullLog(
            ticker=ticker,
            data_type=data_type,
            source=source,
            pull_date=pull_date,
            **values,
        ))
    db.commit()
