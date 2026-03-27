from datetime import datetime

from sqlalchemy import String, Float, Integer, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(200))
    market_cap: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)
    shares_outstanding: Mapped[float | None] = mapped_column(Float)
    peers: Mapped[str | None] = mapped_column(String(500))  # comma-separated tickers e.g. "AMD,AVGO,QCOM"
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    period: Mapped[str] = mapped_column(String(10))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[str] = mapped_column(String(10))

    revenue: Mapped[float | None] = mapped_column(Float)
    cost_of_revenue: Mapped[float | None] = mapped_column(Float)
    gross_profit: Mapped[float | None] = mapped_column(Float)
    operating_income: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    ebitda: Mapped[float | None] = mapped_column(Float)

    cash_from_operations: Mapped[float | None] = mapped_column(Float)
    capital_expenditures: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)

    total_cash: Mapped[float | None] = mapped_column(Float)
    total_debt: Mapped[float | None] = mapped_column(Float)
    total_assets: Mapped[float | None] = mapped_column(Float)
    total_equity: Mapped[float | None] = mapped_column(Float)

    diluted_shares: Mapped[float | None] = mapped_column(Float)

    source: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class AnalystEstimate(Base):
    __tablename__ = "analyst_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    period: Mapped[str] = mapped_column(String(10))

    revenue_estimate: Mapped[float | None] = mapped_column(Float)
    eps_estimate: Mapped[float | None] = mapped_column(Float)
    revenue_growth_estimate: Mapped[float | None] = mapped_column(Float)

    buy_count: Mapped[int | None] = mapped_column(Integer)
    hold_count: Mapped[int | None] = mapped_column(Integer)
    sell_count: Mapped[int | None] = mapped_column(Integer)
    target_price: Mapped[float | None] = mapped_column(Float)

    source: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class EarningsSurprise(Base):
    __tablename__ = "earnings_surprises"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    date: Mapped[str] = mapped_column(String(10))
    actual_eps: Mapped[float | None] = mapped_column(Float)
    estimated_eps: Mapped[float | None] = mapped_column(Float)
    surprise: Mapped[float | None] = mapped_column(Float)
    surprise_percent: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class TextMaterialDB(Base):
    __tablename__ = "text_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    source_type: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    filing_date: Mapped[str | None] = mapped_column(String(10))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    is_user_submitted: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class ValuationResultDB(Base):
    __tablename__ = "valuation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    current_price: Mapped[float] = mapped_column(Float)
    bear_blended: Mapped[float] = mapped_column(Float)
    base_blended: Mapped[float] = mapped_column(Float)
    bull_blended: Mapped[float] = mapped_column(Float)
    result_json: Mapped[dict] = mapped_column(JSON)  # full ValuationResponse
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class DailyPrice(Base):
    __tablename__ = "daily_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    date: Mapped[str] = mapped_column(String(10))  # "2025-03-17"
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class SignalExtractionDB(Base):
    __tablename__ = "signal_extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    source_type: Mapped[str] = mapped_column(String(50))  # "mda", "risk_factors", "earnings_transcript"
    signals_json: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
