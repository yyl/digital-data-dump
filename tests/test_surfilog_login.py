"""Exercise the login probe against a local HTTP server with fake credentials."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from src.surfilog import api_client


spec = importlib.util.spec_from_file_location(
    "surfilog_login", Path(__file__).parents[1] / "scripts" / "surfilog_login.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.fixture
def server(monkeypatch):
    state = {"requests": [], "mode": "success"}

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
            state["requests"].append((self.command, self.path))
            state["credentials"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            # Reproduce the real edge response to urllib's default signature.
            if state["mode"] == "cloudflare" or self.headers.get("User-Agent", "").startswith("Python-urllib/"):
                self.reply(403, {
                    "cloudflare_error": True,
                    "error_code": 1010,
                    "detail": "secret-password secret-token",
                })
            elif state["mode"] == "challenge":
                self.reply(403, {}, **{"CF-Mitigated": "challenge"})
            elif state["mode"] == "forbidden":
                self.reply(403, {"error": "secret-password secret-token"})
            elif state["mode"] == "rejected":
                self.reply(401, {"error": "secret-password secret-token"})
            elif state["mode"] == "google":
                self.reply(400, {"code": "google_account", "error": "secret-password"})
            elif state["mode"] == "redirect":
                self.reply(307, {}, Location="/redirect-target")
            elif state["mode"] == "missing_cookie":
                self.reply(200, {"user": {"id": 1}})
            else:
                self.reply(
                    200, {"user": {"id": 1}, "token": "secret-token"},
                    **{"Set-Cookie": "token=secret-token; Path=/api; HttpOnly; Max-Age=604800"},
                )

        def do_GET(self):
            state["requests"].append((self.command, self.path))
            if self.headers.get("Cookie") != "token=secret-token":
                self.reply(401, {"error": "Authentication required"})
            elif self.path == "/api/auth/me":
                user = None if state["mode"] == "no_identity" else {"id": 1}
                self.reply(200, {"user": user})
            elif self.path == "/api/sessions/4966":
                self.reply(200, state["session_detail"])
            elif state["mode"] == "invalid_sessions":
                self.reply(200, {"sessions": [{"id": 4966, "wave_count": True}]})
            else:
                self.reply(200, {"sessions": [{"id": 4966, "wave_count": 8}]})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(api_client, "API_URL", f"http://127.0.0.1:{httpd.server_port}/api")
    yield state
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_login_reuses_cookie_and_verifies_wave_access(server, capsys):
    probe.check_login("surfer@example.com", "secret-password")
    output = capsys.readouterr().out
    assert "1 session(s), 8 wave(s)" in output
    assert "Token cookie expires:" in output
    assert "secret-token" not in output
    assert "secret-password" not in output
    assert server["credentials"] == {"email": "surfer@example.com", "password": "secret-password"}
    assert server["requests"] == [
        ("POST", "/api/auth/login"),
        ("GET", "/api/auth/me"),
        ("GET", "/api/sessions"),
    ]


def test_real_client_downloads_wave_details_and_syncs_database(server, tmp_path):
    from src.surfilog.analytics import SurfilogAnalytics
    from src.surfilog.database import SurfilogDatabase
    from src.surfilog.sync import SurfilogSyncManager

    server["session_detail"] = {
        "session": {"id": 4966, "user_id": 1, "started_at": "2026-11-01T01:00:00Z",
                    "utc_offset_min": -420, "duration_sec": 3600, "wave_count": 1},
        "waves": [{"id": 30100, "session_id": 4966, "wave_num": 1,
                   "start_time": "2026-11-01T01:10:00Z", "duration_sec": 12,
                   "distance_m": "50.25", "max_speed_kmh": "20.90", "is_excluded": False,
                   "coords_json": [{"ts": "2026-11-01T01:10:00Z", "lat": 37.0, "lon": -122.0}]}],
        "trackPoints": [],
    }
    db = SurfilogDatabase(tmp_path / "surfilog.db")
    client = api_client.SurfilogAPIClient("surfer@example.com", "secret-password")
    assert SurfilogSyncManager(db, client).sync() == {"sessions": 1, "waves": 1, "excluded_waves": 0}
    assert server["requests"][-1] == ("GET", "/api/sessions/4966")
    assert SurfilogAnalytics(db).analyze_sessions() == 1
    row = db.fetch_rows("SELECT * FROM analysis")[0]
    assert row["year_month"] == "2026-10"
    assert row["waves"] == 1
    assert row["surf_distance_m"] == 50.25


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("google", "This account uses Google sign-in"),
        ("cloudflare", "Cloudflare Error 1010 blocked this client signature"),
        ("challenge", "Cloudflare requires a browser challenge"),
        ("forbidden", "Access forbidden; credentials could not be verified"),
        ("rejected", "Login rejected; check your credentials and sign-in method"),
        ("missing_cookie", "no usable 'token' cookie"),
        ("no_identity", "did not authenticate /auth/me"),
        ("invalid_sessions", "valid wave counts"),
        ("redirect", "Unexpected redirect; it was not followed"),
    ],
)
def test_main_reports_failures_without_exposing_secrets(server, monkeypatch, capsys, mode, message):
    server["mode"] = mode
    monkeypatch.setenv("SURFILOG_EMAIL", "surfer@example.com")
    monkeypatch.setenv("SURFILOG_PASSWORD", "secret-password")
    assert probe.main([]) == 1
    captured = capsys.readouterr()
    assert message in captured.err
    assert "secret-token" not in captured.out + captured.err
    assert "secret-password" not in captured.out + captured.err
    if mode in {"cloudflare", "challenge", "forbidden", "rejected"}:
        assert server["requests"] == [("POST", "/api/auth/login")]
    assert all(path != "/redirect-target" for _, path in server["requests"])
