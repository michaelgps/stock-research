# Stock Research - Valuation App

A full-stack stock valuation tool for US equities. It collects company financials, estimates, filings, daily market prices, and optional LLM signals, then shows fiscal-year valuation windows that align forward P/E targets with rolled-forward DCF reference values.

## What It Does

Enter a ticker symbol and the app:

1. Fetches company, financial, estimate, filing, and market price data from SEC EDGAR, FMP, Finnhub, Yahoo Finance, and optional FRED.
2. Stores all historical data in PostgreSQL `tb_` tables instead of overwriting old periods.
3. Runs a base DCF model using annual financial reports, analyst revenue estimates, FCF margins, and CAPM-style WACC.
4. Runs a forward P/E model using fiscal-year EPS estimates, the ticker's historical P/E-to-growth relationship, and historical P/E guardrails. Historical P/E prefers FMP earnings-calendar EPS actuals as a market/adjusted EPS proxy, with split-adjusted GAAP EPS as fallback.
5. Shows each fiscal-year valuation window as P/E case cards, with rolled-forward DCF kept as a reference note.
6. Saves each valuation result by ticker, valuation date, and model version.

## Architecture

```text
backend/                         # FastAPI (Python 3.12)
  app/
    api/routes.py                # REST endpoints
    config/                      # Settings and database config
    data_structure/              # Pydantic models
    db/financial.py              # SQLAlchemy table models
    repositories/                # One repository per table
    services/                    # Data persistence orchestration
    logic/
      data_aggregator.py         # Data collection facade
      data_sources/              # FMP, Finnhub, Yahoo Finance, SEC EDGAR clients
      valuation/                 # DCF, assumptions, multiples, valuation engine
      llm_extraction/            # Optional LLM signal extraction

frontend/                        # React + TypeScript + Vite
  src/
    components/                  # UI components
    services/api.ts              # API client
    types/                       # TypeScript types
```

## Database Design

The current schema is built around historical persistence. Data is not overwritten across reporting periods or valuation dates; repeated pulls on the same ticker/source/day update the same daily row.

| Table | Purpose |
|---|---|
| `tb_company` | Stable company identity such as ticker, name, CIK, exchange, currency, and country |
| `tb_company_profile` | Daily company profile records from FMP/Finnhub/manual sources, including sector, industry, market cap, price, shares, and peer metadata |
| `tb_financial_report` | Annual/quarterly financial statements by ticker, source, period type, fiscal year, and quarter |
| `tb_estimate` | Analyst estimates, quarterly earnings actual EPS, earnings surprises, and EPS validation records for company tickers |
| `tb_market_price` | Daily OHLCV market prices, primarily from Yahoo Finance via `yfinance` |
| `tb_filing` | SEC filing text sections and user-submitted text materials |
| `tb_valuation` | Saved valuation results by ticker, valuation date, and model version |
| `tb_data_pull_log` | Per-day source pull status, inserted/updated counts, and errors |

`tb_data_pull_log.status` uses:

| Status | Meaning |
|---|---|
| `success` | Valid parsed records were inserted or updated |
| `empty` | The provider returned no usable records, so future pulls are not blocked |
| `failed` | The provider call or parser failed |

## Data Sources

| Data | Source | Notes |
|---|---|---|
| Company identity | SEC EDGAR | Primary identity and CIK lookup |
| Company profile | FMP, Finnhub | FMP is preferred for market cap/current price when available |
| Financial reports | SEC EDGAR, FMP fallback | SEC annual statements are preferred |
| Analyst estimates | FMP, Finnhub | Used for forward revenue/EPS assumptions |
| Earnings surprises | FMP, Finnhub | Empty provider responses are logged as `empty`, not `success` |
| Daily OHLCV | Yahoo Finance via `yfinance` | Used to reduce quota pressure on paid APIs |
| SEC text | SEC EDGAR | MD&A and risk factors from 10-K |
| Risk-free rate | FRED optional | Falls back to the model default if unavailable; macro rates are not stored in `tb_estimate` |

## Peer Policy

Peer data is reference-only in the current valuation model. API-returned peers may be stored as reference metadata, and manually configured peers may be inspected separately, but peer P/E does not set the final P/E multiple.

The forward P/E model uses the ticker's own historical P/E-to-growth relationship instead of peer weighting.

Set manual peers with:

```bash
curl -X PUT http://localhost:8000/api/peers/AAPL \
  -H "Content-Type: application/json" \
  -d "{\"peers\":[\"MSFT\",\"GOOGL\"]}"
```

Clear manual peers with:

```bash
curl -X PUT http://localhost:8000/api/peers/AAPL \
  -H "Content-Type: application/json" \
  -d "{\"peers\":[]}"
```

## Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL 16 or Docker
- API keys for FMP and optional providers

## Setup

### 1. Database

Start PostgreSQL via Docker:

```bash
docker-compose up -d
```

Default connection:

```text
postgresql://postgres:123123@localhost:5432/stockapp
```

### 2. Environment Variables

Copy the example file:

```bash
cp .env.example .env
```

Then fill in your keys:

```env
DATABASE_URL=postgresql://postgres:123123@localhost:5432/stockapp
FMP_API_KEY=your_fmp_api_key_here
FINNHUB_API_KEY=your_finnhub_api_key_here
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
FRED_API_KEY=your_fred_api_key_here
APP_ENV=development
LOG_LEVEL=INFO
```

### 3. Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Database tables are created automatically on first startup.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/financial-data` | Fetch financial data by JSON body |
| `GET` | `/api/financial-data/{ticker}` | Fetch financial data by ticker |
| `POST` | `/api/text-materials` | Submit transcript or manual notes |
| `GET` | `/api/text-materials/{ticker}` | Read submitted text materials |
| `DELETE` | `/api/text-materials/{ticker}` | Clear submitted text materials |
| `PUT` | `/api/peers/{ticker}` | Set or clear manual peers |
| `POST` | `/api/extract-signals/{ticker}` | Run optional LLM signal extraction |
| `GET` | `/api/extract-signals/{ticker}` | Read cached LLM signals |
| `POST` | `/api/valuation/{ticker}` | Run valuation and save result |
| `GET` | `/api/valuation/{ticker}` | Convenience valuation endpoint |

Example:

```bash
curl -X POST http://localhost:8000/api/valuation/AAPL
```

## Valuation Methodology

### DCF Model

The DCF model projects revenue and free cash flow, discounts them by WACC, adds terminal value, subtracts net debt, and divides by diluted shares.

Core formula:

```text
FCF_t = Revenue_t * FCF margin
PV(FCF_t) = FCF_t / (1 + WACC)^t
Terminal Value = FCF_final * (1 + terminal_growth) / (WACC - terminal_growth)
Enterprise Value = sum(PV(FCFs)) + PV(Terminal Value)
Equity Value = Enterprise Value - Net Debt
DCF Per Share = Equity Value / Diluted Shares
```

Primary assumptions:

| Input | Method |
|---|---|
| Revenue growth | Analyst next-FY revenue estimate when available, otherwise historical CAGR, otherwise default |
| FCF margin | Historical average FCF margin, otherwise default |
| WACC | CAPM with levered beta, market-cap capital structure, optional FRED 10Y Treasury risk-free rate |
| Terminal growth | Scenario-based Gordon Growth assumption with safety clamp |

Revenue projection:

| Case | Behavior |
|---|---|
| At least 5 annual analyst revenue estimates are available | Uses those year-by-year revenue estimates directly |
| Fewer than 5 analyst revenue estimates are available | Falls back to compounding latest actual revenue by the scenario growth rate |

DCF is primarily used as a base present-value reference. For each fiscal-year valuation window, the base DCF value is rolled forward to the fiscal year end using the base DCF WACC:

```text
DCF Rolled-Forward Value = DCF Present Value Today * (1 + WACC) ^ years_to_fiscal_year_end
```

The rolled-forward DCF value is shown as a reference note for the same fiscal year end. It is not blended with P/E and does not drive the forward P/E case cards.

### Forward P/E Model

The P/E model uses the ticker's own last ~5 fiscal years of daily trailing P/E observations, but it no longer applies historical P/E percentiles directly to forward EPS.

For historical trailing P/E, the model prefers FMP earnings-calendar EPS actuals as a market/adjusted EPS proxy:

```text
Daily Historical P/E = Daily Price / Latest Reported 4-Quarter Market EPS
```

If FMP market EPS is unavailable, the model falls back to split-adjusted GAAP annual EPS from financial statements. The response exposes the EPS basis for each historical P/E year.

Market TTM EPS keeps negative reported quarters in the four-quarter sum, then only uses the resulting TTM value when the total is positive. If a fiscal year has market EPS coverage, the model excludes earlier non-covered trading days instead of mixing market and GAAP denominators in the same yearly P/E distribution.

FMP `epsActual` is not treated as audited GAAP. It is used as a market EPS proxy because it generally follows the earnings-calendar / consensus-surprise denominator investors use for P/E. Finnhub earnings actuals are not used for historical P/E because the current stored date is the fiscal period end date, not the earnings announcement date, which would introduce look-ahead bias.

The model now builds an automatic P/E range rather than a single P/E multiple. It only uses the first three forward fiscal-year EPS estimates for primary P/E valuation. More distant years are treated as too fragile for the core valuation multiple because provider estimates can become sparse or inconsistent.

The `forward_trend` field may still show additional provider years when available. That trend is display/context only; the automatic P/E cases use the first three forward fiscal years.

For each valuation fiscal year, the model uses the target year's own growth when a prior-year EPS estimate is available, then blends in the following year's growth:

```text
Weighted EPS Growth = 70% * (Prior FY EPS -> Target FY EPS growth)
                    + 30% * (Target FY EPS -> Next FY EPS growth)
```

If the target fiscal year is the first available forward estimate, there is no prior estimate in the forward-estimate set, so the model falls back to the next two forward EPS growth segments.

If the first forward fiscal year has already reported one or more quarters, the model uses a partial-year adjustment instead of ignoring those quarters:

```text
Remaining-Year Growth =
  (Target FY EPS Estimate - Target FY Reported EPS So Far)
  / (Prior FY Full EPS - Prior FY Same-Period EPS)
  - 1
```

That remaining-year growth receives the 70% weight, and the next full-year EPS growth receives the 30% weight. This prevents the model from double-counting already-reported quarters or ignoring the fact that part of the forward fiscal year is already known.

Forward EPS is cross-checked against other sources when available:

| Source | Coverage Used | Role |
|---|---|---|
| FMP | First 3 annual forward EPS estimates | Primary valuation input |
| Yahoo Finance | Current FY and next FY EPS | Free cross-check for near-term consensus |
| Alpha Vantage | Up to first 3 annual EPS estimates, if `ALPHA_VANTAGE_API_KEY` is configured | Optional second-source sanity check |

If FMP's fourth or fifth forward year shows an unusual pattern, such as EPS falling while revenue keeps rising, that year does not affect the P/E multiple because it is outside the primary three-year window.

Automatic P/E range construction starts from a smooth growth curve. The table below shows the anchor points; the code interpolates between them so a small change in EPS growth does not jump the valuation from one bucket to another.

| Weighted EPS growth | Initial P/E range |
|---:|---:|
| < 5% | 10-15x |
| 5-10% | 15-22x |
| 10-15% | 18-28x |
| 15-25% | 22-35x |
| 25-40% | 28-45x |
| > 40% | 30-50x |

The initial range is then adjusted automatically:

| Adjustment | Direction |
|---|---|
| Mega-cap quality / durable platform | raises the range |
| High beta, cyclicality, or sector uncertainty | lowers the range |
| Auto / vehicle industry | lowers the range by 4x because the model treats it as cyclically uncertain |
| Semiconductor industry | lowers quality by 1x and uncertainty by 3x to reflect cycle risk |
| Media / streaming / internet advertising uncertainty | lowers the range by 1-2x depending on industry classification |
| Large FY1-to-FY2 growth deceleration | lowers the range |
| Sparse forward growth segments | lowers the range by 2x |
| Any negative forward EPS growth segment | lowers the range by 5x |
| Very high weighted EPS growth above 45% | lowers the range by 2x for visibility risk |
| Historical P/E distribution | acts as a soft guardrail, not a hard cap |

The API echoes uncertainty trigger reasons in each `pe_cases[].uncertainty_reasons` list so the UI can explain why a range was reduced.

If a company has very high weighted growth but also clear growth deceleration, the model can output two automatic cases:

| Case | Meaning |
|---|---|
| `high_growth` | Growth remains strong enough to support a premium P/E range, currently around 30-42x before historical soft guardrails |
| `deceleration` | Growth is discounted because the forward growth path steps down materially, currently around 22-32x before historical soft guardrails |

For high-growth semiconductor names without a large near-term growth step-down, the model can instead output:

| Case | Meaning |
|---|---|
| `base_visibility` | Strong growth is valued at a premium, but without assuming the most optimistic cycle multiple |
| `high_visibility` | Stronger confidence in AI/compute cycle visibility supports the upper premium range |

The main UI shows one card per P/E case. Each card contains the case's median price, EPS x P/E formula, value range, weighted EPS growth, P/E range, and quality/deceleration/uncertainty adjustments. When both `high_growth` and `deceleration` are present, both cards are shown side by side instead of being collapsed into one selected target.

Daily P/E observations are internal calculation inputs only. The API returns yearly summary fields such as `pe_low`, `pe_high`, `pe_avg`, `pe_p25`, `pe_p50`, and `pe_p75`, but not the full daily observation list.

Because Yahoo prices are split-adjusted, fallback GAAP EPS is also adjusted to the current split-adjusted share basis before calculating historical P/E. This prevents stock splits, such as NVDA's 2024 10-for-1 split, from artificially compressing historical P/E multiples.

Split adjustment is inferred conservatively from large diluted-share jumps using common split ratios. This handles major stock splits without calling another paid endpoint, but a dedicated corporate-actions feed would still be preferable for production-grade coverage.

Forward EPS uses the next fiscal year annual EPS estimate from FMP analyst estimates. It is not NTM EPS. The response exposes the EPS basis, fiscal year label, inferred fiscal year end date when available, source, and as-of date.

Forward P/E range formula:

```text
Low Target = Fiscal Year EPS * Auto P/E Low
Mid Target = Fiscal Year EPS * Auto P/E Mid
High Target = Fiscal Year EPS * Auto P/E High
```

In the UI, every P/E case card shows an explicit formula, for example:

```text
EPS $8.93 * 30.0-42.0x P/E = $267.84 - $374.98
```

DCF-implied P/E and peer P/E are only references/cross-checks. They are not used to set the P/E multiple.

### Output Structure

DCF and forward P/E are not averaged into a blended target. The primary valuation response is `fiscal_year_valuation_windows`, which aligns both methods to explicit fiscal year end dates.

| Field | Meaning |
|---|---|
| `fiscal_year_valuation_windows` | Per-fiscal-year windows containing time distance, EPS, automatic P/E case cards, and DCF reference values |
| `pe_cases` | Automatic P/E range cases inside each fiscal-year window, including P/E low/mid/high, value low/mid/high, weighted EPS growth, growth curve, adjustment details, and uncertainty trigger reasons |
| `dcf_view` | Legacy/base DCF present-value reference |
| `pe_view` | Legacy next-fiscal-year P/E view |
| `forward_eps_metadata` | Explicit forward EPS basis, fiscal year period, fiscal year end, source, and as-of date |
| `historical_pe_ranges` | Yearly historical P/E summaries, including `eps`, `eps_basis`, `pe_p25`, `pe_p50`, and `pe_p75` |

Legacy top-level scenario fields still include `bear`, `base`, and `bull` with detailed `dcf` and `multiples` objects, but `blended_per_share` is deprecated and no longer used as the main valuation target.

### Saved Results

Each valuation is saved into `tb_valuation` using:

```text
ticker + valuation_date + model_version
```

Current model version:

```text
dcf_pe_separate_v2
```

Multiple runs on the same day/model update the same row; valuations on different dates are preserved.

## Testing Useful Commands

Backend compile check:

```bash
cd backend
venv\Scripts\python.exe -m compileall app
```

Health check through FastAPI TestClient:

```bash
cd backend
venv\Scripts\python.exe -c "from fastapi.testclient import TestClient; from app.main import app; r=TestClient(app).get('/health'); print(r.status_code, r.json())"
```

Inspect PostgreSQL tables:

```bash
docker exec stock-research-db-1 psql -U postgres -d stockapp -c "\dt"
```

## Known Limitations

- The project currently uses SQLAlchemy `create_all`; production migrations should be added with Alembic before schema changes are shared broadly.
- FMP and Finnhub may return empty data or provider-specific errors depending on the subscription tier.
- Peer data is reference-only. The current P/E range is based on forward EPS growth, company quality, deceleration, uncertainty, and historical P/E guardrails, not peers.
- The automatic P/E policy is deterministic and rule-based; it should be reviewed against expert judgment before being used for high-conviction decisions.
- FRED is optional. If unavailable, the model uses the default risk-free rate.
- DCF currently uses analyst revenue estimates only when at least 5 annual estimates are available; otherwise it falls back to a flat scenario growth path.
- The DCF terminal value formula is standard when `WACC > terminal_growth`; if that safety condition is violated, the code uses a rough fallback cap.
- Final WACC should be reviewed after any signal adjustments to ensure it remains inside the intended range.
- The frontend still reflects the current MVP flow and may need UI updates for manual peer management and database inspection.

## License

Private repository. All rights reserved.
