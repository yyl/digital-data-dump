import pytest
import sqlite3
import os
from src.letterboxd.database import LetterboxdDatabase

class TestLetterboxdDatabase:
    @pytest.fixture
    def mock_db_path(self, tmp_path):
        """Fixture to provide a temporary database path."""
        db_file = tmp_path / "test_letterboxd.db"
        return str(db_file)

    def test_letterboxd_database_connection_and_foreign_keys(self, mock_db_path):
        """Test that LetterboxdDatabase initializes correctly and enables foreign keys."""
        db = LetterboxdDatabase(db_path=mock_db_path)

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys")
            result = cursor.fetchone()
            assert result[0] == 1, "Foreign keys should be enabled"

        with db.get_connection() as conn:
            assert conn.row_factory == sqlite3.Row, "Row factory should be sqlite3.Row"

    def test_letterboxd_database_init_tables(self, mock_db_path):
        """Test that tables are initialized correctly."""
        db = LetterboxdDatabase(db_path=mock_db_path)
        db.init_tables()

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            assert "users" in tables
            assert "watched" in tables
            assert "ratings" in tables

            cursor.execute("PRAGMA table_info(watched)")
            watched_columns = {row[1] for row in cursor.fetchall()}
            assert "tmdb_id" in watched_columns
            assert "runtime_minutes" in watched_columns

    def test_upsert_watched_batch(self, mock_db_path):
        """Test batch upsert of watched movies."""
        db = LetterboxdDatabase(db_path=mock_db_path)
        db.init_tables()
        db.upsert_user({"Username": "testuser"})

        watched_data = [
            {"Letterboxd URI": "uri1", "Name": "Movie 1", "Year": "2021", "Date": "2021-01-01"},
            {"Letterboxd URI": "uri2", "Name": "Movie 2", "Year": "2022", "Date": "2022-01-01"},
        ]

        count = db.upsert_watched_batch(watched_data, "testuser")
        assert count == 2

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM watched")
            assert cursor.fetchone()[0] == 2

    def test_upsert_ratings_batch(self, mock_db_path):
        """Test batch upsert of ratings."""
        db = LetterboxdDatabase(db_path=mock_db_path)
        db.init_tables()
        db.upsert_user({"Username": "testuser"})

        ratings_data = [
            {"Letterboxd URI": "uri1", "Name": "Movie 1", "Year": "2021", "Rating": "4.5", "Date": "2021-01-01"},
            {"Letterboxd URI": "uri2", "Name": "Movie 2", "Year": "2022", "Rating": "3.0", "Date": "2022-01-01"},
        ]

        count = db.upsert_ratings_batch(ratings_data, "testuser")
        assert count == 2

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ratings")
            assert cursor.fetchone()[0] == 2
