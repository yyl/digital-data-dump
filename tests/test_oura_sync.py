"""Tests for Oura SyncManager authentication and error handling."""

import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from src.oura.api_client import OuraAPIClient, OuraAPIError, OuraAuthenticationError
from src.oura.database import OuraDatabase
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


def test_oura_skipped_endpoint_preserves_cursor_and_sync_continues(capsys):
    db = MagicMock()
    db.get_last_sync_date.return_value = "2026-09-01"
    api = MagicMock()
    api.ensure_auth.return_value = True
    api.fetch_daily_data.side_effect = lambda kind, *_: None if kind == "daily_resilience" else []
    manager = OuraSyncManager(db=db, api=api)

    assert manager.sync()["daily_resilience"] == 0
    assert api.fetch_daily_data.call_count == len(manager.UPSERT_METHODS)
    db.set_last_sync_date.assert_not_called()
    assert "daily_resilience: up to date" not in capsys.readouterr().out


def test_oura_sync_adds_detailed_sleep_to_existing_database(tmp_path, monkeypatch):
    db = OuraDatabase(str(tmp_path / "oura.db"))
    db.init_tables()
    with db.get_connection() as conn:
        conn.execute("DROP TABLE sleep_periods")
        conn.execute("DROP TABLE sleep_time")
    with db.read_connection(required_tables=("daily_sleep",)) as conn:
        assert conn is not None

    day = "2026-09-01"
    overnight = {"id": "overnight", "day": day, "hrv": {"items": [None, 57]}}
    nap = {"id": "nap", "day": day, "type": "nap"}
    recommendation = {"id": "bedtime", "day": day, "optimal_bedtime": {"day_tz": 0}}
    api = OuraAPIClient(access_token="fixture")
    monkeypatch.setattr(api, "ensure_auth", lambda: True)

    def request(url, params):
        if url.endswith("/sleep"):
            if params.get("next_token") == "next":
                return {"data": [nap]}
            return {"data": [overnight], "next_token": "next"}
        if url.endswith("/sleep_time"):
            return {"data": [recommendation]}
        return {"data": []}

    make_request = MagicMock(side_effect=request)
    monkeypatch.setattr(api, "_make_request", make_request)
    manager = OuraSyncManager(db=db, api=api)
    stats = manager.sync()
    assert (stats["sleep_periods"], stats["sleep_time"]) == (2, 1)
    assert db.get_last_sync_date("sleep_periods") == day
    assert db.get_last_sync_date("sleep_time") == day

    overnight["hrv"]["items"].append(60)
    stats = manager.sync()
    assert (stats["sleep_periods"], stats["sleep_time"]) == (0, 0)
    make_request.assert_any_call(
        f"{api.BASE_URL}/v2/usercollection/sleep",
        {"start_date": day, "end_date": date.today().isoformat(), "next_token": "next"},
    )
    with db.get_connection() as conn:
        stored_periods = conn.execute("SELECT payload_json FROM sleep_periods ORDER BY id")
        assert [json.loads(row[0]) for row in stored_periods] == [nap, overnight]
        stored_recommendation = conn.execute("SELECT payload_json FROM sleep_time").fetchone()
        assert json.loads(stored_recommendation[0]) == recommendation
