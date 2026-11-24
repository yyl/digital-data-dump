"""Tests for Oura SyncManager authentication and error handling."""

from unittest.mock import MagicMock

import pytest

from src.oura.api_client import OuraAPIError, OuraAuthenticationError
from src.oura.sync import OuraSyncManager


def test_oura_sync_manager_aborts_if_ensure_auth_fails():
    db = MagicMock()
    api = MagicMock()
    api.ensure_auth.return_value = False

    manager = OuraSyncManager(db=db, api=api)
    with pytest.raises(OuraAuthenticationError, match="authenticate"):
        manager.sync()
    db.init_tables.assert_not_called()


def test_oura_sync_manager_stops_on_refresh_failure():
    db = MagicMock()
    api = MagicMock()
    api.ensure_auth.return_value = True
    api.fetch_daily_data.side_effect = OuraAuthenticationError("fixture authentication failure")

    manager = OuraSyncManager(db=db, api=api)
    with pytest.raises(OuraAuthenticationError, match="fixture authentication failure"):
        manager.sync()
    assert api.fetch_daily_data.call_count == 1


def test_oura_failed_write_preserves_endpoint_cursor_for_retry():
    db = MagicMock()
    db.get_last_sync_date.return_value = "2026-09-01"
    db.upsert_daily_activity.side_effect = ValueError("fixture write failure")
    api = MagicMock()
    api.ensure_auth.return_value = True
    records = [{"day": "2026-09-02"}, {"day": "2026-09-03"}]
    api.fetch_daily_data.side_effect = lambda kind, *_: records if kind == "daily_activity" else []
    manager = OuraSyncManager(db=db, api=api)

    with pytest.raises(OuraAPIError, match="daily_activity"):
        manager.sync()
    db.set_last_sync_date.assert_not_called()
    assert api.fetch_daily_data.call_count == len(manager.UPSERT_METHODS)

    db.upsert_daily_activity.side_effect = None
    assert manager.sync()["daily_activity"] == 2
    db.set_last_sync_date.assert_called_once_with("daily_activity", "2026-09-03")
