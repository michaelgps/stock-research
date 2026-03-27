"""
Finnhub data source.
Used for analyst estimates, recommendation trends, and company metadata.
Requires API key from finnhub.io.
"""

import httpx
from app.config.config import get_settings
from app.data_structure.financial import CompanyInfo, AnalystEstimateData, EarningsSurpriseData

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _is_configured() -> bool:
    key = get_settings().finnhub_api_key
    return bool(key) and key != "your_finnhub_api_key_here"


async def _get(endpoint: str, params: dict | None = None) -> dict | list | None:
    if not _is_configured():
        return None

    settings = get_settings()
    url = f"{FINNHUB_BASE}/{endpoint}"
    query = {"token": settings.finnhub_api_key}
    if params:
        query.update(params)

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=query)
        if resp.status_code != 200:
            return None
        return resp.json()


async def get_company_info(ticker: str) -> CompanyInfo | None:
    data = await _get("stock/profile2", {"symbol": ticker.upper()})
    if not data or not data.get("name"):
        return None

    return CompanyInfo(
        ticker=ticker.upper(),
        name=data.get("name"),
        sector=data.get("finnhubIndustry"),
        industry=data.get("finnhubIndustry"),
        market_cap=data.get("marketCapitalization"),
        shares_outstanding=data.get("shareOutstanding"),
    )


async def get_analyst_estimates(ticker: str) -> list[AnalystEstimateData]:
    """Fetch analyst recommendation trends from Finnhub."""
    data = await _get("stock/recommendation", {"symbol": ticker.upper()})
    if not data or not isinstance(data, list):
        return []

    estimates = []
    for entry in data[:4]:  # Last 4 periods
        estimates.append(
            AnalystEstimateData(
                period=entry.get("period", ""),
                buy_count=entry.get("buy", 0) + entry.get("strongBuy", 0),
                hold_count=entry.get("hold", 0),
                sell_count=entry.get("sell", 0) + entry.get("strongSell", 0),
                source="finnhub",
            )
        )

    # Also try to get price target
    target_data = await _get("stock/price-target", {"symbol": ticker.upper()})
    if target_data and estimates:
        estimates[0].target_price = target_data.get("targetMedian")

    return estimates


async def get_earnings_surprises(ticker: str) -> list[EarningsSurpriseData]:
    """Fetch quarterly earnings actual vs estimate from Finnhub."""
    data = await _get("stock/earnings", {"symbol": ticker.upper()})
    if not data or not isinstance(data, list):
        return []

    surprises = []
    for entry in data[:12]:  # Last 12 quarters
        actual = entry.get("actual")
        estimated = entry.get("estimate")
        surprise = entry.get("surprise")
        surprise_pct = entry.get("surprisePercent")

        surprises.append(
            EarningsSurpriseData(
                date=entry.get("period", ""),
                actual_eps=actual,
                estimated_eps=estimated,
                surprise=surprise,
                surprise_percent=surprise_pct,
                source="finnhub",
            )
        )

    return surprises
