"""Analytics module for Strong workout data."""

from collections import defaultdict
from typing import Optional, Dict, Any

from .database import StrongDatabase
from .models import CREATE_ANALYSIS_TABLE, ANALYSIS_INDEXES
from ..comparison import compute_percentage_change, get_comparison_periods
from ..time_utils import utc_now_iso


class StrongAnalytics:
    """Analyzes Strong workout data."""

    def __init__(self, db: Optional[StrongDatabase] = None):
        """Initialize analytics.

        Args:
            db: Database manager instance.
        """
        self.db = db or StrongDatabase()

    def get_weightlifting_summary(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get the latest workout's best set weights and calendar comparisons.

        Historical baselines use each exercise's latest session in the
        comparison month, even if it wasn't in that month's final workout.
        Weights retain the CSV's units, which the export does not identify.
        """
        periods = get_comparison_periods(year_month)
        with self.db.read_connection(required_tables=("workouts", "exercises")) as conn:
            if conn is None:
                return None
            workout = conn.execute("""
                SELECT id, workout_name, started_at
                FROM workouts
                WHERE strftime('%Y-%m', started_at) = ?
                ORDER BY datetime(started_at) DESC, id DESC
                LIMIT 1
            """, (year_month,)).fetchone()
            if workout is None:
                return None

            exercises = [dict(row) for row in conn.execute("""
                SELECT exercise_name, MAX(weight) AS weight
                FROM exercises
                WHERE workout_id = ?
                GROUP BY exercise_name
                ORDER BY MIN(id)
            """, (workout['id'],))]
            if not exercises:
                return None

            history = {}
            for comparison, month in periods.items():
                rows = conn.execute("""
                    WITH session_weights AS (
                        SELECT e.exercise_name, w.id, w.started_at,
                               MAX(e.weight) AS weight
                        FROM exercises e
                        JOIN workouts w ON w.id = e.workout_id
                        WHERE strftime('%Y-%m', w.started_at) = ?
                        GROUP BY e.exercise_name, w.id
                    ), ranked AS (
                        SELECT exercise_name, weight,
                               ROW_NUMBER() OVER (
                                   PARTITION BY exercise_name
                                   ORDER BY datetime(started_at) DESC, id DESC
                               ) AS recency
                        FROM session_weights
                    )
                    SELECT exercise_name, weight FROM ranked WHERE recency = 1
                """, (month,))
                history[comparison] = {row['exercise_name']: row['weight'] for row in rows}

        for exercise in exercises:
            exercise['comparisons'] = {
                comparison: compute_percentage_change(
                    exercise['weight'], weights.get(exercise['exercise_name'])
                )
                for comparison, weights in history.items()
            }

        return {
            'workout_name': workout['workout_name'],
            'started_at': workout['started_at'],
            'exercises': exercises,
        }

    def _ensure_analysis_table(self) -> None:
        """Create analysis table if it doesn't exist."""
        with self.db.get_connection() as conn:
            conn.execute(CREATE_ANALYSIS_TABLE)
            for index_sql in ANALYSIS_INDEXES:
                conn.execute(index_sql)

    def analyze_workouts(self) -> int:
        """Analyze workout activity by month.

        Computes workout count, total minutes, unique exercises, and total
        sets for each month. Writes results to the analysis table.

        Returns:
            Number of monthly records written to the database.
        """
        self._ensure_analysis_table()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Get workout counts and total minutes by month
            workout_stats: Dict[tuple, Dict[str, Any]] = defaultdict(
                lambda: {"workouts": 0, "total_minutes": 0}
            )
            cursor.execute("""
                SELECT
                    strftime('%Y', started_at) as year,
                    strftime('%m', started_at) as month,
                    COUNT(*) as cnt,
                    SUM(duration_minutes) as total_mins
                FROM workouts
                WHERE started_at IS NOT NULL
                GROUP BY year, month
            """)
            for row in cursor.fetchall():
                if row['year'] and row['month']:
                    key = (row['year'], row['month'])
                    workout_stats[key]['workouts'] = row['cnt']
                    workout_stats[key]['total_minutes'] = row['total_mins'] or 0

            # Get unique exercises and total sets by month
            exercise_stats: Dict[tuple, Dict[str, int]] = defaultdict(
                lambda: {"unique_exercises": 0, "total_sets": 0}
            )
            cursor.execute("""
                SELECT
                    strftime('%Y', w.started_at) as year,
                    strftime('%m', w.started_at) as month,
                    COUNT(DISTINCT e.exercise_name) as unique_ex,
                    COUNT(*) as total_sets
                FROM exercises e
                JOIN workouts w ON e.workout_id = w.id
                WHERE w.started_at IS NOT NULL
                GROUP BY year, month
            """)
            for row in cursor.fetchall():
                if row['year'] and row['month']:
                    key = (row['year'], row['month'])
                    exercise_stats[key]['unique_exercises'] = row['unique_ex']
                    exercise_stats[key]['total_sets'] = row['total_sets']

            # Merge all months
            all_months = set(workout_stats.keys()) | set(exercise_stats.keys())

            # Write to database
            updated_at = utc_now_iso()

            for year, month in all_months:
                year_month = f"{year}-{month}"
                ws = workout_stats[(year, month)]
                es = exercise_stats[(year, month)]

                cursor.execute("""
                    INSERT INTO analysis (year_month, year, month, workouts, total_minutes, unique_exercises, total_sets, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(year_month) DO UPDATE SET
                        workouts = excluded.workouts,
                        total_minutes = excluded.total_minutes,
                        unique_exercises = excluded.unique_exercises,
                        total_sets = excluded.total_sets,
                        updated_at = excluded.updated_at
                """, (
                    year_month,
                    year,
                    month,
                    ws['workouts'],
                    ws['total_minutes'],
                    es['unique_exercises'],
                    es['total_sets'],
                    updated_at
                ))

        return len(all_months)
