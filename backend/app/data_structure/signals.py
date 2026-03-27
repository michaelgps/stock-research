"""
Structured signal models extracted by the LLM from text materials.
These are the outputs of Phase 2 and inputs to Phase 3 (valuation engine).
"""

from pydantic import BaseModel


class RiskItem(BaseModel):
    category: str  # "regulatory", "competitive", "macro", "operational", "financial", "legal", "geopolitical"
    severity: str  # "high", "medium", "low"
    detail: str


class MDASignals(BaseModel):
    """Signals extracted from Management Discussion & Analysis."""
    revenue_outlook: str  # "positive", "neutral", "negative"
    revenue_outlook_detail: str
    margin_trend: str  # "expanding", "stable", "contracting"
    margin_detail: str
    growth_drivers: list[str]
    headwinds: list[str]
    capital_allocation: str  # "growth_investment", "shareholder_return", "debt_reduction", "balanced"
    capital_detail: str
    management_tone: str  # "confident", "cautious", "defensive"
    management_tone_detail: str


class RiskSignals(BaseModel):
    """Signals extracted from Risk Factors section."""
    overall_risk_level: str  # "high", "medium", "low"
    risk_items: list[RiskItem]
    new_or_escalated_risks: list[str]
    risk_summary: str


class EarningsTranscriptSignals(BaseModel):
    """Signals extracted from earnings call transcripts."""
    guidance_tone: str  # "positive", "neutral", "negative"
    guidance_detail: str
    analyst_sentiment: str  # "bullish", "mixed", "bearish"
    analyst_concerns: list[str]
    management_confidence: str  # "high", "medium", "low"
    key_quotes: list[str]
    forward_indicators: list[str]


class ExtractionResult(BaseModel):
    """Combined extraction result for a ticker."""
    ticker: str
    mda_signals: MDASignals | None = None
    risk_signals: RiskSignals | None = None
    transcript_signals: EarningsTranscriptSignals | None = None
