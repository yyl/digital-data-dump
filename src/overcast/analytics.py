"""Analytics module for Overcast podcast data."""

from collections import defaultdict
from typing import Optional, Dict

from .database import OvercastDatabase
from .models import CREATE_ANALYSIS_TABLE, CREATE_INDEXES
from ..database import CREATE_SOURCE_TIME_ANALYSIS_TABLE
from ..time_utils import utc_now_iso


class OvercastAnalytics:
    """Analyzes Overcast podcast data."""

    def __init__(self, db: Optional[OvercastDatabase] = None):
        """Initialize analytics.

        Args:
            db: Database manager instance.
        """
        self.db = db or OvercastDatabase()

    def analyze_podcasts(self) -> int:
        """Analyze podcast activity by month.

        Computes new feeds subscribed, feeds removed, and episodes played
        for each month. Writes results to the analysis table.

        Returns:
            Number of monthly records written to the database.
        """
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(CREATE_ANALYSIS_TABLE)
            conn.execute(CREATE_SOURCE_TIME_ANALYSIS_TABLE)
            for index_sql in CREATE_INDEXES:
                conn.execute(index_sql)
            columns = {row['name'] for row in conn.execute("PRAGMA table_info(analysis)")}
            if 'minutes_listened' not in columns:
                conn.execute("ALTER TABLE analysis ADD COLUMN minutes_listened INTEGER DEFAULT 0")
            cursor = conn.cursor()

            # Get feeds added by month (using overcastAddedDate)
            feeds_added: Dict[tuple, int] = defaultdict(int)
            cursor.execute("""
                SELECT 
                    strftime('%Y', overcastAddedDate) as year,
                    strftime('%m', overcastAddedDate) as month
                FROM feeds
                WHERE overcastAddedDate IS NOT NULL
            """)
            for row in cursor.fetchall():
                if row['year'] and row['month']:
                    feeds_added[(row['year'], row['month'])] += 1
            
            # Get feeds removed by month (using dateRemoveDetected)
            feeds_removed: Dict[tuple, int] = defaultdict(int)
            cursor.execute("""
                SELECT 
                    strftime('%Y', dateRemoveDetected) as year,
                    strftime('%m', dateRemoveDetected) as month
                FROM feeds
                WHERE dateRemoveDetected IS NOT NULL
            """)
            for row in cursor.fetchall():
                if row['year'] and row['month']:
                    feeds_removed[(row['year'], row['month'])] += 1
            
            updated_at = utc_now_iso()
            cursor.execute("DELETE FROM analysis_by_source")
            cursor.execute("""
                INSERT INTO analysis_by_source (
                    year_month, source_name, items, timed_items, total_seconds, updated_at
                )
                SELECT strftime('%Y-%m', e.userUpdatedDate),
                       COALESCE(NULLIF(f.title, ''), 'Unknown podcast'),
                       COUNT(*), COUNT(e.duration_seconds), SUM(e.duration_seconds), ?
                FROM episodes e LEFT JOIN feeds f ON f.overcastId = e.feedId
                WHERE e.played = 1 AND strftime('%Y-%m', e.userUpdatedDate) IS NOT NULL
                GROUP BY 1, 2
            """, (updated_at,))
            playback = {
                tuple(row["year_month"].split("-")): (row["items"], row["seconds"])
                for row in cursor.execute("""
                    SELECT year_month, SUM(items) AS items, COALESCE(SUM(total_seconds), 0) AS seconds
                    FROM analysis_by_source GROUP BY year_month
                """)
            }
            all_months = feeds_added.keys() | feeds_removed.keys() | playback.keys()
            for year, month in all_months:
                year_month = f"{year}-{month}"
                episodes_played, seconds = playback.get((year, month), (0, 0))
                minutes_listened = round(seconds / 60)
                
                cursor.execute("""
                    INSERT INTO analysis (year_month, year, month, feeds_added, feeds_removed, episodes_played, minutes_listened, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(year_month) DO UPDATE SET
                        feeds_added = excluded.feeds_added,
                        feeds_removed = excluded.feeds_removed,
                        episodes_played = excluded.episodes_played,
                        minutes_listened = excluded.minutes_listened,
                        updated_at = excluded.updated_at
                """, (
                    year_month,
                    year,
                    month,
                    feeds_added[(year, month)],
                    feeds_removed[(year, month)],
                    episodes_played,
                    minutes_listened,
                    updated_at
                ))
        
        return len(all_months)
