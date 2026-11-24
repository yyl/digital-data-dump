"""SQLite database manager for Charles Schwab data."""

import json
import sqlite3
import time
from typing import Any, Dict, Optional

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_INDEXES, RAW_TABLES


class SchwabDatabase(BaseDatabase):
    """Manages SQLite database for Charles Schwab account snapshots and transactions."""

    source_name = "Charles Schwab"
    raw_table_names = frozenset({"account_snapshots", "transactions", "transaction_items", "sync_state"})
    analysis_table_names = frozenset({"monthly_pnl", "monthly_account_snapshots"})

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager."""
        super().__init__(db_path or str(Config.SCHWAB_DATABASE_PATH))
        self.use_foreign_keys = True

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
            print(f"Schwab database initialized at: {self.db_path}")

    # ==========================================================================
    # Sync State
    # ==========================================================================

    def get_sync_state(self, entity_type: str) -> Optional[Dict[str, Any]]:
        """Get sync state for an entity type."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sync_state WHERE entity_type = ?",
                (entity_type,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_sync_state(self, entity_type: str, last_sync_at: str) -> None:
        """Update sync state for an entity type."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sync_state (entity_type, last_sync_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(entity_type) DO UPDATE SET
                    last_sync_at = excluded.last_sync_at,
                    updated_at = excluded.updated_at
                """,
                (entity_type, last_sync_at, int(time.time())),
            )

    # ==========================================================================
    # Account Snapshots
    # ==========================================================================

    def insert_account_snapshot(
        self,
        account: Dict[str, Any],
        account_hash: str,
        snapshot_at: str,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> None:
        """Insert an append-only account balance snapshot."""
        securities_account = account.get("securitiesAccount", account)
        current_balances = securities_account.get("currentBalances", {})
        initial_balances = securities_account.get("initialBalances", {})
        projected_balances = securities_account.get("projectedBalances", {})

        params = (
            account_hash,
            securities_account.get("accountNumber"),
            snapshot_at,
            securities_account.get("type"),
            current_balances.get("liquidationValue")
            or initial_balances.get("liquidationValue")
            or initial_balances.get("accountValue"),
            current_balances.get("equity") or initial_balances.get("equity"),
            current_balances.get("cashBalance") or initial_balances.get("cashBalance"),
            current_balances.get("buyingPower") or initial_balances.get("buyingPower"),
            json.dumps(current_balances, sort_keys=True),
            json.dumps(initial_balances, sort_keys=True),
            json.dumps(projected_balances, sort_keys=True),
            json.dumps(account, sort_keys=True),
        )

        if cursor:
            self._insert_account_snapshot(cursor, params)
            return

        with self.get_connection() as conn:
            self._insert_account_snapshot(conn.cursor(), params)

    def get_latest_snapshot_time(self, account_hash: str) -> Optional[str]:
        """Get the latest snapshot timestamp for an account hash."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT MAX(snapshot_at) AS latest_snapshot
                FROM account_snapshots
                WHERE account_hash = ?
                """,
                (account_hash,),
            )
            row = cursor.fetchone()
            return row["latest_snapshot"] if row and row["latest_snapshot"] else None

    def _insert_account_snapshot(self, cursor: sqlite3.Cursor, params: tuple) -> None:
        """Insert an account snapshot using an existing cursor."""
        cursor.execute(
            """
            INSERT INTO account_snapshots (
                account_hash, account_number, snapshot_at, account_type,
                liquidation_value, equity, cash_balance, buying_power,
                current_balances_json, initial_balances_json,
                projected_balances_json, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )

    # ==========================================================================
    # Transactions
    # ==========================================================================

    def get_latest_transaction_time(self, account_hash: str) -> Optional[str]:
        """Get the latest stored transaction timestamp for an account hash."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COALESCE(MAX(time), MAX(trade_date)) AS latest_time
                FROM transactions
                WHERE account_hash = ?
                """,
                (account_hash,),
            )
            row = cursor.fetchone()
            return row["latest_time"] if row and row["latest_time"] else None

    def upsert_transaction(
        self,
        transaction: Dict[str, Any],
        account_hash: str,
        account_number: Optional[str],
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> bool:
        """Insert or update a Schwab transaction. Returns True only for new inserts."""
        transaction_id = transaction.get("activityId")
        if transaction_id is None:
            return False

        tid = str(transaction_id)

        params = (
            account_hash,
            tid,
            transaction.get("accountNumber") or account_number,
            transaction.get("time"),
            transaction.get("tradeDate"),
            transaction.get("type"),
            transaction.get("status"),
            transaction.get("subAccount"),
            str(transaction["positionId"]) if transaction.get("positionId") is not None else None,
            str(transaction["orderId"]) if transaction.get("orderId") is not None else None,
            transaction.get("netAmount"),
            json.dumps(transaction, sort_keys=True),
        )

        def _do(cur: sqlite3.Cursor) -> bool:
            cur.execute(
                "SELECT 1 FROM transactions WHERE account_hash = ? AND transaction_id = ?",
                (account_hash, tid),
            )
            is_new = cur.fetchone() is None
            self._upsert_transaction(cur, params)
            self._upsert_transaction_items(cur, transaction, account_hash, tid)
            return is_new

        if cursor:
            return _do(cursor)

        with self.get_connection() as conn:
            return _do(conn.cursor())

    def _upsert_transaction(self, cursor: sqlite3.Cursor, params: tuple) -> None:
        """Upsert a transaction using an existing cursor."""
        cursor.execute(
            """
            INSERT INTO transactions (
                account_hash, transaction_id, account_number, time, trade_date,
                type, status, sub_account, position_id, order_id, net_amount, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_hash, transaction_id) DO UPDATE SET
                account_number = excluded.account_number,
                time = excluded.time,
                trade_date = excluded.trade_date,
                type = excluded.type,
                status = excluded.status,
                sub_account = excluded.sub_account,
                position_id = excluded.position_id,
                order_id = excluded.order_id,
                net_amount = excluded.net_amount,
                raw_json = excluded.raw_json,
                synced_at = strftime('%s', 'now')
            """,
            params,
        )

    def _upsert_transaction_items(
        self,
        cursor: sqlite3.Cursor,
        transaction: Dict[str, Any],
        account_hash: str,
        transaction_id: str,
    ) -> None:
        """Upsert all transferItems rows for a transaction."""
        for idx, item in enumerate(transaction.get("transferItems") or []):
            instrument = item.get("instrument") or {}
            cursor.execute(
                """
                INSERT INTO transaction_items (
                    account_hash, transaction_id, item_index,
                    asset_type, instrument_id, symbol, description,
                    instrument_type, closing_price,
                    amount, cost, price, fee_type, position_effect,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_hash, transaction_id, item_index) DO UPDATE SET
                    asset_type       = excluded.asset_type,
                    instrument_id    = excluded.instrument_id,
                    symbol           = excluded.symbol,
                    description      = excluded.description,
                    instrument_type  = excluded.instrument_type,
                    closing_price    = excluded.closing_price,
                    amount           = excluded.amount,
                    cost             = excluded.cost,
                    price            = excluded.price,
                    fee_type         = excluded.fee_type,
                    position_effect  = excluded.position_effect,
                    raw_json         = excluded.raw_json
                """,
                (
                    account_hash,
                    transaction_id,
                    idx,
                    instrument.get("assetType"),
                    instrument.get("instrumentId"),
                    instrument.get("symbol"),
                    instrument.get("description"),
                    instrument.get("type"),
                    instrument.get("closingPrice"),
                    item.get("amount"),
                    item.get("cost"),
                    item.get("price"),
                    item.get("feeType"),
                    item.get("positionEffect"),
                    json.dumps(item, sort_keys=True),
                ),
            )

    # ==========================================================================
    # Statistics
    # ==========================================================================

    def get_stats(self) -> Dict[str, int]:
        """Get counts of all synced entities."""
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table in ["account_snapshots", "transactions", "transaction_items",
                       "monthly_pnl", "monthly_account_snapshots"]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
        return stats
