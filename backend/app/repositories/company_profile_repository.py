from sqlalchemy.orm import Session

from app.db.financial import CompanyProfile
from app.data_structure.financial import CompanyInfo
from app.repositories.data_pull_log_repository import today_str


def upsert(
    db: Session,
    info: CompanyInfo,
    source: str,
    profile_date: str | None = None,
    peers: list[str] | None = None,
    raw_data: dict | list | None = None,
) -> tuple[int, int]:
    ticker = info.ticker.upper()
    profile_date = profile_date or today_str()
    row = db.query(CompanyProfile).filter(
        CompanyProfile.ticker == ticker,
        CompanyProfile.profile_date == profile_date,
        CompanyProfile.source == source,
    ).first()
    values = {
        "sector": info.sector,
        "industry": info.industry,
        "market_cap": info.market_cap,
        "current_price": info.current_price,
        "shares_outstanding": info.shares_outstanding,
        "peers_json": peers,
        "raw_data_json": raw_data,
    }
    if row:
        for key, value in values.items():
            if value is not None:
                setattr(row, key, value)
        db.commit()
        return 0, 1
    db.add(CompanyProfile(ticker=ticker, profile_date=profile_date, source=source, **values))
    db.commit()
    return 1, 0


def get_latest(db: Session, ticker: str) -> CompanyProfile | None:
    return db.query(CompanyProfile).filter(
        CompanyProfile.ticker == ticker.upper()
    ).order_by(CompanyProfile.profile_date.desc(), CompanyProfile.id.desc()).first()


def get_latest_by_source(db: Session, ticker: str, source: str) -> CompanyProfile | None:
    return db.query(CompanyProfile).filter(
        CompanyProfile.ticker == ticker.upper(),
        CompanyProfile.source == source,
    ).order_by(CompanyProfile.profile_date.desc(), CompanyProfile.id.desc()).first()


def set_manual_peers(db: Session, ticker: str, peers: list[str], profile_date: str | None = None) -> None:
    ticker = ticker.upper()
    profile_date = profile_date or today_str()
    row = db.query(CompanyProfile).filter(
        CompanyProfile.ticker == ticker,
        CompanyProfile.profile_date == profile_date,
        CompanyProfile.source == "manual",
    ).first()
    peers_json = {"manual": [p.upper() for p in peers if p.upper() != ticker], "reference": []}
    if row:
        row.peers_json = peers_json
    else:
        db.add(CompanyProfile(
            ticker=ticker,
            profile_date=profile_date,
            source="manual",
            sector=None,
            industry=None,
            market_cap=None,
            current_price=None,
            shares_outstanding=None,
            peers_json=peers_json,
            raw_data_json={"manual_peers": peers_json["manual"]},
        ))
    db.commit()
