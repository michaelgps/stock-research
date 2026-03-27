"""
PostgreSQL cache for LLM signal extraction results.
Stores extraction results so we don't re-call Claude for the same text materials.
Uses the same 24h TTL as the financial data cache.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.financial import SignalExtractionDB
from app.data_structure.signals import (
    MDASignals,
    RiskSignals,
    EarningsTranscriptSignals,
    ExtractionResult,
)

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


def _is_stale(updated_at: datetime) -> bool:
    return datetime.utcnow() - updated_at > timedelta(hours=CACHE_TTL_HOURS)


def load_cached_signals(db: Session, ticker: str) -> ExtractionResult | None:
    """Load cached extraction results. Returns None if any are missing or stale."""
    ticker = ticker.upper()
    rows = db.query(SignalExtractionDB).filter(
        SignalExtractionDB.ticker == ticker
    ).all()

    if not rows:
        return None

    # Check staleness on any row
    for row in rows:
        if _is_stale(row.updated_at):
            return None

    result = ExtractionResult(ticker=ticker)
    for row in rows:
        if row.source_type == "mda":
            result.mda_signals = MDASignals(**row.signals_json)
        elif row.source_type == "risk_factors":
            result.risk_signals = RiskSignals(**row.signals_json)
        elif row.source_type in ("earnings_transcript", "manual"):
            result.transcript_signals = EarningsTranscriptSignals(**row.signals_json)

    logger.info(f"Signal cache hit for {ticker}")
    return result


def save_signals_to_cache(db: Session, result: ExtractionResult) -> None:
    """Save extraction results to the database."""
    ticker = result.ticker.upper()
    now = datetime.utcnow()

    # Clear old extractions for this ticker
    db.query(SignalExtractionDB).filter(
        SignalExtractionDB.ticker == ticker
    ).delete()

    if result.mda_signals:
        db.add(SignalExtractionDB(
            ticker=ticker,
            source_type="mda",
            signals_json=result.mda_signals.model_dump(),
            updated_at=now,
        ))

    if result.risk_signals:
        db.add(SignalExtractionDB(
            ticker=ticker,
            source_type="risk_factors",
            signals_json=result.risk_signals.model_dump(),
            updated_at=now,
        ))

    if result.transcript_signals:
        db.add(SignalExtractionDB(
            ticker=ticker,
            source_type="earnings_transcript",
            signals_json=result.transcript_signals.model_dump(),
            updated_at=now,
        ))

    db.commit()
    logger.info(f"Saved signal extractions for {ticker}")
