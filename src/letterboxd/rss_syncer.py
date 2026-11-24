"""Fetch and parse Letterboxd RSS feed for watched movies and ratings."""

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from .database import LetterboxdDatabase

logger = logging.getLogger(__name__)

# Letterboxd extension namespaces
NS = {
    "letterboxd": "https://letterboxd.com",
    "tmdb": "https://themoviedb.org",
    "dc": "http://purl.org/dc/elements/1.1/",
}

class LetterboxdRSSSyncer:
    """Syncs Letterboxd data from a public RSS feed."""

    def __init__(self, db: Optional[LetterboxdDatabase] = None, rss_url: Optional[str] = None, timeout: int = 10):
        """Initialize syncer.

        Args:
            db: Database manager instance.
            rss_url: The RSS feed URL to fetch.
            timeout: HTTP request timeout in seconds.
        """
        from ..config import Config
        self.db = db or LetterboxdDatabase()
        self.rss_url = rss_url or Config.LETTERBOXD_RSS_URL
        self.timeout = timeout

    @staticmethod
    def _normalize_uri(link: str) -> str:
        """Convert a user-specific film URL to a canonical film URL.
        
        Example:
            https://letterboxd.com/longyu/film/the-substance/
            -> https://letterboxd.com/film/the-substance/
        """
        # A simple regex to take out the username part.
        # It assumes the format is always https://letterboxd.com/<username>/film/<slug>/
        match = re.match(r"(https?://letterboxd\.com)/[^/]+(/film/[^/]+/?.*)", link)
        if match:
            return f"{match.group(1)}{match.group(2)}"
        return link

    def sync(self) -> Dict[str, int]:
        """Fetch RSS feed and upsert watched and rated movies.

        Returns:
            Dictionary with counts of processed records.
        """
        stats = {"watched": 0, "ratings": 0}
        if not self.rss_url:
            logger.warning("Letterboxd RSS URL is not configured.")
            return stats

        logger.info(f"Fetching Letterboxd RSS feed from {self.rss_url}")
        
        try:
            req = Request(self.rss_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=self.timeout) as resp:
                rss_data = resp.read()
        except OSError:
            raise RuntimeError("Failed to fetch the Letterboxd RSS feed.") from None

        return self._process_rss_data(rss_data)

    def _process_rss_data(self, xml_data: bytes) -> Dict[str, int]:
        """Parse RSS XML and upsert records."""
        stats = {"watched": 0, "ratings": 0}

        try:
            items = self._parse_items(xml_data)
        except ET.ParseError:
            raise RuntimeError("Failed to parse the Letterboxd RSS feed.") from None

        if not items:
            return stats

        self.db.init_tables()

        # Group items to minimize individual inserts, but here we can just loop since feed is small (~4 items usually)
        for item in items:
            username = item.get("username", "unknown")
            self.db.ensure_user(username)

            # Prevent duplication with CSV data that has a different URI by checking name/date
            if item["watched_at"] and self.db.movie_exists_on_date(username, item["movie_name"], item["watched_at"]):
                logger.debug(f"Skipping movie {item['movie_name']} watched on {item['watched_at']} (already exists)")
                continue

            watched_data = {
                "Letterboxd URI": item["letterboxd_uri"],
                "Name": item["movie_name"],
                "Year": item["year"],
                "TMDB ID": item.get("tmdb_id"),
                "Date": item["watched_at"]
            }
            if self.db.upsert_watched(watched_data, username):
                stats["watched"] += 1

            if item["rating"] is not None:
                rating_data = {
                    "Letterboxd URI": item["letterboxd_uri"],
                    "Name": item["movie_name"],
                    "Year": item["year"],
                    "Date": item["watched_at"],
                    "Rating": item["rating"]
                }
                if self.db.upsert_rating(rating_data, username):
                    stats["ratings"] += 1

        logger.info(f"Imported {stats['watched']} watched movies via RSS")
        logger.info(f"Imported {stats['ratings']} ratings via RSS")
        return stats

    def _parse_items(self, xml_data: bytes) -> List[Dict[str, Any]]:
        """Parse RSS XML into a list of movie dicts."""
        items = []
        root = ET.fromstring(xml_data)

        for item_el in root.iter("item"):
            title_el = item_el.find("letterboxd:filmTitle", NS)
            year_el = item_el.find("letterboxd:filmYear", NS)
            watched_date_el = item_el.find("letterboxd:watchedDate", NS)
            rating_el = item_el.find("letterboxd:memberRating", NS)
            link_el = item_el.find("link")
            creator_el = item_el.find("dc:creator", NS)
            tmdb_id_el = None
            for tag in ("tmdb:movieId", "tmdb:filmId", "tmdb:id"):
                candidate = item_el.find(tag, NS)
                if candidate is not None:
                    tmdb_id_el = candidate
                    break

            if title_el is None or title_el.text is None:
                continue
            if link_el is None or link_el.text is None:
                continue

            movie_name = html.unescape(title_el.text.strip())
            
            link = link_el.text.strip()
            canonical_uri = self._normalize_uri(link)

            year = None
            if year_el is not None and year_el.text:
                try:
                    year = int(year_el.text.strip())
                except ValueError:
                    pass

            watched_at = None
            if watched_date_el is not None and watched_date_el.text:
                watched_at = watched_date_el.text.strip()
            else:
                # If no watchedDate exists, we might try pubDate but usually watchedDate is available.
                continue

            rating: Optional[float] = None
            if rating_el is not None and rating_el.text:
                try:
                    rating = float(rating_el.text.strip())
                except ValueError:
                    pass

            username = "unknown"
            if creator_el is not None and creator_el.text:
                username = creator_el.text.strip()

            tmdb_id = None
            if tmdb_id_el is not None and tmdb_id_el.text:
                try:
                    tmdb_id = int(tmdb_id_el.text.strip())
                except ValueError:
                    pass

            items.append({
                "movie_name": movie_name,
                "year": year,
                "watched_at": watched_at,
                "rating": rating,
                "tmdb_id": tmdb_id,
                "letterboxd_uri": canonical_uri,
                "username": username
            })

        return items
