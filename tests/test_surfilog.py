"""Surfilog snapshots, local calendar months, wave corrections, and publishing."""

from copy import deepcopy
import json
import sqlite3
from unittest.mock import MagicMock

import pytest

import main
from src.config import Config
from src.publish.publisher import Publisher
from src.surfilog.analytics import SurfilogAnalytics
from src.surfilog.api_client import SurfilogAPIError
from src.surfilog.database import SurfilogDatabase
from src.surfilog.sync import SurfilogSyncManager, normalize_session


def session_payload(session_id=1, started_at="2026-10-26T16:09:15Z", offset=-420):
    """Synthetic data shaped like the inspected session detail response."""
    coords = [{"ts": started_at, "lat": 37.0, "lon": -122.0, "speedKmh": 15.5}]
    return {
        "session": {
            "id": session_id, "name": "Synthetic surf session", "started_at": started_at,
            "utc_offset_min": offset, "duration_sec": 3600, "wave_count": 2,
            "public_token": "share-token-must-not-be-stored",
            "session_metrics": {"paddlingDistanceM": 1234},
        },
        "waves": [
            {"id": session_id * 100 + 1, "session_id": session_id, "wave_num": 1,
             "start_time": started_at, "duration_sec": 10, "distance_m": "40.25",
             "max_speed_kmh": "15.50", "is_excluded": False,
             "start_lat": "37.0", "start_lon": "-122.0", "coords_json": coords},
            {"id": session_id * 100 + 2, "session_id": session_id, "wave_num": 2,
             "start_time": started_at, "duration_sec": 20, "distance_m": "90.00",
             "max_speed_kmh": "29.90", "is_excluded": True,
             "start_lat": None, "start_lon": None, "coords_json": []},
        ],
        "trackPoints": [{"ts": started_at, "lat": "37.0", "lon": "-122.0", "speed_kmh": "3.10", "hr": 100}],
    }


class FakeAPI:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.user_id = 7
        self.logins = 0

    def login(self):
        self.logins += 1

    def get_sessions(self):
        return [{"id": payload["session"]["id"]} for payload in self.payloads]

    def get_session(self, session_id):
        return deepcopy(next(p for p in self.payloads if p["session"]["id"] == session_id))


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    return SurfilogDatabase(tmp_path / "surfilog.db")


def raw_snapshot(db):
    with db.get_connection() as conn:
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ("sessions", "waves", "sync_state")}


def analysis(db):
    return db.fetch_rows("SELECT * FROM analysis ORDER BY year_month")


def test_repeat_sync_preserves_wave_details_and_refreshes_corrections(db):
    api = FakeAPI(session_payload())
    manager = SurfilogSyncManager(db, api)
    assert manager.sync() == {"sessions": 1, "waves": 1, "excluded_waves": 1}
    manager.sync()
    assert api.logins == 2
    assert db.get_stats() == {"sessions": 1, "waves": 1, "excluded_waves": 1}
    with db.get_connection() as conn:
        session = dict(conn.execute("SELECT * FROM sessions").fetchone())
        wave = dict(conn.execute("SELECT * FROM waves WHERE id = 101").fetchone())
    assert session["local_started_at"] == "2026-10-26T09:09:15-07:00"
    assert session["reported_wave_count"] == 2
    assert "public_token" not in json.loads(session["raw_json"])
    assert json.loads(session["track_points_json"]) == api.payloads[0]["trackPoints"]
    assert wave["distance_m"] == 40.25
    assert wave["max_speed_kmh"] == 15.5
    assert json.loads(wave["coords_json"]) == api.payloads[0]["waves"][0]["coords_json"]
    assert json.loads(wave["raw_json"])["id"] == 101

    SurfilogAnalytics(db).analyze_sessions()
    row = analysis(db)[0]
    assert row["sessions"] == 1
    assert row["waves"] == 1  # Excluded rides remain raw but don't count.
    assert row["total_duration_seconds"] == 3600
    assert row["surf_time_seconds"] == 10
    assert row["surf_distance_m"] == 40.25
    assert row["max_speed_kmh"] == 15.5
    assert row["median_wave_seconds"] == 10
    assert row["median_speed_kmh"] == 15.5
    assert row["paddling_distance_m"] == 1234

    # Restore a ride; metrics refresh without counting repeated downloads twice.
    api.payloads[0]["waves"][1]["is_excluded"] = False
    manager.sync()
    SurfilogAnalytics(db).analyze_sessions()
    row = analysis(db)[0]
    assert row["waves"] == 2
    assert row["surf_distance_m"] == 130.25
    assert row["surf_time_seconds"] == 30
    assert row["max_speed_kmh"] == 29.9
    assert row["longest_wave_m"] == 90
    assert row["max_wave_seconds"] == 20
    assert row["median_wave_seconds"] == 15
    assert row["median_speed_kmh"] == pytest.approx(22.7)
    assert row["total_duration_seconds"] == 3600  # No multiplication by wave count.


@pytest.mark.parametrize("started,offset,month", [
    ("2027-01-01T00:15:00Z", -420, "2026-12"),
    ("2026-01-31T15:00:00Z", 840, "2026-02"),
    ("2026-11-01T05:00:00Z", 0, "2026-11"),
    ("2026-11-01T05:00:00Z", None, "2026-11"),
])
def test_month_follows_session_local_date_not_upload_date(db, started, offset, month):
    payload = session_payload(started_at=started, offset=offset)
    payload["session"]["created_at"] = "2027-06-01T00:00:00Z"
    SurfilogSyncManager(db, FakeAPI(payload)).sync()
    SurfilogAnalytics(db).analyze_sessions()
    assert analysis(db)[0]["year_month"] == month


def test_reprocessed_waves_deleted_sessions_and_empty_account_clear_old_metrics(db):
    api = FakeAPI(session_payload(), session_payload(2, "2026-09-01T16:00:00Z"))
    manager = SurfilogSyncManager(db, api)
    manager.sync()
    SurfilogAnalytics(db).analyze_sessions()
    assert len(analysis(db)) == 2
    api.payloads = [session_payload()]
    api.payloads[0]["waves"] = []
    manager.sync()
    SurfilogAnalytics(db).analyze_sessions()
    assert db.get_stats() == {"sessions": 1, "waves": 0, "excluded_waves": 0}
    assert len(analysis(db)) == 1
    assert analysis(db)[0]["waves"] == 0
    assert analysis(db)[0]["median_wave_seconds"] is None
    assert analysis(db)[0]["median_speed_kmh"] is None
    api.payloads = []
    manager.sync()
    SurfilogAnalytics(db).analyze_sessions()
    assert analysis(db) == []
    assert db.get_stats() == {"sessions": 0, "waves": 0, "excluded_waves": 0}


def test_failed_later_request_preserves_complete_previous_snapshot(db):
    api = FakeAPI(session_payload())
    manager = SurfilogSyncManager(db, api)
    manager.sync()
    before = raw_snapshot(db)
    api.payloads.append(session_payload(2))
    api.get_session = MagicMock(side_effect=[session_payload(), SurfilogAPIError("HTTP 500")])
    with pytest.raises(SurfilogAPIError, match="HTTP 500"):
        manager.sync()
    assert raw_snapshot(db) == before


@pytest.mark.parametrize("change", [
    lambda p: p["session"].update(duration_sec=float("nan")),
    lambda p: p["session"].update(utc_offset_min=9999),
    lambda p: p["session"].update(started_at="2026-10-26T09:09:15"),
    lambda p: p["waves"][0].update(distance_m=-1),
    lambda p: p["waves"][0].update(is_excluded="false"),
    lambda p: p["waves"][0].update(session_id=999),
    lambda p: p["waves"][0].update(coords_json={"unexpected": "object"}),
    lambda p: p["waves"][1].update(id=101),
    lambda p: p["waves"][1].update(wave_num=1),
])
def test_invalid_snapshot_never_overwrites_good_data(db, change):
    api = FakeAPI(session_payload())
    manager = SurfilogSyncManager(db, api)
    manager.sync()
    before = raw_snapshot(db)
    change(api.payloads[0])
    with pytest.raises(SurfilogAPIError):
        manager.sync()
    assert raw_snapshot(db) == before


def test_database_failure_rolls_back_sessions_waves_and_sync_marker(db):
    SurfilogSyncManager(db, FakeAPI(session_payload())).sync()
    before = raw_snapshot(db)
    session, waves = normalize_session(session_payload(2), 2, "new-sync-marker")
    waves[0]["session_id"] = 999  # Reproduce a failed write after deletion starts.
    with pytest.raises(sqlite3.IntegrityError):
        db.replace_snapshot([session], waves, 7, "new-sync-marker")
    assert raw_snapshot(db) == before


def test_other_account_cannot_replace_the_stored_snapshot(db):
    api = FakeAPI(session_payload())
    manager = SurfilogSyncManager(db, api)
    manager.sync()
    before = raw_snapshot(db)
    api.user_id = 8
    with pytest.raises(ValueError, match="account differs"):
        manager.sync()
    assert raw_snapshot(db) == before


def test_status_needs_no_credentials_and_does_not_create_a_database(db):
    status = SurfilogSyncManager(db, FakeAPI()).get_status()
    assert status == {"sessions": 0, "waves": 0, "excluded_waves": 0, "last_successful_sync_at": None}
    assert not db.exists()


def test_status_reports_raw_counts_without_needing_monthly_analysis(db):
    SurfilogSyncManager(db, FakeAPI(session_payload())).sync()
    status = SurfilogSyncManager(db, FakeAPI()).get_status()
    assert status["sessions"] == 1
    assert status["waves"] == 1
    assert status["excluded_waves"] == 1
    assert status["last_successful_sync_at"]
    assert db.fetch_rows("SELECT * FROM analysis") == []


def test_reports_and_yaml_publish_aggregates_with_comparisons_and_date_limits(db):
    october = session_payload()
    september = session_payload(2, "2026-09-01T16:00:00Z")
    september["waves"][1]["is_excluded"] = False
    september_second = session_payload(3, "2026-09-02T16:00:00Z")
    september_second["waves"][0].update(duration_sec=35, max_speed_kmh=40)
    last_october = session_payload(4, "2025-10-01T16:00:00Z")
    last_october["session"].update(duration_sec=1800, session_metrics={"paddlingDistanceM": 1000})
    last_october["waves"][0].update(duration_sec=5, max_speed_kmh=10, distance_m=20)
    SurfilogSyncManager(db, FakeAPI(october, september, september_second, last_october)).sync()
    SurfilogAnalytics(db).analyze_sessions()
    absent = MagicMock()
    absent.fetch_rows.return_value = []
    absent.read_connection.return_value.__enter__.return_value = None
    other_sources = ("readwise", "foursquare", "letterboxd", "overcast", "strong",
                     "apple_health", "blog", "hardcover", "github_activity", "oura")
    publisher = Publisher(surfilog_db=db, **{f"{source}_db": absent for source in other_sources})
    assert publisher._get_target_year_month() == "2026-10"
    markdown = publisher.generate_markdown("2026-10")
    assert "## Surfing" in markdown
    for line in (
        "**Sessions**: 1 (-50% MoM, +0% YoY)",
        "**Waves Caught**: 1 (-67% MoM, +0% YoY)",
        "**Time in the Water**: 1h 0m (-50% MoM, +100% YoY)",
        "**Riding Time**: 0m 10s (-85% MoM, +100% YoY)",
        "**Median Wave Time**: 10.0 s (-50% MoM, +100% YoY)",
        "**Max Wave Time**: 10.0 s (-71% MoM, +100% YoY)",
        "**Median Wave Top Speed**: 15.5 km/h (-48% MoM, +55% YoY)",
        "**Max Speed**: 15.5 km/h (-61% MoM, +55% YoY)",
        "**Riding Distance**: 40.2 m (-76% MoM, +101% YoY)",
        "**Paddling Distance**: 1,234.0 m (-50% MoM, +23% YoY)",
        "**Longest Wave**: 40.2 m (-55% MoM, +101% YoY)",
    ):
        assert line in markdown
    files = publisher.data_generator.generate_data_files(min_year_month="2026-10", max_year_month="2026-10")
    assert set(files) == {"data/activity/surfing.yaml"}
    exported = files["data/activity/surfing.yaml"]
    assert '- month: "2026-10"' in exported
    assert "2026-09" not in exported
    assert "  waves: 1" in exported
    assert "  surf_distance_m: 40.25" in exported
    for private in ("Synthetic surf session", "share-token-must-not-be-stored", "-122.0", "coords_json"):
        assert private not in markdown + exported

    with db.get_connection() as conn:
        conn.execute("ALTER TABLE analysis DROP COLUMN median_wave_seconds")
        conn.execute("ALTER TABLE analysis DROP COLUMN median_speed_kmh")

    legacy_markdown = publisher.generate_markdown("2026-10")
    assert "**Median Wave Time**: N/A (N/A MoM, N/A YoY)" in legacy_markdown
    assert "**Max Wave Time**: 10.0 s (-71% MoM, +100% YoY)" in legacy_markdown
    SurfilogAnalytics(db).analyze_sessions()
    assert "**Median Wave Time**: 10.0 s (-50% MoM, +100% YoY)" in publisher.generate_markdown("2026-10")


def test_optional_source_skips_only_missing_configuration(monkeypatch):
    monkeypatch.setattr(Config, "SURFILOG_EMAIL", "")
    monkeypatch.setattr(Config, "SURFILOG_PASSWORD", "")
    operation = MagicMock()
    main._run_optional_surfilog(operation)
    operation.assert_not_called()
    monkeypatch.setattr(Config, "SURFILOG_EMAIL", "surfer@example.com")
    monkeypatch.setattr(Config, "SURFILOG_PASSWORD", "test-password")
    operation.side_effect = SurfilogAPIError("HTTP 401")
    with pytest.raises(SurfilogAPIError, match="HTTP 401"):
        main._run_optional_surfilog(operation)


@pytest.mark.parametrize("command", ["surfilog-sync", "surfilog-analyze"])
def test_cli_dispatches_surfilog_commands(monkeypatch, command):
    operation = MagicMock()
    monkeypatch.setattr(main, "cmd_" + command.replace("-", "_"), operation)
    monkeypatch.setattr("sys.argv", ["main.py", command])
    main.main()
    operation.assert_called_once_with()
