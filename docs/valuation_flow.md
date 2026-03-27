# Stock Research Engine: Valuation Flow

## Part 1 — Generic Flow (How the Engine Works)

### Overview

The engine produces a **next-fiscal-year price target** for any US-listed stock using two independent models blended 50/50:
- **DCF** (Discounted Cash Flow) — intrinsic value from projected free cash flows
- **Forward P/E** — relative value from a triangulated P/E multiple applied to consensus EPS

Each model is run 3 times (bear/base/bull), giving 3 blended price targets.

### Architecture

```
POST /api/valuation/{ticker}
    |
    v
Phase 1: Data Collection (data_aggregator.py)
    |
    v
Phase 2: LLM Signal Extraction (optional)
    |
    v
Phase 3: Valuation Engine (engine.py)
    |-- assumptions.py  -> scenario assumptions
    |-- dcf.py          -> DCF model
    |-- multiples.py    -> P/E triangulation
    |-- fmp.py          -> peer P/E + EPS growth
    |-- yfinance_client.py -> cross-validation
    |
    v
ValuationResponse (bear/base/bull targets)
```

---

### Phase 1: Data Collection

**File:** `backend/app/logic/data_aggregator.py`

The engine collects data from multiple sources with a priority hierarchy:

| Source | What it provides | Priority |
|--------|-----------------|----------|
| **SEC EDGAR** | Annual financial statements (10-K), MD&A text, risk factors | Primary (ground truth) |
| **FMP API** | Company profile (price, sector, market cap), analyst consensus estimates (EPS + revenue, 5 years forward), peer list, daily prices (5yr), income statements | Secondary |
| **Finnhub** | Earnings surprises, supplementary estimates | Tertiary |
| **Yahoo Finance** | Consensus EPS cross-validation | Validation only |

**Caching:** All data is cached in PostgreSQL with a 24-hour TTL. Cache hits skip all API calls.

**Key data extracted:**

| Input | How it's derived |
|-------|-----------------|
| Latest actual revenue | Most recent annual filing (revenue field) |
| Latest actual EPS | `net_income / diluted_shares` from most recent annual filing |
| FY end date | `date` field from most recent annual filing (e.g., 2025-09-27 for AAPL) |
| Forward EPS | First FMP analyst estimate period (sorted ascending) |
| Analyst revenue estimates | FMP consensus revenue for each forward year (up to 5 years) |
| Net debt | `total_debt - total_cash` from latest annual filing |
| Diluted shares | Latest annual filing, fallback to company profile |
| FCF margin history | `free_cash_flow / revenue` averaged over 5 recent annual filings |
| Daily prices | FMP daily OHLC for ~5 years (used for historical P/E ranges) |

---

### Phase 2: LLM Signal Extraction (Optional)

**File:** `backend/app/logic/valuation/assumptions.py` (`_apply_signal_adjustments`)

If the user has submitted 10-K MD&A, risk factors, or earnings call transcripts, Claude extracts directional signals that nudge the base assumptions:

| Signal | Source | Effect |
|--------|--------|--------|
| Revenue outlook: positive/negative | MD&A | +/-1pp revenue growth |
| Margin trend: expanding/contracting | MD&A | +/-1pp FCF margin |
| Management tone: confident/defensive | MD&A | -/+0.5pp WACC |
| Overall risk level: high/low | Risk factors | +1pp / -0.5pp WACC |
| Guidance tone: positive/negative | Earnings transcript | +/-0.5pp growth |
| Management confidence: low | Earnings transcript | +0.5pp WACC |

If no text materials are submitted, base assumptions are used as-is (no adjustment).

---

### Phase 3: Valuation Engine

**File:** `backend/app/logic/valuation/engine.py` (orchestrator)

#### Step 3.1: Build Scenario Assumptions

**File:** `backend/app/logic/valuation/assumptions.py` (`build_scenarios`)

**Revenue growth rate** — derived from analyst consensus:
```
base_growth = (next_FY_analyst_revenue / latest_actual_revenue) - 1
```
Fallback chain: analyst next-FY -> historical 5-year CAGR -> default 5%.

**FCF margin** — 5-year historical average of `free_cash_flow / revenue`.

**WACC** — CAPM model:
```
cost_of_equity = risk_free_rate (4.3%) + sector_beta * equity_risk_premium (5%)
WACC = equity_weight * cost_of_equity + debt_weight * cost_of_debt * (1 - tax_rate)
```
Clamped to [8%, 15%]. Sector beta from a lookup table (e.g., Technology = 1.2).

**Three scenarios** are built by spreading around the base:

| Parameter | Bear | Base | Bull |
|-----------|------|------|------|
| Revenue growth | base - 1.5pp | base | base + 1.5pp |
| FCF margin | base - 1.5pp | base | base + 1.5pp |
| WACC | base + 0.75pp | base | base - 0.75pp |
| Terminal growth | 2.5% | 3.0% | 3.5% |

Terminal growth is capped at `WACC - 2pp` to ensure the Gordon Growth formula converges.

---

#### Step 3.2: DCF Model

**File:** `backend/app/logic/valuation/dcf.py` (`run_dcf`)

**Revenue projection** — two modes:
- **Analyst consensus mode** (preferred): If 5+ years of analyst consensus revenues are available, use them directly year-by-year. No flat growth compounding.
- **Flat growth mode** (fallback): Compound `latest_revenue * (1 + growth_rate)^t` for each year.

**FCF projection:**
```
projected_FCF[t] = revenue[t] * fcf_margin
```

**Terminal value** (Gordon Growth Model):
```
terminal_value = FCF[last_year] * (1 + terminal_growth) / (WACC - terminal_growth)
```

**Discounting and per-share value:**
```
PV_FCFs     = SUM( FCF[t] / (1 + WACC)^t )          for t = 1..5
PV_terminal = terminal_value / (1 + WACC)^5
EV          = PV_FCFs + PV_terminal
equity      = EV - net_debt
per_share   = equity / diluted_shares
```

---

#### Step 3.3: Forward EPS Growth Rate

**File:** `backend/app/logic/data_sources/fmp.py` (`_compute_eps_growth`)

The EPS growth rate is used in the P/E triangulation (growth adjustment and PEG). It is **anchored on the latest actual (reported) EPS**, not on forward estimates alone.

**Method: 2-year forward CAGR from actual EPS**
```
growth = (FY+2_estimate_EPS / actual_EPS) ^ (1 / years_between) - 1
```

**Time-window adjustment:**
- Compute months remaining to next FY end
- If **>= 6 months** to next FY end: use standard window (actual -> FY+2)
- If **< 6 months** to next FY end: shift forward by 1 year (actual -> FY+3, or FY+1 -> FY+2 fallback) — the market is already looking through the current fiscal year

**Fallback chain:**
1. Actual EPS -> FY+2 estimate (2-year CAGR) — **preferred**
2. Actual EPS -> FY+1 estimate (1-year growth) — if FY+2 unavailable
3. Estimate-only CAGR (first 2 forward estimates) — if no actual EPS available

**Why this matters:** Without anchoring on actual EPS, the growth rate can be wildly wrong. Example: NVDA FY2026 actual EPS = $4.93, but FMP only returns forward estimates starting FY2027. An estimate-only CAGR from FY2027->FY2031 gives 14.1%, while the actual-anchored 2-year CAGR ($4.93 -> $10.89) gives 48.6%.

---

#### Step 3.4: P/E Multiple Determination (Triangulation)

**File:** `backend/app/logic/valuation/multiples.py` (`determine_pe_multiple`)

Three independent P/E sources are combined via weighted average:

##### (a) Historical Trailing P/E — weight 50%

**Data:** 5 years of daily OHLC prices + annual EPS from filings.

For each fiscal year, compute:
- `pe_high = max(daily_high) / annual_EPS`
- `pe_low = min(daily_low) / annual_EPS`
- `pe_avg = mean(daily_close) / annual_EPS`

Average across 5 years to get `avg_pe_low`, `avg_pe_avg`, `avg_pe_high`.

**Growth adjustment:** Compare forward EPS growth to historical EPS CAGR:
```
hist_eps_growth = (newest_EPS / oldest_EPS) ^ (1 / years_span) - 1
growth_diff     = forward_eps_growth - hist_eps_growth
adjustment      = growth_diff * 50    (each 1pp faster growth = +0.5x PE)
                  capped at +/-15% of avg_pe_avg
```

Scenario mapping: bear = `avg_pe_low + adj`, base = `avg_pe_avg + adj`, bull = `avg_pe_high + adj`.

##### (b) Peer PEG-Adjusted P/E — weight 30%

**File:** `backend/app/logic/data_sources/fmp.py` (`get_peer_forward_pe`)

For each peer (from FMP stock peers API):
1. Fetch forward EPS, current price, actual EPS, and FY end date
2. Compute `forward_pe = price / forward_eps`
3. Compute `eps_growth` using the same actual-anchored 2-year CAGR
4. Compute `PEG = forward_pe / (eps_growth * 100)`

Then:
```
median_PEG          = median of all peer PEG ratios
growth_adjusted_pe  = median_PEG * (ticker_eps_growth * 100)
```

This ensures a slow-growing ticker doesn't inherit the high raw P/E of its fast-growing peers.

Scenario mapping: bear = `growth_adj_pe * 0.85`, base = `growth_adj_pe`, bull = `growth_adj_pe * 1.15`.

##### (c) Justified P/E — weight 20%

```
justified_pe = base_DCF_per_share / forward_EPS
```

"What P/E would the market need to assign to match our DCF valuation?"

This creates a feedback loop between DCF and P/E — the DCF cross-checks the multiples model.

Scenario mapping: bear = `justified_pe * 0.90`, base = `justified_pe`, bull = `justified_pe * 1.10`.

##### Combining

```
final_pe = (historical_pe * 0.50 + peer_pe * 0.30 + justified_pe * 0.20) / total_weight
```

Floor: P/E is never below 5.0x.

---

#### Step 3.5: Forward P/E Price

```
forward_pe_price = forward_EPS * triangulated_PE_multiple
```

---

#### Step 3.6: Blend

```
blended_target = 0.50 * DCF_per_share + 0.50 * forward_PE_price
```

If one model fails (e.g., no forward EPS), the other model's price is used at 100%.

---

#### Step 3.7: Cross-Validation

**File:** `backend/app/logic/data_sources/yfinance_client.py` (`cross_validate_eps`)

After computing the forward EPS from FMP, the engine compares it against Yahoo Finance consensus:
- Fetch YF's `earnings_estimate` for current FY ("0y") and next FY ("+1y")
- Compute divergence: `|yf_eps - fmp_eps| / fmp_eps`
- Flag warning if divergence > 15%

Result is stored in `data_quality["yf_cross_validation"]` for transparency.

**Note on fiscal year alignment:** YF's "0y" (current FY) corresponds to FMP's first forward estimate. For companies with non-calendar FY ends (NVDA = Jan, AAPL = Sep), the calendar year labels differ but the periods align because both sources skip already-reported fiscal years.

---

#### Step 3.8: 5-Year Forward Trend

```
For each forward year with an EPS estimate:
    implied_price[year] = EPS[year] * base_PE_multiple
```

Uses the base scenario P/E applied to each year's consensus EPS. Provides a trajectory of where the stock "should" trade if P/E holds constant at the engine's base estimate.

---

### Output

The `ValuationResponse` contains:

| Field | Description |
|-------|-------------|
| `ticker` | Ticker symbol |
| `current_price` | Latest market price |
| `bear`, `base`, `bull` | Each: DCF result + multiples result + blended target |
| `forward_trend` | 5-year EPS + implied price trajectory |
| `historical_pe_ranges` | Yearly PE high/low/avg for context |
| `peer_comparison` | Peer forward PEs, PEGs, growth rates |
| `signal_adjustments` | What the LLM signals changed (if any) |
| `data_quality` | Audit trail: sources used, growth rates, cross-validation |

---

---

## Part 2 — AAPL Worked Example

**Run date:** 2026-03-12 | **Current price:** $260.81 | **FY end:** September 27

### Phase 1: Data Collected

| Input | Value | Source |
|-------|-------|--------|
| Latest actual revenue (FY2025) | $416.2B | SEC EDGAR annual filing |
| Latest actual EPS (FY2025) | $7.46 | $112.0B net income / 15.00B shares |
| FY end date | 2025-09-27 | Filing date |
| Forward EPS (FY2026) | $8.48 | FMP analyst consensus (first forward period) |
| Net debt | $66.7B | $96.7B debt - $29.9B cash |
| Diluted shares | 15.00B | Latest annual filing |
| 5yr avg FCF margin | 26.2% | Historical FCF/revenue average |
| Sector | Technology | FMP company profile |
| Sector beta | 1.2 | Lookup table |
| Peers | GOOGL, META, MSFT, NVDA | FMP stock peers API |

**Analyst Consensus Estimates (FMP):**

| Year | Revenue | EPS |
|------|---------|-----|
| FY2026 | $463.4B | $8.48 |
| FY2027 | $494.3B | $9.30 |
| FY2028 | $523.0B | $10.26 |
| FY2029 | $567.1B | $11.69 |
| FY2030 | $581.7B | $13.33 |

**YF Cross-Validation:**

| | FMP | Yahoo Finance | Divergence |
|---|-----|---------------|------------|
| Next-FY EPS | $8.48 | $8.51 (40 analysts) | 0.4% — no warning |

---

### Phase 2: LLM Signals

No text materials submitted. All assumptions are unadjusted.

---

### Phase 3: Valuation

#### Step 3.1: Scenario Assumptions

**Revenue growth:**
```
$463.4B (FY2026 analyst est) / $416.2B (FY2025 actual) - 1 = 11.4%
```

**WACC:**
```
cost_of_equity = 4.3% + 1.2 * 5.0% = 10.3%
```
After capital structure weighting (debt/equity mix) and clamping: **8.0%**

| Parameter | Bear | Base | Bull |
|-----------|------|------|------|
| Revenue growth | 9.9% | 11.4% | 12.9% |
| FCF margin | 24.7% | 26.2% | 27.7% |
| WACC | 8.75% | 8.0% | 8.0% (floored) |
| Terminal growth | 2.5% | 3.0% | 3.5% |

---

#### Step 3.2: DCF (Base Case)

**Revenue source:** Analyst consensus (5 years available >= 5 years needed).

| Year | Revenue (consensus) | x FCF Margin (26.2%) | = Projected FCF | / (1.08)^t | = PV |
|------|--------------------|-----------------------|-----------------|------------|------|
| FY2026 (t=1) | $463.4B | | $121.6B | / 1.080 | $112.6B |
| FY2027 (t=2) | $494.3B | | $129.7B | / 1.166 | $111.2B |
| FY2028 (t=3) | $523.0B | | $137.2B | / 1.260 | $108.9B |
| FY2029 (t=4) | $567.1B | | $148.8B | / 1.360 | $109.4B |
| FY2030 (t=5) | $581.7B | | $152.6B | / 1.469 | $103.9B |

```
PV of FCFs = $546.0B

Terminal value = $152.6B * (1 + 3.0%) / (8.0% - 3.0%) = $3,144.5B
PV of terminal = $3,144.5B / (1.08)^5 = $2,140.1B

Enterprise value = $546.0B + $2,140.1B = $2,686.2B
Equity value     = $2,686.2B - $66.7B  = $2,619.4B
Per share         = $2,619.4B / 15.00B  = $174.58
```

---

#### Step 3.3: Forward EPS Growth

```
Actual EPS (FY2025):     $7.46
FY end:                  2025-09-27
Next FY end:             ~2026-09-27
Months to next FY end:   ~6.5 months (> 6) -> no time-window shift

Target: FY2028 estimate (index shift+1 = 0+1 = 1, i.e., 2nd forward year)
FY2028 EPS estimate:     $10.26
Years from actual:       2028 - 2025 = 3

Growth = ($10.26 / $7.46) ^ (1/3) - 1 = 11.6%
```

---

#### Step 3.4: P/E Triangulation (Base Case)

##### (a) Historical P/E — 50% weight

| FY | EPS | PE Low | PE Avg | PE High |
|----|-----|--------|--------|---------|
| 2021 | $5.61 | 21.2x | 24.4x | 28.0x |
| 2022 | $6.11 | 21.1x | 25.9x | 29.9x |
| 2023 | $6.13 | 20.2x | 26.4x | 32.3x |
| 2024 | $6.08 | 27.0x | 31.9x | 39.0x |
| 2025 | $7.46 | 22.7x | 30.0x | 34.8x |

5-year averages: low **22.4x**, avg **27.7x**, high **32.8x**

**Growth adjustment:**
```
hist_eps_growth  = ($7.46 / $5.61) ^ (1/4) - 1 = 7.4%
forward_growth   = 11.6%
growth_diff      = 11.6% - 7.4% = 4.2pp
adjustment       = 4.2 * 50 = +2.1x PE    (capped at +/-15% of 27.7 = +/-4.2)
```

Base historical PE = 27.7 + 2.1 = **29.8x**

##### (b) Peer PEG-Adjusted P/E — 30% weight

| Peer | Fwd PE | EPS Growth | PEG |
|------|--------|------------|-----|
| GOOGL | 27.0x | 10.9% | 27.0 / 10.9 = 2.48 |
| META | 22.0x | 20.0% | 22.0 / 20.0 = 1.10 |
| MSFT | 24.6x | 18.0% | 24.6 / 18.0 = 1.37 |
| NVDA | 22.6x | 48.6% | 22.6 / 48.6 = 0.46 |

```
Median PEG = median(2.48, 1.10, 1.37, 0.46) = median sorted [0.46, 1.10, 1.37, 2.48] = 1.23
Growth-adjusted PE = 1.23 * 11.6 = 14.3x
```

##### (c) Justified P/E — 20% weight

```
Base DCF per share / forward EPS = $174.58 / $8.48 = 20.6x
```

##### Combined (Base)

| Source | PE Value | Weight | Contribution |
|--------|----------|--------|-------------|
| Historical | 29.8x | 50% | 14.9 |
| Peer (PEG) | 14.3x | 30% | 4.3 |
| Justified | 20.6x | 20% | 4.1 |
| **Total** | **23.3x** | 100% | **23.3** |

---

#### Step 3.5: Forward P/E Price

```
$8.48 * 23.3x = $197.53
```

---

#### Step 3.6: Blend

```
50% * $174.58 (DCF) + 50% * $197.53 (Fwd PE) = $186.06
```

---

#### All Three Scenarios

| | Bear | Base | Bull |
|---|------|------|------|
| DCF per share | $132.59 | $174.58 | $202.37 |
| P/E multiple | 19.6x | 23.3x | 26.9x |
| Fwd PE price | $166.16 | $197.53 | $228.05 |
| **Blended target** | **$149.38** | **$186.06** | **$215.21** |

**vs. current price $260.81** — all scenarios imply AAPL is trading above the engine's fair value range.

---

#### 5-Year Forward Trend (Base P/E = 23.3x)

| Year | Consensus EPS | Implied Price |
|------|--------------|---------------|
| 2026 | $8.48 | $197.53 |
| 2027 | $9.30 | $216.78 |
| 2028 | $10.26 | $239.00 |
| 2029 | $11.69 | $272.41 |
| 2030 | $13.33 | $310.59 |

At the base P/E, AAPL's implied price would surpass its current $260.81 between FY2029 and FY2030.

---

#### Data Quality Audit Trail

```json
{
  "revenue_growth_source": "analyst_next_fy (11.4%)",
  "dcf_revenue_source": "analyst_consensus_5_years",
  "fcf_margin_source": "historical_average",
  "wacc_method": "capm_sector_beta",
  "forward_eps_growth": "11.6%",
  "actual_eps_anchor": 7.46,
  "fy_end_date": "2025-09-27",
  "forward_eps": 8.48,
  "pe_range_years": 5,
  "peer_count": 4,
  "peer_median_pe": 23.6,
  "peer_growth_adjusted_pe": 14.3,
  "peer_median_peg": 1.23,
  "justified_pe": 20.6,
  "yf_cross_validation": {
    "yf_current_fy_eps": 8.51,
    "fmp_eps": 8.48,
    "divergence": 0.004,
    "warning": false
  }
}
```
