"""Tests for importing Strava surf sessions into Surfilog via Surfilog's Strava API."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock

import pytest

import main
from src.config import Config
from src.surfilog import api_client
from src.surfilog.api_client import (
    SurfilogAPIClient,
    SurfilogAPIError,
    SurfilogStravaDisconnectedError,
)
from src.surfilog.strava_import import SurfilogStravaImporter


def strava_activity(
    activity_id,
    *,
    name="Morning Shift",
    sport_type="Surfing",
    started_at="2026-11-06T13:19:33Z",
    already_imported=False,
    session_id=None,
):
    return {
        "id": str(activity_id),
        "name": name,
        "sport_type": sport_type,
        "started_at": started_at,
        "duration_sec": 3600,
        "distance_m": 4500.0,
        "device_name": None,
        "already_imported": already_imported,
        "session_id": session_id,
        "strava_url": f"https://www.strava.com/activities/{activity_id}",
    }


@pytest.fixture
def strava_server(monkeypatch):
    state = {
        "requests": [],
        "connected": True,
        "pages": {1: {"activities": [], "hasMore": False, "stravaPageNext": None}},
        "import_responses": {},
        "status_mode": "ok",
        "activities_mode": "ok",
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, payload, **headers):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_POST(self):
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            state["requests"].append(("POST", self.path, length))
            if parsed.path == "/api/auth/login":
                json.loads(body)
                self.reply(
                    200,
                    {"user": {"id": 42}},
                    **{"Set-Cookie": "token=secret-cookie; Path=/api; HttpOnly; Max-Age=604800"},
                )
                return
            if self.headers.get("Cookie") != "token=secret-cookie":
                self.reply(401, {"error": "secret-cookie"})
                return
            if parsed.path.startswith("/api/strava/import/"):
                activity_id = parsed.path.rsplit("/", 1)[-1]
                status, payload = state["import_responses"].get(
                    activity_id, (200, {"session_id": int(activity_id) % 10000 + 1})
                )
                self.reply(status, payload)
                return
            self.reply(404, {"error": "not found"})

        def do_GET(self):
            parsed = urlparse(self.path)
            state["requests"].append(("GET", self.path, 0))
            if self.headers.get("Cookie") != "token=secret-cookie":
                self.reply(401, {"error": "Authentication required"})
                return
            if parsed.path == "/api/auth/me":
                self.reply(200, {"user": {"id": 42}})
                return
            if parsed.path == "/api/strava/status":
                if state["status_mode"] == "disconnected":
                    self.reply(401, {"code": "STRAVA_DISCONNECTED", "secret": "secret-strava-token"})
                else:
                    self.reply(200, {"connected": state["connected"]})
                return
            if parsed.path == "/api/strava/activities":
                if state["activities_mode"] == "disconnected":
                    self.reply(401, {"code": "STRAVA_DISCONNECTED", "secret": "secret-strava-token"})
                    return
                query = parse_qs(parsed.query)
                page = int(query.get("stravaPageFrom", ["1"])[0])
                self.reply(200, state["pages"][page])
                return
            self.reply(404, {"error": "not found"})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(api_client, "API_URL", f"http://127.0.0.1:{httpd.server_port}/api")
    yield state
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_real_http_paginates_filters_and_imports_oldest_first(strava_server, capsys):
    strava_server["pages"] = {
        1: {
            "activities": [
                strava_activity("300", name="Newest Surf", started_at="2026-11-20T09:00:00Z", already_imported=False),
                strava_activity("250", name="Already In", started_at="2026-11-15T09:00:00Z", already_imported=True, session_id=10),
                strava_activity("240", name="Pool Swim", sport_type="Swimming", started_at="2026-11-14T08:00:00Z", already_imported=False),
            ],
            "hasMore": True,
            "stravaPageNext": 2,
        },
        2: {
            "activities": [
                # Duplicate across page boundary should be deduplicated.
                strava_activity("300", name="Newest Surf", started_at="2026-11-20T09:00:00Z", already_imported=False),
                strava_activity("200", name="Older Surf", started_at="2026-11-10T09:00:00Z", already_imported=False),
                strava_activity("150", name="Race Conflict", started_at="2026-11-08T09:00:00Z", already_imported=False),
            ],
            "hasMore": False,
            "stravaPageNext": None,
        },
    }
    strava_server["import_responses"] = {
        "150": (409, {"error": "already imported"}),
        "200": (200, {"session_id": 7001}),
        "300": (200, {"session_id": 7002}),
    }

    client = SurfilogAPIClient("surfer@example.com", "secret-password")
    summary = SurfilogStravaImporter(client, per_page=10).import_new()

    assert summary["checked"] == 5
    assert summary["already_imported"] == 1
    assert summary["skipped_sport"] == 1
    assert summary["conflicts"] == ["150"]
    assert summary["imported"] == [
        {"activity_id": "200", "session_id": 7001},
        {"activity_id": "300", "session_id": 7002},
    ]
    assert summary["failed"] == []

    post_imports = [(path, length) for method, path, length in strava_server["requests"]
                    if method == "POST" and path.startswith("/api/strava/import/")]
    assert post_imports == [
        ("/api/strava/import/150", 0),
        ("/api/strava/import/200", 0),
        ("/api/strava/import/300", 0),
    ]
    output = capsys.readouterr().out
    assert "2 imported, 2 already imported, 1 skipped, 0 failed" in output


def test_dry_run_makes_no_import_posts_and_respects_since_filter(strava_server, capsys):
    strava_server["pages"] = {
        1: {
            "activities": [
                strava_activity("300", name="Nov Surf", started_at="2026-11-12T09:00:00Z"),
                strava_activity("200", name="Oct Surf", started_at="2026-10-20T09:00:00Z"),
            ],
            "hasMore": False,
            "stravaPageNext": None,
        }
    }
    client = SurfilogAPIClient("surfer@example.com", "secret-password")
    summary = SurfilogStravaImporter(client).import_new(dry_run=True, since="2026-11-01")

    assert summary["dry_run"] is True
    assert summary["pending"] == 1
    assert summary["skipped_before_since"] == 1
    assert summary["imported"] == []
    assert not any(path.startswith("/api/strava/import/") for _, path, _ in strava_server["requests"])
    # Verify padded after query parameter was sent to Surfilog.
    activities_req = next(path for method, path, _ in strava_server["requests"]
                          if method == "GET" and path.startswith("/api/strava/activities"))
    assert "after=" in activities_req
    assert "300 (2026-11-12, Surfing, Nov Surf)" in capsys.readouterr().out


def test_disconnected_strava_fails_with_safe_message(strava_server):
    strava_server["connected"] = False
    client = SurfilogAPIClient("surfer@example.com", "secret-password")
    with pytest.raises(SurfilogStravaDisconnectedError, match="not connected"):
        SurfilogStravaImporter(client).import_new()

    strava_server["connected"] = True
    strava_server["activities_mode"] = "disconnected"
    with pytest.raises(SurfilogStravaDisconnectedError, match="reconnect your Strava account") as exc_info:
        SurfilogStravaImporter(client).import_new()
    assert "secret-strava-token" not in str(exc_info.value)


def test_per_activity_error_continues_other_imports_then_raises(strava_server, capsys):
    strava_server["pages"] = {
        1: {
            "activities": [
                strava_activity("300", name="Good Newer", started_at="2026-11-12T09:00:00Z"),
                strava_activity("200", name="Corrupt GPX", started_at="2026-11-11T09:00:00Z"),
                strava_activity("100", name="Good Older", started_at="2026-11-10T09:00:00Z"),
            ],
            "hasMore": False,
            "stravaPageNext": None,
        }
    }
    strava_server["import_responses"] = {
        "100": (200, {"session_id": 8001}),
        "200": (400, {"code": "invalid_gpx", "secret": "never-leak"}),
        "300": (200, {"session_id": 8003}),
    }
    client = SurfilogAPIClient("surfer@example.com", "secret-password")
    with pytest.raises(SurfilogAPIError, match="Failed to import 1 Strava"):
        SurfilogStravaImporter(client).import_new()

    post_paths = [path for method, path, _ in strava_server["requests"]
                  if method == "POST" and path.startswith("/api/strava/import/")]
    assert post_paths == [
        "/api/strava/import/100",
        "/api/strava/import/200",
        "/api/strava/import/300",
    ]
    out = capsys.readouterr().out
    assert "GPS track could not be read" in out
    assert "never-leak" not in out
    assert "2 imported, 0 already imported, 0 skipped, 1 failed" in out


def test_rate_limit_stops_remaining_imports(strava_server):
    strava_server["pages"] = {
        1: {
            "activities": [
                strava_activity("200", started_at="2026-11-11T09:00:00Z"),
                strava_activity("100", started_at="2026-11-10T09:00:00Z"),
            ],
            "hasMore": False,
            "stravaPageNext": None,
        }
    }
    strava_server["import_responses"] = {
        "100": (429, {"error": "too many requests"}),
        "200": (200, {"session_id": 9001}),
    }
    client = SurfilogAPIClient("surfer@example.com", "secret-password")
    with pytest.raises(SurfilogAPIError, match="Failed to import 1"):
        SurfilogStravaImporter(client).import_new()

    post_paths = [path for method, path, _ in strava_server["requests"]
                  if method == "POST" and path.startswith("/api/strava/import/")]
    assert post_paths == ["/api/strava/import/100"]


@pytest.mark.parametrize("bad_id", ["", "0", "-5", "123/../../etc", "abc", True, None])
def test_invalid_strava_activity_id_rejected_before_network(bad_id):
    client = SurfilogAPIClient("surfer@example.com", "secret-password")
    client.user_id = 1
    with pytest.raises(SurfilogAPIError, match="Invalid Strava activity ID"):
        client.import_strava_activity(bad_id)


def test_non_advancing_pagination_cursor_rejected(strava_server):
    strava_server["pages"] = {
        1: {"activities": [], "hasMore": True, "stravaPageNext": 1}
    }
    client = SurfilogAPIClient("surfer@example.com", "secret-password")
    with pytest.raises(SurfilogAPIError, match="non-advancing"):
        SurfilogStravaImporter(client).import_new()


def test_custom_sport_types_and_cli_dispatch(monkeypatch):
    operation = MagicMock(return_value={"imported": []})
    monkeypatch.setattr(main, "cmd_surfilog_import_strava", operation)
    assert main.main([
        "surfilog-import-strava",
        "--dry-run",
        "--since", "2026-11-01",
        "--sport-type", "Surfing",
        "--sport-type", "WindSurf",
    ]) == 0
    operation.assert_called_once_with(
        dry_run=True,
        since="2026-11-01",
        sport_types=["Surfing", "WindSurf"],
    )


def test_cli_validates_credentials_and_bad_since_date(monkeypatch, capsys):
    monkeypatch.setattr(Config, "SURFILOG_EMAIL", "")
    monkeypatch.setattr(Config, "SURFILOG_PASSWORD", "")
    assert main.main(["surfilog-import-strava"]) == 1
    assert "SURFILOG_EMAIL" in capsys.readouterr().out

    monkeypatch.setattr(Config, "SURFILOG_EMAIL", "surfer@example.com")
    monkeypatch.setattr(Config, "SURFILOG_PASSWORD", "secret")
    assert main.main(["surfilog-import-strava", "--since", "not-a-date"]) == 1
    assert "YYYY-MM-DD" in capsys.readouterr().out
