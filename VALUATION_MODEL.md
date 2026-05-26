# Valuation Model Technical Reference

This document describes the current end-to-end valuation flow used by the app.

## Phases

| Phase | Purpose |
|---|---|
| Data collection | Pull company, financial, estimate, filing, and price data into PostgreSQL |
| Optional signal extraction | Use LLM extraction on filings/transcripts when text is available |
| Valuation | Build fiscal-year valuation windows, then save the valuation result |

## Data Persistence

The database keeps historical records instead of overwriting prior periods.

| Table | Stored Data |
|---|---|
| `tb_company` | Stable company identity |
| `tb_company_profile` | Daily profile records and manual/reference peers |
| `tb_financial_report` | Financial reports by fiscal period and source |
| `tb_estimate` | Analyst estimates, earnings surprises, EPS validation |
| `tb_market_price` | Daily OHLCV prices |
| `tb_filing` | SEC filing sections, user text, and cached signal material |
| `tb_valuation` | Valuation results by ticker/date/model version |
| `tb_data_pull_log` | Pull status by ticker/source/data type/day |

Repeated pulls on the same day update the same daily/source row. Different reporting periods and different valuation dates are preserved.

`tb_data_pull_log.status` values:

| Status | Meaning |
|---|---|
| `success` | Valid parsed records were inserted or updated |
| `empty` | Provider returned no usable records |
| `failed` | Provider call or parser failed |

## Data Sources

| Data | Source |
|---|---|
| Company identity | SEC EDGAR |
| Company profile | FMP, Finnhub |
| Financial reports | SEC EDGAR primary, FMP fallback |
| Analyst estimates | FMP, Finnhub |
| Earnings surprises | FMP, Finnhub |
| Daily prices | Yahoo Finance via `yfinance` |
| Filing text | SEC EDGAR |
| Risk-free rate | FRED optional, default fallback |

Yahoo Finance is used for daily OHLCV to reduce quota pressure on paid APIs.

## Peer Valuation Rule

Peer data is reference-only in the current model.

API-returned peers may be stored as reference metadata, and manual peers may be inspected separately, but peer P/E does not set the final P/E multiple.

## DCF Model

The DCF model is primarily used as a base present-value reference.

Main inputs:

| Input | Source/Method |
|---|---|
| Revenue growth | Analyst next-FY revenue estimate, historical CAGR fallback, default fallback |
| FCF margin | Historical average FCF margin, default fallback |
| WACC | CAPM with levered beta and market-cap capital structure |
| Risk-free rate | FRED DGS10 if configured, otherwise default |
| Terminal growth | Scenario assumption with safety clamp below discount rate |

Core formula:

```text
Enterprise Value = PV(projected FCFs) + PV(terminal value)
Equity Value = Enterprise Value - net debt
DCF per share = Equity Value / diluted shares
```

## Forward P/E Model

The forward P/E model uses the ticker's own last ~5 fiscal years of daily trailing P/E observations.

The observations are sorted and mapped to scenario percentiles:

| Scenario | Multiple |
|---|---|
| Bear | P25 |
| Base | P50 / median |
| Bull | P75 |

The raw daily P/E values are kept internal to the valuation calculation. API consumers receive yearly summary ranges and percentiles, not the full daily observation list.

```text
Forward P/E value = next fiscal year EPS * selected P/E multiple
```

The EPS denominator is explicitly labeled as next fiscal year EPS, not NTM EPS. The API returns the fiscal year label, inferred fiscal year end date when available, source, and as-of date.

DCF-implied P/E and peer P/E may be displayed as cross-checks, but they are not inputs into the P/E multiple.

## Separate Output

The final output does not average DCF and forward P/E. The primary output is a list of fiscal-year valuation windows:

| Field | Description |
|---|---|
| `fiscal_year_valuation_windows` | One row per fiscal year, including FY end date, distance from valuation date, forward P/E target, DCF rolled-forward value, and P25/P50/P75 P/E scenarios |
| `pe_scenarios` | Bear/base/bull scenario cards inside each fiscal-year window |
| `dcf_view` | Legacy/base DCF present-value reference |
| `pe_view` | Legacy next-fiscal-year P/E view |

DCF roll-forward formula:

```text
DCF Rolled-Forward Value = DCF Present Value Today * (1 + WACC) ^ years_to_fiscal_year_end
```

## Saved Valuation

Each valuation is saved into `tb_valuation` with:

```text
ticker + valuation_date + model_version
```

This preserves historical valuation results while allowing multiple same-day runs to update the same row.
