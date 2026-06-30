from pydantic import BaseModel, Field


class TechnicalZone(BaseModel):
    """One support/resistance/active liquidity zone."""

    level_type: str
    price_low: float
    price_high: float
    center_price: float
    strength_score: float
    relevance_score: float
    strength_label: str
    evidence: list[str] = Field(default_factory=list)
    invalid_if: str | None = None
    breakout_confirmation: str | None = None
    distance_to_current_pct: float | None = None
    raw_details: dict = Field(default_factory=dict)


class TechnicalReferenceLevel(BaseModel):
    """One reference level that supports context but is not a volume-confirmed zone."""

    reference_type: str
    level_type: str
    price: float | None = None
    price_low: float | None = None
    price_high: float | None = None
    label: str
    strength_label: str = "reference"
    evidence: list[str] = Field(default_factory=list)
    distance_to_current_pct: float | None = None
    raw_details: dict = Field(default_factory=dict)


class TechnicalLevelsResponse(BaseModel):
    """Daily OHLCV liquidity-zone technical levels."""

    ticker: str
    current_price: float
    analysis_date: str
    lookback_days: int
    atr20: float
    atr20_pct: float
    support_zones: list[TechnicalZone] = Field(default_factory=list)
    resistance_zones: list[TechnicalZone] = Field(default_factory=list)
    active_zones: list[TechnicalZone] = Field(default_factory=list)
    long_term_zones: list[TechnicalZone] = Field(default_factory=list)
    reference_levels: list[TechnicalReferenceLevel] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
