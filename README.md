# Stock Research - Valuation App

A full-stack stock valuation tool that combines DCF (Discounted Cash Flow) and forward P/E analysis to generate bear/base/bull price targets for any publicly traded US stock.

## What It Does

Enter a ticker symbol and the app:

1. **Fetches financial data** from FMP, Finnhub, Yahoo Finance, and SEC EDGAR
2. **Runs a DCF model** — projects revenue and free cash flow, discounts to present value
3. **Runs a forward P/E model** — triangulates historical P/E, peer comparison, and DCF-justified P/E
4. **Blends both models** (50/50) into bear/base/bull price targets
5. **Shows additional analysis** — reverse DCF (implied growth), margin of safety, terminal value warning

### Example Output (AAPL)

| Scenario | DCF | Forward P/E | Blended |
|----------|-----|-------------|---------|
| Bear     | $120 | $160       | $140    |
| Base     | $142 | $191       | $166    |
| Bull     | $165 | $225       | $195    |

Plus: reverse DCF shows the market implies ~21% revenue growth, margin of safety verdict, and terminal value sensitivity warning.

## Architecture

```
backend/                  # FastAPI (Python 3.12)
  app/
    api/routes.py         # REST endpoints
    config/               # Settings, database config
    data_structure/        # Pydantic models (financial, valuation, signals)
    db/                   # SQLAlchemy models + DB read/write
    logic/
      data_aggregator.py  # Orchestrates data collection from all sources
      data_sources/       # FMP, Finnhub, Yahoo Finance, SEC EDGAR clients
      valuation/
        assumptions.py    # WACC (CAPM + levered beta), growth, margins
        dcf.py            # DCF model
        multiples.py      # Forward P/E triangulation
        engine.py         # Orchestrator: runs DCF + P/E, blends, adds analysis
      llm_extraction/     # LLM signal extraction from filings/transcripts

frontend/                 # React + TypeScript + Vite
  src/
    components/           # UI components (ticker input, valuation summary, charts)
    services/api.ts       # API client
    types/                # TypeScript type definitions
```

## Prerequisites

- **Python 3.12+**
- **Node.js 18+**
- **PostgreSQL 16** (or Docker)
- **API Keys** (see below)

## Setup

### 1. Database

Start PostgreSQL via Docker:

```bash
docker-compose up -d
```

Or use an existing PostgreSQL instance. Default connection: `postgresql://postgres:123123@localhost:5432/stockapp`

### 2. Environment Variables

Copy the example and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
FMP_API_KEY=your_key_here          # https://financialmodelingprep.com/developer

# Optional (enhance results)
FINNHUB_API_KEY=your_key_here      # https://finnhub.io/
ANTHROPIC_API_KEY=your_key_here    # https://console.anthropic.com/ (for LLM signals)
FRED_API_KEY=your_key_here         # https://fred.stlouisfed.org/docs/api/api_key.html
```

| Key | Required | Free Tier | What It Does |
|-----|----------|-----------|--------------|
| `FMP_API_KEY` | Yes | 250 calls/day | Financial statements, analyst estimates, peer data |
| `FINNHUB_API_KEY` | No | 60 calls/min | Analyst recommendations, earnings surprises |
| `ANTHROPIC_API_KEY` | No | Pay-per-use | LLM extraction from MD&A, risk factors, transcripts |
| `FRED_API_KEY` | No | Unlimited | Live 10Y Treasury yield for risk-free rate |

### 3. Backend

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The database tables are created automatically on first startup.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

## Usage

### Quick Start (UI)

1. Open http://localhost:5173
2. Enter a ticker (e.g., `AAPL`)
3. Click **Fetch Data** to load financial data
4. Click **Run Valuation** to get price targets

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET/POST` | `/api/financial-data/{ticker}` | Fetch all financial data |
| `POST` | `/api/text-materials` | Submit earnings transcript or notes |
| `GET` | `/api/text-materials/{ticker}` | Get submitted text materials |
| `POST` | `/api/extract-signals/{ticker}` | Run LLM signal extraction |
| `GET/POST` | `/api/valuation/{ticker}` | Run full valuation |

### Example API Call

```bash
# Run valuation for Apple
curl -X POST http://localhost:8000/api/valuation/AAPL | python -m json.tool
```

## Valuation Methodology

### DCF Model

1. **Revenue projection** — Uses analyst consensus revenue estimates (FMP) for up to 5 years, falls back to historical CAGR
2. **FCF projection** — Applies historical average FCF margin to projected revenue
3. **WACC** — CAPM with:
   - Risk-free rate from FRED API (10Y Treasury, live)
   - Levered beta via Hamada equation (unlever sector beta, relever with company D/E)
   - Market cap (not book equity) for capital structure weights
4. **Terminal value** — Gordon Growth Model at 3% perpetual growth
5. **Enterprise value** — PV of projected FCFs + PV of terminal value
6. **Per-share value** — (Enterprise value - net debt) / diluted shares

### Forward P/E Model

P/E multiple is triangulated from three sources (weighted):
- **50% Historical** — Average trailing P/E from 5 years of daily prices
- **30% Peer** — Median forward P/E of industry peers, PEG-adjusted for growth
- **20% Justified** — DCF intrinsic value / forward EPS (cross-check)

Applied to forward EPS (analyst consensus) to get per-share value.

### Additional Analysis

- **Reverse DCF** — Back-solves the revenue growth rate implied by the current market price
- **Margin of Safety** — Compares intrinsic value to market price (undervalued / fairly valued / overvalued)
- **Terminal Value Warning** — Flags when terminal value exceeds 75% of enterprise value
- **LLM Signals** (optional) — Extracts sentiment from MD&A, risk factors, and earnings call transcripts to nudge assumptions

## Known Limitations

- **Peer selection** — Uses FMP's peer API which groups by industry, not by business model. Can produce poor comparisons (e.g., NVDA grouped with AAPL instead of AMD).
- **Negative earnings** — Companies with negative FCF margins (e.g., MU in a cyclical trough) produce $0 DCF values. An EV/Sales fallback is not yet implemented.
- **50/50 blend** — The fixed DCF/P/E weighting doesn't suit all companies. High-growth, low-FCF companies (NVDA, TSLA) are better served by higher P/E weight.
- **FMP rate limits** — Free tier allows 250 calls/day. Each valuation uses ~20+ calls (financial data + peers + daily prices). Daily prices are cached in the database to reduce API usage.

## License

Private repository. All rights reserved.
