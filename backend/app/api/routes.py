from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.data_structure.financial import (
    FinancialDataResponse,
    TickerRequest,
    TextSubmitRequest,
    TextMaterial,
)
from app.data_structure.signals import ExtractionResult
from app.data_structure.valuation import ValuationResponse
from app.logic.data_aggregator import collect_financial_data
from app.logic.llm_extraction.extractor import extract_signals
from app.logic.valuation import run_valuation
from app.db.financial_store import save_user_text, get_user_texts, clear_user_texts, save_valuation_result
from app.db.signal_store import load_cached_signals, save_signals_to_cache

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.post("/api/financial-data", response_model=FinancialDataResponse)
async def get_financial_data(request: TickerRequest, db: Session = Depends(get_db)):
    """Collect and return all financial data for a given ticker."""
    ticker = request.ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    try:
        result = await collect_financial_data(ticker, db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {str(e)}")


@router.get("/api/financial-data/{ticker}", response_model=FinancialDataResponse)
async def get_financial_data_by_ticker(ticker: str, db: Session = Depends(get_db)):
    """GET convenience endpoint for fetching financial data."""
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    try:
        result = await collect_financial_data(ticker, db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {str(e)}")


@router.post("/api/text-materials")
async def submit_text_material(request: TextSubmitRequest, db: Session = Depends(get_db)):
    """Submit text material (e.g., pasted earnings transcript) for a ticker."""
    ticker = request.ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    if len(request.content) > 200000:
        raise HTTPException(status_code=400, detail="Content too large (max 200K characters)")

    allowed_types = {"earnings_transcript", "manual"}
    if request.source_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of: {', '.join(allowed_types)}",
        )

    material = TextMaterial(
        ticker=ticker,
        source_type=request.source_type,
        content=request.content.strip(),
    )
    save_user_text(db, ticker, material)

    return {"status": "ok", "ticker": ticker, "source_type": request.source_type, "chars": len(material.content)}


@router.get("/api/text-materials/{ticker}")
async def get_text_materials(ticker: str, db: Session = Depends(get_db)):
    """Get all user-submitted text materials for a ticker."""
    ticker = ticker.strip().upper()
    materials = get_user_texts(db, ticker)
    return {"ticker": ticker, "count": len(materials), "materials": materials}


@router.delete("/api/text-materials/{ticker}")
async def delete_text_materials(ticker: str, db: Session = Depends(get_db)):
    """Clear all user-submitted text materials for a ticker."""
    ticker = ticker.strip().upper()
    clear_user_texts(db, ticker)
    return {"status": "ok", "ticker": ticker}


@router.post("/api/extract-signals/{ticker}", response_model=ExtractionResult)
async def run_signal_extraction(ticker: str, db: Session = Depends(get_db)):
    """
    Run LLM extraction on text materials for a ticker.
    Requires financial data to be fetched first (Phase 1).
    Results are cached in PostgreSQL.
    """
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    # Check signal cache first
    cached = load_cached_signals(db, ticker)
    if cached:
        return cached

    # Get financial data (from cache if available)
    try:
        financial_data = await collect_financial_data(ticker, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {str(e)}")

    if not financial_data.text_materials:
        raise HTTPException(status_code=404, detail=f"No text materials found for {ticker}. Fetch financial data first.")

    # Run extraction
    try:
        result = extract_signals(ticker, financial_data.text_materials)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM extraction failed: {str(e)}")

    # Save to cache
    save_signals_to_cache(db, result)

    return result


@router.get("/api/extract-signals/{ticker}", response_model=ExtractionResult)
async def get_signal_extraction(ticker: str, db: Session = Depends(get_db)):
    """Get cached signal extraction results for a ticker."""
    ticker = ticker.strip().upper()
    cached = load_cached_signals(db, ticker)
    if not cached:
        raise HTTPException(status_code=404, detail=f"No extraction results for {ticker}. Run POST /api/extract-signals/{ticker} first.")
    return cached


@router.post("/api/valuation/{ticker}", response_model=ValuationResponse)
async def run_ticker_valuation(ticker: str, db: Session = Depends(get_db)):
    """
    Run full valuation (DCF + multiples) for a ticker.
    Requires Phase 1 data. Optionally uses Phase 2 signals if available.
    """
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    # Get financial data (Phase 1)
    try:
        financial_data = await collect_financial_data(ticker, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {str(e)}")

    # Get signals if available (Phase 2) — optional, valuation works without them
    signals = load_cached_signals(db, ticker)

    # Run valuation (Phase 3)
    try:
        result = await run_valuation(financial_data, signals, db=db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Valuation failed: {str(e)}")

    # Persist valuation result to DB
    try:
        save_valuation_result(db, ticker, result.model_dump())
    except Exception:
        pass  # non-critical, don't fail the response

    return result


@router.get("/api/valuation/{ticker}", response_model=ValuationResponse)
async def get_ticker_valuation(ticker: str, db: Session = Depends(get_db)):
    """GET convenience endpoint — same as POST."""
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    try:
        financial_data = await collect_financial_data(ticker, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {str(e)}")

    signals = load_cached_signals(db, ticker)

    try:
        result = await run_valuation(financial_data, signals, db=db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Valuation failed: {str(e)}")

    try:
        save_valuation_result(db, ticker, result.model_dump())
    except Exception:
        pass

    return result
