"""
Pydantic models for Phase 3 valuation engine output.
"""

from pydantic import BaseModel


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
    justified_pe: float | None = None  # DCF-implied P/E cross-check


class ScenarioResult(BaseModel):
    """Combined result for a single scenario (bear, base, or bull)."""
    label: str  # "bear", "base", "bull"
    dcf: DCFResult
    multiples: MultiplesResult
    blended_per_share: float  # final blended price target


class ForwardYearEstimate(BaseModel):
    """One year of forward valuation."""
    year: str
    eps: float
    implied_price: float  # eps × base P/E multiple


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
    growth_adjusted_pe: float | None = None  # median_peg × ticker growth


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
    base_intrinsic: float  # blended base-case value
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
    forward_trend: list[ForwardYearEstimate]  # 5-year forward P/E trend
    historical_pe_ranges: list[dict]  # yearly high/low/avg P/E for context
    peer_comparison: PeerComparison | None = None  # peer forward P/E context
    signal_adjustments: dict  # documents how LLM signals shifted assumptions
    data_quality: dict  # notes on missing data, fallback values used
    reverse_dcf: ReverseDCF | None = None  # implied growth from current price
    margin_of_safety: MarginOfSafety | None = None  # upside/downside indicator
    terminal_value_warning: str | None = None  # warning if TV dominates EV
