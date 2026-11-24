"""Sync manager for Charles Schwab account data."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .api_client import SchwabAPIClient
from .database import SchwabDatabase


INITIAL_TRANSACTION_LOOKBACK_DAYS = 365
SNAPSHOT_MIN_INTERVAL_HOURS = 24


def _schwab_datetime(dt: datetime) -> str:
    """Format a datetime for Schwab transaction query parameters."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_sync_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO sync timestamp."""
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None


class SchwabSyncManager:
    """Orchestrates synchronization of Schwab account snapshots and transactions."""

    ENTITY_ACCOUNT_SNAPSHOTS = "account_snapshots"
    ENTITY_TRANSACTIONS_PREFIX = "transactions"

    def __init__(
        self,
        db: Optional[SchwabDatabase] = None,
        api: Optional[SchwabAPIClient] = None,
    ):
        """Initialize sync manager."""
        self.db = db or SchwabDatabase()
        self.api = api or SchwabAPIClient()

    def ensure_auth(self) -> bool:
        """Ensure Schwab authentication is available."""
        if self.api.ensure_auth():
            return True
        print("Error: Failed to authenticate with Charles Schwab")
        return False

    def _account_hashes_by_number(self) -> Dict[str, str]:
        """Return a plain account number to hash lookup."""
        pairs = self.api.get_account_numbers()
        return {
            str(pair["accountNumber"]): str(pair["hashValue"])
            for pair in pairs
            if pair.get("accountNumber") and pair.get("hashValue")
        }

    def _transaction_window(self, account_hash: str, sync_start: datetime) -> tuple[str, str]:
        """Return transaction fetch start/end dates for an account."""
        latest_transaction = _parse_sync_datetime(
            self.db.get_latest_transaction_time(account_hash)
        )

        if latest_transaction:
            start = latest_transaction
        else:
            start = sync_start - timedelta(days=INITIAL_TRANSACTION_LOOKBACK_DAYS)

        return _schwab_datetime(start), _schwab_datetime(sync_start)

    def sync(self) -> Dict[str, Any]:
        """Sync Schwab account snapshots and transactions."""
        stats = {
            "account_snapshots": 0,
            "transactions": 0,
            "accounts": 0,
        }

        if not self.ensure_auth():
            raise RuntimeError("Could not authenticate with Charles Schwab.")

        self.db.init_tables()

        sync_start = datetime.now(timezone.utc)
        sync_start_iso = sync_start.isoformat().replace("+00:00", "Z")

        print("Syncing Charles Schwab accounts...")
        hash_by_number = self._account_hashes_by_number()
        accounts = self.api.get_accounts()
        stats["accounts"] = len(accounts)
        synced_account_hashes = set()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for wrapper in accounts:
                account = wrapper.get("securitiesAccount", wrapper)
                account_number = str(account.get("accountNumber", ""))
                account_hash = hash_by_number.get(account_number, account_number)

                if not account_hash:
                    print("  Skipping account without account number/hash")
                    continue
                synced_account_hashes.add(account_hash)

                # Skip snapshot if one was taken recently
                snapshot_skipped = False
                latest_snapshot = _parse_sync_datetime(
                    self.db.get_latest_snapshot_time(account_hash)
                )
                if latest_snapshot:
                    hours_since = (sync_start - latest_snapshot).total_seconds() / 3600
                    if hours_since < SNAPSHOT_MIN_INTERVAL_HOURS:
                        snapshot_skipped = True

                if not snapshot_skipped:
                    self.db.insert_account_snapshot(
                        wrapper,
                        account_hash=account_hash,
                        snapshot_at=sync_start_iso,
                        cursor=cursor,
                    )
                    stats["account_snapshots"] += 1

                start_date, end_date = self._transaction_window(account_hash, sync_start)
                transactions = self.api.get_transactions(account_hash, start_date, end_date)

                new_txn_count = 0
                for transaction in transactions:
                    if self.db.upsert_transaction(
                        transaction,
                        account_hash=account_hash,
                        account_number=account_number,
                        cursor=cursor,
                    ):
                        stats["transactions"] += 1
                        new_txn_count += 1

                snapshot_msg = "snapshot saved" if not snapshot_skipped else "snapshot skipped (recent)"
                print(
                    f"  {account_hash[:8]}...: {snapshot_msg}, "
                    f"{len(transactions)} transactions fetched, {new_txn_count} new"
                )

        self.db.update_sync_state(self.ENTITY_ACCOUNT_SNAPSHOTS, sync_start_iso)
        for account_hash in synced_account_hashes:
            self.db.update_sync_state(
                f"{self.ENTITY_TRANSACTIONS_PREFIX}:{account_hash}",
                sync_start_iso,
            )

        print("\nSchwab sync complete!")
        print(f"  Accounts: {stats['accounts']}")
        print(f"  Account snapshots: {stats['account_snapshots']}")
        print(f"  Transactions: {stats['transactions']}")

        return stats

    def get_status(self) -> Dict[str, Any]:
        """Get current Schwab sync status."""
        try:
            self.db.init_tables()
            return {
                "database_stats": self.db.get_stats(),
                "has_token": not self.api.needs_auth(),
            }
        except Exception as e:
            return {
                "error": str(e),
                "has_token": not self.api.needs_auth(),
            }
