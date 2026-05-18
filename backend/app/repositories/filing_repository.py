import hashlib

from sqlalchemy.orm import Session

from app.db.financial import Filing
from app.data_structure.financial import TextMaterial


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def upsert_many(db: Session, ticker: str, materials: list[TextMaterial], source: str = "sec_edgar") -> tuple[int, int]:
    inserted = 0
    updated = 0
    ticker = ticker.upper()
    for material in materials:
        section_type = material.source_type
        accession_number = f"{source}:{material.filing_date or 'unknown'}:{section_type}:{_hash_content(material.content)[:12]}"
        row = db.query(Filing).filter(
            Filing.ticker == ticker,
            Filing.source == source,
            Filing.accession_number == accession_number,
            Filing.section_type == section_type,
        ).first()
        values = {
            "filing_type": "user_text" if source == "user" else ("signal_extraction" if source == "llm" else "10-K"),
            "filing_date": material.filing_date,
            "fiscal_year": material.fiscal_year,
            "fiscal_quarter": None,
            "content": material.content,
            "source_url": None,
            "is_user_submitted": source == "user",
            "content_hash": _hash_content(material.content),
            "raw_data_json": material.model_dump(),
        }
        if row:
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
        else:
            db.add(Filing(
                ticker=ticker,
                source=source,
                accession_number=accession_number,
                section_type=section_type,
                **values,
            ))
            inserted += 1
    db.commit()
    return inserted, updated


def get_text_materials(db: Session, ticker: str) -> list[TextMaterial]:
    rows = db.query(Filing).filter(Filing.ticker == ticker.upper()).all()
    return [
        TextMaterial(
            ticker=row.ticker,
            source_type=row.section_type,
            content=row.content,
            filing_date=row.filing_date,
            fiscal_year=row.fiscal_year,
        )
        for row in rows
    ]


def delete_user_texts(db: Session, ticker: str) -> None:
    db.query(Filing).filter(
        Filing.ticker == ticker.upper(),
        Filing.is_user_submitted == True,
    ).delete()
    db.commit()
