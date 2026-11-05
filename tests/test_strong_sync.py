"""Strong API transport, observed CSV parity rules, and safe snapshot migration."""

from copy import deepcopy
import csv
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import main
from src.config import Config
from src.publish.markdown_generator import MarkdownGenerator
from src.strong.analytics import StrongAnalytics
from src.strong.api_client import API_URL, StrongAPIClient, StrongAPIError
from src.strong.database import StrongDatabase
from src.strong.sync import StrongSyncManager, normalize_workouts


MEASUREMENTS = {"squat": {"id": "squat", "name": {"en": "Squat", "custom": "Custom squat"}}}


def cell(kind, value, **kwargs):
    return {"cellType": kind, "value": value, **kwargs}


def workout(workout_id="api-uuid", start="2026-11-01T06:30:00Z", end="2026-11-01T07:25:59Z"):
    return {
        "id": workout_id, "logType": "WORKOUT", "name": {"en": "Full"},
        "startDate": start, "endDate": end,
        "_embedded": {"cellSetGroup": [{
            "_links": {"measurement": {"href": "/api/measurements/squat"}},
            "cellSets": [
                # Notes can be visible but have isCompleted=false in real exports.
                {"isCompleted": False, "cells": [cell("NOTE", "Keep knees out")]},
                {"isCompleted": True, "cells": [
                    cell("BARBELL_WEIGHT", "43.09127515"), cell("REPS", "5"), cell("RPE", "8.5"),
                    cell("BARBELL_WEIGHT", "999", isHidden=True),
                ]},
                {"cells": [cell("REST_TIMER", "105")]},
                {"isHidden": True, "cells": [cell("BARBELL_WEIGHT", "999")]},
                {"isCompleted": False, "cells": [cell("BARBELL_WEIGHT", "999")]},
            ],
        }, {"isHidden": True, "cellSets": [{"cells": [cell("REPS", "999")]}]}]},
    }


class FakeAPI:
    def __init__(self, *logs):
        self.logs = list(logs)
        self.user_id = "account-id"
        self.closed = False

    def login(self):
        pass

    def get_measurements(self):
        return deepcopy(MEASUREMENTS)

    def get_workout_logs(self):
        return deepcopy(self.logs)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(Config, "FILES_DIR", tmp_path)
    monkeypatch.setattr(Config, "STRONG_USER", "")
    monkeypatch.setattr(Config, "STRONG_PASS", "")
    monkeypatch.setattr(Config, "STRONG_WEIGHT_UNIT", "lb")
    monkeypatch.setattr(Config, "STRONG_TIMEZONE", "America/Los_Angeles")


@pytest.fixture
def db(tmp_path):
    return StrongDatabase(str(tmp_path / "strong.db"))


def raw_snapshot(db):
    with db.get_connection() as conn:
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ("workouts", "exercises", "sync_state", "analysis")}


def response(data, status=200):
    result = MagicMock()
    result.status_code = status
    result.json.return_value = data
    result.text = "password=secret; accessToken=private-token"
    return result


def test_login_paginates_global_custom_exercises_and_workouts_without_following_hosts():
    session = MagicMock()
    session.headers = {}
    session.request.side_effect = [
        response({"accessToken": "private-token", "userId": "account-id"}),
        response({"_embedded": {"measurement": [{"id": "global-1"}]},
                  "_links": {"next": {"href": "https://other.invalid/api/measurements?page=2"}}}),
        response({"_embedded": {"measurement": [{"id": "global-1"}, {"id": "global-2"}]}}),
        response({"_embedded": {"measurement": [{"id": "custom"}]}}),
        response({"_embedded": {"log": [{"id": "log-1"}]},
                  "_links": {"continuation": {"href": "/api/users/account-id?continuation=next%2Bpage"}}}),
        response({"_embedded": {"log": [{"id": "log-2"}]}}),
    ]
    api = StrongAPIClient("email", "secret", session=session)
    api.login()
    assert api.user_id == "account-id"
    assert session.headers["Authorization"] == "Bearer private-token"
    assert set(api.get_measurements()) == {"global-1", "global-2", "custom"}
    assert api.get_workout_logs() == [{"id": "log-1"}, {"id": "log-2"}]
    calls = session.request.call_args_list
    assert all(c.args[1].startswith(API_URL) and c.kwargs["allow_redirects"] is False for c in calls)
    assert calls[2].kwargs["params"] == {"page": 2}
    assert calls[-1].kwargs["params"]["continuation"] == "next+page"
    api.close()
    assert "Authorization" not in session.headers
    session.close.assert_called_once()


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
def test_http_errors_do_not_echo_secrets_or_retry(status, capsys):
    session = MagicMock()
    session.headers = {}
    session.request.return_value = response({}, status)
    api = StrongAPIClient("email", "secret", session=session)
    with pytest.raises(StrongAPIError, match=f"HTTP {status}") as error:
        api.login()
    assert "secret" not in str(error.value)
    assert "private-token" not in str(error.value)
    assert capsys.readouterr().out == ""
    assert api.user_id is None and "Authorization" not in session.headers
    session.request.assert_called_once()


@pytest.mark.parametrize("payload", [[], {}, {"accessToken": "token"}, {"accessToken": "", "userId": "u"}])
def test_bad_login_response_cannot_authenticate(payload):
    session = MagicMock()
    session.headers = {}
    session.request.return_value = response(payload)
    api = StrongAPIClient("email", "secret", session=session)
    with pytest.raises(StrongAPIError):
        api.login()
    assert api.user_id is None


def test_network_and_non_json_errors_are_safe(monkeypatch):
    # Older suites replace sys.modules['requests'] during collection. Give this
    # fake transport a concrete exception class in either test environment.
    class NetworkError(Exception):
        pass

    monkeypatch.setattr("src.strong.api_client.requests.RequestException", NetworkError)
    session = MagicMock()
    session.headers = {}
    api = StrongAPIClient("email", "secret", session=session)
    session.request.side_effect = NetworkError("secret/private-token")
    with pytest.raises(StrongAPIError, match="connection failed") as error:
        api.login()
    assert "secret" not in str(error.value)
    session.request.side_effect = None
    session.request.return_value = response({})
    session.request.return_value.json.side_effect = ValueError("private-token")
    with pytest.raises(StrongAPIError, match="invalid JSON"):
        api.login()


@pytest.mark.parametrize("kind", ["repeated_cursor", "repeated_id", "empty_page", "bad_shape", "missing_collection"])
def test_incomplete_workout_pagination_is_an_error(kind):
    session = MagicMock()
    session.headers = {}
    api = StrongAPIClient("email", "secret", session=session)
    api.user_id = "account-id"
    page = {"_embedded": {"log": [{"id": "one"}]},
            "_links": {"continuation": {"href": "/api/users/u?continuation=next"}}}
    second = deepcopy(page)
    second["_embedded"]["log"] = [{"id": "two"}]
    if kind == "repeated_id":
        second = {"_embedded": {"log": [{"id": "one"}]}}
    elif kind == "empty_page":
        second["_embedded"]["log"] = []
    elif kind == "bad_shape":
        second = {"_embedded": {"log": {}}}
    elif kind == "missing_collection":
        second = {"_embedded": {}}
    session.request.side_effect = [response(page), response(second)]
    with pytest.raises(StrongAPIError):
        api.get_workout_logs()


def test_explicit_empty_log_collection_is_valid():
    session = MagicMock()
    session.headers = {}
    api = StrongAPIClient("email", "secret", session=session)
    api.user_id = "account-id"
    session.request.return_value = response({"_embedded": {"log": []}})
    assert api.get_workout_logs() == []


def test_exercise_pagination_cannot_silently_stop_after_http_failure():
    session = MagicMock()
    session.headers = {}
    api = StrongAPIClient("email", "secret", session=session)
    api.user_id = "account-id"
    page = {"_embedded": {"measurement": [{"id": "squat"}]},
            "_links": {"next": {"href": "/api/measurements?page=1"}}}
    session.request.side_effect = [response(page), response({}, 500)]
    with pytest.raises(StrongAPIError, match="HTTP 500"):
        api.get_measurements()


@pytest.mark.parametrize("items", [[], [{"id": "squat"}]])
def test_exercise_pagination_rejects_a_stalled_cursor(items):
    session = MagicMock()
    session.headers = {}
    api = StrongAPIClient("email", "secret", session=session)
    api.user_id = "account-id"
    session.request.return_value = response({"_embedded": {"measurement": items},
        "_links": {"next": {"href": "/api/measurements?page=0"}}})
    with pytest.raises(StrongAPIError, match="did not advance"):
        api.get_measurements()


def test_normalization_matches_visible_csv_sets_pounds_notes_and_local_month():
    workouts, sets = normalize_workouts([workout()], MEASUREMENTS,
                                      weight_unit="lb", timezone="America/Los_Angeles")
    assert workouts["api-uuid"] == {
        "id": "api-uuid", "workout_name": "Full", "started_at": "2026-10-31 23:30:00",
        "started_at_utc": "2026-11-01T06:30:00.000000Z",
        "duration_minutes": 55, "notes": None,
    }
    assert sets["api-uuid"] == [{
        "exercise_name": "Custom squat", "set_order": 1, "weight": 95,
        "reps": 5, "rpe": 8.5, "distance": 0, "seconds": 0, "notes": "Keep knees out",
    }]


@pytest.mark.parametrize("duration", ["60", "00:01:00"])
def test_kg_timed_sets_legacy_completion_and_workout_timezone(duration):
    log = workout()
    log["timezoneId"] = "Asia/Tokyo"
    log["name"] = {"custom": "Timed"}
    log["_embedded"]["cellSetGroup"][0]["cellSets"] = [{"cells": [cell("DURATION", duration)]}]
    workouts, sets = normalize_workouts([log], MEASUREMENTS, weight_unit="kg", timezone="UTC")
    assert workouts["api-uuid"]["started_at"] == "2026-11-01 15:30:00"
    assert sets["api-uuid"][0]["seconds"] == 60
    assert sets["api-uuid"][0]["weight"] == 0


def test_sync_migrates_csv_ids_and_refreshes_deletions_without_duplicates(db):
    db.init_tables()
    db.save_workouts({"2026-10-31 23:30:00": {
        "id": "2026-10-31 23:30:00", "started_at": "2026-10-31 23:30:00", "workout_name": "Full",
    }}, {})
    StrongAnalytics(db).analyze_workouts()
    api = FakeAPI(workout(), workout("deleted-later"))
    manager = StrongSyncManager(db, api)
    assert manager.sync() == {"workouts": 2, "exercises": 2}
    assert db.fetch_rows("SELECT * FROM analysis") == []
    with db.get_connection() as conn:
        assert {r[0] for r in conn.execute("SELECT id FROM workouts")} == {"api-uuid", "deleted-later"}
    api.logs.pop()
    manager.sync()
    manager.sync()
    assert db.get_stats() == {"workouts": 1, "exercises": 1}
    assert api.closed
    assert db.get_sync_state()["source"] == "api"
    assert StrongAnalytics(db).analyze_workouts() == 1
    summary = StrongAnalytics(db).get_weightlifting_summary("2026-10")
    assert summary["weight_unit"] == "lb"
    markdown = MarkdownGenerator().generate_monthly_summary({"year": "2026", "month": "10", "strong": summary})
    assert "pounds (lb)" in markdown
    assert "| Custom squat | 95 |" in markdown


@pytest.mark.parametrize("failure", ["bad_number", "missing_exercise", "empty", "other_account", "bad_timestamp"])
def test_failed_sync_preserves_existing_raw_analysis_and_state(db, failure):
    StrongSyncManager(db, FakeAPI(workout())).sync()
    StrongAnalytics(db).analyze_workouts()
    before = raw_snapshot(db)
    api = FakeAPI(workout())
    if failure == "bad_number":
        api.logs[0]["_embedded"]["cellSetGroup"][0]["cellSets"][1]["cells"][0]["value"] = "NaN"
    elif failure == "missing_exercise":
        api.logs[0]["_embedded"]["cellSetGroup"][0]["_links"]["measurement"]["href"] = "/api/measurements/missing"
    elif failure == "empty":
        api.logs = []
    elif failure == "other_account":
        api.user_id = "different-account"
    else:
        api.logs[0]["startDate"] = "2026-10-10T09:00:00"
    with pytest.raises((StrongAPIError, ValueError)):
        StrongSyncManager(db, api).sync()
    assert api.closed
    assert raw_snapshot(db) == before


def test_database_failure_rolls_back_deletions_and_analysis_invalidation(db):
    StrongSyncManager(db, FakeAPI(workout())).sync()
    StrongAnalytics(db).analyze_workouts()
    before = raw_snapshot(db)
    with db.get_connection() as conn:
        conn.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON exercises "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        StrongSyncManager(db, FakeAPI(workout("new"))).sync()
    assert raw_snapshot(db) == before


def test_missing_final_page_collection_preserves_the_entire_existing_snapshot(db):
    StrongSyncManager(db, FakeAPI(workout("one"), workout("two"))).sync()
    StrongAnalytics(db).analyze_workouts()
    before = raw_snapshot(db)
    session = MagicMock()
    session.headers = {}
    session.request.side_effect = [
        response({"accessToken": "private-token", "userId": "account-id"}),
        response({"_embedded": {"measurement": list(MEASUREMENTS.values())}}),
        response({"_embedded": {"measurement": []}}),
        response({"_embedded": {"log": [workout("one")]},
                  "_links": {"continuation": {"href": "/api/users/u?continuation=next"}}}),
        response({"_embedded": {}}),
    ]
    api = StrongAPIClient("email", "secret", session=session)
    with pytest.raises(StrongAPIError, match="invalid paginated response"):
        StrongSyncManager(db, api).sync()
    assert raw_snapshot(db) == before
    assert "Authorization" not in session.headers
    session.close.assert_called_once()


def test_dst_fold_uses_utc_for_latest_workout_and_comparison_but_local_months(db):
    earlier = workout("earlier", "2026-11-01T08:45:00Z", "2026-11-01T08:46:00Z")
    later = workout("later", "2026-11-01T09:15:00Z", "2026-11-01T09:16:00Z")
    december = workout("december", "2026-12-15T17:00:00Z", "2026-12-15T17:01:00Z")
    later["_embedded"]["cellSetGroup"][0]["cellSets"][1]["cells"][0]["value"] = "45.359237"
    december["_embedded"]["cellSetGroup"][0]["cellSets"][1]["cells"][0]["value"] = "90.718474"
    StrongSyncManager(db, FakeAPI(later, earlier, december)).sync()
    analytics = StrongAnalytics(db)
    november = analytics.get_weightlifting_summary("2026-11")
    # 01:15 PST is later than 01:45 PDT on the same local calendar day.
    assert november["started_at"] == "2026-11-01 01:15:00"
    assert november["exercises"][0]["weight"] == 100
    assert analytics.get_weightlifting_summary("2026-12")["exercises"][0]["comparisons"]["mom"] == 100
    assert analytics.analyze_workouts() == 2


def test_legacy_schema_stays_readable_and_migrates_without_losing_rows(db):
    from src.strong.models import CREATE_EXERCISES_TABLE

    with db.get_connection() as conn:
        conn.execute("CREATE TABLE workouts (id TEXT PRIMARY KEY, workout_name TEXT, "
                     "started_at TEXT, duration_minutes INTEGER, notes TEXT)")
        conn.execute(CREATE_EXERCISES_TABLE)
        conn.execute("INSERT INTO workouts VALUES ('csv-date', 'Full', '2026-10-15 09:00:00', 55, NULL)")
        conn.execute("INSERT INTO exercises (workout_id, exercise_name, set_order, weight) "
                     "VALUES ('csv-date', 'Squat', 1, 95)")
    assert StrongAnalytics(db).get_weightlifting_summary("2026-10")["exercises"][0]["weight"] == 95
    with db.get_connection() as conn:
        assert "started_at_utc" not in {r["name"] for r in conn.execute("PRAGMA table_info(workouts)")}
    db.init_tables()
    assert db.get_stats() == {"workouts": 1, "exercises": 1}
    with db.get_connection() as conn:
        assert conn.execute("SELECT started_at_utc FROM workouts").fetchone()[0] is None
    assert StrongAnalytics(db).get_weightlifting_summary("2026-10")["exercises"][0]["weight"] == 95


def write_csv(path):
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Date", "Workout Name", "Duration", "Exercise Name", "Set Order", "Weight", "Reps"])
        writer.writerow(["2026-10-31 23:30:00", "Full", "55m", "Custom squat", 1, 95, 5])


def test_csv_fallback_is_automatic_only_before_api_migration(db, tmp_path):
    write_csv(tmp_path / "strong_workouts.csv")
    manager = StrongSyncManager(db)
    assert manager.sync() == {"workouts": 1, "exercises": 1}
    StrongSyncManager(db, FakeAPI(workout())).sync()
    with pytest.raises(StrongAPIError, match="strong-sync --csv"):
        manager.sync()
    assert manager.sync(from_csv=True) == {"workouts": 1, "exercises": 1}
    assert db.get_stats() == {"workouts": 1, "exercises": 1}
    assert db.get_sync_state()["source"] == "csv"
    with db.get_connection() as conn:
        assert conn.execute("SELECT id FROM workouts").fetchone()[0] == "2026-10-31 23:30:00"


def test_configured_api_failure_never_falls_back_to_csv(db, tmp_path, monkeypatch):
    write_csv(tmp_path / "strong_workouts.csv")
    monkeypatch.setattr(Config, "STRONG_USER", "email")
    monkeypatch.setattr(Config, "STRONG_PASS", "secret")
    with patch("src.strong.sync.StrongAPIClient") as client:
        client.return_value.login.side_effect = StrongAPIError("Login rejected")
        with pytest.raises(StrongAPIError, match="Login rejected"):
            StrongSyncManager(db).sync()
        client.return_value.close.assert_called_once()
    assert not db.exists()


def test_cli_routes_explicit_csv_recovery():
    with patch("sys.argv", ["main.py", "strong-sync", "--csv"]), patch.object(main, "cmd_strong_sync") as sync:
        main.main()
    sync.assert_called_once_with(from_csv=True)
