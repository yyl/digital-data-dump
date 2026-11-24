from unittest.mock import Mock

import pytest

from src.config import Config
from src.foursquare.api_client import FoursquareAPIError
from src.foursquare.database import FoursquareDatabase
from src.foursquare.sync import FoursquareSyncManager


def test_existing_cursor_survives_empty_sync_and_failed_write(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    db = FoursquareDatabase(str(tmp_path / "foursquare.db"))
    db.init_tables()
    db.upsert_user("user", 123)
    api = Mock()
    api.needs_auth.return_value = False
    api.get_user_id.return_value = "user"
    api.fetch_place_details.return_value = None
    manager = FoursquareSyncManager(db=db, api=api)

    api.fetch_checkins.return_value = []
    assert manager.sync()["checkins"] == 0
    api.fetch_checkins.assert_called_once_with(after_timestamp=123)
    assert db.get_last_pulled_timestamp("user") == 123

    checkin = {"id": "new", "createdAt": 124, "venue": {"id": "venue", "name": "Venue"}}
    api.fetch_checkins.return_value = [checkin, {"id": "invalid", "createdAt": 125}]
    with pytest.raises(FoursquareAPIError, match="missing required fields"):
        manager.sync()
    assert db.get_last_pulled_timestamp("user") == 123
    assert db.get_stats()["checkins"] == 0

    api.fetch_checkins.return_value = [checkin]
    assert manager.sync()["checkins"] == 1
    assert db.get_last_pulled_timestamp("user") == 124
    db.upsert_user("user", 123)
    assert db.get_last_pulled_timestamp("user") == 124
