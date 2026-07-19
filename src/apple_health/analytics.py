"""Analytics module for Apple Health workout data."""

from typing import Optional

from .database import AppleHealthDatabase
from .models import CREATE_ANALYSIS_TABLE, ANALYSIS_INDEXES
from ..time_utils import utc_now_iso


class AppleHealthAnalytics:
    """Analyzes Apple Health workouts by month."""

    def __init__(self, db: Optional[AppleHealthDatabase] = None):
        """Initialize analytics."""
        self.db = db or AppleHealthDatabase()

    def _ensure_analysis_table(self) -> None:
        """Create the analysis table, recreating stale derived schema if needed."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(analysis)")
            columns = {row[1] for row in cursor.fetchall()}
            expected_columns = {
                "year_month",
                "year",
                "month",
                "workouts",
                "total_duration_seconds",
                "total_calories",
                "updated_at",
            }
            if columns and columns != expected_columns:
                cursor.execute("DROP TABLE analysis")
            conn.execute(CREATE_ANALYSIS_TABLE)
            for index_sql in ANALYSIS_INDEXES:
                conn.execute(index_sql)

    def analyze_workouts(self) -> int:
        """Roll up Apple Health workouts into monthly analysis rows."""
        self._ensure_analysis_table()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    strftime('%Y', started_at) AS year,
                    strftime('%m', started_at) AS month,
                    COUNT(*) AS workouts,
                    CAST(ROUND(SUM(COALESCE(duration_seconds, 0))) AS INTEGER) AS total_duration_seconds,
                    ROUND(COALESCE(SUM(total_calories), 0), 2) AS total_calories
                FROM workouts
                WHERE started_at IS NOT NULL
                AND activity_type != 'walk'
                GROUP BY year, month
                """
            )
            rows = cursor.fetchall()
            updated_at = utc_now_iso()

            for row in rows:
                if not row["year"] or not row["month"]:
                    continue
                year_month = f"{row['year']}-{row['month']}"
                cursor.execute(
                    """
                    INSERT INTO analysis (year_month, year, month, workouts, total_duration_seconds, total_calories, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(year_month) DO UPDATE SET
                        workouts = excluded.workouts,
                        total_duration_seconds = excluded.total_duration_seconds,
                        total_calories = excluded.total_calories,
                        updated_at = excluded.updated_at
                    """,
                    (
                        year_month,
                        row["year"],
                        row["month"],
                        row["workouts"],
                        row["total_duration_seconds"] or 0,
                        row["total_calories"] or 0,
                        updated_at,
                    ),
                )

        return len(rows)
