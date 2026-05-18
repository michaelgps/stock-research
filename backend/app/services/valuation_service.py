from app.repositories import data_pull_log_repository, valuation_repository


def save_valuation_result(db, ticker: str, result_dict: dict) -> None:
    valuation_repository.upsert(
        db,
        ticker=ticker,
        valuation_date=data_pull_log_repository.today_str(),
        result_dict=result_dict,
    )
