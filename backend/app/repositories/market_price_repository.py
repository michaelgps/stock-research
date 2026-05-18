from sqlalchemy.orm import Session

from app.db.financial import MarketPrice


def upsert_many(db: Session, ticker: str, prices: list[dict], source: str = "yfinance") -> tuple[int, int]:
    inserted = 0
    updated = 0
    ticker = ticker.upper()
    for price in prices:
        price_date = price.get("date")
        if not price_date:
            continue
        row = db.query(MarketPrice).filter(
            MarketPrice.ticker == ticker,
            MarketPrice.price_date == price_date,
            MarketPrice.source == source,
        ).first()
        values = {
            "open_price": price.get("open"),
            "high_price": price.get("high"),
            "low_price": price.get("low"),
            "close_price": price.get("close"),
            "adjusted_close_price": price.get("adj_close") or price.get("adjusted_close"),
            "volume": price.get("volume"),
        }
        if row:
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
        else:
            db.add(MarketPrice(ticker=ticker, price_date=price_date, source=source, **values))
            inserted += 1
    db.commit()
    return inserted, updated


def get_prices(db: Session, ticker: str, source: str = "yfinance") -> list[dict]:
    rows = db.query(MarketPrice).filter(
        MarketPrice.ticker == ticker.upper(),
        MarketPrice.source == source,
    ).order_by(MarketPrice.price_date.desc()).all()
    return [
        {
            "date": row.price_date,
            "open": row.open_price,
            "high": row.high_price,
            "low": row.low_price,
            "close": row.close_price,
            "volume": row.volume,
        }
        for row in rows
    ]
