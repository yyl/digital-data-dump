"""Analytics module for Readwise data."""

import re
import statistics
from collections import defaultdict
from typing import Optional

from .database import ReadwiseDatabase
from .models import CREATE_ANALYSIS_TABLE, ANALYSIS_INDEXES
from ..time_utils import utc_now_iso


def parse_reading_time_minutes(value: str | None) -> int | None:
    """Extract Readwise's estimated minutes when present."""
    match = re.search(r'(\d+)', str(value))
    return int(match.group(1)) if match else None


class ReadwiseAnalytics:
    """Analyzes Readwise data."""

    def __init__(self, db: Optional[ReadwiseDatabase] = None):
        """Initialize analytics.

        Args:
            db: Database manager instance.
        """
        self.db = db or ReadwiseDatabase()

    def _ensure_analysis_table(self) -> None:
        """Create analysis table if it doesn't exist."""
        with self.db.get_connection() as conn:
            conn.execute(CREATE_ANALYSIS_TABLE)
            for index_sql in ANALYSIS_INDEXES:
                conn.execute(index_sql)

    def analyze_archived(self) -> int:
        """Analyze archived articles by month.

        Computes the number of articles, total words, reading time,
        and per-article word count stats (max, median, min) for archived
        items each month. Writes the result to the analysis table.

        Returns:
            Number of monthly records written to the database.
        """
        self._ensure_analysis_table()

        query = """
        SELECT
            strftime('%m', last_moved_at) as month,
            strftime('%Y', last_moved_at) as year,
            reading_time,
            word_count
        FROM documents
        WHERE location = 'archive' AND last_moved_at IS NOT NULL
        ORDER BY year DESC, month DESC
        """

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()

        # Aggregation
        stats = defaultdict(lambda: {
            'articles': 0,
            'words': 0,
            'reading_time_mins': 0,
            'word_counts': [],
        })

        for row in rows:
            key = (row['year'], row['month'])
            wc = row['word_count'] or 0

            stats[key]['articles'] += 1
            stats[key]['words'] += wc
            stats[key]['reading_time_mins'] += parse_reading_time_minutes(row['reading_time']) or 0
            stats[key]['word_counts'].append(wc)

        # Write to database
        updated_at = utc_now_iso()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            for (year, month), data in stats.items():
                year_month = f"{year}-{month}"
                wc_list = data['word_counts']
                max_words = max(wc_list) if wc_list else 0
                median_words = int(statistics.median(wc_list)) if wc_list else 0
                min_words = min(wc_list) if wc_list else 0
                cursor.execute("""
                    INSERT INTO analysis (year_month, year, month, articles, words,
                        reading_time_mins, max_words_per_article,
                        median_words_per_article, min_words_per_article, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(year_month) DO UPDATE SET
                        articles = excluded.articles,
                        words = excluded.words,
                        reading_time_mins = excluded.reading_time_mins,
                        max_words_per_article = excluded.max_words_per_article,
                        median_words_per_article = excluded.median_words_per_article,
                        min_words_per_article = excluded.min_words_per_article,
                        updated_at = excluded.updated_at
                """, (
                    year_month,
                    year,
                    month,
                    data['articles'],
                    data['words'],
                    data['reading_time_mins'],
                    max_words,
                    median_words,
                    min_words,
                    updated_at
                ))

        return len(stats)
