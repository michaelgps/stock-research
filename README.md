# Stock Research - Valuation App

A full-stack stock valuation tool for US equities. It collects company financials, estimates, filings, daily market prices, and optional LLM signals, then shows fiscal-year valuation windows that align forward P/E targets with rolled-forward DCF reference values.

## What It Does

Enter a ticker symbol and the app:

1. Fetches company, financial, estimate, filing, and market price data from SEC EDGAR, FMP, Finnhub, Yahoo Finance, and optional FRED.
2. Stores all historical data in PostgreSQL `tb_` tables instead of overwriting old periods.
3. Runs a base DCF model using annual financial reports, analyst revenue estimates, FCF margins, and CAPM-style WACC.
4. Runs a forward P/E model using next fiscal year EPS and the ticker's own historical P/E percentiles: P25, P50, and P75. Historical P/E prefers FMP earnings-calendar EPS actuals as a market/adjusted EPS proxy, with split-adjusted GAAP EPS as fallback.
5. Shows each fiscal-year valuation window with both a forward P/E target and a DCF value rolled forward to that same fiscal year end.
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

The forward P/E model uses the ticker's own historical P/E distribution instead of peer weighting.

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

The rolled-forward DCF value is shown next to the forward P/E target for the same fiscal year end. It is not blended with P/E.

### Forward P/E Model

The P/E model uses the ticker's own last ~5 fiscal years of daily trailing P/E observations.

For historical trailing P/E, the model prefers FMP earnings-calendar EPS actuals as a market/adjusted EPS proxy:

```text
Daily Historical P/E = Daily Price / Latest Reported 4-Quarter Market EPS
```

If FMP market EPS is unavailable, the model falls back to split-adjusted GAAP annual EPS from financial statements. The response exposes the EPS basis for each historical P/E year.

Market TTM EPS keeps negative reported quarters in the four-quarter sum, then only uses the resulting TTM value when the total is positive. If a fiscal year has market EPS coverage, the model excludes earlier non-covered trading days instead of mixing market and GAAP denominators in the same yearly P/E distribution.

FMP `epsActual` is not treated as audited GAAP. It is used as a market EPS proxy because it generally follows the earnings-calendar / consensus-surprise denominator investors use for P/E. Finnhub earnings actuals are not used for historical P/E because the current stored date is the fiscal period end date, not the earnings announcement date, which would introduce look-ahead bias.

The model sorts all valid daily P/E observations and uses percentiles:

| Scenario | Historical P/E multiple |
|---|---|
| Bear | P25, the 25th percentile |
| Base | P50, the median |
| Bull | P75, the 75th percentile |

Daily P/E observations are internal calculation inputs only. The API returns yearly summary fields such as `pe_low`, `pe_high`, `pe_avg`, `pe_p25`, `pe_p50`, and `pe_p75`, but not the full daily observation list.

Because Yahoo prices are split-adjusted, fallback GAAP EPS is also adjusted to the current split-adjusted share basis before calculating historical P/E. This prevents stock splits, such as NVDA's 2024 10-for-1 split, from artificially compressing historical P/E multiples.

Split adjustment is inferred conservatively from large diluted-share jumps using common split ratios. This handles major stock splits without calling another paid endpoint, but a dedicated corporate-actions feed would still be preferable for production-grade coverage.

Forward EPS uses the next fiscal year annual EPS estimate from FMP analyst estimates. It is not NTM EPS. The response exposes the EPS basis, fiscal year label, inferred fiscal year end date when available, source, and as-of date.

Forward P/E formula:

```text
Forward P/E Value = Next Fiscal Year EPS * Selected P/E Multiple
```

In the UI, the base target is shown as an explicit formula, for example:

```text
EPS $8.75 * 27.8x P/E = $243.25
```

DCF-implied P/E and peer P/E are only references/cross-checks. They are not used to set the P/E multiple.

### Output Structure

DCF and forward P/E are not averaged into a blended target. The primary valuation response is `fiscal_year_valuation_windows`, which aligns both methods to explicit fiscal year end dates.

| Field | Meaning |
|---|---|
| `fiscal_year_valuation_windows` | Per-fiscal-year windows containing forward P/E target, DCF rolled-forward value, time distance, EPS, P/E multiple, and P25/P50/P75 scenario cards |
| `pe_scenarios` | Bear/base/bull P/E outputs inside each fiscal-year window, mapped to P25/P50/P75 |
| `dcf_view` | Legacy/base DCF present-value reference |
| `pe_view` | Legacy next-fiscal-year P/E view |
| `forward_eps_metadata` | Explicit forward EPS basis, fiscal year period, fiscal year end, source, and as-of date |
| `historical_pe_ranges` | Yearly historical P/E summaries, including `eps`, `eps_basis`, `pe_p25`, `pe_p50`, and `pe_p75` |

Legacy scenario fields still include `bear`, `base`, and `bull` with detailed `dcf` and `multiples` objects, but `blended_per_share` is deprecated and no longer used as the main valuation target.

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
- Peer data is reference-only. The current P/E multiple is based on the ticker's own historical P/E percentiles, not peers.
- FRED is optional. If unavailable, the model uses the default risk-free rate.
- DCF currently uses analyst revenue estimates only when at least 5 annual estimates are available; otherwise it falls back to a flat scenario growth path.
- The DCF terminal value formula is standard when `WACC > terminal_growth`; if that safety condition is violated, the code uses a rough fallback cap.
- Final WACC should be reviewed after any signal adjustments to ensure it remains inside the intended range.
- The frontend still reflects the current MVP flow and may need UI updates for manual peer management and database inspection.

## License

Private repository. All rights reserved.
