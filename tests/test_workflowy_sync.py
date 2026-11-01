import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from src.workflowy.api_client import WorkflowyAPIClient, WorkflowyAPIError, WorkflowyRateLimitError
from src.workflowy.database import WorkflowyDatabase
from src.workflowy.sync import WorkflowySyncManager
from src.workflowy.analytics import WorkflowyAnalytics


def node(node_id: str, **overrides):
    value = {
        "id": node_id,
        "parent_id": None,
        "name": f"Node {node_id}",
        "note": None,
        "priority": 100,
        "completed": False,
        "data": {"layoutMode": "bullets"},
        "createdAt": 1,
        "modifiedAt": 1,
        "completedAt": None,
    }
    value.update(overrides)
    return value


class FakeAPI:
    def __init__(self, exports):
        self.exports = list(exports)

    def export_all_nodes(self):
        result = self.exports.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def db(tmp_path: Path):
    database = WorkflowyDatabase(str(tmp_path / "workflowy.db"))
    database.init_tables()
    return database


def test_sync_inserts_updates_tombstones_and_reactivates(db):
    api = FakeAPI([[normalized(node("one")), normalized(node("two"))]])
    manager = WorkflowySyncManager(db=db, api=api)

    assert manager.sync() == {
        "fetched": 2, "inserted": 2, "updated": 0, "unchanged": 0, "tombstoned": 0,
    }

    api.exports.append([normalized(node("one", name="Changed", modifiedAt=2))])
    assert manager.sync() == {
        "fetched": 1, "inserted": 0, "updated": 1, "unchanged": 0, "tombstoned": 1,
    }

    with db.get_connection() as conn:
        rows = conn.execute("SELECT id, name, is_deleted FROM nodes ORDER BY id").fetchall()
    assert [(row["id"], row["name"], row["is_deleted"]) for row in rows] == [
        ("one", "Changed", 0), ("two", "Node two", 1),
    ]

    api.exports.append([normalized(node("one", name="Changed", modifiedAt=2)), normalized(node("two"))])
    stats = manager.sync()
    assert stats["updated"] == 1
    assert stats["tombstoned"] == 0
    assert db.get_sync_status()["tombstoned_nodes"] == 0


def test_failed_export_preserves_nodes_and_successful_state(db):
    manager = WorkflowySyncManager(db=db, api=FakeAPI([[normalized(node("one"))]]))
    manager.sync()
    before = db.get_sync_status()

    manager.api = FakeAPI([WorkflowyAPIError("bad export")])
    with pytest.raises(WorkflowyAPIError):
        manager.sync()

    after = db.get_sync_status()
    assert after["active_nodes"] == 1
    assert after["tombstoned_nodes"] == 0
    assert after["sync_state"]["last_successful_sync_at"] == before["sync_state"]["last_successful_sync_at"]


def test_api_client_sends_bearer_token_and_validates_payload():
    response = MagicMock(status_code=200)
    response.json.return_value = {"nodes": [node("one")]}
    session = MagicMock()
    session.get.return_value = response
    client = WorkflowyAPIClient(api_key="secret", session=session)

    result = client.export_all_nodes()

    assert result[0]["id"] == "one"
    assert session.get.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert session.get.call_args.args[0].endswith("/nodes-export")

    response.json.return_value = {"nodes": [node("one"), node("one")]}
    with pytest.raises(WorkflowyAPIError, match="duplicate"):
        client.export_all_nodes()


def test_api_client_rate_limit_is_actionable():
    response = MagicMock(status_code=429, headers={"Retry-After": "60"})
    session = MagicMock()
    session.get.return_value = response

    with pytest.raises(WorkflowyRateLimitError, match="one complete node export per minute"):
        WorkflowyAPIClient(api_key="secret", session=session).export_all_nodes()


def test_api_client_allows_null_modified_at():
    """modifiedAt can be null in the Workflowy API."""
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "nodes": [{
            "id": "one",
            "parent_id": None,
            "name": "Node one",
            "note": None,
            "priority": 100,
            "completed": False,
            "data": {"layoutMode": "bullets"},
            "createdAt": 1,
            "modifiedAt": None,
            "completedAt": None,
        }]
    }
    session = MagicMock()
    session.get.return_value = response
    client = WorkflowyAPIClient(api_key="secret", session=session)

    result = client.export_all_nodes()

    assert result[0]["id"] == "one"
    assert result[0]["modified_at"] is None


def normalized(raw):
    """Use the production normalizer so fake sync data matches client output."""
    return WorkflowyAPIClient._normalize_node(raw, set())


def timestamp(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def analysis_rows(db):
    with db.get_connection() as conn:
        return {
            row["year_month"]: (row["nodes_added"], row["nodes_modified"], row["nodes_removed"])
            for row in conn.execute("SELECT * FROM analysis")
        }


def test_monthly_activity_retains_edits_and_removals_across_restore(db, monkeypatch):
    jan = timestamp("2026-01-31T23:59:59Z")
    feb = timestamp("2026-02-01T00:00:00Z")
    mar = timestamp("2026-03-01T00:00:00Z")
    clock = {"now": "2026-02-02T00:00:00Z"}
    monkeypatch.setattr("src.workflowy.sync.utc_now_iso", lambda: clock["now"])
    first = normalized(node("one", createdAt=jan, modifiedAt=feb))
    second = normalized(node("two", createdAt=feb, modifiedAt=feb))
    third = normalized(node("three", createdAt=feb, modifiedAt=None))
    api = FakeAPI([[first, second, third]])
    manager = WorkflowySyncManager(db=db, api=api)
    analytics = WorkflowyAnalytics(db=db)
    manager.sync()
    analytics.analyze_nodes()
    assert analysis_rows(db) == {"2026-01": (1, 0, 0), "2026-02": (2, 1, 0)}

    # Two edits to the same node in February still count as one modified node.
    clock["now"] = "2026-02-20T00:00:00Z"
    api.exports.append([normalized(node("one", createdAt=jan, modifiedAt=feb + 10)), third])
    manager.sync()
    # Repeated exports must not record another removal.
    api.exports.append([normalized(node("one", createdAt=jan, modifiedAt=feb + 10)), third])
    manager.sync()
    analytics.analyze_nodes()
    assert analysis_rows(db)["2026-02"] == (2, 1, 1)

    clock["now"] = "2026-03-02T00:00:00Z"
    api.exports.append([normalized(node("one", createdAt=jan, modifiedAt=mar)), second, third])
    manager.sync()
    analytics.analyze_nodes()
    # The latest edit no longer overwrites the earlier month's activity.
    assert analysis_rows(db) == {
        "2026-01": (1, 0, 0), "2026-02": (2, 1, 1), "2026-03": (0, 1, 0),
    }
    clock["now"] = "2026-03-03T00:00:00Z"
    api.exports.append([normalized(node("one", createdAt=jan, modifiedAt=mar)), third])
    manager.sync()
    analytics.analyze_nodes()
    assert analysis_rows(db)["2026-03"] == (0, 1, 1)
    # Restoration doesn't add another creation; each month's removal survives.
    analytics.analyze_nodes()
    assert analysis_rows(db)["2026-02"] == (2, 1, 1)
    assert analysis_rows(db)["2026-03"] == (0, 1, 1)


def test_activity_history_rolls_back_with_failed_snapshot(db, monkeypatch):
    first = normalized(node("one", createdAt=1, modifiedAt=2))
    manager = WorkflowySyncManager(db=db, api=FakeAPI([[first]]))
    manager.sync()
    with db.get_connection() as conn:
        conn.execute(
            """CREATE TRIGGER fail_state BEFORE UPDATE OF last_successful_sync_at ON sync_state
               BEGIN SELECT RAISE(ABORT, 'snapshot failure'); END"""
        )
    manager.api = FakeAPI([[normalized(node("two", createdAt=3, modifiedAt=4))]])
    with pytest.raises(sqlite3.IntegrityError, match="snapshot failure"):
        manager.sync()
    with db.get_connection() as conn:
        assert conn.execute("SELECT node_id, modified_at FROM node_modifications").fetchall()[0][:] == ("one", 2)
        assert conn.execute("SELECT COUNT(*) FROM node_modifications").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM node_removals").fetchone()[0] == 0
        assert conn.execute("SELECT id, is_deleted FROM nodes").fetchall()[0][:] == ("one", 0)


def test_legacy_mirror_seeds_latest_edit_without_inventing_removal(db):
    jan = timestamp("2026-01-01T00:00:00Z")
    feb = timestamp("2026-02-01T00:00:00Z")
    with db.get_connection() as conn:
        db.upsert_node(normalized(node("legacy", createdAt=jan, modifiedAt=feb)), "2026-03-01T00:00:00Z", conn.cursor())
        conn.execute("UPDATE nodes SET is_deleted = 1")
        conn.execute("DROP TABLE node_modifications")
        conn.execute("DROP TABLE node_removals")
    analytics = WorkflowyAnalytics(db=db)
    analytics.analyze_nodes()
    assert analysis_rows(db) == {"2026-01": (1, 0, 0), "2026-02": (0, 1, 0)}
    analytics.analyze_nodes()
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM node_modifications").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM node_removals").fetchone()[0] == 0


def test_quiet_months_and_empty_snapshots(db, monkeypatch):
    analytics = WorkflowyAnalytics(db=db)
    assert analytics.analyze_nodes() == 0
    monkeypatch.setattr("src.workflowy.sync.utc_now_iso", lambda: "2026-03-01T00:00:00Z")
    manager = WorkflowySyncManager(db=db, api=FakeAPI([[]]))
    manager.sync()
    analytics.analyze_nodes()
    assert analysis_rows(db) == {"2026-03": (0, 0, 0)}
    manager.api = FakeAPI([[normalized(node("old", createdAt=timestamp("2025-12-31T23:59:59Z"), modifiedAt=None))]])
    manager.sync()
    analytics.analyze_nodes()
    assert analysis_rows(db) == {
        "2025-12": (1, 0, 0), "2026-01": (0, 0, 0),
        "2026-02": (0, 0, 0), "2026-03": (0, 0, 0),
    }
