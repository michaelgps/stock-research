"""
SEC EDGAR data source.
Primary source for official reported financial data.
Uses the free EDGAR API (data.sec.gov).
"""

import re
import html
import logging

import httpx
from app.data_structure.financial import CompanyInfo, FinancialStatementData, TextMaterial

logger = logging.getLogger(__name__)

# SEC EDGAR requires a User-Agent header with contact info
EDGAR_HEADERS = {
    "User-Agent": "StockResearchApp/1.0 (contact@example.com)",
    "Accept": "application/json",
}

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


async def _get_cik_for_ticker(ticker: str) -> str | None:
    """Look up the CIK number for a given ticker symbol."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(COMPANY_TICKERS_URL, headers=EDGAR_HEADERS)
        resp.raise_for_status()
        data = resp.json()

    ticker_upper = ticker.upper()
    for entry in data.values():
        if entry.get("ticker", "").upper() == ticker_upper:
            # CIK must be zero-padded to 10 digits
            return str(entry["cik_str"]).zfill(10)

    return None


async def get_company_info(ticker: str) -> CompanyInfo | None:
    """Fetch basic company info from SEC EDGAR submissions endpoint."""
    cik = await _get_cik_for_ticker(ticker)
    if not cik:
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            SUBMISSIONS_URL.format(cik=cik), headers=EDGAR_HEADERS
        )
        resp.raise_for_status()
        data = resp.json()

    return CompanyInfo(
        ticker=ticker.upper(),
        name=data.get("name"),
        sector=data.get("sic"),  # SIC code, not sector name
        industry=data.get("sicDescription"),
    )


async def get_financial_statements(
    ticker: str,
) -> list[FinancialStatementData]:
    """
    Fetch financial data from SEC EDGAR XBRL company facts.
    Returns annual statements derived from reported XBRL facts.
    """
    cik = await _get_cik_for_ticker(ticker)
    if not cik:
        return []

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            COMPANY_FACTS_URL.format(cik=cik), headers=EDGAR_HEADERS
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        facts = resp.json()

    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    # Map XBRL concept names to our schema fields
    concept_map = {
        "Revenues": "revenue",
        "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
        "CostOfRevenue": "cost_of_revenue",
        "CostOfGoodsAndServicesSold": "cost_of_revenue",
        "GrossProfit": "gross_profit",
        "OperatingIncomeLoss": "operating_income",
        "NetIncomeLoss": "net_income",
        "Assets": "total_assets",
        "StockholdersEquity": "total_equity",
        "LongTermDebt": "total_debt",
        "CashAndCashEquivalentsAtCarryingValue": "total_cash",
        "NetCashProvidedByUsedInOperatingActivities": "cash_from_operations",
        "PaymentsToAcquirePropertyPlantAndEquipment": "capital_expenditures",
        "WeightedAverageNumberOfDilutedSharesOutstanding": "diluted_shares",
    }

    # Collect annual (10-K) data points grouped by fiscal year.
    # XBRL 10-K filings contain both full-year and quarterly sub-period entries.
    # We filter to full-year entries only: those spanning > 300 days (start to end).
    # Balance sheet items (Assets, Equity, etc.) have no start date — they are
    # point-in-time, so we keep the latest end date per fiscal year for those.
    annual_data: dict[int, dict] = {}  # keyed by fiscal year (int)

    # Balance sheet concepts (point-in-time, no start date)
    balance_sheet_fields = {"total_assets", "total_equity", "total_debt", "total_cash"}

    for concept_name, field_name in concept_map.items():
        concept = us_gaap.get(concept_name)
        if not concept:
            continue

        units = concept.get("units", {})
        values = units.get("USD", units.get("shares", []))

        for entry in values:
            form = entry.get("form", "")
            if form != "10-K":
                continue

            end_date = entry.get("end", "")
            fy = entry.get("fy")
            if not end_date or not fy:
                continue

            start_date = entry.get("start", "")

            if field_name in balance_sheet_fields:
                # Point-in-time: keep the entry with the latest end date per FY
                if fy not in annual_data:
                    annual_data[fy] = {"date": end_date, "_fy": fy}
                # Update date if this end_date is later
                if end_date > annual_data[fy]["date"]:
                    annual_data[fy]["date"] = end_date
                if field_name not in annual_data[fy]:
                    annual_data[fy][field_name] = entry.get("val")
            else:
                # Flow items (income/cash flow): must span > 300 days
                if not start_date:
                    continue
                from datetime import date as dt_date
                try:
                    d_start = dt_date.fromisoformat(start_date)
                    d_end = dt_date.fromisoformat(end_date)
                    days = (d_end - d_start).days
                except ValueError:
                    continue
                if days < 300:
                    continue

                if fy not in annual_data:
                    annual_data[fy] = {"date": end_date, "_fy": fy}
                # 10-K filings include prior-year comparatives tagged with the
                # same fy.  Keep the entry with the latest end date — that is
                # the actual current-year figure.
                existing_end = annual_data[fy].get(f"_end_{field_name}", "")
                if field_name not in annual_data[fy] or end_date > existing_end:
                    annual_data[fy][field_name] = entry.get("val")
                    annual_data[fy][f"_end_{field_name}"] = end_date

    # Convert to schema objects
    statements = []
    for fy, data in sorted(annual_data.items(), reverse=True):
        year = fy
        date_str = data["date"]

        # Compute free cash flow if we have the components
        cfo = data.get("cash_from_operations")
        capex = data.get("capital_expenditures")
        fcf = None
        if cfo is not None and capex is not None:
            fcf = cfo - capex

        statements.append(
            FinancialStatementData(
                period="annual",
                fiscal_year=year,
                date=date_str,
                revenue=data.get("revenue"),
                cost_of_revenue=data.get("cost_of_revenue"),
                gross_profit=data.get("gross_profit"),
                operating_income=data.get("operating_income"),
                net_income=data.get("net_income"),
                cash_from_operations=cfo,
                capital_expenditures=capex,
                free_cash_flow=fcf,
                total_cash=data.get("total_cash"),
                total_debt=data.get("total_debt"),
                total_assets=data.get("total_assets"),
                total_equity=data.get("total_equity"),
                diluted_shares=data.get("diluted_shares"),
                source="sec_edgar",
            )
        )

    return statements


async def _get_latest_10k_url(cik: str) -> tuple[str, str] | None:
    """Find the URL and filing date of the most recent 10-K filing."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            SUBMISSIONS_URL.format(cik=cik), headers=EDGAR_HEADERS
        )
        resp.raise_for_status()
        data = resp.json()

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])
    filing_dates = filings.get("filingDate", [])

    for i, form in enumerate(forms):
        if form == "10-K":
            accession = accessions[i].replace("-", "")
            cik_num = cik.lstrip("0")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession}/{primary_docs[i]}"
            return url, filing_dates[i]

    return None


def _extract_section(full_text: str, section_name: str) -> str | None:
    """
    Extract a named section from 10-K text.
    Looks for the section heading and extracts text until the next major section.
    """
    # Patterns for section boundaries
    if section_name == "mda":
        start_patterns = [
            r"Management.s Discussion and Analysis of Financial Condition",
            r"MANAGEMENT.S DISCUSSION AND ANALYSIS",
        ]
        end_patterns = [
            r"Quantitative and Qualitative Disclosures?\s*About\s*Market\s*Risk",
            r"QUANTITATIVE AND QUALITATIVE",
            r"Item\s*7A[\.\s]",
            r"ITEM\s*7A[\.\s]",
        ]
    elif section_name == "risk_factors":
        start_patterns = [
            r"Item\s*1A[\.\s]*\s*Risk\s*Factors",
            r"ITEM\s*1A[\.\s]*\s*RISK\s*FACTORS",
        ]
        end_patterns = [
            r"Item\s*1B[\.\s]",
            r"ITEM\s*1B[\.\s]",
            r"Item\s*1C[\.\s]",
            r"ITEM\s*1C[\.\s]",
            r"Unresolved\s*Staff\s*Comments",
            r"UNRESOLVED\s*STAFF\s*COMMENTS",
            r"Item\s*2[\.\s]",
            r"ITEM\s*2[\.\s]",
        ]
    else:
        return None

    # Find the last occurrence of the start pattern (skip table of contents)
    start_pos = -1
    for pattern in start_patterns:
        for match in re.finditer(pattern, full_text):
            start_pos = match.start()  # Keep updating — last match is the real one

    if start_pos == -1:
        return None

    section_text = full_text[start_pos:]

    # Find the end boundary (skip first 1000 chars to avoid matching within heading area)
    end_pos = len(section_text)
    for pattern in end_patterns:
        match = re.search(pattern, section_text[1000:])
        if match and (1000 + match.start()) < end_pos:
            end_pos = 1000 + match.start()

    section_text = section_text[:end_pos].strip()

    # Truncate if too long (LLM context limits)
    max_chars = 30000
    if len(section_text) > max_chars:
        section_text = section_text[:max_chars] + "\n\n[... truncated for length ...]"

    return section_text


async def get_10k_text_materials(ticker: str) -> list[TextMaterial]:
    """
    Download the latest 10-K filing and extract MD&A and Risk Factors sections.
    Returns TextMaterial objects for each extracted section.
    """
    cik = await _get_cik_for_ticker(ticker)
    if not cik:
        return []

    filing_info = await _get_latest_10k_url(cik)
    if not filing_info:
        return []

    filing_url, filing_date = filing_info
    fiscal_year = int(filing_date[:4])

    # Download the 10-K HTML
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(filing_url, headers=EDGAR_HEADERS)
            if resp.status_code != 200:
                logger.warning(f"Failed to download 10-K for {ticker}: HTTP {resp.status_code}")
                return []
            raw_html = resp.text
    except Exception as e:
        logger.warning(f"Failed to download 10-K for {ticker}: {e}")
        return []

    # Convert HTML to plain text
    text = re.sub(r"<[^>]+>", "\n", raw_html)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    # Clean up lines
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    full_text = "\n".join(lines)

    materials = []

    # Extract MD&A
    mda_text = _extract_section(full_text, "mda")
    if mda_text and len(mda_text) > 500:
        materials.append(
            TextMaterial(
                ticker=ticker.upper(),
                source_type="mda",
                content=mda_text,
                filing_date=filing_date,
                fiscal_year=fiscal_year,
            )
        )

    # Extract Risk Factors
    risk_text = _extract_section(full_text, "risk_factors")
    if risk_text and len(risk_text) > 500:
        materials.append(
            TextMaterial(
                ticker=ticker.upper(),
                source_type="risk_factors",
                content=risk_text,
                filing_date=filing_date,
                fiscal_year=fiscal_year,
            )
        )

    return materials
