"""
Discounted Cash Flow model.
All math is deterministic — no LLM calls.
"""

from app.data_structure.financial import FinancialStatementData
from app.data_structure.valuation import ScenarioAssumptions, DCFResult


def run_dcf(
    assumptions: ScenarioAssumptions,
    latest_revenue: float,
    net_debt: float,
    shares_outstanding: float,
    analyst_revenues: list[float] | None = None,
) -> DCFResult:
    """
    Run a DCF model given assumptions, latest revenue, net debt, and share count.

    If analyst_revenues is provided (year-by-year consensus revenue estimates),
    use those directly instead of compounding revenue_growth_rate. This gives
    more accurate projections when analyst consensus is available.

    Steps:
    1. Project revenue forward (analyst consensus or flat growth rate)
    2. Apply fcf_margin to get projected FCF each year
    3. Discount projected FCFs back to present
    4. Compute terminal value via perpetuity growth model
    5. Discount terminal value
    6. EV = PV(FCFs) + PV(terminal) → equity_value = EV - net_debt
    """
    r = assumptions.revenue_growth_rate
    margin = assumptions.fcf_margin
    wacc = assumptions.discount_rate
    g = assumptions.terminal_growth_rate
    years = assumptions.projection_years

    # 1. Project revenue and FCF
    # Prefer analyst year-by-year revenue when available; fall back to flat growth
    projected_fcf = []
    if analyst_revenues and len(analyst_revenues) >= years:
        for i in range(years):
            fcf = analyst_revenues[i] * margin
            projected_fcf.append(fcf)
    else:
        revenue = latest_revenue
        for year in range(1, years + 1):
            revenue = revenue * (1 + r)
            fcf = revenue * margin
            projected_fcf.append(fcf)

    # 2. Discount projected FCFs
    pv_fcfs = 0.0
    for i, fcf in enumerate(projected_fcf):
        pv_fcfs += fcf / (1 + wacc) ** (i + 1)

    # 3. Terminal value (Gordon Growth Model on last year's FCF)
    terminal_fcf = projected_fcf[-1]
    if wacc <= g:
        # Safety: if growth >= discount rate, cap terminal value
        terminal_value = terminal_fcf * 20  # rough cap
    else:
        terminal_value = terminal_fcf * (1 + g) / (wacc - g)

    # 4. Discount terminal value
    pv_terminal = terminal_value / (1 + wacc) ** years

    # 5. Enterprise value → equity value → per share
    enterprise_value = pv_fcfs + pv_terminal
    equity_value = enterprise_value - net_debt
    per_share = max(equity_value / shares_outstanding, 0) if shares_outstanding > 0 else 0

    return DCFResult(
        projected_fcf=[round(f, 0) for f in projected_fcf],
        terminal_value=round(terminal_value, 0),
        present_value_fcfs=round(pv_fcfs, 0),
        present_value_terminal=round(pv_terminal, 0),
        enterprise_value=round(enterprise_value, 0),
        equity_value=round(equity_value, 0),
        per_share_value=round(per_share, 2),
        assumptions=assumptions,
    )
