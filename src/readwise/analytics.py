"""Analytics module for Readwise data."""

import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Mapping, Optional

from .database import ReadwiseDatabase
from .models import CREATE_ANALYSIS_TABLE, ANALYSIS_INDEXES
from ..database import CREATE_SOURCE_TIME_ANALYSIS_TABLE
from ..time_utils import utc_now_iso


def parse_reading_time_minutes(value: str | None) -> int | None:
    """Extract Readwise's estimated minutes when present."""
    match = re.search(r'(\d+)', str(value))
    return int(match.group(1)) if match else None


def resolve_article_source(article: Mapping[str, Any]) -> Optional[str]:
    """Derive a source name for an article.

    Resolution chain:
    1. ``site_name`` – use the Readwise-provided value when present.
    2. Title prefix – the substring before the first ``:`` in the title.
       Newsletter emails almost always follow a ``Name: Subject`` pattern
       (e.g. "Money Stuff: SpaceX Crash Insurance").
    3. ``author`` – the raw author string as a last resort.
    4. ``None`` – the caller decides on the fallback (usually "Other").
    """
    site = (article.get('site_name') or "").strip()
    if site:
        return site

    title = (article.get('title') or "").strip()
    if ':' in title:
        prefix = title.split(':', 1)[0].strip()
        if prefix:
            return prefix

    author = (article.get('author') or "").strip()
    if author:
        return author

    return None

class ReadwiseAnalytics:
    """Analyzes Readwise data."""

    def __init__(self, db: Optional[ReadwiseDatabase] = None):
        """Initialize analytics.

        Args:
            db: Database manager instance.
        """
        self.db = db or ReadwiseDatabase()

    def analyze_archived(self) -> int:
        """Analyze archived articles by month.

        Computes the number of articles, total words, reading time,
        and per-article word count stats (max, median, min) for archived
        items each month. Writes the result to the analysis table.

        Returns:
            Number of monthly records written to the database.
        """
        query = """
        SELECT
            strftime('%m', last_moved_at) as month,
            strftime('%Y', last_moved_at) as year,
            reading_time, word_count, title, site_name, author
        FROM documents
        WHERE location = 'archive' AND strftime('%Y-%m', last_moved_at) IS NOT NULL
        ORDER BY year DESC, month DESC
        """

        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(CREATE_ANALYSIS_TABLE)
            conn.execute(CREATE_SOURCE_TIME_ANALYSIS_TABLE)
            for index_sql in ANALYSIS_INDEXES:
                conn.execute(index_sql)
            stats = defaultdict(lambda: {'reading_time_mins': 0, 'word_counts': []})
            source_stats = defaultdict(Counter)

            for row in conn.execute(query):
                year, month = row['year'], row['month']
                minutes = parse_reading_time_minutes(row['reading_time'])
                month_stats = stats[year, month]
                month_stats['reading_time_mins'] += minutes or 0
                month_stats['word_counts'].append(row['word_count'] or 0)

                source = resolve_article_source(dict(row)) or 'Other'
                totals = source_stats[f"{year}-{month}", source]
                totals['items'] += 1
                if minutes is not None:
                    totals['timed_items'] += 1
                    totals['total_seconds'] += minutes * 60

            updated_at = utc_now_iso()
            conn.execute("DELETE FROM analysis_by_source")
            conn.execute("DELETE FROM analysis")
            conn.executemany("""
                INSERT INTO analysis_by_source (
                    year_month, source_name, items, timed_items, total_seconds, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                (month, source, totals['items'], totals['timed_items'], totals.get('total_seconds'), updated_at)
                for (month, source), totals in source_stats.items()
            ))
            for (year, month), data in stats.items():
                year_month = f"{year}-{month}"
                wc_list = data['word_counts']
                max_words = max(wc_list) if wc_list else 0
                median_words = int(statistics.median(wc_list)) if wc_list else 0
                min_words = min(wc_list) if wc_list else 0
                conn.execute("""
                    INSERT INTO analysis (year_month, year, month, articles, words,
                        reading_time_mins, max_words_per_article,
                        median_words_per_article, min_words_per_article, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    year_month,
                    year,
                    month,
                    len(wc_list),
                    sum(wc_list),
                    data['reading_time_mins'],
                    max_words,
                    median_words,
                    min_words,
                    updated_at
                ))

        return len(stats)
