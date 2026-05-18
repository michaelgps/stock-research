# Valuation Model Technical Reference

This document describes the current end-to-end valuation flow used by the app.

## Phases

| Phase | Purpose |
|---|---|
| Data collection | Pull company, financial, estimate, filing, and price data into PostgreSQL |
| Optional signal extraction | Use LLM extraction on filings/transcripts when text is available |
| Valuation | Run DCF + forward P/E, blend outputs, and save the valuation result |

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

Peer comparison uses manual peers only.

API-returned peers may be stored as reference metadata, but they are not used in the valuation calculation. If a ticker has no manual peers, the peer component is skipped and the forward P/E model reweights the remaining components.

## DCF Model

The DCF model runs bear/base/bull scenarios.

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

The forward P/E model combines available components:

| Component | Default Weight | Notes |
|---|---:|---|
| Historical P/E | 50% | Uses historical prices and annual EPS |
| Manual peer P/E | 30% | Only used when manual peers exist |
| DCF-justified P/E | 20% | DCF base value divided by forward EPS |

If one component is unavailable, weights are normalized across the available components.

```text
Forward P/E value = forward EPS * blended P/E multiple
```

## Blended Output

The final bear/base/bull values blend DCF and forward P/E:

```text
Blended price = 50% * DCF value + 50% * forward P/E value
```

Fallback rules:

| Situation | Behavior |
|---|---|
| P/E unavailable | Use DCF only |
| DCF unavailable | Use P/E only |
| Both unavailable | Return zero value |

## Saved Valuation

Each valuation is saved into `tb_valuation` with:

```text
ticker + valuation_date + model_version
```

This preserves historical valuation results while allowing multiple same-day runs to update the same row.
