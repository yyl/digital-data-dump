"""SQLite database manager for Foursquare data."""

import sqlite3
import time
from typing import Optional, Dict, Any

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_TABLES, RAW_INDEXES, CREATE_VIEWS


class FoursquareDatabase(BaseDatabase):
    """Manages SQLite database for Foursquare data."""

    source_name = 'Foursquare'
    raw_table_names = frozenset({'users', 'places', 'checkins', 'sync_state'})
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager."""
        super().__init__(db_path or str(Config.FOURSQUARE_DATABASE_PATH))
        self.use_foreign_keys = True
    
    def init_tables(self) -> None:
        """Create raw sync tables if they don't exist."""
        # Use BaseDatabase.exists() which handles Path check
        is_new = not self.exists()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table_sql in RAW_TABLES:
                cursor.execute(table_sql)
            for index_sql in RAW_INDEXES:
                cursor.execute(index_sql)
            for view_sql in CREATE_VIEWS:
                cursor.execute(view_sql)
        
        if is_new:
            print(f"Foursquare database initialized at: {self.db_path}")
    
    # ==========================================================================
    # User Operations
    # ==========================================================================
    
    def get_user(self, foursquare_user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE foursquare_user_id = ?",
                (foursquare_user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_last_pulled_timestamp(self, foursquare_user_id: str) -> int:
        """Get last pulled timestamp for a user."""
        user = self.get_user(foursquare_user_id)
        return user["last_pulled_timestamp"] if user else 0
    
    def upsert_user(self, foursquare_user_id: str, last_pulled_timestamp: int = 0) -> None:
        """Insert or update user."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (foursquare_user_id, last_pulled_timestamp, last_updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(foursquare_user_id) DO UPDATE SET
                    last_pulled_timestamp = excluded.last_pulled_timestamp,
                    last_updated_at = excluded.last_updated_at
            """, (foursquare_user_id, last_pulled_timestamp, int(time.time())))
    
    # ==========================================================================
    # Place Operations
    # ==========================================================================
    
    def place_exists(self, fsq_place_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
        """Check if a place exists."""
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM places WHERE fsq_place_id = ? LIMIT 1",
                (fsq_place_id,)
            )
            return cursor.fetchone() is not None

        with self.get_connection() as conn:
            return self.place_exists(fsq_place_id, conn)
    
    def upsert_place(self, place_data: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> bool:
        """Insert or update a place."""
        fsq_place_id = place_data.get("fsq_id") or place_data.get("fsq_place_id")
        if not fsq_place_id:
            return False
        
        if conn:
            cursor = conn.cursor()
            
            # Extract location data
            location = place_data.get("location", {})
            geocodes = place_data.get("geocodes", {}).get("main", {})
            
            # Extract primary category
            categories = place_data.get("categories", [])
            primary_category = categories[0] if categories else {}
            
            cursor.execute("""
                INSERT INTO places (
                    fsq_place_id, name, latitude, longitude, address, locality,
                    region, postcode, country, formatted_address,
                    primary_category_fsq_id, primary_category_name,
                    website, tel, email, price, rating, last_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fsq_place_id) DO UPDATE SET
                    name = excluded.name,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    address = excluded.address,
                    locality = excluded.locality,
                    region = excluded.region,
                    postcode = excluded.postcode,
                    country = excluded.country,
                    formatted_address = excluded.formatted_address,
                    primary_category_fsq_id = excluded.primary_category_fsq_id,
                    primary_category_name = excluded.primary_category_name,
                    website = excluded.website,
                    tel = excluded.tel,
                    email = excluded.email,
                    price = excluded.price,
                    rating = excluded.rating,
                    last_updated_at = excluded.last_updated_at
            """, (
                fsq_place_id,
                place_data.get("name"),
                place_data.get("latitude") or geocodes.get("latitude"),
                place_data.get("longitude") or geocodes.get("longitude"),
                location.get("address"),
                location.get("locality"),
                location.get("region"),
                location.get("postcode"),
                location.get("country"),
                location.get("formatted_address"),
                primary_category.get("id") or primary_category.get("fsq_category_id"),
                primary_category.get("name"),
                place_data.get("website"),
                place_data.get("tel"),
                place_data.get("email"),
                place_data.get("price"),
                place_data.get("rating"),
                int(time.time())
            ))
            return True

        with self.get_connection() as conn:
            return self.upsert_place(place_data, conn)
    
    # ==========================================================================
    # Checkin Operations
    # ==========================================================================
    
    def checkin_exists(self, checkin_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
        """Check if a checkin exists."""
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM checkins WHERE checkin_id = ? LIMIT 1",
                (checkin_id,)
            )
            return cursor.fetchone() is not None

        with self.get_connection() as conn:
            return self.checkin_exists(checkin_id, conn)
    
    def insert_checkin(self, checkin_data: Dict[str, Any], foursquare_user_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
        """Insert a checkin (skip if exists)."""
        checkin_id = checkin_data.get("id")
        if not checkin_id or self.checkin_exists(checkin_id, conn):
            return False
        
        venue = checkin_data.get("venue", {})
        place_fsq_id = venue.get("id")
        if not place_fsq_id:
            return False
        
        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO checkins (
                    checkin_id, foursquare_user_id, place_fsq_id, created_at,
                    type, shout, private, visibility, is_mayor, liked,
                    comments_count, likes_count, photos_count,
                    source_name, source_url, time_zone_offset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                checkin_id,
                foursquare_user_id,
                place_fsq_id,
                checkin_data.get("createdAt"),
                checkin_data.get("type"),
                checkin_data.get("shout"),
                1 if checkin_data.get("private") else 0,
                checkin_data.get("visibility"),
                1 if checkin_data.get("isMayor") else 0,
                1 if checkin_data.get("like") else 0,
                checkin_data.get("comments", {}).get("count", 0),
                checkin_data.get("likes", {}).get("count", 0),
                checkin_data.get("photos", {}).get("count", 0),
                checkin_data.get("source", {}).get("name"),
                checkin_data.get("source", {}).get("url"),
                checkin_data.get("timeZoneOffset")
            ))
            return True

        with self.get_connection() as conn:
            return self.insert_checkin(checkin_data, foursquare_user_id, conn)
    
    # ==========================================================================
    # Statistics
    # ==========================================================================
    
    def get_stats(self) -> Dict[str, int]:
        """Get counts of all entities."""
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table in ["users", "places", "checkins"]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
        return stats
