"""Analytics module for Letterboxd data."""

from collections import defaultdict
from datetime import datetime
from typing import Optional, Dict, Any

from .database import LetterboxdDatabase
from .models import CREATE_ANALYSIS_TABLE, ANALYSIS_INDEXES
from ..time_utils import utc_now_iso


class LetterboxdAnalytics:
    """Analyzes Letterboxd data."""

    def __init__(self, db: Optional[LetterboxdDatabase] = None):
        """Initialize analytics.

        Args:
            db: Database manager instance.
        """
        self.db = db or LetterboxdDatabase()

    def _ensure_analysis_table(self) -> None:
        """Create analysis table if it doesn't exist."""
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(CREATE_ANALYSIS_TABLE)
            for index_sql in ANALYSIS_INDEXES:
                conn.execute(index_sql)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis)")}
            if "minutes_watched" not in columns:
                conn.execute("ALTER TABLE analysis ADD COLUMN minutes_watched INTEGER DEFAULT 0;")

    def analyze_watched(self) -> int:
        """Analyze watched movies by month.

        Computes movie count, rating stats, and average years since release
        for each month. Writes results to the analysis table.

        Returns:
            Number of monthly records written to the database.
        """
        self._ensure_analysis_table()

        # Get watched movies with their ratings (left join to include unrated)
        query = """
        SELECT
            strftime('%m', w.watched_at) as month,
            strftime('%Y', w.watched_at) as year,
            w.year as release_year,
            w.runtime_minutes,
            r.rating
        FROM watched w
        LEFT JOIN ratings r ON w.letterboxd_uri = r.letterboxd_uri
        WHERE w.watched_at IS NOT NULL
        ORDER BY year DESC, month DESC
        """

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()

        # Aggregation
        stats: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {
            'count': 0,
            'minutes_watched': 0,
            'ratings': [],
            'years_since_release': []
        })

        current_year = datetime.now().year

        for row in rows:
            key = (row['year'], row['month'])
            stats[key]['count'] += 1

            if row['runtime_minutes'] is not None:
                stats[key]['minutes_watched'] += int(row['runtime_minutes'])
            
            if row['rating'] is not None:
                stats[key]['ratings'].append(row['rating'])
            
            if row['release_year'] is not None:
                years_since = current_year - row['release_year']
                stats[key]['years_since_release'].append(years_since)

        # Write to database
        updated_at = utc_now_iso()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            for (year, month), data in stats.items():
                year_month = f"{year}-{month}"
                
                # Calculate stats
                movies_watched = round(float(data['count']), 2)
                minutes_watched = int(data['minutes_watched'])
                
                ratings = data['ratings']
                if ratings:
                    avg_rating = round(sum(ratings) / len(ratings), 2)
                    min_rating = round(min(ratings), 2)
                    max_rating = round(max(ratings), 2)
                else:
                    avg_rating = min_rating = max_rating = 0.0
                
                years_list = data['years_since_release']
                if years_list:
                    avg_years_since = round(sum(years_list) / len(years_list), 2)
                else:
                    avg_years_since = 0.0

                cursor.execute("""
                    INSERT INTO analysis (year_month, year, month, movies_watched, minutes_watched, avg_rating, min_rating, max_rating, avg_years_since_release, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(year_month) DO UPDATE SET
                        movies_watched = excluded.movies_watched,
                        minutes_watched = excluded.minutes_watched,
                        avg_rating = excluded.avg_rating,
                        min_rating = excluded.min_rating,
                        max_rating = excluded.max_rating,
                        avg_years_since_release = excluded.avg_years_since_release,
                        updated_at = excluded.updated_at
                """, (
                    year_month,
                    year,
                    month,
                    movies_watched,
                    minutes_watched,
                    avg_rating,
                    min_rating,
                    max_rating,
                    avg_years_since,
                    updated_at
                ))

        return len(stats)
