"""
Alpha Vantage data source.

Used as an optional cross-check for annual EPS estimates. These values are not
used as primary valuation inputs unless the valuation engine explicitly chooses
to do so later.
"""

import logging

import httpx

from app.config.config import get_settings

logger = logging.getLogger(__name__)

ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"


def _is_configured() -> bool:
    key = get_settings().alpha_vantage_api_key
    return bool(key) and key != "your_alpha_vantage_api_key_here"


async def get_annual_eps_estimates(ticker: str, limit: int = 3) -> list[dict]:
    """Fetch annual EPS estimates from Alpha Vantage EARNINGS_ESTIMATES."""
    if not _is_configured():
        return []

    settings = get_settings()
    params = {
        "function": "EARNINGS_ESTIMATES",
        "symbol": ticker.upper(),
        "apikey": settings.alpha_vantage_api_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(ALPHA_VANTAGE_BASE, params=params)
        if resp.status_code != 200:
            logger.warning(
                "Alpha Vantage EARNINGS_ESTIMATES failed with status %s: %s",
                resp.status_code,
                resp.text[:300],
            )
            return []
        payload = resp.json()

    rows = payload.get("annualEarningsEstimates") or payload.get("annualReports") or []
    estimates = []
    for row in rows:
        fiscal_year = _extract_fiscal_year(row)
        eps = _safe_float(
            row.get("consensusEPSForecast")
            or row.get("estimatedEPSAvg")
            or row.get("epsEstimateAverage")
            or row.get("epsAvg")
        )
        if fiscal_year is None or eps is None or eps <= 0:
            continue
        estimates.append({
            "period": str(fiscal_year),
            "eps_estimate": eps,
            "source": "alpha_vantage",
            "raw": row,
        })

    estimates.sort(key=lambda item: int(item["period"]))
    return estimates[:limit]


def _extract_fiscal_year(row: dict) -> int | None:
    for key in ("fiscalDateEnding", "date"):
        value = row.get(key)
        if value and len(str(value)) >= 4 and str(value)[:4].isdigit():
            return int(str(value)[:4])
    value = row.get("fiscalYear") or row.get("year")
    if value and str(value).isdigit():
        return int(value)
    return None


def _safe_float(value) -> float | None:
    if value in (None, "", "None", "null"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return round(result, 5)
