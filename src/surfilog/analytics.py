"""Monthly surfing metrics from session-local dates and non-excluded waves."""

from collections import defaultdict
from statistics import median

from ..time_utils import utc_now_iso
from .database import SurfilogDatabase
from .models import CREATE_ANALYSIS_TABLE, METRICS, WAVE_MEDIAN_METRICS


class SurfilogAnalytics:
    def __init__(self, db=None):
        self.db = db or SurfilogDatabase()

    def analyze_sessions(self):
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(CREATE_ANALYSIS_TABLE)
            existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis)")}
            for metric in WAVE_MEDIAN_METRICS:
                if metric not in existing_columns:
                    conn.execute(f"ALTER TABLE analysis ADD COLUMN {metric} REAL")

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
            waves_by_month = defaultdict(list)
            for wave in conn.execute("""
                SELECT s.date_month, w.duration_sec, w.max_speed_kmh
                FROM waves w JOIN sessions s ON s.id = w.session_id
                WHERE w.is_excluded = 0
            """):
                waves_by_month[wave["date_month"]].append(wave)

            conn.execute("DELETE FROM analysis")
            updated_at = utc_now_iso()
            columns = ("year_month", "year", "month", *METRICS, *WAVE_MEDIAN_METRICS, "updated_at")
            records = []
            for row in rows:
                year_month = row["year_month"]
                waves = waves_by_month[year_month]
                median_duration = median(wave["duration_sec"] for wave in waves) if waves else None
                median_speed = median(wave["max_speed_kmh"] for wave in waves) if waves else None
                records.append((year_month, *year_month.split("-"),
                                *(row[metric] for metric in METRICS),
                                median_duration, median_speed, updated_at))
            conn.executemany(
                f"INSERT INTO analysis ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                records,
            )
        return len(rows)
