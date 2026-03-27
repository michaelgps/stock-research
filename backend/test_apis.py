"""Quick test script for all data source integrations."""
import asyncio
from app.logic.data_sources.fmp import (
    get_company_info as fmp_company,
    get_financial_statements as fmp_stmts,
    get_analyst_estimates as fmp_est,
    get_earnings_surprises as fmp_surp,
)
from app.logic.data_sources.finnhub_client import (
    get_company_info as fh_company,
    get_analyst_estimates as fh_est,
)
from app.logic.data_sources.sec_edgar import get_10k_text_materials


async def main():
    ticker = "AAPL"

    # FMP
    print("=== FMP: Company ===")
    info = await fmp_company(ticker)
    if info:
        print(f"  {info.name} | {info.sector} | {info.industry}")
        print(f"  Price: {info.current_price} | Mkt Cap: {info.market_cap}")
    else:
        print("  No data")

    print("\n=== FMP: Financials ===")
    stmts = await fmp_stmts(ticker)
    print(f"  {len(stmts)} years")
    for s in stmts[:3]:
        print(f"  {s.date}: rev={s.revenue} ni={s.net_income} fcf={s.free_cash_flow}")

    print("\n=== FMP: Estimates ===")
    est = await fmp_est(ticker)
    print(f"  {len(est)} periods")
    for e in est[:3]:
        print(f"  {e.period}: rev={e.revenue_estimate} eps={e.eps_estimate}")

    print("\n=== FMP: Surprises ===")
    surp = await fmp_surp(ticker)
    print(f"  {len(surp)} quarters")
    for s in surp[:4]:
        pct = f"{s.surprise_percent:+.1f}%" if s.surprise_percent is not None else "N/A"
        print(f"  {s.date}: actual={s.actual_eps} est={s.estimated_eps} surprise={pct}")

    # Finnhub
    print("\n=== Finnhub: Company ===")
    fh_info = await fh_company(ticker)
    if fh_info:
        print(f"  {fh_info.name} | {fh_info.sector} | Mkt Cap: {fh_info.market_cap}")
    else:
        print("  No data")

    print("\n=== Finnhub: Estimates ===")
    fh_estimates = await fh_est(ticker)
    print(f"  {len(fh_estimates)} periods")
    for e in fh_estimates:
        print(f"  {e.period}: buy={e.buy_count} hold={e.hold_count} sell={e.sell_count} target={e.target_price}")

    # SEC EDGAR 10-K text
    print("\n=== SEC EDGAR: 10-K Text ===")
    materials = await get_10k_text_materials(ticker)
    for m in materials:
        print(f"  {m.source_type}: {len(m.content)} chars, filed {m.filing_date}")


asyncio.run(main())
