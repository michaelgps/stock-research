from sqlalchemy.orm import Session

from app.db.financial import Company
from app.data_structure.financial import CompanyInfo


def upsert(db: Session, info: CompanyInfo, cik: str | None = None) -> tuple[int, int]:
    ticker = info.ticker.upper()
    row = db.query(Company).filter(Company.ticker == ticker).first()
    values = {
        "company_name": info.name,
        "cik": cik,
        "currency": info.currency,
    }
    if row:
        for key, value in values.items():
            if value is not None:
                setattr(row, key, value)
        db.commit()
        return 0, 1
    db.add(Company(ticker=ticker, **values))
    db.commit()
    return 1, 0


def get(db: Session, ticker: str) -> Company | None:
    return db.query(Company).filter(Company.ticker == ticker.upper()).first()
