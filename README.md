# Stock Research Engine

A full-stack stock research tool for US equities. It collects company financials, estimates, filings, daily market prices, and optional LLM signals, then supports two main workflows:

1. Fiscal-year valuation using separated DCF reference values and forward P/E market multiple cases.
2. Technical support/resistance analysis using one-year daily OHLCV volume-by-price zones plus moving-average, gap, and prior high/low references.

## What It Does

Enter a ticker symbol and the app:

1. Fetches company, financial, estimate, filing, and market price data from SEC EDGAR, FMP, Finnhub, Yahoo Finance, and optional FRED.
2. Stores all historical data in PostgreSQL `tb_` tables instead of overwriting old periods.
3. Runs a base DCF model using annual financial reports, analyst revenue estimates, FCF margins, and CAPM-style WACC.
4. Runs a forward P/E model using fiscal-year EPS estimates, the ticker's historical P/E-to-growth relationship, and historical P/E guardrails. Historical P/E prefers FMP earnings-calendar EPS actuals as a market/adjusted EPS proxy, with split-adjusted GAAP EPS as fallback.
5. Shows each fiscal-year valuation window as P/E case cards, with rolled-forward DCF kept as a reference note.
6. Computes support/resistance zones from one year of daily price-volume history.
7. Shows moving averages, gaps, and prior highs/lows as separate reference levels rather than mixing them into volume-confirmed support/resistance.
8. Saves each valuation result by ticker, valuation date, and model version.

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
      technical/                 # Support/resistance volume-by-price logic
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
| `tb_technical_level` | Saved same-day support/resistance/active technical levels by ticker, source, level type, and rank |
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
| Analyst estimates | FMP, Finnhub, Alpha Vantage, Yahoo fallback | FMP annual EPS is preferred; Alpha Vantage `EARNINGS_ESTIMATES` can backfill annual EPS estimates when configured; Yahoo current/next FY EPS is the final near-term fallback |
| Earnings surprises | FMP, Finnhub | Empty provider responses are logged as `empty`, not `success` |
| Daily OHLCV | Yahoo Finance via `yfinance` | Used to reduce quota pressure on paid APIs |
| Technical levels | Derived from `tb_market_price` | Uses stored Yahoo daily OHLCV when recent data exists |
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
python -m uvicorn app.main:app --reload --port 8000
```

Database tables are created automatically on first startup.

On Windows, if `uvicorn` is not recognized, run it through the venv Python directly:

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

The frontend scripts use Vite's `--configLoader runner` and write TypeScript/Vite build cache to `frontend/.cache` instead of `node_modules/.tmp` or `node_modules/.vite-temp`. This avoids Windows permission errors after rebooting or reinstalling dependencies.

## Cloud Deployment With Render

The repository includes a `render.yaml` Blueprint for deploying:

| Render resource | Project component |
|---|---|
| `stock-research-backend` | FastAPI backend from `backend/` |
| `stock-research-frontend` | Vite static site from `frontend/` |
| `stock-research-db` | Managed PostgreSQL database |

Recommended first deployment flow:

1. Push the latest code to GitHub.
2. In Render, choose `New` -> `Blueprint`.
3. Connect the GitHub repository.
4. Render reads `render.yaml` and creates the backend, frontend, and Postgres database.
5. Fill the secret/env vars that are marked `sync: false`.

Backend environment variables:

```env
APP_ENV=production
LOG_LEVEL=INFO
DATABASE_URL=<auto-filled from Render Postgres>
CORS_ORIGINS=https://your-frontend.onrender.com
FMP_API_KEY=your_fmp_api_key
FINNHUB_API_KEY=your_finnhub_api_key
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_api_key
FRED_API_KEY=your_fred_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
```

Frontend environment variables:

```env
VITE_API_BASE_URL=https://your-backend.onrender.com
```

Important deployment notes:

- Do not commit real API keys.
- The backend start command on Render is `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- The frontend build command is `npm ci && npm run build`.
- `CORS_ORIGINS` can be either comma-separated text or a JSON list.
- The included database plan is `basic-256mb`, Render's lowest long-lived paid Postgres tier. You can temporarily change it to `free`, but Render's free Postgres is not suitable for long-term use.
- After the frontend receives its final Render URL, copy that URL into the backend `CORS_ORIGINS`.
- After the backend receives its final Render URL, copy that URL into the frontend `VITE_API_BASE_URL`.

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
| `GET` | `/api/technical/{ticker}` | Compute and save support/resistance technical levels |

Example:

```bash
curl -X POST http://localhost:8000/api/valuation/AAPL
```

Technical levels example:

```bash
curl http://localhost:8000/api/technical/AAPL
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

The 5-Year Forward Valuation section keeps every forward EPS year returned by the active provider. If a provider returns five years, the UI still shows five years. Years that are not matched by another source within a 5% tolerance are marked `unverified` because longer-dated EPS estimates often lack cross-source validation. Near-term years with matching Alpha Vantage/Yahoo/FMP values are marked `cross-checked`.

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
| Alpha Vantage | `EARNINGS_ESTIMATES`, up to first 3 annual EPS estimates, if `ALPHA_VANTAGE_API_KEY` is configured | First fallback and second-source sanity check |
| Yahoo Finance | Current FY and next FY EPS | Final free near-term fallback if FMP and Alpha Vantage are unavailable |

If FMP returns an entitlement error such as `402 Payment Required` for analyst estimates, the model does not treat this as a rate-limit event. It records the provider-access issue in `data_quality`. When Alpha Vantage is configured and has usable annual EPS estimates, the backend marks `forward_eps_source` as `alpha_vantage_annual_eps_estimates_fallback` and still produces fiscal-year P/E valuation windows. If Alpha Vantage is unavailable but Yahoo Finance has usable current-FY consensus EPS, the backend marks `forward_eps_source` as `yfinance_fallback_current_fy_consensus`. If none of these sources provides usable forward EPS, the UI shows a clear "Forward P/E valuation unavailable" message instead of rendering empty valuation cards.

Fallback order is intentionally one-way:

```text
FMP annual analyst EPS
-> Alpha Vantage annual EPS estimates
-> Yahoo Finance current/next FY consensus EPS
-> no forward P/E valuation window
```

Alpha Vantage is optional. If `ALPHA_VANTAGE_API_KEY` is missing or still set to the placeholder value, the backend skips Alpha Vantage and records the reason in `alpha_vantage_eps_validation`. Alpha Vantage responses are cached daily in `tb_estimate` with `source = "alpha_vantage"` and `estimate_period = "eps_validation"` so repeated same-day valuations do not spend extra Alpha Vantage calls.

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

### Cyclicality and Peak-Earnings Guardrail

High near-term EPS growth does not automatically justify a high P/E multiple. The model now adds a cyclicality layer before finalizing the automatic P/E range. This is designed for companies whose earnings can spike near the top of a cycle, especially memory, commodity, auto, energy, shipping, airlines, banks, and other highly cyclical businesses.

The model estimates:

| Signal | Meaning |
|---|---|
| `cyclicality_score` | How cyclical the company appears, based on industry tags plus historical gross margin, FCF margin, and EPS volatility |
| `peak_earnings_risk` | Whether forward EPS may be peak-cycle EPS rather than normalized earning power |
| `structural_re_rating_score` | How much confidence the model has that higher growth deserves a genuine valuation re-rating |

The simplified logic is:

```text
Growth-implied P/E = P/E range from weighted forward EPS growth
Historical prior = recent/historical P/E median range
Structural score = confidence that growth is durable rather than cyclical
Peak risk = penalty for applying high multiples to potentially peak EPS

Final P/E range moves toward historical/normalized P/E when cyclicality and peak risk are high.
```

This is intentionally asymmetric:

| Company type | Model behavior |
|---|---|
| Low cyclicality compounder | Growth-implied P/E can remain the main driver |
| Mixed semiconductor / cyclical growth | Growth-implied P/E is blended back toward historical P/E and penalized for peak-risk |
| Memory / commodity cyclical | The model strongly avoids `peak forward EPS * high-growth P/E` |

For example, MU is treated as a memory/storage cycle stock even when the provider industry field only says "Semiconductors." Its high FY1/FY2 EPS growth can still produce a higher case, but the P/E range is pulled back toward normalized/historical levels unless the company proves structural re-rating through durable FY3-FY5 growth, margin stability, and better cycle resistance.

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

Forward EPS uses the next fiscal year annual EPS estimate from FMP analyst estimates when available. It is not NTM EPS. If FMP has no usable forward EPS for the ticker under the active data plan, Alpha Vantage annual EPS estimates may be used as the first clearly labeled fallback, followed by Yahoo Finance current-FY consensus EPS as the final fallback. The response exposes the EPS basis, fiscal year label, inferred fiscal year end date when available, source, and as-of date.

The most useful data-quality fields for debugging EPS source selection are:

| Field | Meaning |
|---|---|
| `forward_eps_source` | Which provider supplied the EPS used in the P/E valuation window |
| `forward_eps_fallback_warning` | Explanation when the model had to fall back from FMP |
| `alpha_vantage_eps_validation` | Alpha Vantage configuration status, matched periods, and parsed annual EPS estimates |
| `yf_cross_validation` | Yahoo current/next FY EPS values used as cross-check or final fallback |
| `forward_eps_unavailable_reason` | Provider-access or missing-data reason when no forward EPS can be used |

Each `forward_trend[]` item also includes:

| Field | Meaning |
|---|---|
| `source` | Provider that supplied that year's EPS estimate |
| `eps_validation_status` | `cross_checked` when another source agrees within tolerance, otherwise `unverified` |
| `eps_validation_sources` | Sources involved in the validation check |
| `eps_validation_note` | Human-readable validation note for the UI |

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
| `pe_cases` | Automatic P/E range cases inside each fiscal-year window, including P/E low/mid/high, value low/mid/high, weighted EPS growth, growth curve, adjustment details, cyclicality/peak-risk fields, and uncertainty trigger reasons |
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

## Technical Support / Resistance Methodology

The technical-level feature is intentionally separate from valuation. It does not predict fair value and it does not say whether a stock should be bought. It answers a narrower question:

```text
Where did the stock have meaningful historical trading activity, and what nearby reference levels should a trader notice?
```

The primary support/resistance map uses only the latest one-year daily OHLCV history, approximately `252` trading days. The API also returns a separate longer-term volume reference layer using up to `756` trading days, roughly three years, when enough local price history exists.

The two layers are intentionally not mixed:

| Layer | Lookback | Purpose |
|---|---:|---|
| Primary support/resistance | ~1Y / 252 trading days | Current market structure and main price map |
| Longer-term volume references | Up to ~3Y / 756 trading days | Older high-volume memory zones for context only |

### Main Output Layers

The API separates two concepts that should not be mixed:

| Layer | Source | Meaning |
|---|---|---|
| `support_zones` | Volume-confirmed price zones below current price | Areas where the stock had continuous heavy historical trading below current price |
| `resistance_zones` | Volume-confirmed price zones above current price | Areas where the stock had continuous heavy historical trading above current price |
| `active_zones` | Volume-confirmed price zones containing current price | Current price is inside a historical trading cluster |
| `long_term_zones` | Up to 3Y volume-confirmed historical zones | Older volume-memory areas shown separately as references |
| `reference_levels` | Moving averages, gaps, Fibonacci retracements, prior high/low | Important context, but not volume-confirmed support/resistance by itself |

The UI mirrors this split:

- The `Price Map` only shows primary 1Y volume-confirmed support/resistance/active zones plus the current price line.
- Longer-term 3Y zones are shown in their own section and are not drawn into the primary map.
- Moving averages, gaps, Fibonacci retracements, and prior high/low levels are shown below in `Reference Levels`.
- Reference levels are not drawn as dashed lines on the map, because that made the chart visually noisy and confused them with true volume zones.

### ATR In Plain English

ATR means Average True Range. In this project, `ATR20` means:

```text
How many dollars this stock usually moves per day over roughly the last 20 trading days.
```

Examples:

| Stock behavior | ATR meaning |
|---|---|
| Low-volatility stock | Smaller normal daily swing; support/resistance zones should be narrower |
| High-volatility stock | Larger normal daily swing; zones and invalidation buffers should be wider |

The model uses ATR to avoid applying one fixed dollar width to every stock. A `$3` zone may be huge for a low-priced slow stock and meaningless for a fast-moving high-volatility stock.

### Volume-By-Price Construction

The model builds an estimated volume-by-price profile from daily OHLCV data in `tb_market_price`.

Because daily candles do not tell us the exact intraday volume at every price, this is an approximation. It should be read as estimated volume-by-price, not a true intraday volume profile.

Current process:

1. Load the latest `252` trading days.
2. Split the price range into adaptive price bins.
3. For each daily candle, distribute that day's volume across the candle's `low-high` range.
4. The distribution is no longer uniform. More weight is placed near:

```text
Typical Price = (High + Low + Close) / 3
```

5. High and low extremes still receive some volume, but less than the middle area near typical price.

This change was made because uniform distribution can overstate wick prices. For example, a stock might briefly touch a high or low with little actual volume, but uniform allocation would incorrectly treat that extreme as heavily traded.

### Zone Detection

After building the one-year volume profile, the model finds continuous price areas with high volume.

Current thresholds:

| Rule | Meaning |
|---|---|
| Top 20% of this ticker's own volume bins | Candidate `strong` volume area |
| Top 40% of this ticker's own volume bins | Candidate `medium` volume area |
| Continuous area required | Single-bin spikes are filtered out |
| Minimum width | At least `0.5 * ATR20` or at least two bins |
| Main display distance | Only zones within 30% of current price are shown in the main result |
| Nearby same-side merge | Adjacent support/resistance zones separated by only a tiny low-volume gap are merged |

The top 20% / top 40% thresholds are relative to the ticker itself. The model does not use a fixed volume number such as `100M`, because each stock has a different normal trading volume.

Medium zones that significantly overlap a strong zone are removed from display, so the UI does not show two versions of the same area. The current implementation treats overlap of at least `20%` of the medium zone as significant.

If two same-side zones are nearly touching, such as `$395-$404` and `$405-$416`, the model treats them as one practical trading area instead of showing two visually confusing boxes.

### Longer-Term Volume References

Some stocks may show no qualified support or resistance in the latest one-year profile, especially after a large move or a sharp drawdown. That does not always mean there is no older market memory.

To handle this without polluting the main chart, the API also calculates a longer-term volume profile:

| Rule | Current behavior |
|---|---|
| Lookback | Up to `756` trading days, roughly 3 years |
| Minimum data required | At least `504` trading days |
| Display role | Reference only |
| Main chart role | Not drawn into the primary `Price Map` |
| Persistence | Not persisted into `tb_technical_level` |

Example interpretation:

```text
MSFT may have no 1Y volume-confirmed support below current price,
but a 3Y reference may show an older high-volume area around $320-$332.
```

That older area is useful context, but it should not be treated the same as a fresh 1Y support zone.

### Strength Score

Each volume-confirmed zone receives a `strength_score` from 0 to 100.

Current components:

| Component | Purpose |
|---|---|
| `volume_density` | How heavy the zone's average bin volume is compared with the ticker's highest-volume bin |
| `zone_width` | Whether the zone is wide enough to represent an actual area rather than a narrow spike |
| `continuity` | Rewards continuous high-volume bins |
| `ma_confluence` | Adds a bonus when 50D or 200D moving average is inside or very near the zone |
| `strong_tier_floor` / `medium_tier_floor` | Optional tier baseline so a top-20% or top-40% volume zone starts from the expected tier range |

The score breakdown is designed to add back to the displayed `strength_score`. If a moving-average bonus would push a zone above `100`, the bonus is capped so the total remains explainable.

Labels:

| Score / Tier | Display |
|---|---|
| Strong tier or score >= 80 | `strong` |
| Medium tier | `medium` |

Important: `Active score` does not mean buy score or upside probability. It means the current price is inside a volume-confirmed zone, and the score is that zone's strength.

### Moving Averages

The model currently calculates:

| Moving Average | Use |
|---|---|
| 50D MA | Reference level and possible confluence bonus |
| 200D MA | Reference level and possible confluence bonus |

Moving averages do not create strong support/resistance zones by themselves.

They are used in two ways:

1. If a moving average sits inside or very close to a volume-confirmed zone, that zone gets a score bonus and evidence such as `200D_MA`.
2. The moving average is shown separately in `reference_levels` so the user can see it without confusing it with volume-confirmed support/resistance.

### Gaps

The model detects meaningful one-year daily gaps:

| Gap Type | Reference |
|---|---|
| Gap up | Prior day's high to current day's low |
| Gap down | Current day's high to prior day's low |

Gap zones are references only. The model does not treat the middle of a gap as a high-volume area, because gaps are often low-volume or no-trade price vacuums. The important parts are the gap edges.

For distance and sorting, a gap uses the nearest edge to the current price, not the midpoint of the gap.

### Prior High / Prior Low

The one-year prior high and prior low are included as reference levels only.

They do not create strong support/resistance by themselves. This is intentional: prior highs/lows are useful market-memory points, but the project currently keeps them separate from volume-confirmed zones.

### Integer / Round-Number Levels

Round-number levels are currently not included.

This is intentional based on the current product direction. They can be useful in real markets, but they also create a lot of visual noise. The current version prioritizes:

1. Volume-confirmed zones.
2. Moving-average references.
3. Gap references.
4. Fibonacci retracement references.
5. Prior high/low references.

### Fibonacci Retracements

Fibonacci retracements are included as reference levels only, similar to moving averages.

The model does not treat Fibonacci prices as volume-confirmed support or resistance by themselves. They are context points that may matter more when they line up with:

1. A volume-confirmed zone.
2. A moving average.
3. A gap edge.
4. A prior high or prior low.

Current process:

1. Use the latest one-year price history.
2. Find the dominant one-year swing high and swing low.
3. If the low happened before the high, treat it as an uptrend swing and calculate pullback references below the high.
4. If the high happened before the low, treat it as a downtrend swing and calculate rebound references above the low.
5. Return the common `38.2%`, `50.0%`, `61.8%`, and `78.6%` retracement prices, filtered to the same 30% nearby window as other references.

Important limitation: this is a simple one-year swing calculation. It is not yet doing advanced swing-point detection, Elliott-wave analysis, or multi-timeframe Fibonacci clustering.

### Price Discovery / No Resistance Case

If a stock is near a one-year high and there is little or no historical trading above current price, the model may return no volume-confirmed resistance.

That is not automatically a bug. It means:

```text
The model does not see a nearby one-year volume-confirmed overhead supply zone.
```

In that case, the UI may still show reference levels, such as prior high or moving averages, but it should not invent a strong resistance zone.

### Invalidation / Confirmation Text

Each volume-confirmed zone includes simple rule text:

| Zone Type | Example Meaning |
|---|---|
| Support | A daily close meaningfully below the zone weakens the support thesis |
| Resistance | A daily close meaningfully above the zone weakens the resistance thesis |
| Active | A daily close outside the active area means price has left the current trading cluster |

The current invalidation buffer uses ATR:

```text
Support invalidation ~= zone_low - 0.25 * ATR20
Resistance invalidation ~= zone_high + 0.25 * ATR20
```

Volume confirmation and multi-day retest logic are not implemented yet.

### Technical API Response

`GET /api/technical/{ticker}` returns:

| Field | Meaning |
|---|---|
| `ticker` | Uppercase ticker |
| `current_price` | Latest close from stored daily market prices |
| `analysis_date` | Date of the latest daily price used |
| `lookback_days` | Number of trading days used, normally up to 252 |
| `atr20` | Approximate normal daily dollar move |
| `atr20_pct` | `atr20 / current_price` |
| `support_zones` | Volume-confirmed support zones below current price |
| `resistance_zones` | Volume-confirmed resistance zones above current price |
| `active_zones` | Volume-confirmed zones containing current price |
| `long_term_zones` | Up to 3Y volume-confirmed historical zones shown as reference context only |
| `reference_levels` | Moving averages, gaps, Fibonacci retracements, prior high/low references |
| `relevance_score` | Per-zone 0-100 near-term relevance based on distance to current price; this is context, not strength |
| `notes` | Plain-English model notes and limitations |

Example response shape:

```json
{
  "ticker": "AAPL",
  "current_price": 298.01,
  "analysis_date": "2026-06-20",
  "lookback_days": 252,
  "atr20": 7.12,
  "support_zones": [
    {
      "level_type": "support",
      "price_low": 266.0,
      "price_high": 275.0,
      "strength_score": 100.0,
      "strength_label": "strong",
      "evidence": ["volume_cluster", "top_20_volume", "continuous_volume_area", "200D_MA"]
    }
  ],
  "reference_levels": [
    {
      "reference_type": "moving_average",
      "level_type": "support",
      "price": 288.63,
      "label": "50D MA"
    }
  ]
}
```

### Technical Data Persistence

The API saves technical levels into `tb_technical_level`.

Only volume-confirmed `support_zones`, `resistance_zones`, and `active_zones` are persisted. `reference_levels` such as moving averages, gaps, Fibonacci retracements, and prior high/low are recalculated and returned live, but are not stored in `tb_technical_level`.

`long_term_zones` are also recalculated live and are not persisted. The database table stores only the primary 1Y support/resistance/active output.

The current persistence behavior is:

```text
ticker + level_date + source + level_type + rank
```

For the same ticker/source/date, the repository deletes that day's previous technical levels and writes the fresh result. This matches the project convention that same-day repeated runs update the same result, while results from different dates are preserved.

Current source:

```text
technical_v1
```

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

Technical endpoint smoke test:

```bash
cd backend
venv\Scripts\python.exe -c "from fastapi.testclient import TestClient; from app.main import app; r=TestClient(app).get('/api/technical/AAPL'); print(r.status_code); print(r.json().keys())"
```

Direct technical model inspection:

```bash
cd backend
venv\Scripts\python.exe -c "from app.config.database import SessionLocal; from app.services.technical_service import get_technical_levels; db=SessionLocal(); r=get_technical_levels(db,'AAPL'); db.close(); print('support', [(z.price_low,z.price_high,z.strength_label,z.strength_score,z.evidence) for z in r.support_zones]); print('long_term', [(z.level_type,z.price_low,z.price_high,z.strength_label,z.strength_score) for z in r.long_term_zones]); print('refs', [(x.reference_type,x.label,x.price,x.price_low,x.price_high) for x in r.reference_levels])"
```

Frontend checks:

```bash
cd frontend
npm run build
npm run lint
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
- Technical volume-by-price currently uses daily OHLCV only. It is an approximation, not a true intraday volume profile.
- Technical volume allocation uses a typical-price weighting method, but still cannot know the real intraday price-volume distribution without intraday bars or tick data.
- Primary technical zones still use the latest one-year profile. The separate `long_term_zones` layer uses up to three years as reference context only and is not mixed into the primary price map.
- Technical support/resistance does not currently use options open interest, gamma, VWAP, or analyst target clusters.
- Technical invalidation text uses price and ATR buffers only. Relative volume confirmation, multi-day confirmation, and retest logic are not implemented yet.
- Reference levels are intentionally separated from volume-confirmed zones. A moving average, Fibonacci retracement, gap, or prior high/low alone should not be read as a strong support/resistance zone.
- The frontend still reflects the current MVP flow and may need UI updates for manual peer management and database inspection.

## License

Private repository. All rights reserved.
