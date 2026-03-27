# How the DCF Model Computes a Stock's Price (AAPL Example)

## What is a DCF?

DCF stands for **Discounted Cash Flow**. It answers one question: *"How much is a company worth based on the cash it will generate in the future?"*

The idea is simple: a dollar earned next year is worth less than a dollar today (because you could invest today's dollar and earn interest). So we take all the cash a company is expected to generate over the next 5 years, plus an estimate of everything after that, and "discount" it back to what it's worth right now.

The final formula:

```
Stock Price = (Present Value of Future Cash Flows + Present Value of Terminal Value - Net Debt) / Shares Outstanding
```

---

## Step-by-Step: AAPL's DCF

### Step 1: Projected Revenue (How much AAPL will sell)

**Revenue** = total money a company earns from selling products and services, before any costs.

We use **analyst consensus estimates** — the average prediction from ~48 professional Wall Street analysts who cover AAPL — sourced from **FMP (Financial Modeling Prep)**, a financial data API.

| Year | Revenue (Analyst Consensus) |
|------|---------------------------|
| FY2026 | $463.4B |
| FY2027 | $494.3B |
| FY2028 | $523.0B |
| FY2029 | $567.1B |
| FY2030 | $581.7B |

For reference, AAPL's actual FY2025 revenue was **$416.2B**, so FY2026 represents ~11.4% growth.

If analyst estimates are unavailable, the model falls back to compounding the latest revenue by a single growth rate. But year-by-year analyst numbers are preferred because they capture the expected trajectory (growth slowing from 11% to 2.6% by year 5).

---

### Step 2: Projected FCF (How much cash AAPL actually keeps)

**FCF (Free Cash Flow)** = cash left over after a company pays all its operating expenses and invests in equipment/infrastructure. This is the "real" money available to shareholders.

```
FCF = Cash from Operations - Capital Expenditures
```

For AAPL FY2025: $111.5B (cash from ops) - $12.7B (capex) = **$98.8B FCF**

Rather than forecasting each cost separately, we use the **FCF Margin** — the percentage of revenue that becomes free cash flow:

```
FCF Margin = FCF / Revenue
```

We average AAPL's last 5 years to smooth out one-off fluctuations:

| Year | Revenue | FCF | FCF Margin |
|------|---------|-----|-----------|
| FY2021 | $365.8B | $93.0B | 25.4% |
| FY2022 | $394.3B | $111.4B | 28.3% |
| FY2023 | $383.3B | $99.6B | 26.0% |
| FY2024 | $391.0B | $108.8B | 27.8% |
| FY2025 | $416.2B | $98.8B | 23.7% |
| **5yr Average** | | | **26.2%** |

Now we multiply each year's analyst revenue by the 26.2% margin:

| Year | Revenue | x 26.2% Margin | = Projected FCF |
|------|---------|----------------|-----------------|
| FY2026 | $463.4B | x 0.262 | = $121.4B |
| FY2027 | $494.3B | x 0.262 | = $129.5B |
| FY2028 | $523.0B | x 0.262 | = $137.0B |
| FY2029 | $567.1B | x 0.262 | = $148.6B |
| FY2030 | $581.7B | x 0.262 | = $152.4B |

---

### Step 3: WACC — The Discount Rate

**WACC (Weighted Average Cost of Capital)** = the minimum return a company must earn to satisfy both its debt holders (banks/bondholders) and equity holders (shareholders). It's used as the "discount rate" — the rate at which we shrink future cash flows back to today's value.

WACC blends two costs:

```
WACC = (Equity Weight x Cost of Equity) + (Debt Weight x Cost of Debt after tax)
```

#### 3a. Risk-Free Rate (from FRED API)

The **Risk-Free Rate (Rf)** is the return on a "zero risk" investment — the US 10-year Treasury bond yield. Instead of hardcoding this, the model fetches it live from the **FRED API (Federal Reserve Economic Data)**, series `DGS10`. This ensures the discount rate reflects current interest rate conditions.

| Input | Value | Source |
|-------|-------|--------|
| **Rf** | ~4.3% (varies daily) | FRED API, 10-Year Treasury (DGS10) |

If the FRED API is unreachable, it falls back to a 4.3% default.

#### 3b. Levered Beta (company-specific risk via Hamada's Equation)

**Beta** measures how much a stock moves relative to the overall market. Beta 1.0 = moves with the market. Beta > 1.0 = more volatile/risky.

Instead of using a generic sector beta (e.g. 1.2 for all tech), the model computes a **company-specific levered beta** using **Hamada's Equation**. This adjusts for AAPL's actual debt level vs the sector average.

**Step 1 — Unlever the sector beta** to isolate the "pure business risk" (called the **asset beta**), removing the effect of debt from the sector average:

```
Beta_asset = Sector_Beta / (1 + (1 - Tax Rate) x Sector D/E)
           = 1.2 / (1 + 0.79 x 0.30)
           = 1.2 / 1.237 = 0.970
```

The sector D/E ratio (0.30 for Technology) represents how much debt the average tech company carries relative to equity.

**Step 2 — Relever using AAPL's specific debt-to-equity ratio** based on market values:

```
D/E (market) = Total Debt / Market Cap = $96.7B / $3,676B = 0.026

Beta_levered = 0.970 x (1 + 0.79 x 0.026)
             = 0.970 x 1.021 = 0.990
```

AAPL's levered beta (0.99) is **lower** than the sector beta (1.2) because AAPL carries much less debt relative to its market cap than the average tech company.

#### 3c. Cost of Equity (what shareholders demand)

Calculated using **CAPM (Capital Asset Pricing Model)**:

```
Cost of Equity = Risk-Free Rate + Beta x Equity Risk Premium
               = 4.3% + 0.99 x 5.0% = 9.25%
```

| Input | Value | What it is |
|-------|-------|-----------|
| **Rf (Risk-Free Rate)** | ~4.3% | 10-Year US Treasury yield |
| **Beta** | 0.99 | AAPL-specific levered beta (Hamada) |
| **ERP (Equity Risk Premium)** | 5.0% | Extra return investors demand for stocks over bonds (Damodaran) |

#### 3d. Cost of Debt (what lenders charge)

```
Cost of Debt (after tax) = Interest Rate x (1 - Tax Rate) = 5.0% x (1 - 0.21) = 3.95%
```

Companies deduct interest payments from taxes, so the true cost of debt is lower than the interest rate. The US corporate tax rate is 21%.

#### 3e. Capital Structure Weights (Market Value)

The weights reflect how much of the company is financed by debt vs equity, using **market values** (not book values from the balance sheet):

| | Market Value | Weight |
|---|---|---|
| **Equity (Market Cap)** | $3,676B | **97.4%** |
| **Debt** | $96.7B | **2.6%** |

> **Why market cap, not book equity?** AAPL's book equity is only $50.7B because Apple has spent hundreds of billions on share buybacks, which shrinks book equity. Using book values would make AAPL appear 66% debt-financed — wildly misleading. Market cap reflects what investors actually value the equity at.

#### 3f. Final WACC

```
WACC = 97.4% x 9.25% + 2.6% x 3.95%
     = 9.01% + 0.10%
     = 9.12%
```

The model clamps WACC to a 6%–15% range as a sanity check, but AAPL's 9.12% falls naturally in that range — no artificial floors needed.

---

### Step 4: Discount the Cash Flows

"Discounting" means converting future money to today's value. A dollar next year at 9.12% discount is worth $1/1.0912 = $0.916 today.

| Year | FCF | Discount Factor | Present Value |
|------|-----|----------------|---------------|
| FY2026 | $121.4B | 1/(1.0912)^1 = 0.916 | $111.3B |
| FY2027 | $129.5B | 1/(1.0912)^2 = 0.840 | $108.8B |
| FY2028 | $137.0B | 1/(1.0912)^3 = 0.770 | $105.5B |
| FY2029 | $148.6B | 1/(1.0912)^4 = 0.706 | $104.9B |
| FY2030 | $152.4B | 1/(1.0912)^5 = 0.647 | $98.6B |
| **Total PV of FCFs** | | | **$529.1B** |

---

### Step 5: Terminal Value (Everything after Year 5)

We can't forecast individual years forever, so we assume that after year 5, FCF grows at a steady rate **forever**. This perpetual stream of cash is called the **Terminal Value**, calculated using the **GGM (Gordon Growth Model)**:

```
Terminal Value = FCF_Year5 x (1 + g) / (WACC - g)
```

| Input | Value | What it is |
|-------|-------|-----------|
| **FCF_Year5** | $152.4B | Last projected free cash flow |
| **g (Terminal Growth Rate)** | 3.0% | Assumed perpetual annual growth rate (base case) |
| **WACC** | 9.12% | Discount rate |

```
TV = $152.4B x 1.03 / (0.0912 - 0.03) = $156.9B / 0.0612 = $2,564B
PV of TV = $2,564B / (1.0912)^5 = $1,659B
```

The denominator `(WACC - g)` is very sensitive — small changes in WACC or g produce large swings in terminal value. This is why WACC accuracy matters so much.

#### Terminal Value Warning

The model flags a warning when the terminal value exceeds **75% of total enterprise value**. For AAPL:

```
TV% of EV = $1,659B / ($529B + $1,659B) = 75.8%
```

> **Warning:** Terminal value accounts for ~76% of enterprise value. This means the valuation depends heavily on the assumption that AAPL grows at 3% perpetually. The model automatically surfaces this as a risk indicator.

---

### Step 6: Enterprise Value to Per-Share Price

**EV (Enterprise Value)** = total value of the business (debt + equity combined):
```
EV = PV of FCFs + PV of Terminal Value = $529B + $1,659B = $2,188B
```

**Net Debt** = total debt minus cash on hand. This is subtracted because if you "bought" the whole company, you'd inherit its debt but also its cash:
```
Net Debt = Total Debt - Total Cash = $96.7B - $29.9B = $66.7B
```

**Equity Value** = what belongs to shareholders:
```
Equity Value = EV - Net Debt = $2,188B - $66.7B = $2,121B
```

**Shares Outstanding** = 15.00B (total shares of AAPL stock that exist)

```
Price Per Share = $2,121B / 15.00B = ~$141
```

---

## New Feature: Margin of Safety

The model computes how the base-case intrinsic value compares to the current market price:

| | Value |
|---|---|
| **Current Market Price** | $250.12 |
| **Base-Case Intrinsic** | ~$141 |
| **Upside/Downside** | **-43.6%** |
| **Verdict** | **Overvalued** |

Thresholds: >15% upside = "undervalued", within ±15% = "fairly valued", >15% downside = "overvalued".

The model also provides **bear** and **bull** scenarios with ±1.5pp adjustments on growth, margin, and WACC to give a range.

---

## New Feature: Reverse DCF

Instead of asking "what's the stock worth?", the Reverse DCF asks: **"What growth rate is the market pricing in?"**

It takes the current market price ($250.12) and back-solves for the revenue growth rate that would produce a DCF value equal to that price — using the same FCF margin, WACC, and terminal growth as the base case.

For AAPL, the market-implied revenue growth rate works out to roughly **17-18% annually for 5 years** — significantly above analyst consensus of ~7% average. This suggests the market is either pricing in faster growth than analysts expect, or investors are using a lower discount rate.

---

## Glossary

| Abbreviation | Full Name | What It Means |
|---|---|---|
| **DCF** | Discounted Cash Flow | Valuation method based on future cash generation |
| **FCF** | Free Cash Flow | Cash from operations minus capital expenditures |
| **WACC** | Weighted Average Cost of Capital | Blended cost of debt + equity financing; used as the discount rate |
| **CAPM** | Capital Asset Pricing Model | Formula to compute cost of equity: Rf + Beta × ERP |
| **ERP** | Equity Risk Premium | Extra return demanded for stocks over risk-free bonds |
| **Rf** | Risk-Free Rate | Yield on 10-Year US Treasury bond (from FRED API) |
| **GGM** | Gordon Growth Model | Perpetuity formula for terminal value: FCF × (1+g) / (WACC-g) |
| **EV** | Enterprise Value | Total business value = PV of cash flows + PV of terminal value |
| **TV** | Terminal Value | Value of all cash flows beyond the projection period (year 5+) |
| **Beta** | Beta Coefficient | Stock volatility relative to the market (1.0 = same as market) |
| **D/E** | Debt-to-Equity Ratio | Total debt divided by equity value (market cap) |
| **FRED** | Federal Reserve Economic Data | Free API from the St. Louis Fed for economic data series |
| **FMP** | Financial Modeling Prep | Financial data API used for analyst estimates and financials |
