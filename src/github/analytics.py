"""Analytics for GitHub activity data."""

from typing import Optional

from .database import GitHubDatabase
from .models import CREATE_ANALYSIS_TABLE, ANALYSIS_INDEXES, VISIBILITY_METRICS
from ..time_utils import utc_now_iso


class GitHubAnalytics:
    """Generates monthly analysis from GitHub commit data."""
    
    def __init__(self, db: Optional[GitHubDatabase] = None):
        """Initialize analytics.
        
        Args:
            db: Database manager instance.
        """
        self.db = db or GitHubDatabase()

    def _ensure_analysis_table(self) -> None:
        """Create analysis table if it doesn't exist."""
        with self.db.get_connection() as conn:
            conn.execute(CREATE_ANALYSIS_TABLE)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis)")}
            for metric in VISIBILITY_METRICS:
                if metric not in columns:
                    # Leave old values unknown until raw commits are re-aggregated.
                    conn.execute(f"ALTER TABLE analysis ADD COLUMN {metric} INTEGER")
            for index_sql in ANALYSIS_INDEXES:
                conn.execute(index_sql)
    
    def analyze_commits(self) -> int:
        """Aggregate commits by month and write to analysis table.
        
        Groups commits by date_month and computes:
        - commits and repos_touched: combined totals
        - public/private commits and distinct repos touched
        
        Returns:
            Number of monthly records written.
        """
        self._ensure_analysis_table()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT date_month, COUNT(*) AS commits, COUNT(DISTINCT repo) AS repos_touched,
                       SUM(CASE WHEN is_private = 0 THEN 1 ELSE 0 END) AS public_commits,
                       SUM(CASE WHEN is_private = 1 THEN 1 ELSE 0 END) AS private_commits,
                       COUNT(DISTINCT CASE WHEN is_private = 0 THEN repo END) AS public_repos_touched,
                       COUNT(DISTINCT CASE WHEN is_private = 1 THEN repo END) AS private_repos_touched
                FROM commits
                WHERE date_month IS NOT NULL AND date_month != ''
                GROUP BY date_month
                ORDER BY date_month
            """)
            rows = cursor.fetchall()
        
        now = utc_now_iso()
        count = 0
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            for row in rows:
                year_month = row["date_month"]
                parts = year_month.split("-")
                if len(parts) != 2 or len(parts[0]) != 4:
                    continue
                
                year, month = parts
                
                cursor.execute("""
                    INSERT INTO analysis (
                        year_month, year, month, commits, repos_touched,
                        public_commits, private_commits, public_repos_touched,
                        private_repos_touched, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(year_month) DO UPDATE SET
                        commits = excluded.commits,
                        repos_touched = excluded.repos_touched,
                        public_commits = excluded.public_commits,
                        private_commits = excluded.private_commits,
                        public_repos_touched = excluded.public_repos_touched,
                        private_repos_touched = excluded.private_repos_touched,
                        updated_at = excluded.updated_at
                """, (
                    year_month, year, month, row["commits"], row["repos_touched"],
                    *(row[metric] for metric in VISIBILITY_METRICS), now,
                ))
                count += 1
        
        return count
