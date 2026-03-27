"""
Yahoo Finance data source via yfinance library.
Used as a cross-validation source for analyst consensus EPS estimates.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class YFinanceEstimate:
    """Consensus EPS estimate from Yahoo Finance."""
    period: str  # "0y" (current FY), "+1y" (next FY)
    avg_eps: float | None
    low_eps: float | None
    high_eps: float | None
    year_ago_eps: float | None
    growth: float | None  # e.g. 0.14 = 14%
    num_analysts: int | None


def get_yfinance_estimates(ticker: str) -> list[YFinanceEstimate]:
    """
    Fetch consensus EPS estimates from Yahoo Finance.
    Returns estimates for current quarter, next quarter, current FY, next FY.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        ee = t.earnings_estimate
        if ee is None or ee.empty:
            return []

        results = []
        for period in ee.index:
            row = ee.loc[period]
            results.append(YFinanceEstimate(
                period=str(period),
                avg_eps=_safe_float(row.get("avg")),
                low_eps=_safe_float(row.get("low")),
                high_eps=_safe_float(row.get("high")),
                year_ago_eps=_safe_float(row.get("yearAgoEps")),
                growth=_safe_float(row.get("growth")),
                num_analysts=_safe_int(row.get("numberOfAnalysts")),
            ))
        return results
    except ImportError:
        logger.warning("yfinance not installed — skipping Yahoo Finance estimates")
        return []
    except Exception as e:
        logger.warning("yfinance error for %s: %s", ticker, e)
        return []


def get_yfinance_eps_for_validation(ticker: str) -> dict:
    """
    Get current-FY and next-FY EPS from Yahoo Finance for cross-validation.

    Returns dict with:
      - current_fy_eps: consensus EPS for current fiscal year
      - next_fy_eps: consensus EPS for next fiscal year
      - current_fy_growth: YoY growth for current FY
      - next_fy_growth: YoY growth for next FY
      - num_analysts: number of analysts covering
    """
    estimates = get_yfinance_estimates(ticker)
    result = {}

    for est in estimates:
        if est.period == "0y":
            result["current_fy_eps"] = est.avg_eps
            result["current_fy_growth"] = est.growth
            result["current_fy_year_ago_eps"] = est.year_ago_eps
            result["num_analysts"] = est.num_analysts
        elif est.period == "+1y":
            result["next_fy_eps"] = est.avg_eps
            result["next_fy_growth"] = est.growth

    return result


def cross_validate_eps(
    fmp_next_fy_eps: float | None,
    ticker: str,
    threshold: float = 0.15,
) -> dict:
    """
    Cross-validate FMP's next-FY EPS estimate against Yahoo Finance.

    Returns:
      - yf_eps: Yahoo Finance next-FY EPS
      - fmp_eps: FMP next-FY EPS
      - divergence: absolute percentage difference
      - warning: True if divergence > threshold (default 15%)
      - source_used: which source to prefer ("fmp", "yfinance", or "average")
    """
    yf_data = get_yfinance_eps_for_validation(ticker)
    yf_eps = yf_data.get("current_fy_eps")  # Yahoo "0y" = current FY ≈ FMP's next FY

    result = {
        "yf_current_fy_eps": yf_eps,
        "yf_next_fy_eps": yf_data.get("next_fy_eps"),
        "yf_current_fy_growth": yf_data.get("current_fy_growth"),
        "yf_next_fy_growth": yf_data.get("next_fy_growth"),
        "yf_num_analysts": yf_data.get("num_analysts"),
        "fmp_eps": fmp_next_fy_eps,
        "divergence": None,
        "warning": False,
    }

    if yf_eps and fmp_next_fy_eps and yf_eps > 0 and fmp_next_fy_eps > 0:
        divergence = abs(yf_eps - fmp_next_fy_eps) / fmp_next_fy_eps
        result["divergence"] = round(divergence, 3)
        result["warning"] = divergence > threshold

    return result


def get_daily_prices(ticker: str, period: str = "5y") -> list[dict]:
    """
    Fetch daily OHLCV prices from Yahoo Finance.
    Returns list of dicts with keys: date, open, high, low, close, volume.
    Same format as FMP's get_daily_prices for drop-in replacement.
    """
    try:
        import yfinance as yf
        df = yf.download(ticker.upper(), period=period, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return []

        # Handle multi-level columns from yfinance (ticker as second level)
        if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
            df = df.droplevel(level=1, axis=1)

        results = []
        for idx, row in df.iterrows():
            results.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return results
    except ImportError:
        logger.warning("yfinance not installed — cannot fetch daily prices")
        return []
    except Exception as e:
        logger.warning("yfinance daily prices error for %s: %s", ticker, e)
        return []


def _safe_float(val) -> float | None:
    """Safely convert to float, handling NaN and None."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return round(f, 5)
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    """Safely convert to int."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
