"""Letterboxd CSV importer with auto-discovery."""

import csv
from pathlib import Path
from typing import Optional, Dict, Any

from ..config import Config
from .database import LetterboxdDatabase
from .tmdb_client import TMDBAPIError, TMDBClient


class LetterboxdImporter:
    """Imports Letterboxd data from CSV export files."""
    
    def __init__(self, db: Optional[LetterboxdDatabase] = None):
        """Initialize importer."""
        self.db = db or LetterboxdDatabase()
    
    @staticmethod
    def find_latest_export() -> Optional[Path]:
        """Find the latest Letterboxd export folder in files/.
        
        Scans for folders starting with 'letterboxd' and returns
        the one with the latest name (alphabetically/by date).
        """
        files_dir = Config.FILES_DIR
        if not files_dir.exists():
            return None
        
        letterboxd_folders = sorted([
            f for f in files_dir.iterdir()
            if f.is_dir() and f.name.startswith("letterboxd")
        ], reverse=True)  # Latest first (by name)
        
        return letterboxd_folders[0] if letterboxd_folders else None
    
    def import_from_directory(self, export_dir: Path) -> Dict[str, int]:
        """Import all CSV files from an export directory.
        
        Args:
            export_dir: Path to Letterboxd export folder
            
        Returns:
            Dictionary with import counts
        """
        stats = {"users": 0, "watched": 0, "ratings": 0}
        
        # Initialize database
        self.db.init_tables()
        
        # Import profile first (needed for FK)
        profile_path = export_dir / "profile.csv"
        username = None
        if profile_path.exists():
            username = self._import_profile(profile_path)
            if username:
                stats["users"] = 1
                print(f"Imported user: {username}")
        
        if not username:
            print("Error: Could not find username in profile.csv")
            return stats
        
        # Import watched
        watched_path = export_dir / "watched.csv"
        if watched_path.exists():
            stats["watched"] = self._import_watched(watched_path, username)
            print(f"Imported {stats['watched']} watched movies")
        
        # Import ratings
        ratings_path = export_dir / "ratings.csv"
        if ratings_path.exists():
            stats["ratings"] = self._import_ratings(ratings_path, username)
            print(f"Imported {stats['ratings']} ratings")
        
        return stats
    
    def _import_profile(self, csv_path: Path) -> Optional[str]:
        """Import profile.csv and return username."""
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if self.db.upsert_user(row):
                    return row.get("Username")
        return None
    
    def _import_watched(self, csv_path: Path, username: str, batch_size: int = 100) -> int:
        """Import watched.csv."""
        count = 0
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            batch = []
            for row in reader:
                tmdb_id = self._extract_tmdb_id(row)
                if tmdb_id is not None:
                    row["TMDB ID"] = tmdb_id
                batch.append(row)
                if len(batch) >= batch_size:
                    count += self.db.upsert_watched_batch(batch, username)
                    batch = []
            if batch:
                count += self.db.upsert_watched_batch(batch, username)
        return count

    @staticmethod
    def _extract_tmdb_id(row: Dict[str, Any]) -> Optional[int]:
        """Normalize any TMDB identifier provided by Letterboxd exports."""
        for key in ("tmdbID", "tmdbId", "TMDB ID"):
            value = row.get(key)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    def _import_ratings(self, csv_path: Path, username: str, batch_size: int = 100) -> int:
        """Import ratings.csv."""
        count = 0
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            batch = []
            for row in reader:
                batch.append(row)
                if len(batch) >= batch_size:
                    count += self.db.upsert_ratings_batch(batch, username)
                    batch = []
            if batch:
                count += self.db.upsert_ratings_batch(batch, username)
        return count

    def enrich_missing_runtime(self, client: Optional[TMDBClient] = None) -> int:
        """Backfill runtime data for watched movies using TMDB."""
        missing_before = self.db.get_movies_missing_runtime()
        if not missing_before:
            return 0

        client = client or TMDBClient()
        if not client.is_configured():
            raise TMDBAPIError(
                "TMDB credentials are not configured (set TMDB_ACCESS_TOKEN or TMDB_API_KEY); "
                f"cannot enrich runtime for {len(missing_before)} watched movie(s)."
            )

        count = 0
        for movie in missing_before:
            match = client.get_runtime(
                title=movie["movie_name"],
                year=movie.get("year"),
                tmdb_id=movie.get("tmdb_id"),
            )
            if not match:
                continue

            matched_tmdb_id, runtime_minutes = match
            if self.db.update_movie_metadata(
                letterboxd_uri=movie["letterboxd_uri"],
                tmdb_id=matched_tmdb_id,
                runtime_minutes=runtime_minutes,
            ):
                count += 1

        if count:
            print(f"Enriched runtime metadata for {count} watched movies")

        remaining = self.db.get_movies_missing_runtime()
        if remaining:
            missing_titles = ", ".join(
                f"{movie['movie_name']} ({movie['year']})" if movie.get("year") else movie["movie_name"]
                for movie in remaining
            )
            print(
                f"Could not find TMDB runtime for {len(remaining)} watched movies: {missing_titles}"
            )
        return count
    
    def sync(self) -> Dict[str, int]:
        """Auto-discover latest export and import it.
        
        If a CSV export exists in files/, it imports that first as a historical 
        backfill. Then, if an RSS URL is configured, it fetches incremental updates.
        
        Returns:
            Dictionary with combined import counts
        """
        stats = {"users": 0, "watched": 0, "ratings": 0, "runtime_enriched": 0}

        # 1. Fallback / Historical CSV import (Only if database is empty)
        self.db.init_tables()
        is_empty = self.db.get_stats().get("watched", 0) == 0

        if is_empty:
            export_dir = self.find_latest_export()
            if export_dir:
                print(f"Database empty. Found Letterboxd export for backfill: {export_dir.name}")
                csv_stats = self.import_from_directory(export_dir)
                stats["users"] += csv_stats.get("users", 0)
                stats["watched"] += csv_stats.get("watched", 0)
                stats["ratings"] += csv_stats.get("ratings", 0)
            else:
                print("No Letterboxd export folder found in files/ (skipping CSV historical import)")
        else:
            print("Database already populated (skipping historical CSV backfill)")

        # 2. Incremental RSS sync
        rss_url = Config.LETTERBOXD_RSS_URL
        if rss_url:
            from .rss_syncer import LetterboxdRSSSyncer
            syncer = LetterboxdRSSSyncer(db=self.db, rss_url=rss_url)
            rss_stats = syncer.sync()
            stats["watched"] += rss_stats.get("watched", 0)
            stats["ratings"] += rss_stats.get("ratings", 0)
        else:
            print("No Letterboxd RSS URL configured (skipping RSS sync)")

        stats["runtime_enriched"] = self.enrich_missing_runtime()
        
        return stats
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        try:
            self.db.init_tables()
            return {
                "database_stats": self.db.get_stats(),
                "latest_export": self.find_latest_export()
            }
        except Exception as e:
            return {"error": str(e)}
