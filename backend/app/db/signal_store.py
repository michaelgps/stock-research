"""
LLM signal persistence using tb_filing.

The simplified table set does not include a separate signal table, so extracted
signals are stored as structured text records with source="llm" and
filing_type="signal_extraction". This keeps signal history without adding
another business table.
"""

import json

from sqlalchemy.orm import Session

from app.data_structure.financial import TextMaterial
from app.data_structure.signals import (
    EarningsTranscriptSignals,
    ExtractionResult,
    MDASignals,
    RiskSignals,
)
from app.repositories import data_pull_log_repository, filing_repository


def load_cached_signals(db: Session, ticker: str) -> ExtractionResult | None:
    ticker = ticker.upper()
    if not data_pull_log_repository.has_success(db, ticker, "signal_extraction", "anthropic"):
        return None

    result = ExtractionResult(ticker=ticker)
    for material in filing_repository.get_text_materials(db, ticker):
        if material.source_type == "signal_mda":
            result.mda_signals = MDASignals(**json.loads(material.content))
        elif material.source_type == "signal_risk_factors":
            result.risk_signals = RiskSignals(**json.loads(material.content))
        elif material.source_type == "signal_earnings_transcript":
            result.transcript_signals = EarningsTranscriptSignals(**json.loads(material.content))

    if result.mda_signals or result.risk_signals or result.transcript_signals:
        return result
    return None


def save_signals_to_cache(db: Session, result: ExtractionResult) -> None:
    ticker = result.ticker.upper()
    materials: list[TextMaterial] = []
    if result.mda_signals:
        materials.append(TextMaterial(
            ticker=ticker,
            source_type="signal_mda",
            content=json.dumps(result.mda_signals.model_dump()),
        ))
    if result.risk_signals:
        materials.append(TextMaterial(
            ticker=ticker,
            source_type="signal_risk_factors",
            content=json.dumps(result.risk_signals.model_dump()),
        ))
    if result.transcript_signals:
        materials.append(TextMaterial(
            ticker=ticker,
            source_type="signal_earnings_transcript",
            content=json.dumps(result.transcript_signals.model_dump()),
        ))

    inserted, updated = filing_repository.upsert_many(db, ticker, materials, source="llm")
    data_pull_log_repository.mark(
        db,
        ticker,
        "signal_extraction",
        "anthropic",
        "success",
        records_inserted=inserted,
        records_updated=updated,
    )
