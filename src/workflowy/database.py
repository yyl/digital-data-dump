"""SQLite persistence for Workflowy node exports."""

import sqlite3
from typing import Any, Dict, Optional

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_INDEXES, RAW_TABLES


class WorkflowyDatabase(BaseDatabase):
    """Manage the local, tombstone-preserving Workflowy mirror."""

    ENTITY_NODES = "nodes"

    def __init__(self, db_path: Optional[str] = None):
        super().__init__(str(db_path or Config.WORKFLOWY_DATABASE_PATH))

    def init_tables(self) -> None:
        is_new = not self.exists()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for statement in RAW_TABLES:
                cursor.execute(statement)
            for statement in RAW_INDEXES:
                cursor.execute(statement)
        if is_new:
            print(f"Workflowy database initialized at: {self.db_path}")

    def record_export_started(self, timestamp: str) -> None:
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (entity_type, last_export_started_at)
                VALUES (?, ?)
                ON CONFLICT(entity_type) DO UPDATE SET
                    last_export_started_at = excluded.last_export_started_at
                """,
                (self.ENTITY_NODES, timestamp),
            )

    def upsert_node(self, node: Dict[str, Any], sync_time: str, cursor: sqlite3.Cursor) -> str:
        """Upsert one validated node and return inserted, updated, or unchanged."""
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node["id"],))
        existing = cursor.fetchone()
        source_columns = (
            "parent_id", "name", "note", "priority", "layout_mode", "completed",
            "created_at", "modified_at", "completed_at", "raw_json",
        )
        if existing:
            changed = any(existing[column] != self._db_value(column, node) for column in source_columns)
            if not changed and not existing["is_deleted"]:
                cursor.execute(
                    "UPDATE nodes SET last_seen_at = ? WHERE id = ?",
                    (sync_time, node["id"]),
                )
                return "unchanged"

            cursor.execute(
                """
                UPDATE nodes SET
                    parent_id = ?, name = ?, note = ?, priority = ?, layout_mode = ?,
                    completed = ?, created_at = ?, modified_at = ?, completed_at = ?,
                    is_deleted = 0, last_seen_at = ?, raw_json = ?
                WHERE id = ?
                """,
                self._source_values(node) + (sync_time, node["raw_json"], node["id"]),
            )
            return "updated"

        cursor.execute(
            """
            INSERT INTO nodes (
                id, parent_id, name, note, priority, layout_mode, completed,
                created_at, modified_at, completed_at, is_deleted, first_seen_at,
                last_seen_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (node["id"],) + self._source_values(node) + (sync_time, sync_time, node["raw_json"]),
        )
        return "inserted"

    def tombstone_missing_nodes(self, sync_time: str, cursor: sqlite3.Cursor) -> int:
        cursor.execute(
            """
            UPDATE nodes
            SET is_deleted = 1
            WHERE is_deleted = 0 AND last_seen_at < ?
            """,
            (sync_time,),
        )
        return cursor.rowcount

    def update_sync_state(self, sync_time: str, stats: Dict[str, int], cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            INSERT INTO sync_state (
                entity_type, last_successful_sync_at, last_export_node_count,
                last_inserted_count, last_updated_count, last_unchanged_count,
                last_tombstoned_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type) DO UPDATE SET
                last_successful_sync_at = excluded.last_successful_sync_at,
                last_export_node_count = excluded.last_export_node_count,
                last_inserted_count = excluded.last_inserted_count,
                last_updated_count = excluded.last_updated_count,
                last_unchanged_count = excluded.last_unchanged_count,
                last_tombstoned_count = excluded.last_tombstoned_count
            """,
            (
                self.ENTITY_NODES,
                sync_time,
                stats["fetched"],
                stats["inserted"],
                stats["updated"],
                stats["unchanged"],
                stats["tombstoned"],
            ),
        )

    def get_sync_status(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM nodes WHERE is_deleted = 0")
            active = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM nodes WHERE is_deleted = 1")
            deleted = cursor.fetchone()[0]
            cursor.execute("SELECT * FROM sync_state WHERE entity_type = ?", (self.ENTITY_NODES,))
            row = cursor.fetchone()
        return {"active_nodes": active, "tombstoned_nodes": deleted, "sync_state": dict(row) if row else None}

    @staticmethod
    def _db_value(column: str, node: Dict[str, Any]) -> Any:
        if column == "completed":
            return 1 if node["completed"] else 0
        return node[column]

    @staticmethod
    def _source_values(node: Dict[str, Any]) -> tuple[Any, ...]:
        return (
            node["parent_id"], node["name"], node["note"], node["priority"],
            node["layout_mode"], 1 if node["completed"] else 0,
            node["created_at"], node["modified_at"], node["completed_at"],
        )
