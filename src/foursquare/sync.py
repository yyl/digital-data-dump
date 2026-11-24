"""Sync manager for Foursquare data synchronization."""

from typing import Optional

from .database import FoursquareDatabase
from .api_client import FoursquareAPIClient, FoursquareAPIError


class FoursquareSyncManager:
    """Orchestrates synchronization of Foursquare data."""
    
    def __init__(
        self,
        db: Optional[FoursquareDatabase] = None,
        api: Optional[FoursquareAPIClient] = None
    ):
        """Initialize sync manager."""
        self.db = db or FoursquareDatabase()
        self.api = api or FoursquareAPIClient()
    
    def ensure_auth(self) -> bool:
        """Ensure we have a valid access token, running OAuth if needed."""
        if self.api.needs_auth():
            print("No Foursquare access token found. Starting OAuth flow...")
            token = self.api.run_oauth_flow()
            if not token:
                print("Error: Failed to obtain access token")
                return False
        return True
    
    def sync(self) -> dict:
        """Sync all Foursquare data.
        
        Returns:
            Dictionary with sync statistics
        """
        stats = {
            "checkins": 0,
            "places": 0,
        }
        
        # Ensure authentication
        if not self.ensure_auth():
            raise FoursquareAPIError("Could not authenticate with Foursquare.")
        
        # Get user ID
        user_id = self.api.get_user_id()
        if not user_id:
            raise FoursquareAPIError("Could not get the authenticated Foursquare user.")
        
        print(f"Authenticated as Foursquare user: {user_id}")
        
        # Initialize database
        self.db.init_tables()
        
        # Get last pulled timestamp for incremental sync
        last_timestamp = self.db.get_last_pulled_timestamp(user_id)
        if last_timestamp > 0:
            print(f"Incremental sync: fetching checkins after timestamp {last_timestamp}")
        else:
            print("Full sync: fetching all checkins...")
        
        # Fetch checkins
        checkins = self.api.fetch_checkins(after_timestamp=last_timestamp)
        print(f"Fetched {len(checkins)} new checkins")
        
        if not checkins:
            self.db.upsert_user(user_id)
            print("No new checkins to sync")
            return stats
        
        # Track highest timestamp for incremental sync
        highest_timestamp = last_timestamp
        
        # Process checkins
        with self.db.get_connection() as conn:
            self.db.upsert_user(user_id, conn=conn)
            for i, checkin in enumerate(checkins):
                created_at = checkin.get("createdAt")
                venue = checkin.get("venue", {})
                place_id = venue.get("id")
                
                if not checkin.get("id") or type(created_at) is not int or not place_id:
                    raise FoursquareAPIError("A Foursquare checkin is missing required fields.")

                # MUST ensure place exists before inserting checkin (FK constraint)
                if not self.db.place_exists(place_id, conn=conn):
                    # Try Places API first for richer data
                    place_data = self.api.fetch_place_details(place_id)

                    if not place_data:
                        # Fallback: use venue data from checkin (v2 API format)
                        venue_location = venue.get("location", {})
                        categories = venue.get("categories", [])
                        primary_category = categories[0] if categories else {}

                        place_data = {
                            "fsq_place_id": place_id,
                            "name": venue.get("name"),
                            "latitude": venue_location.get("lat"),
                            "longitude": venue_location.get("lng"),
                            "location": {
                                "address": venue_location.get("address"),
                                "locality": venue_location.get("city"),
                                "region": venue_location.get("state"),
                                "postcode": venue_location.get("postalCode"),
                                "country": venue_location.get("country"),
                                "formatted_address": ", ".join(venue_location.get("formattedAddress", []))
                            },
                            "categories": [{
                                "id": primary_category.get("id"),
                                "name": primary_category.get("name")
                            }] if primary_category else []
                        }
                    
                    if not self.db.upsert_place(place_data, conn=conn):
                        raise FoursquareAPIError("Could not save the place for a Foursquare checkin.")
                    stats["places"] += 1
                
                # Now safe to insert checkin (place exists)
                if self.db.insert_checkin(checkin, user_id, conn=conn):
                    stats["checkins"] += 1

                # Track highest timestamp
                if created_at > highest_timestamp:
                    highest_timestamp = created_at

                # Progress indicator
                if (i + 1) % 100 == 0:
                    print(f"  Processed {i + 1}/{len(checkins)} checkins...")
        
            self.db.upsert_user(user_id, highest_timestamp, conn=conn)
        
        print("\nFoursquare sync complete!")
        print(f"  Checkins: {stats['checkins']}")
        print(f"  Places: {stats['places']}")
        
        return stats
    
    def get_status(self) -> dict:
        """Get current sync status."""
        try:
            self.db.init_tables()
            return {
                "database_stats": self.db.get_stats(),
                "has_token": not self.api.needs_auth()
            }
        except Exception as e:
            return {
                "error": str(e),
                "has_token": not self.api.needs_auth()
            }
