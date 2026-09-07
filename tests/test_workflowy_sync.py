import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from src.workflowy.api_client import WorkflowyAPIClient, WorkflowyAPIError, WorkflowyRateLimitError
from src.workflowy.database import WorkflowyDatabase
from src.workflowy.sync import WorkflowySyncManager


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
