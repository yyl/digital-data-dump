"""SQLite database manager for Overcast data."""

import sqlite3
from typing import Optional, Dict, Any

from ..config import Config
from ..database import BaseDatabase


class OvercastDatabase(BaseDatabase):
    """Manages SQLite database for Overcast data."""

    source_name = 'Overcast'
    raw_table_names = frozenset({'feeds', 'episodes', 'playlists'})
    analysis_table_names = frozenset({'analysis', 'analysis_by_source'})
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager."""
        super().__init__(db_path or str(Config.OVERCAST_DATABASE_PATH))
    
    def latest_played_episode(self) -> dict | None:
        """Return the most recently updated played episode and its show title."""
        rows = self.fetch_rows("""
            SELECT e.title, e.overcastUrl AS url, f.title AS detail, e.userUpdatedDate AS date
            FROM episodes e
            LEFT JOIN feeds f ON f.overcastId = e.feedId
            WHERE e.played = 1 AND e.title <> '' AND julianday(e.userUpdatedDate) IS NOT NULL
            ORDER BY julianday(e.userUpdatedDate) DESC, e.title, e.overcastUrl
            LIMIT 1
        """, required_tables=("feeds", "episodes"))
        return rows[0] if rows else None

    def get_stats(self) -> Dict[str, int]:
        """Get counts from the database."""
        stats = {"feeds": 0, "episodes": 0, "playlists": 0}
        
        if not self.exists():
            return stats
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for table in ["feeds", "episodes", "playlists"]:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        stats[table] = cursor.fetchone()[0]
                    except sqlite3.OperationalError:
                        pass
        except Exception:
            pass
        
        return stats
