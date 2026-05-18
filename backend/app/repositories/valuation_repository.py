from sqlalchemy.orm import Session

from app.db.financial import Valuation

MODEL_VERSION = "dcf_pe_blend_v1"


def upsert(db: Session, ticker: str, valuation_date: str, result_dict: dict, model_version: str = MODEL_VERSION) -> None:
    ticker = ticker.upper()
    row = db.query(Valuation).filter(
        Valuation.ticker == ticker,
        Valuation.valuation_date == valuation_date,
        Valuation.model_version == model_version,
    ).first()

    bear = result_dict.get("bear", {})
    base = result_dict.get("base", {})
    bull = result_dict.get("bull", {})
    margin = result_dict.get("margin_of_safety") or {}

    values = {
        "current_price": result_dict.get("current_price"),
        "bear_blended": bear.get("blended_per_share"),
        "base_blended": base.get("blended_per_share"),
        "bull_blended": bull.get("blended_per_share"),
        "bear_dcf": (bear.get("dcf") or {}).get("per_share_value"),
        "base_dcf": (base.get("dcf") or {}).get("per_share_value"),
        "bull_dcf": (bull.get("dcf") or {}).get("per_share_value"),
        "bear_forward_pe": (bear.get("multiples") or {}).get("forward_pe_value"),
        "base_forward_pe": (base.get("multiples") or {}).get("forward_pe_value"),
        "bull_forward_pe": (bull.get("multiples") or {}).get("forward_pe_value"),
        "base_pe_multiple": (base.get("multiples") or {}).get("pe_multiple"),
        "forward_eps": (base.get("multiples") or {}).get("forward_eps"),
        "implied_upside_pct": margin.get("upside_pct"),
        "verdict": margin.get("verdict"),
        "assumptions_json": {
            "bear": (bear.get("dcf") or {}).get("assumptions"),
            "base": (base.get("dcf") or {}).get("assumptions"),
            "bull": (bull.get("dcf") or {}).get("assumptions"),
        },
        "dcf_json": {"bear": bear.get("dcf"), "base": base.get("dcf"), "bull": bull.get("dcf")},
        "multiples_json": {
            "bear": bear.get("multiples"),
            "base": base.get("multiples"),
            "bull": bull.get("multiples"),
        },
        "peer_comparison_json": result_dict.get("peer_comparison"),
        "reverse_dcf_json": result_dict.get("reverse_dcf"),
        "margin_of_safety_json": result_dict.get("margin_of_safety"),
        "terminal_value_warning": result_dict.get("terminal_value_warning"),
        "signal_adjustments_json": result_dict.get("signal_adjustments"),
        "data_quality_json": result_dict.get("data_quality"),
        "input_refs_json": {},
        "result_json": result_dict,
    }

    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        db.add(Valuation(
            ticker=ticker,
            valuation_date=valuation_date,
            model_version=model_version,
            **values,
        ))
    db.commit()
