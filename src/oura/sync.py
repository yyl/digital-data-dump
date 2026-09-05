"""Sync manager for Oura Ring data synchronization."""

from datetime import date, timedelta
from typing import Optional, Dict, Any

from .database import OuraDatabase
from .api_client import OuraAPIClient


# Default start date for initial full sync
DEFAULT_START_DATE = "2020-01-01"


class OuraSyncManager:
    """Orchestrates synchronization of Oura Ring daily data."""

    # Map data types to their database upsert methods
    UPSERT_METHODS = {
        "daily_activity": "upsert_daily_activity",
        "daily_sleep": "upsert_daily_sleep",
        "daily_readiness": "upsert_daily_readiness",
        "daily_stress": "upsert_daily_stress",
        "daily_resilience": "upsert_daily_resilience",
        "daily_spo2": "upsert_daily_spo2",
        "daily_cardiovascular_age": "upsert_daily_cardiovascular_age",
    }

    def __init__(
        self,
        db: Optional[OuraDatabase] = None,
        api: Optional[OuraAPIClient] = None,
    ):
        """Initialize sync manager."""
        self.db = db or OuraDatabase()
        self.api = api or OuraAPIClient()

    def ensure_auth(self) -> bool:
        """Ensure Oura authentication is available."""
        if self.api.ensure_auth():
            return True
        print("Error: Failed to authenticate with Oura Ring")
        return False

    def _sync_data_type(self, data_type: str) -> int:
        """Sync a single data type.

        Args:
            data_type: One of the UPSERT_METHODS keys.

        Returns:
            Number of records synced.
        """
        upsert_method_name = self.UPSERT_METHODS[data_type]
        upsert_method = getattr(self.db, upsert_method_name)

        # Determine start date for fetch
        last_sync = self.db.get_last_sync_date(data_type)
        if last_sync:
            # Overlap by 1 day to catch any late-arriving data
            start_date = last_sync
        else:
            start_date = DEFAULT_START_DATE

        end_date = date.today().isoformat()

        print(f"  Fetching {data_type} ({start_date} → {end_date})...")
        records = self.api.fetch_daily_data(data_type, start_date, end_date)

        if not records:
            return 0

        # Upsert all records, but only count genuinely new ones
        # (records from the overlapping re-fetched day are upserted
        # for freshness but don't count as new syncs)
        new_count = 0
        latest_day = last_sync or ""
        for record in records:
            try:
                upsert_method(record)
                day = record.get("day", "")
                if day > latest_day:
                    latest_day = day
                if not last_sync or day > last_sync:
                    new_count += 1
            except Exception as e:
                print(f"  Error upserting {data_type} record {record.get('id')}: {e}")

        # Update sync state with the latest day we've seen
        if latest_day:
            self.db.set_last_sync_date(data_type, latest_day)

        return new_count

    # Endpoints that may require Gen 3+ hardware or active subscription
    GEN3_ENDPOINTS = {
        "daily_resilience",
        "daily_spo2",
        "daily_cardiovascular_age",
    }

    def sync(self) -> Dict[str, Any]:
        """Sync all daily data types.

        Returns:
            Dictionary with sync statistics per data type.
        """
        stats = {}

        # Ensure authentication
        if not self.ensure_auth():
            return stats

        # Initialize database
        self.db.init_tables()

        print("Syncing Oura Ring data...")

        for data_type in self.UPSERT_METHODS:
            if getattr(self.api, "_refresh_failed", False):
                print(f"  ✗ Skipping {data_type}: authentication failed")
                stats[data_type] = 0
                continue

            try:
                count = self._sync_data_type(data_type)
                stats[data_type] = count
                if count > 0:
                    print(f"  ✓ {data_type}: {count} records")
                elif getattr(self.api, "_refresh_failed", False):
                    print(f"  ✗ {data_type}: authentication failed")
                else:
                    last_sync = self.db.get_last_sync_date(data_type)
                    if last_sync:
                        print(f"  · {data_type}: up to date")
                    elif data_type in self.GEN3_ENDPOINTS:
                        print(
                            f"  ⊘ {data_type}: skipped"
                            " (may require Gen 3+ ring or active Oura membership)"
                        )
                    else:
                        print(f"  · {data_type}: no data")
            except Exception as e:
                print(f"  ✗ {data_type}: error — {e}")
                stats[data_type] = 0

        total = sum(stats.values())
        print(f"\nOura sync complete! {total} total records synced.")
        return stats

    def get_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        try:
            self.db.init_tables()
            return {
                "database_stats": self.db.get_stats(),
                "sync_dates": self.db.get_sync_dates(),
                "has_token": not self.api.needs_auth(),
            }
        except Exception as e:
            return {
                "error": str(e),
                "has_token": not self.api.needs_auth(),
            }
