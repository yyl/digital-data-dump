"""Workflowy full-snapshot sync orchestration."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from ..time_utils import utc_now_iso
from .api_client import WorkflowyAPIClient
from .database import WorkflowyDatabase


class WorkflowySyncInProgressError(RuntimeError):
    """Raised when another Workflowy sync currently owns the source lock."""


class WorkflowySyncManager:
    """Apply one validated Workflowy export as an atomic local snapshot."""

    def __init__(
        self,
        db: Optional[WorkflowyDatabase] = None,
        api: Optional[WorkflowyAPIClient] = None,
    ):
        self.db = db or WorkflowyDatabase()
        self.api = api or WorkflowyAPIClient()

    def sync(self) -> Dict[str, int]:
        self.db.init_tables()
        with self._exclusive_lock():
            export_started_at = utc_now_iso()
            self.db.record_export_started(export_started_at)
            nodes = self.api.export_all_nodes()
            sync_time = utc_now_iso()
            stats = {"fetched": len(nodes), "inserted": 0, "updated": 0, "unchanged": 0, "tombstoned": 0}

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                for node in nodes:
                    outcome = self.db.upsert_node(node, sync_time, cursor)
                    stats[outcome] += 1
                stats["tombstoned"] = self.db.tombstone_missing_nodes(sync_time, cursor)
                self.db.update_sync_state(sync_time, stats, cursor)

        print(
            "Workflowy sync complete: "
            f"{stats['fetched']} fetched, {stats['inserted']} inserted, "
            f"{stats['updated']} updated, {stats['unchanged']} unchanged, "
            f"{stats['tombstoned']} tombstoned"
        )
        return stats

    def get_status(self) -> Dict[str, Any]:
        self.db.init_tables()
        return self.db.get_sync_status()

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        lock_path = Path(f"{self.db.db_path}.sync.lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WorkflowySyncInProgressError("A Workflowy sync is already running.") from exc
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
