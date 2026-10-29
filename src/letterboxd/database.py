"""SQLite database manager for Letterboxd data."""

import time
from typing import Optional, Dict, Any, List

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_TABLES, RAW_INDEXES


class LetterboxdDatabase(BaseDatabase):
    """Manages SQLite database for Letterboxd data."""

    source_name = 'Letterboxd'
    raw_table_names = frozenset({'users', 'watched', 'ratings'})
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager."""
        super().__init__(db_path or str(Config.LETTERBOXD_DATABASE_PATH))
        self.use_foreign_keys = True
    
    def init_tables(self) -> None:
        """Create raw sync tables if they don't exist."""
        is_new = not self.exists()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table_sql in RAW_TABLES:
                cursor.execute(table_sql)
            self._migrate_watched_table(cursor)
            for index_sql in RAW_INDEXES:
                cursor.execute(index_sql)
        
        if is_new:
            print(f"Letterboxd database initialized at: {self.db_path}")

    @staticmethod
    def _migrate_watched_table(cursor) -> None:
        """Add metadata columns to older watched tables in-place."""
        cursor.execute("PRAGMA table_info(watched)")
        columns = {row[1] for row in cursor.fetchall()}

        if "tmdb_id" not in columns:
            cursor.execute("ALTER TABLE watched ADD COLUMN tmdb_id INTEGER")
        if "runtime_minutes" not in columns:
            cursor.execute("ALTER TABLE watched ADD COLUMN runtime_minutes INTEGER")
        if "metadata_updated_at" not in columns:
            cursor.execute("ALTER TABLE watched ADD COLUMN metadata_updated_at INTEGER")
    
    def upsert_user(self, user_data: Dict[str, Any]) -> bool:
        """Insert or update a user."""
        username = user_data.get("Username")
        if not username:
            return False
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (
                    username, date_joined, given_name, family_name, email,
                    location, website, bio, pronoun, favorite_films, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    date_joined = excluded.date_joined,
                    given_name = excluded.given_name,
                    family_name = excluded.family_name,
                    email = excluded.email,
                    location = excluded.location,
                    website = excluded.website,
                    bio = excluded.bio,
                    pronoun = excluded.pronoun,
                    favorite_films = excluded.favorite_films,
                    updated_at = excluded.updated_at
            """, (
                username,
                user_data.get("Date Joined"),
                user_data.get("Given Name"),
                user_data.get("Family Name"),
                user_data.get("Email Address"),
                user_data.get("Location"),
                user_data.get("Website"),
                user_data.get("Bio"),
                user_data.get("Pronoun"),
                user_data.get("Favorite Films"),
                int(time.time())
            ))
            return True
    
    def ensure_user(self, username: str) -> bool:
        """Ensure a user exists, creating a minimal record if needed."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return False  # already exists
            cursor.execute(
                "INSERT INTO users (username, updated_at) VALUES (?, ?)",
                (username, int(time.time()))
            )
            return True  # created

    def movie_exists_on_date(self, username: str, movie_name: str, watched_at: str) -> bool:
        """Check if a watch record exists for a movie around a given date (+/- 2 days to handle timezones)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM watched 
                WHERE username = ? AND movie_name = ? 
                AND abs(julianday(watched_at) - julianday(?)) <= 2
            """, (username, movie_name, watched_at))
            return cursor.fetchone() is not None
    
    def upsert_watched(self, watched_data: Dict[str, Any], username: str) -> bool:
        """Insert or update a watched movie."""
        return self.upsert_watched_batch([watched_data], username) > 0

    def upsert_watched_batch(self, watched_list: List[Dict[str, Any]], username: str) -> int:
        """Insert or update multiple watched movies in a single transaction."""
        if not watched_list:
            return 0

        data = []
        for row in watched_list:
            uri = row.get("Letterboxd URI")
            if not uri:
                continue
            tmdb_id = row.get("TMDB ID")
            try:
                tmdb_id = int(tmdb_id) if tmdb_id not in (None, "") else None
            except (TypeError, ValueError):
                tmdb_id = None
            data.append((
                uri,
                row.get("Name"),
                int(row.get("Year")) if row.get("Year") else None,
                tmdb_id,
                row.get("Date"),
                username
            ))

        if not data:
            return 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO watched (
                    letterboxd_uri, movie_name, year, tmdb_id, watched_at, username
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(letterboxd_uri) DO UPDATE SET
                    movie_name = excluded.movie_name,
                    year = excluded.year,
                    tmdb_id = COALESCE(excluded.tmdb_id, watched.tmdb_id),
                    watched_at = excluded.watched_at
            """, data)
            return len(data)
    
    def upsert_rating(self, rating_data: Dict[str, Any], username: str) -> bool:
        """Insert or update a movie rating."""
        return self.upsert_ratings_batch([rating_data], username) > 0

    def upsert_ratings_batch(self, ratings_list: List[Dict[str, Any]], username: str) -> int:
        """Insert or update multiple movie ratings in a single transaction."""
        if not ratings_list:
            return 0

        data = []
        for row in ratings_list:
            uri = row.get("Letterboxd URI")
            if not uri:
                continue
            try:
                data.append((
                    uri,
                    row.get("Name"),
                    int(row.get("Year")) if row.get("Year") else None,
                    float(row.get("Rating")),
                    row.get("Date"),
                    username
                ))
            except (ValueError, TypeError):
                continue

        if not data:
            return 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO ratings (
                    letterboxd_uri, movie_name, year, rating, rated_at, username
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(letterboxd_uri) DO UPDATE SET
                    movie_name = excluded.movie_name,
                    year = excluded.year,
                    rating = excluded.rating,
                    rated_at = excluded.rated_at
            """, data)
            return len(data)
    
    def get_stats(self) -> Dict[str, int]:
        """Get counts of all entities."""
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table in ["users", "watched", "ratings"]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
        return stats

    def get_movies_missing_runtime(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return watched movies that still need runtime enrichment."""
        query = """
            SELECT letterboxd_uri, movie_name, year, tmdb_id
            FROM watched
            WHERE runtime_minutes IS NULL OR runtime_minutes <= 0
            ORDER BY date(watched_at) DESC, movie_name ASC
        """
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_movie_metadata(
        self,
        letterboxd_uri: str,
        tmdb_id: Optional[int] = None,
        runtime_minutes: Optional[int] = None,
    ) -> bool:
        """Persist runtime metadata back onto the watched table."""
        if runtime_minutes is None:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE watched
                SET tmdb_id = COALESCE(?, tmdb_id),
                    runtime_minutes = ?,
                    metadata_updated_at = ?
                WHERE letterboxd_uri = ?
                """,
                (tmdb_id, runtime_minutes, int(time.time()), letterboxd_uri),
            )
            return cursor.rowcount > 0
