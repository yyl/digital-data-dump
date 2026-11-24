"""Read monthly sleep and readiness scores for reporting and exports."""

from .database import OuraDatabase


SCORE_FILTER = "source_table IN ('daily_sleep', 'daily_readiness') AND metric = 'score'"


def report_months(db: OuraDatabase) -> list[str]:
    return [row["year_month"] for row in db.fetch_rows(
        f"SELECT DISTINCT year_month FROM analysis WHERE {SCORE_FILTER}"
    ) if row["year_month"]]


def monthly_scores(db: OuraDatabase, year_month: str | None = None) -> list[dict]:
    query = f"""
        SELECT year_month, source_table, median_value, avg_value
        FROM analysis
        WHERE {SCORE_FILTER}
    """
    params = ()
    if year_month is not None:
        query += " AND year_month = ?"
        params = (year_month,)
    query += " ORDER BY year_month, source_table"

    monthly = {}
    for row in db.fetch_rows(query, params):
        month = row["year_month"]
        score = "sleep" if row["source_table"] == "daily_sleep" else "readiness"
        summary = monthly.setdefault(month, {"year_month": month})
        summary[f"median_{score}_score"] = row["median_value"]
        average = row["avg_value"]
        summary[f"avg_{score}_score"] = round(average, 2) if average is not None else None
    return list(monthly.values())
