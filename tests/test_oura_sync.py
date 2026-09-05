"""Tests for Oura SyncManager authentication and error handling."""

from unittest.mock import MagicMock
from src.oura.sync import OuraSyncManager


def test_oura_sync_manager_aborts_if_ensure_auth_fails():
    db = MagicMock()
    api = MagicMock()
    api.ensure_auth.return_value = False

    manager = OuraSyncManager(db=db, api=api)
    stats = manager.sync()

    assert stats == {}
    db.init_tables.assert_not_called()


def test_oura_sync_manager_stops_on_refresh_failure():
    db = MagicMock()
    api = MagicMock()
    api.ensure_auth.return_value = True
    api._refresh_failed = False

    # Simulate first fetch causing a refresh failure
    def mock_fetch(data_type, start, end):
        api._refresh_failed = True
        return []

    api.fetch_daily_data.side_effect = mock_fetch

    manager = OuraSyncManager(db=db, api=api)
    stats = manager.sync()

    # Should record 0 for endpoints and not raise or false-report up to date
    assert stats["daily_activity"] == 0
    # Remaining endpoints should be skipped because api._refresh_failed is True
    assert api.fetch_daily_data.call_count == 1
