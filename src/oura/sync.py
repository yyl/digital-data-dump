"""Sync manager for Oura Ring data synchronization."""

from datetime import date, timedelta
from typing import Optional, Dict, Any

from .database import OuraDatabase
from .api_client import GEN3_ENDPOINTS, OuraAPIClient, OuraAPIError, OuraAuthenticationError


# Default start date for initial full sync
DEFAULT_START_DATE = "2020-01-01"


class OuraSyncManager:
    """Orchestrates synchronization of Oura Ring data."""

    # Map data types to their database upsert methods
    UPSERT_METHODS = {
        "daily_activity": "upsert_daily_activity",
        "daily_sleep": "upsert_daily_sleep",
        "daily_readiness": "upsert_daily_readiness",
        "daily_stress": "upsert_daily_stress",
        "daily_resilience": "upsert_daily_resilience",
        "daily_spo2": "upsert_daily_spo2",
        "daily_cardiovascular_age": "upsert_daily_cardiovascular_age",
        "sleep_periods": "upsert_sleep_period",
        "sleep_time": "upsert_sleep_time",
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

    def _sync_data_type(self, data_type: str) -> int | None:
        """Sync a single data type.

        Args:
            data_type: One of the UPSERT_METHODS keys.

        Returns:
            Number of records synced, or None when an optional endpoint was skipped.
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

        if records is None:
            return None
        if not records:
            return 0

        # Upsert all records, but only count genuinely new ones
        # (records from the overlapping re-fetched day are upserted
        # for freshness but don't count as new syncs)
        new_count = 0
        latest_day = last_sync or ""
        for record in records:
            day = record["day"]
            if date.fromisoformat(day).isoformat() != day:
                raise OuraAPIError(f"Oura returned an invalid day for {data_type}.")
            upsert_method(record)
            latest_day = max(latest_day, day)
            if not last_sync or day > last_sync:
                new_count += 1

        # Update sync state with the latest day we've seen
        if latest_day:
            self.db.set_last_sync_date(data_type, latest_day)

        return new_count

    def sync(self) -> Dict[str, Any]:
        """Sync all supported data types.

        Returns:
            Dictionary with sync statistics per data type.
        """
        stats = {}

        # Ensure authentication
        if not self.ensure_auth():
            raise OuraAuthenticationError("Could not authenticate with Oura Ring.")

        # Initialize database
        self.db.init_tables()

        print("Syncing Oura Ring data...")

        failures = []
        for data_type in self.UPSERT_METHODS:
            try:
                count = self._sync_data_type(data_type)
            except OuraAuthenticationError:
                raise
            except Exception as e:
                print(f"  ✗ {data_type}: error — {e}")
                failures.append(data_type)
                continue

            stats[data_type] = count or 0
            if count is None:
                continue
            if count:
                print(f"  ✓ {data_type}: {count} records")
            elif self.db.get_last_sync_date(data_type):
                print(f"  · {data_type}: up to date")
            elif data_type in GEN3_ENDPOINTS:
                print(f"  · {data_type}: no data (may require Gen 3+ or an active membership)")
            else:
                print(f"  · {data_type}: no data")

        if failures:
            raise OuraAPIError(f"Oura sync incomplete for {', '.join(failures)}.")
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
