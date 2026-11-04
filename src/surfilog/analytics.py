"""Monthly surfing metrics from session-local dates and non-excluded waves."""

from ..time_utils import utc_now_iso
from .database import SurfilogDatabase
from .models import CREATE_ANALYSIS_TABLE, METRICS


class SurfilogAnalytics:
    def __init__(self, db=None):
        self.db = db or SurfilogDatabase()

    def analyze_sessions(self):
        with self.db.get_connection() as conn:
            conn.execute(CREATE_ANALYSIS_TABLE)
            rows = conn.execute("""
                SELECT s.date_month AS year_month,
                    COUNT(*) AS sessions,
                    COALESCE(SUM(w.waves), 0) AS waves,
                    SUM(s.duration_sec) AS total_duration_seconds,
                    COALESCE(SUM(w.surf_time_seconds), 0) AS surf_time_seconds,
                    COALESCE(SUM(w.surf_distance_m), 0) AS surf_distance_m,
                    COALESCE(SUM(s.paddling_distance_m), 0) AS paddling_distance_m,
                    COALESCE(MAX(w.max_speed_kmh), 0) AS max_speed_kmh,
                    COALESCE(MAX(w.longest_wave_m), 0) AS longest_wave_m,
                    COALESCE(MAX(w.max_wave_seconds), 0) AS max_wave_seconds
                FROM sessions s
                LEFT JOIN (
                    SELECT session_id, COUNT(*) AS waves,
                        SUM(duration_sec) AS surf_time_seconds,
                        SUM(distance_m) AS surf_distance_m,
                        MAX(max_speed_kmh) AS max_speed_kmh,
                        MAX(distance_m) AS longest_wave_m,
                        MAX(duration_sec) AS max_wave_seconds
                    FROM waves WHERE is_excluded = 0 GROUP BY session_id
                ) w ON w.session_id = s.id
                GROUP BY s.date_month ORDER BY s.date_month
            """).fetchall()
            conn.execute("DELETE FROM analysis")
            updated_at = utc_now_iso()
            columns = ("year_month", "year", "month", *METRICS, "updated_at")
            conn.executemany(
                f"INSERT INTO analysis ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [(row["year_month"], *row["year_month"].split("-"),
                  *(row[metric] for metric in METRICS), updated_at) for row in rows],
            )
        return len(rows)
