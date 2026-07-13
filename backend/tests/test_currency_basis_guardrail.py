from app.data_structure.financial import (
    AnalystEstimateData,
    CompanyInfo,
    FinancialDataResponse,
    FinancialStatementData,
)
from app.logic.valuation.engine import (
    _get_forward_eps_estimate,
    _is_dcf_currency_compatible,
    _replace_fmp_eps_with_yfinance,
    _requires_yfinance_currency_fallback,
)


def _foreign_currency_adr_data() -> FinancialDataResponse:
    return FinancialDataResponse(
        company=CompanyInfo(ticker="TEST", currency="USD"),
        annual_statements=[
            FinancialStatementData(
                period="annual",
                fiscal_year=2025,
                date="2025-12-31",
                revenue=1_000,
                net_income=400,
                diluted_shares=10,
                currency="TWD",
                source="fmp",
            )
        ],
        quarterly_statements=[],
        analyst_estimates=[
            AnalystEstimateData(period="2025", eps_estimate=320, source="fmp"),
            AnalystEstimateData(period="2026", eps_estimate=500, source="fmp"),
        ],
        earnings_surprises=[],
        text_materials=[],
    )


def test_fmp_eps_conflict_with_adr_consensus_triggers_yahoo_fallback():
    data = _foreign_currency_adr_data()
    selected_fmp = _get_forward_eps_estimate(data)
    yahoo_validation = {
        "fmp_eps": 500,
        "yf_current_fy_eps": 15.9,
        "yf_next_fy_eps": 20.3,
        "divergence": 0.968,
        "warning": True,
    }
    yahoo_estimates = [
        AnalystEstimateData(period="2026", eps_estimate=15.9, source="yfinance"),
        AnalystEstimateData(period="2027", eps_estimate=20.3, source="yfinance"),
    ]

    assert selected_fmp is not None
    assert selected_fmp.period == "2026"
    assert _requires_yfinance_currency_fallback(selected_fmp, yahoo_validation)

    replacement = _replace_fmp_eps_with_yfinance(data.analyst_estimates, yahoo_estimates)
    assert [estimate.source for estimate in replacement] == ["yfinance", "yfinance"]
    assert replacement[0].eps_estimate == 15.9


def test_foreign_currency_financials_disable_dcf_without_fx_conversion():
    available, reason = _is_dcf_currency_compatible(
        _foreign_currency_adr_data(),
        has_eps_currency_mismatch=True,
    )

    assert not available
    assert reason is not None
    assert "TWD" in reason
    assert "USD" in reason
