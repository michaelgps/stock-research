from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class Company(Base):
    __tablename__ = "tb_company"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    cik: Mapped[str | None] = mapped_column(String(20), index=True)
    exchange: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))
    country: Mapped[str | None] = mapped_column(String(100))
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CompanyProfile(Base):
    __tablename__ = "tb_company_profile"
    __table_args__ = (
        UniqueConstraint("ticker", "profile_date", "source", name="uq_company_profile_day_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    profile_date: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(200))
    market_cap: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)
    shares_outstanding: Mapped[float | None] = mapped_column(Float)
    peers_json: Mapped[dict | list | None] = mapped_column(JSON)
    raw_data_json: Mapped[dict | list | None] = mapped_column(JSON)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class FinancialReport(Base):
    __tablename__ = "tb_financial_report"
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "source",
            "period_type",
            "fiscal_year",
            "fiscal_quarter",
            name="uq_financial_report_period_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    period_type: Mapped[str] = mapped_column(String(20), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    fiscal_quarter: Mapped[int] = mapped_column(Integer, default=0)
    report_date: Mapped[str] = mapped_column(String(10))
    filing_date: Mapped[str | None] = mapped_column(String(10))
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
    raw_data_json: Mapped[dict | list | None] = mapped_column(JSON)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Estimate(Base):
    __tablename__ = "tb_estimate"
    __table_args__ = (
        UniqueConstraint("ticker", "estimate_date", "source", "estimate_period", name="uq_estimate_day_period_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    estimate_date: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    estimate_period: Mapped[str] = mapped_column(String(20), index=True)
    record_type: Mapped[str] = mapped_column(String(50), default="analyst_estimate", index=True)
    revenue_estimate: Mapped[float | None] = mapped_column(Float)
    eps_estimate: Mapped[float | None] = mapped_column(Float)
    revenue_growth_estimate: Mapped[float | None] = mapped_column(Float)
    actual_eps: Mapped[float | None] = mapped_column(Float)
    estimated_eps: Mapped[float | None] = mapped_column(Float)
    surprise: Mapped[float | None] = mapped_column(Float)
    surprise_percent: Mapped[float | None] = mapped_column(Float)
    buy_count: Mapped[int | None] = mapped_column(Integer)
    hold_count: Mapped[int | None] = mapped_column(Integer)
    sell_count: Mapped[int | None] = mapped_column(Integer)
    target_price: Mapped[float | None] = mapped_column(Float)
    raw_data_json: Mapped[dict | list | None] = mapped_column(JSON)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MarketPrice(Base):
    __tablename__ = "tb_market_price"
    __table_args__ = (
        UniqueConstraint("ticker", "price_date", "source", name="uq_market_price_day_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    price_date: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    open_price: Mapped[float | None] = mapped_column(Float)
    high_price: Mapped[float | None] = mapped_column(Float)
    low_price: Mapped[float | None] = mapped_column(Float)
    close_price: Mapped[float | None] = mapped_column(Float)
    adjusted_close_price: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Filing(Base):
    __tablename__ = "tb_filing"
    __table_args__ = (
        UniqueConstraint("ticker", "source", "accession_number", "section_type", name="uq_filing_section"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    filing_type: Mapped[str] = mapped_column(String(50))
    accession_number: Mapped[str] = mapped_column(String(120), index=True)
    filing_date: Mapped[str | None] = mapped_column(String(10))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer)
    section_type: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    is_user_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_data_json: Mapped[dict | list | None] = mapped_column(JSON)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Valuation(Base):
    __tablename__ = "tb_valuation"
    __table_args__ = (
        UniqueConstraint("ticker", "valuation_date", "model_version", name="uq_valuation_day_model"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    valuation_date: Mapped[str] = mapped_column(String(10), index=True)
    model_version: Mapped[str] = mapped_column(String(50), index=True)
    current_price: Mapped[float | None] = mapped_column(Float)
    bear_blended: Mapped[float | None] = mapped_column(Float)
    base_blended: Mapped[float | None] = mapped_column(Float)
    bull_blended: Mapped[float | None] = mapped_column(Float)
    bear_dcf: Mapped[float | None] = mapped_column(Float)
    base_dcf: Mapped[float | None] = mapped_column(Float)
    bull_dcf: Mapped[float | None] = mapped_column(Float)
    bear_forward_pe: Mapped[float | None] = mapped_column(Float)
    base_forward_pe: Mapped[float | None] = mapped_column(Float)
    bull_forward_pe: Mapped[float | None] = mapped_column(Float)
    base_pe_multiple: Mapped[float | None] = mapped_column(Float)
    forward_eps: Mapped[float | None] = mapped_column(Float)
    implied_upside_pct: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(50))
    assumptions_json: Mapped[dict | list | None] = mapped_column(JSON)
    dcf_json: Mapped[dict | list | None] = mapped_column(JSON)
    multiples_json: Mapped[dict | list | None] = mapped_column(JSON)
    peer_comparison_json: Mapped[dict | list | None] = mapped_column(JSON)
    reverse_dcf_json: Mapped[dict | list | None] = mapped_column(JSON)
    margin_of_safety_json: Mapped[dict | list | None] = mapped_column(JSON)
    terminal_value_warning: Mapped[str | None] = mapped_column(Text)
    signal_adjustments_json: Mapped[dict | list | None] = mapped_column(JSON)
    data_quality_json: Mapped[dict | list | None] = mapped_column(JSON)
    input_refs_json: Mapped[dict | list | None] = mapped_column(JSON)
    result_json: Mapped[dict | list | None] = mapped_column(JSON)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TechnicalLevel(Base):
    __tablename__ = "tb_technical_level"
    __table_args__ = (
        UniqueConstraint("ticker", "level_date", "source", "level_type", "rank", name="uq_technical_level_day_rank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    level_date: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    level_type: Mapped[str] = mapped_column(String(20), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    price_low: Mapped[float | None] = mapped_column(Float)
    price_high: Mapped[float | None] = mapped_column(Float)
    center_price: Mapped[float | None] = mapped_column(Float)
    strength_score: Mapped[float | None] = mapped_column(Float)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    strength_label: Mapped[str | None] = mapped_column(String(20))
    evidence_json: Mapped[dict | list | None] = mapped_column(JSON)
    invalid_if: Mapped[str | None] = mapped_column(Text)
    breakout_confirmation: Mapped[str | None] = mapped_column(Text)
    lookback_days: Mapped[int] = mapped_column(Integer, default=252)
    raw_data_json: Mapped[dict | list | None] = mapped_column(JSON)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DataPullLog(Base):
    __tablename__ = "tb_data_pull_log"
    __table_args__ = (
        UniqueConstraint("ticker", "data_type", "source", "pull_date", name="uq_data_pull_log_day_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    data_type: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    pull_date: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    date_created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    date_modified: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
