"""Overcast OPML importer with auto-discovery."""

import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

import requests

from ..config import Config
from .database import OvercastDatabase
from .rss_fetcher import RSSFetcher
from .models import ADD_DURATION_COLUMN


class OvercastImporter:
    """Imports Overcast data from OPML export files."""
    
    def __init__(self, db: OvercastDatabase | None = None):
        """Initialize importer."""
        self.db = db if db is not None else OvercastDatabase()

    @staticmethod
    def get_authenticated_cookie() -> Optional[str]:
        """Return an Overcast session cookie for direct export, if configured."""
        if Config.OVERCAST_COOKIE:
            return Config.OVERCAST_COOKIE

        if not (Config.OVERCAST_EMAIL and Config.OVERCAST_PASSWORD):
            return None

        try:
            session = requests.Session()
            response = session.post(
                "https://overcast.fm/login",
                data={
                    "then": "podcasts",
                    "email": Config.OVERCAST_EMAIL,
                    "password": Config.OVERCAST_PASSWORD,
                },
                allow_redirects=True,
                timeout=30,
            )
        except requests.RequestException as exc:
            print(f"Error authenticating to Overcast: {exc}")
            return None

        if "Incorrect password" in response.text:
            print("Error: Overcast login failed. Check OVERCAST_EMAIL / OVERCAST_PASSWORD.")
            return None

        cookie = session.cookies.get("o")
        if not cookie:
            print("Error: Overcast login did not return a session cookie.")
            return None

        return cookie
    
    @staticmethod
    def find_latest_export() -> Optional[Path]:
        """Find the latest Overcast OPML export in files/.
        
        Scans for files matching 'overcast*.opml' pattern and returns
        the one with the latest modification time.
        """
        files_dir = Config.FILES_DIR
        if not files_dir.exists():
            return None
        
        opml_files = sorted(
            files_dir.glob("overcast*.opml"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        return opml_files[0] if opml_files else None
    
    def sync(self, *, enrich_durations: bool = True) -> Dict[str, int] | None:
        """Auto-discover latest export and import it.
        
        Returns:
            Dictionary with import counts, or None when no export is configured.
        """
        opml_file = None
        run_env = None
        command = [
            "overcast-to-sqlite", "save",
            str(self.db.db_path),
            "--no-archive",
        ]

        cookie = self.get_authenticated_cookie()
        if cookie:
            print("Fetching export directly from Overcast...")
            run_env = os.environ.copy()
            run_env["OVERCAST_COOKIE"] = cookie
        else:
            opml_file = self.find_latest_export()
            if not opml_file:
                if Config.OVERCAST_EMAIL or Config.OVERCAST_PASSWORD:
                    raise RuntimeError("Overcast login failed and no local OPML export is available.")
                print("Skipping Overcast import: no configured or local export.")
                return None

            print(f"Found export: {opml_file.name}")
            command.extend(["--load", str(opml_file)])
        
        # Run overcast-to-sqlite command
        Path(self.db.db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
                env=run_env,
            )
            print("Import complete!")
            
            # Get stats from database
            stats = self.get_db_stats()
            print(f"  feeds: {stats['feeds']}")
            print(f"  episodes: {stats['episodes']}")
            print(f"  playlists: {stats['playlists']}")
            
            # Enrich with durations
            if enrich_durations:
                self._enrich_durations()
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("overcast-to-sqlite timed out after 60 seconds.") from None
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"overcast-to-sqlite exited with status {e.returncode}.") from None
        except FileNotFoundError:
            raise RuntimeError("overcast-to-sqlite is unavailable. Run uv sync.") from None
        return stats
    
    def _enrich_durations(self) -> None:
        """Fetch and populate missing episode durations from RSS feeds."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Ensure column exists
            conn.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in cursor.execute("PRAGMA table_info(episodes)")}
            if "duration_seconds" not in columns:
                cursor.execute(ADD_DURATION_COLUMN)
            conn.commit()
                
            # 2. Get missing episodes so we can normalize titles for robust matching
            cursor.execute("""
                SELECT DISTINCT e.feedId, e.title as ep_title, f.xmlUrl, f.title as feed_title
                FROM episodes e
                JOIN feeds f ON e.feedId = f.overcastId
                WHERE e.duration_seconds IS NULL AND f.xmlUrl IS NOT NULL
            """)
            missing_rows = [dict(row) for row in cursor.fetchall()]

            if not missing_rows:
                return

            # Group into feeds list for the fetcher
            feeds_dict = {}
            # Map (feed_id, normalized_title) -> original_db_title
            db_title_map = {}
            
            import re
            import html
            def normalize_title(t: str) -> str:
                if not t: return ''
                t = html.unescape(t).lower()
                t = t.replace('’', '').replace('‘', '')
                t = t.replace('”', '').replace('“', '')
                t = t.replace("'", '').replace('"', '')
                return re.sub(r'\s+', ' ', t).strip()

            for row in missing_rows:
                feed_id = row['feedId']
                ep_title = row['ep_title']
                
                if feed_id not in feeds_dict:
                    feeds_dict[feed_id] = {
                        "overcastId": feed_id,
                        "xmlUrl": row['xmlUrl'],
                        "title": row['feed_title']
                    }
                
                if ep_title:
                    norm_title = normalize_title(ep_title)
                    db_title_map[(feed_id, norm_title)] = ep_title

            feeds = list(feeds_dict.values())
            print(f"Fetching durations for {len(feeds)} feeds...")
            
            # 3. Fetch durations and map using normalized titles
            fetcher = RSSFetcher()
            raw_durations = fetcher.fetch_durations(feeds)
            
            if not raw_durations:
                return
                
            durations_to_update = {}
            for (feed_id, rss_title), duration_seconds in raw_durations.items():
                norm_rss_title = normalize_title(rss_title)
                # If the normalized RSS title matches a normalized DB title
                if (feed_id, norm_rss_title) in db_title_map:
                    original_db_title = db_title_map[(feed_id, norm_rss_title)]
                    durations_to_update[(feed_id, original_db_title)] = duration_seconds
                
            if not durations_to_update:
                return
                
            # 4. Batch update database
            updated_count = 0
            for (feed_id, title), duration_seconds in durations_to_update.items():
                cursor.execute("""
                    UPDATE episodes
                    SET duration_seconds = ?
                    WHERE feedId = ? AND title = ? AND duration_seconds IS NULL
                """, (duration_seconds, feed_id, title))
                updated_count += cursor.rowcount
                
            print(f"  Enriched {updated_count} episodes with durations.")
    
    def get_db_stats(self) -> Dict[str, int]:
        """Get counts from the database."""
        return self.db.get_stats()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "database_stats": self.get_db_stats(),
            "latest_export": self.find_latest_export(),
            "direct_export_configured": bool(
                Config.OVERCAST_COOKIE or
                (Config.OVERCAST_EMAIL and Config.OVERCAST_PASSWORD)
            ),
        }
