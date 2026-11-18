"""Analytics module for Apple Health workout data."""

import sqlite3
from typing import Optional

from .database import AppleHealthDatabase
from .models import ACTIVITY_ROLLUP, ANALYSIS_INDEXES, CREATE_ACTIVITY_ANALYSIS_TABLE, CREATE_ANALYSIS_TABLE
from ..time_utils import utc_now_iso


class AppleHealthAnalytics:
    """Analyzes Apple Health workouts by month."""

    def __init__(self, db: Optional[AppleHealthDatabase] = None):
        """Initialize analytics."""
        self.db = db or AppleHealthDatabase()

    def _ensure_analysis_tables(self, conn: sqlite3.Connection) -> None:
        """Create derived tables and replace a stale monthly schema."""
        columns = {row[1] for row in conn.execute("PRAGMA table_info(analysis)")}
        expected_columns = {
            "year_month", "year", "month", "workouts", "total_duration_seconds",
            "total_calories", "updated_at",
        }
        if columns and columns != expected_columns:
            conn.execute("DROP TABLE analysis")
        conn.execute(CREATE_ANALYSIS_TABLE)
        conn.execute(CREATE_ACTIVITY_ANALYSIS_TABLE)
        for index_sql in ANALYSIS_INDEXES:
            conn.execute(index_sql)

    def analyze_workouts(self) -> int:
        """Rebuild both monthly rollups from the same workout snapshot."""
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_analysis_tables(conn)
            updated_at = utc_now_iso()
            # Rebuild both tables so workouts moved or removed during sync leave no stale totals.
            conn.execute("DELETE FROM analysis_by_activity")
            conn.execute("DELETE FROM analysis")
            conn.execute(f"""
                INSERT INTO analysis_by_activity (
                    year_month, activity_type, workouts, total_duration_seconds,
                    total_calories, avg_heart_rate, max_heart_rate, updated_at
                )
                SELECT rollup.*, ? FROM ({ACTIVITY_ROLLUP}) AS rollup
            """, (updated_at,))
            return conn.execute("""
                INSERT INTO analysis (
                    year_month, year, month, workouts, total_duration_seconds,
                    total_calories, updated_at
                )
                SELECT year_month, substr(year_month, 1, 4), substr(year_month, 6, 2),
                       SUM(workouts), CAST(ROUND(SUM(total_duration_seconds)) AS INTEGER),
                       ROUND(COALESCE(SUM(total_calories), 0), 2), ?
                FROM analysis_by_activity
                GROUP BY year_month
            """, (updated_at,)).rowcount
