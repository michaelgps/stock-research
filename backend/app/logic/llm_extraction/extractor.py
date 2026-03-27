"""
LLM extraction engine.
Sends text materials to Claude API and parses structured JSON signals back.
"""

import json
import logging

import anthropic

from app.config.config import get_settings
from app.data_structure.financial import TextMaterial
from app.data_structure.signals import (
    MDASignals,
    RiskSignals,
    EarningsTranscriptSignals,
    ExtractionResult,
)
from app.logic.llm_extraction.prompts import get_prompt

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 2000


def _call_claude(system_prompt: str, user_message: str) -> str:
    """Call Claude API and return the text response."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text


def _parse_json(raw: str) -> dict:
    """Parse JSON from Claude's response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        # Remove markdown code fences
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


def extract_mda_signals(material: TextMaterial) -> MDASignals | None:
    """Extract signals from an MD&A text material."""
    try:
        system, user = get_prompt("mda", material.ticker, material.content)
        raw = _call_claude(system, user)
        data = _parse_json(raw)
        return MDASignals(**data)
    except Exception as e:
        logger.error(f"MDA extraction failed for {material.ticker}: {e}")
        return None


def extract_risk_signals(material: TextMaterial) -> RiskSignals | None:
    """Extract signals from a Risk Factors text material."""
    try:
        system, user = get_prompt("risk_factors", material.ticker, material.content)
        raw = _call_claude(system, user)
        data = _parse_json(raw)
        return RiskSignals(**data)
    except Exception as e:
        logger.error(f"Risk extraction failed for {material.ticker}: {e}")
        return None


def extract_transcript_signals(material: TextMaterial) -> EarningsTranscriptSignals | None:
    """Extract signals from an earnings transcript."""
    try:
        system, user = get_prompt("earnings_transcript", material.ticker, material.content)
        raw = _call_claude(system, user)
        data = _parse_json(raw)
        return EarningsTranscriptSignals(**data)
    except Exception as e:
        logger.error(f"Transcript extraction failed for {material.ticker}: {e}")
        return None


def extract_signals(ticker: str, text_materials: list[TextMaterial]) -> ExtractionResult:
    """
    Run LLM extraction on all text materials for a ticker.
    Returns an ExtractionResult with signals from each text type.
    """
    result = ExtractionResult(ticker=ticker.upper())

    for material in text_materials:
        if material.source_type == "mda":
            logger.info(f"Extracting MD&A signals for {ticker}")
            result.mda_signals = extract_mda_signals(material)

        elif material.source_type == "risk_factors":
            logger.info(f"Extracting Risk Factor signals for {ticker}")
            result.risk_signals = extract_risk_signals(material)

        elif material.source_type in ("earnings_transcript", "manual"):
            logger.info(f"Extracting transcript signals for {ticker}")
            result.transcript_signals = extract_transcript_signals(material)

    return result
