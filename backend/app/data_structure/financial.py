from pydantic import BaseModel


class CompanyInfo(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    current_price: float | None = None
    shares_outstanding: float | None = None


class FinancialStatementData(BaseModel):
    period: str  # "annual" or "quarterly"
    fiscal_year: int
    fiscal_quarter: int | None = None
    date: str

    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    ebitda: float | None = None

    cash_from_operations: float | None = None
    capital_expenditures: float | None = None
    free_cash_flow: float | None = None

    total_cash: float | None = None
    total_debt: float | None = None
    total_assets: float | None = None
    total_equity: float | None = None

    diluted_shares: float | None = None
    source: str | None = None


class AnalystEstimateData(BaseModel):
    period: str
    revenue_estimate: float | None = None
    eps_estimate: float | None = None
    revenue_growth_estimate: float | None = None
    buy_count: int | None = None
    hold_count: int | None = None
    sell_count: int | None = None
    target_price: float | None = None
    source: str | None = None


class EarningsSurpriseData(BaseModel):
    date: str
    actual_eps: float | None = None
    estimated_eps: float | None = None
    surprise: float | None = None  # actual - estimated
    surprise_percent: float | None = None
    source: str | None = None


class TextMaterial(BaseModel):
    ticker: str
    source_type: str  # "mda", "risk_factors", "earnings_transcript", "manual"
    content: str
    filing_date: str | None = None
    fiscal_year: int | None = None


class FinancialDataResponse(BaseModel):
    company: CompanyInfo
    annual_statements: list[FinancialStatementData]
    quarterly_statements: list[FinancialStatementData]
    analyst_estimates: list[AnalystEstimateData]
    earnings_surprises: list[EarningsSurpriseData]
    text_materials: list[TextMaterial]


class TickerRequest(BaseModel):
    ticker: str


class TextSubmitRequest(BaseModel):
    ticker: str
    source_type: str  # "earnings_transcript" or "manual"
    content: str
