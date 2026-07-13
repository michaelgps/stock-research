"""
Pydantic models for Phase 3 valuation engine output.
"""

from pydantic import BaseModel, Field


class ScenarioAssumptions(BaseModel):
    """Assumptions used in a single bear/base/bull scenario."""
    revenue_growth_rate: float  # e.g. 0.05 = 5%
    fcf_margin: float  # e.g. 0.25 = 25%
    terminal_growth_rate: float  # e.g. 0.03 = 3%
    discount_rate: float  # WACC, e.g. 0.10 = 10%
    projection_years: int  # typically 5


class DCFResult(BaseModel):
    """Output from a single DCF scenario."""
    projected_fcf: list[float]  # FCF for each projection year
    terminal_value: float
    present_value_fcfs: float  # sum of discounted projected FCFs
    present_value_terminal: float  # discounted terminal value
    enterprise_value: float  # PV(FCFs) + PV(terminal)
    equity_value: float  # EV - net debt
    per_share_value: float
    assumptions: ScenarioAssumptions


class MultiplesResult(BaseModel):
    """Output from forward P/E valuation."""
    forward_pe_value: float | None = None  # price from forward P/E
    forward_eps: float | None = None  # the forward EPS used
    pe_multiple: float | None = None  # the P/E multiple applied
    pe_low: float | None = None
    pe_high: float | None = None
    justified_pe: float | None = None  # deprecated: DCF cross-check, not used in P/E valuation
    details: dict = Field(default_factory=dict)


class ScenarioResult(BaseModel):
    """Combined result for a single scenario (bear, base, or bull)."""
    label: str  # "bear", "base", "bull"
    dcf: DCFResult | None = None
    multiples: MultiplesResult
    blended_per_share: float | None = None  # deprecated: DCF and P/E are no longer blended


class ValuationView(BaseModel):
    """One standalone valuation framework view."""
    label: str
    methodology: str
    bear_value: float | None = None
    base_value: float | None = None
    bull_value: float | None = None
    upside_pct: float | None = None
    verdict: str | None = None
    notes: list[str] = Field(default_factory=list)


class ForwardEpsMetadata(BaseModel):
    """Metadata for the EPS denominator used in forward P/E valuation."""
    basis: str
    period: str | None = None
    fiscal_year: int | None = None
    fiscal_year_end: str | None = None
    eps: float | None = None
    source: str | None = None
    as_of_date: str | None = None


class ForwardYearEstimate(BaseModel):
    """One year of forward valuation."""
    year: str
    eps: float
    pe_multiple: float | None = None
    implied_price: float  # eps x base P/E multiple
    source: str | None = None
    eps_validation_status: str = "unverified"
    eps_validation_sources: list[str] = Field(default_factory=list)
    eps_validation_note: str | None = None


class FiscalYearPECase(BaseModel):
    """One automatic P/E range case inside a fiscal-year valuation window."""
    label: str
    method: str
    pe_low: float
    pe_mid: float
    pe_high: float
    value_low: float
    value_mid: float
    value_high: float
    upside_low_pct: float | None = None
    upside_mid_pct: float | None = None
    upside_high_pct: float | None = None
    verdict: str | None = None
    weighted_eps_growth: float | None = None
    growth_curve: str | None = None
    quality_adjustment: float = 0
    deceleration_adjustment: float = 0
    uncertainty_adjustment: float = 0
    uncertainty_reasons: list[str] = Field(default_factory=list)
    cyclicality_score: float | None = None
    cyclicality_label: str | None = None
    cyclicality_reasons: list[str] = Field(default_factory=list)
    peak_earnings_risk: float | None = None
    peak_earnings_reasons: list[str] = Field(default_factory=list)
    structural_re_rating_score: float | None = None
    structural_re_rating_reasons: list[str] = Field(default_factory=list)
    historical_guardrail_pe: float | None = None
    explanation: str


class FiscalYearValuationWindow(BaseModel):
    """DCF and Forward P/E values aligned to one fiscal-year end date."""
    fiscal_year: int
    fiscal_year_end: str | None = None
    valuation_date: str
    years_from_valuation_date: float | None = None
    time_distance_label: str
    forward_eps: float
    pe_multiple: float | None = None
    forward_pe_value: float | None = None
    forward_pe_upside_pct: float | None = None
    forward_pe_verdict: str | None = None
    pe_cases: list[FiscalYearPECase] = Field(default_factory=list)
    dcf_present_value: float | None = None
    dcf_rolled_forward_value: float | None = None
    dcf_rolled_forward_upside_pct: float | None = None
    dcf_rolled_forward_verdict: str | None = None
    discount_rate_used: float | None = None
    discount_rate_source: str = "base_dcf_wacc"


class PeerPEData(BaseModel):
    """Peer company forward P/E data."""
    ticker: str
    price: float
    forward_eps: float
    forward_pe: float
    market_cap: float | None = None
    eps_growth: float | None = None  # forward EPS CAGR (e.g. 0.15 = 15%)


class PeerComparison(BaseModel):
    """Aggregated peer P/E comparison."""
    peers: list[PeerPEData]
    median_pe: float | None = None
    cap_weighted_pe: float | None = None
    median_peg: float | None = None  # median PEG across peers
    growth_adjusted_pe: float | None = None  # median_peg x ticker growth


class ReverseDCF(BaseModel):
    """Reverse DCF: what growth rate the market is pricing in."""
    implied_growth_rate: float  # e.g. 0.12 = 12% annual revenue growth
    terminal_growth_rate: float  # the terminal growth used
    discount_rate: float  # WACC used
    fcf_margin: float  # FCF margin used
    interpretation: str  # human-readable interpretation


class MarginOfSafety(BaseModel):
    """Margin of safety: upside/downside vs current price."""
    current_price: float
    base_intrinsic: float  # base-case value for the selected standalone view
    bear_intrinsic: float
    bull_intrinsic: float
    upside_pct: float  # (base - current) / current, e.g. -0.30 = 30% overvalued
    verdict: str  # "undervalued", "fairly_valued", "overvalued"


class ValuationResponse(BaseModel):
    """Full valuation output returned to the frontend."""
    ticker: str
    current_price: float
    bear: ScenarioResult
    base: ScenarioResult
    bull: ScenarioResult
    dcf_view: ValuationView
    pe_view: ValuationView
    forward_eps_metadata: ForwardEpsMetadata | None = None
    fiscal_year_valuation_windows: list[FiscalYearValuationWindow] = Field(default_factory=list)
    forward_trend: list[ForwardYearEstimate]  # 5-year forward P/E trend
    historical_pe_ranges: list[dict]  # yearly high/low/avg P/E for context
    peer_comparison: PeerComparison | None = None  # peer forward P/E context
    signal_adjustments: dict  # documents how LLM signals shifted assumptions
    data_quality: dict  # notes on missing data, fallback values used
    reverse_dcf: ReverseDCF | None = None  # implied growth from current price
    margin_of_safety: MarginOfSafety | None = None  # upside/downside indicator
    terminal_value_warning: str | None = None  # warning if TV dominates EV
