"""SQLite database manager for Readwise Data Exporter."""

import sqlite3
from typing import Optional, List, Dict, Any

from ..config import Config
from ..database import BaseDatabase
from ..time_utils import utc_now_iso
from .models import RAW_TABLES, RAW_INDEXES


class ReadwiseDatabase(BaseDatabase):
    """Manages SQLite database connections and operations."""

    source_name = 'Readwise'
    raw_table_names = frozenset({
        'books',
        'highlights',
        'highlight_tags',
        'book_tags',
        'documents',
        'document_tags',
        'sync_state',
    })
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager.
        
        Args:
            db_path: Path to SQLite database. Defaults to config path.
        """
        super().__init__(db_path or str(Config.DATABASE_PATH))
    
    def init_tables(self) -> None:
        """Create raw sync tables if they don't exist."""
        is_new = not self.exists()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table_sql in RAW_TABLES:
                cursor.execute(table_sql)
            for index_sql in RAW_INDEXES:
                cursor.execute(index_sql)
        
        if is_new:
            print(f"Database initialized at: {self.db_path}")

    def check_tables_exist(self) -> bool:
        """Check if required tables exist in the database.

        Returns:
            True if all required tables exist, False otherwise.
        """
        required_tables = ["books", "highlights", "documents"]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table in required_tables:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)
                )
                if not cursor.fetchone():
                    return False
        return True
    
    # ==========================================================================
    # Sync State Operations
    # ==========================================================================
    
    def get_sync_state(self, entity_type: str) -> Optional[Dict[str, Any]]:
        """Get the last sync state for an entity type."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sync_state WHERE entity_type = ?",
                (entity_type,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def update_sync_state(
        self,
        entity_type: str,
        last_sync_at: Optional[str] = None,
        last_cursor: Optional[str] = None
    ) -> None:
        """Update or insert sync state for an entity type."""
        if last_sync_at is None:
            last_sync_at = utc_now_iso()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sync_state (entity_type, last_sync_at, last_cursor)
                VALUES (?, ?, ?)
                ON CONFLICT(entity_type) DO UPDATE SET
                    last_sync_at = excluded.last_sync_at,
                    last_cursor = excluded.last_cursor
            """, (entity_type, last_sync_at, last_cursor))
    
    # ==========================================================================
    # Book Operations
    # ==========================================================================
    
    def upsert_book(self, book: Dict[str, Any], cursor: Optional[sqlite3.Cursor] = None) -> None:
        """Insert or update a book record."""
        if cursor:
            self._perform_upsert_book(cursor, book)
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            self._perform_upsert_book(cursor, book)

    def _perform_upsert_book(self, cursor: sqlite3.Cursor, book: Dict[str, Any]) -> None:
        """Internal implementation of upsert_book."""
        cursor.execute("""
            INSERT INTO books (
                user_book_id, title, author, readable_title, source,
                cover_image_url, unique_url, category, document_note,
                summary, readwise_url, source_url, external_id, asin,
                is_deleted, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_book_id) DO UPDATE SET
                title = excluded.title,
                author = excluded.author,
                readable_title = excluded.readable_title,
                source = excluded.source,
                cover_image_url = excluded.cover_image_url,
                unique_url = excluded.unique_url,
                category = excluded.category,
                document_note = excluded.document_note,
                summary = excluded.summary,
                readwise_url = excluded.readwise_url,
                source_url = excluded.source_url,
                external_id = excluded.external_id,
                asin = excluded.asin,
                is_deleted = excluded.is_deleted,
                updated_at = excluded.updated_at
        """, (
            book.get("user_book_id"),
            book.get("title"),
            book.get("author"),
            book.get("readable_title"),
            book.get("source"),
            book.get("cover_image_url"),
            book.get("unique_url"),
            book.get("category"),
            book.get("document_note"),
            book.get("summary"),
            book.get("readwise_url"),
            book.get("source_url"),
            book.get("external_id"),
            book.get("asin"),
            1 if book.get("is_deleted") else 0,
            utc_now_iso()
        ))

        # Handle book tags
        if book.get("book_tags"):
            self._sync_book_tags(cursor, book["user_book_id"], book["book_tags"])
    
    def _sync_book_tags(
        self,
        cursor: sqlite3.Cursor,
        book_id: int,
        tags: List[Dict[str, Any]]
    ) -> None:
        """Sync tags for a book."""
        # Delete existing tags
        cursor.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))
        # Insert new tags
        tag_data = [
            (book_id, tag.get("name") if isinstance(tag, dict) else str(tag))
            for tag in tags
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO book_tags (book_id, tag_name) VALUES (?, ?)",
            tag_data
        )
    
    # ==========================================================================
    # Highlight Operations
    # ==========================================================================
    
    def upsert_highlight(self, highlight: Dict[str, Any], book_id: int, cursor: Optional[sqlite3.Cursor] = None) -> None:
        """Insert or update a highlight record."""
        if cursor:
            self._perform_upsert_highlight(cursor, highlight, book_id)
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            self._perform_upsert_highlight(cursor, highlight, book_id)

    def _perform_upsert_highlight(self, cursor: sqlite3.Cursor, highlight: Dict[str, Any], book_id: int) -> None:
        """Internal implementation of upsert_highlight."""
        cursor.execute("""
            INSERT INTO highlights (
                id, book_id, text, note, location, location_type, color,
                url, external_id, end_location, highlighted_at, created_at,
                updated_at, is_favorite, is_discard, is_deleted, readwise_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                book_id = excluded.book_id,
                text = excluded.text,
                note = excluded.note,
                location = excluded.location,
                location_type = excluded.location_type,
                color = excluded.color,
                url = excluded.url,
                external_id = excluded.external_id,
                end_location = excluded.end_location,
                highlighted_at = excluded.highlighted_at,
                updated_at = excluded.updated_at,
                is_favorite = excluded.is_favorite,
                is_discard = excluded.is_discard,
                is_deleted = excluded.is_deleted,
                readwise_url = excluded.readwise_url
        """, (
            highlight.get("id"),
            book_id,
            highlight.get("text"),
            highlight.get("note"),
            highlight.get("location"),
            highlight.get("location_type"),
            highlight.get("color"),
            highlight.get("url"),
            highlight.get("external_id"),
            highlight.get("end_location"),
            highlight.get("highlighted_at"),
            highlight.get("created_at"),
            highlight.get("updated_at"),
            1 if highlight.get("is_favorite") else 0,
            1 if highlight.get("is_discard") else 0,
            1 if highlight.get("is_deleted") else 0,
            highlight.get("readwise_url")
        ))

        # Handle highlight tags
        if highlight.get("tags"):
            self._sync_highlight_tags(cursor, highlight["id"], highlight["tags"])
    
    def _sync_highlight_tags(
        self,
        cursor: sqlite3.Cursor,
        highlight_id: int,
        tags: List[Dict[str, Any]]
    ) -> None:
        """Sync tags for a highlight."""
        # Delete existing tags
        cursor.execute("DELETE FROM highlight_tags WHERE highlight_id = ?", (highlight_id,))
        # Insert new tags
        tag_data = [
            (highlight_id, tag.get("name") if isinstance(tag, dict) else str(tag))
            for tag in tags
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO highlight_tags (highlight_id, tag_name) VALUES (?, ?)",
            tag_data
        )
    
    # ==========================================================================
    # Document Operations (Reader)
    # ==========================================================================
    
    def upsert_document(self, doc: Dict[str, Any]) -> None:
        """Insert or update a Reader document."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO documents (
                    id, url, source_url, title, author, source, category,
                    location, site_name, word_count, reading_time, notes,
                    summary, image_url, parent_id, reading_progress,
                    published_date, first_opened_at, last_opened_at,
                    saved_at, last_moved_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    url = excluded.url,
                    source_url = excluded.source_url,
                    title = excluded.title,
                    author = excluded.author,
                    source = excluded.source,
                    category = excluded.category,
                    location = excluded.location,
                    site_name = excluded.site_name,
                    word_count = excluded.word_count,
                    reading_time = excluded.reading_time,
                    notes = excluded.notes,
                    summary = excluded.summary,
                    image_url = excluded.image_url,
                    parent_id = excluded.parent_id,
                    reading_progress = excluded.reading_progress,
                    published_date = excluded.published_date,
                    first_opened_at = excluded.first_opened_at,
                    last_opened_at = excluded.last_opened_at,
                    saved_at = excluded.saved_at,
                    last_moved_at = excluded.last_moved_at,
                    updated_at = excluded.updated_at
            """, (
                doc.get("id"),
                doc.get("url"),
                doc.get("source_url"),
                doc.get("title"),
                doc.get("author"),
                doc.get("source"),
                doc.get("category"),
                doc.get("location"),
                doc.get("site_name"),
                doc.get("word_count"),
                doc.get("reading_time"),
                doc.get("notes"),
                doc.get("summary"),
                doc.get("image_url"),
                doc.get("parent_id"),
                doc.get("reading_progress"),
                doc.get("published_date"),
                doc.get("first_opened_at"),
                doc.get("last_opened_at"),
                doc.get("saved_at"),
                doc.get("last_moved_at"),
                doc.get("created_at"),
                doc.get("updated_at")
            ))
            
            # Handle document tags
            if doc.get("tags"):
                self._sync_document_tags(cursor, doc["id"], doc["tags"])
    
    def _sync_document_tags(
        self,
        cursor: sqlite3.Cursor,
        document_id: str,
        tags: Dict[str, Any]
    ) -> None:
        """Sync tags for a document."""
        # Delete existing tags
        cursor.execute("DELETE FROM document_tags WHERE document_id = ?", (document_id,))
        # Insert new tags (Reader returns tags as a dict)
        if isinstance(tags, dict):
            tag_data = []
            for key, value in tags.items():
                tag_name = value if isinstance(value, str) else key
                tag_data.append((document_id, key, tag_name))

            cursor.executemany(
                "INSERT OR IGNORE INTO document_tags (document_id, tag_key, tag_name) VALUES (?, ?, ?)",
                tag_data
            )
    
    # ==========================================================================
    # Statistics
    # ==========================================================================
    
    def get_stats(self) -> Dict[str, int]:
        """Get counts of all entities in the database."""
        stats = {}
        queries = {
            "books": "SELECT COUNT(*) FROM books",
            "highlights": "SELECT COUNT(*) FROM highlights",
            "documents": "SELECT COUNT(*) FROM documents",
        }
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table, query in queries.items():
                cursor.execute(query)
                stats[table] = cursor.fetchone()[0]
        return stats
