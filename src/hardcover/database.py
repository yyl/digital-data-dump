"""Database manager for Hardcover book data."""

from typing import Optional, Dict, Any, List

from ..config import Config
from ..database import BaseDatabase
from . import models


class HardcoverDatabase(BaseDatabase):
    """SQLite database manager for Hardcover books."""

    source_name = 'Hardcover'
    raw_table_names = frozenset({'books'})
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager.
        
        Args:
            db_path: Path to SQLite database. Defaults to config value.
        """
        super().__init__(str(db_path or Config.HARDCOVER_DATABASE_PATH))
    
    def init_tables(self) -> None:
        """Create raw sync tables if they don't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(models.CREATE_BOOKS_TABLE)
        print(f"Hardcover database initialized at: {self.db_path}")
    
    def upsert_book(self, book: Dict[str, Any]) -> None:
        """Insert or update a finished book.
        
        Args:
            book: Dictionary with slug, title, author, rating, date_added,
                  reviewed_at, and date_read fields.
        """
        self.upsert_books([book])

    def upsert_books(self, books: List[Dict[str, Any]]) -> None:
        """Insert or update multiple finished books in a single transaction.

        Args:
            books: List of dictionaries with book data.
        """
        if not books:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Prepare data for executemany
            data = [
                (
                    book["slug"],
                    book["title"],
                    book.get("author"),
                    book.get("rating"),
                    book.get("date_added"),
                    book.get("reviewed_at"),
                    book.get("date_read"),
                    book["slug"],
                )
                for book in books
            ]

            cursor.executemany("""
                INSERT INTO books (id, title, author, rating, date_added, reviewed_at, date_read, slug)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    author = excluded.author,
                    rating = excluded.rating,
                    date_added = excluded.date_added,
                    reviewed_at = excluded.reviewed_at,
                    date_read = excluded.date_read,
                    slug = excluded.slug
            """, data)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics.
        
        Returns:
            Dictionary with row counts.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM books")
            books_count = cursor.fetchone()[0]
            
            return {
                "books": books_count,
            }
