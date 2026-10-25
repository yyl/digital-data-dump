"""Private activity data must not escape through normal logs or tracebacks."""

import json
import logging
import sqlite3
import subprocess
import sys
import traceback
from unittest.mock import MagicMock

import pytest
import requests

import main
from src.config import Config
from src.github.api_client import GitHubActivityClient
from src.github.database import GitHubDatabase
from src.github.sync import GitHubSyncError, GitHubSyncManager


PRIVATE_REPO = "confidential-repository-marker"
PRIVATE_MESSAGE = "confidential-commit-message-marker"
PRIVATE_SHA = "confidential-sha-marker"
TOKEN = "confidential-token-marker"
PRIVATE_URL = f"https://api.github.com/repos/user/{PRIVATE_REPO}/commits"
SENSITIVE_VALUES = (PRIVATE_REPO, PRIVATE_MESSAGE, PRIVATE_SHA, TOKEN, PRIVATE_URL)


def response(data=None, status=200, *, body=None, url=PRIVATE_URL, headers=None):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.reason = "OK" if status == 200 else f"Failure involving {PRIVATE_MESSAGE}"
    result.headers = {"X-RateLimit-Remaining": "5000", **(headers or {})}
    result._content = body if body is not None else json.dumps(data).encode()
    result.request = requests.Request(
        "GET", url, headers={"Authorization": f"Bearer {TOKEN}"},
    ).prepare()
    return result


def failure(kind):
    details = f"{PRIVATE_URL}?token={TOKEN}: {PRIVATE_MESSAGE} {PRIVATE_SHA}"
    if kind.isdigit():
        return response({"message": details}, status=int(kind))
    if kind.startswith("409_"):
        payload = {"409_list": b"[]", "409_null": b"null", "409_invalid": details.encode()}
        return response(status=409, body=payload[kind])
    if kind == "invalid_json":
        return response(body=details.encode())
    if kind == "invalid_payload":
        return response([PRIVATE_MESSAGE])
    errors = {
        "timeout": requests.exceptions.ReadTimeout,
        "connection": requests.exceptions.ConnectionError,
        "tls": requests.exceptions.SSLError,
        "redirect": requests.exceptions.TooManyRedirects,
        "invalid_url": requests.exceptions.InvalidURL,
        "chunked": requests.exceptions.ChunkedEncodingError,
    }
    return errors[kind](details)


@pytest.fixture
def activity(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(Config, "CODEBASE_USERNAME", "user")
    monkeypatch.setattr(Config, "CODEBASE_GITHUB_TOKEN", TOKEN)
    api = GitHubActivityClient(token=TOKEN, username="user")
    api._min_request_interval = 0
    db = GitHubDatabase(str(tmp_path / "github.db"))
    manager = GitHubSyncManager(db=db, api=api)
    monkeypatch.setattr("src.github.sync.GitHubSyncManager", lambda: manager)
    return manager, api, db


def arrange_failure(api, kind, stage):
    repo = {
        "full_name": f"user/{PRIVATE_REPO}", "name": PRIVATE_REPO,
        "owner": {"login": "user"}, "fork": False, "private": True,
    }
    values = [response({"login": "user"}), response([])]
    if stage == "discovery":
        values.append(failure(kind))
    else:
        if stage == "stale_public":
            # A formerly public URL redirects to the private URL in the error.
            repo = {**repo, "full_name": "user/public-origin", "name": "public-origin", "private": False}
        values.append(response([repo]))
        if stage == "next_page":
            values.append(response([{
                "sha": PRIVATE_SHA,
                "commit": {"message": PRIVATE_MESSAGE, "author": {"date": "2026-10-01T00:00:00Z"}},
            }], headers={"Link": f'<{PRIVATE_URL}?page=2>; rel="next"'}))
        values.append(failure(kind))
    api.session.get = MagicMock(side_effect=values)


@pytest.mark.parametrize("stage,kind", [
    (stage, kind)
    for stage in ("discovery", "first_page", "next_page", "stale_public")
    for kind in ("403", "404", "timeout", "connection", "redirect", "invalid_json")
] + [
    ("first_page", kind) for kind in
    ("500", "tls", "invalid_url", "chunked", "409_list", "409_null", "409_invalid", "invalid_payload")
])
def test_activity_cli_errors_are_safe_in_stdout_stderr_and_logging(
    activity, capsys, caplog, stage, kind,
):
    _, api, db = activity
    arrange_failure(api, kind, stage)
    with pytest.raises(GitHubSyncError) as caught:
        try:
            main.cmd_github_analyze()
        except GitHubSyncError:
            # Exercise the same formatter as an uncaught CLI exception and logging.exception.
            traceback.print_exc(file=sys.stderr)
            logging.getLogger(__name__).exception("Activity sync failed")
            raise
    output = capsys.readouterr()
    rendered = output.out + output.err + caplog.text + str(caught.value) + repr(caught.value)
    assert "GitHub activity sync failed" in rendered
    assert "Traceback" in output.err
    for sensitive in SENSITIVE_VALUES:
        assert sensitive not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert not hasattr(caught.value, "request")
    assert not hasattr(caught.value, "response")
    if kind.isdigit() or kind.startswith("409_"):
        status = kind.split("_", 1)[0]
        assert f"HTTP {status}" in str(caught.value)
    assert db.get_stats() == {"commits": 0, "repos": 0}


@pytest.mark.parametrize("command", ["github-sync", "publish", "backfill"])
def test_sync_failure_aborts_cli_before_publishing(activity, monkeypatch, capsys, command):
    _, api, _ = activity
    arrange_failure(api, "403", "first_page")
    for source in ("readwise", "letterboxd", "foursquare", "overcast", "strong",
                   "apple_health", "blog", "hardcover", "oura"):
        monkeypatch.setattr(main, f"cmd_{source}_analyze", lambda: None)
    publisher = MagicMock()
    monkeypatch.setattr("src.publish.Publisher", publisher)
    monkeypatch.setattr(sys, "argv", ["main.py", command])
    with pytest.raises(GitHubSyncError):
        try:
            main.main()
        except GitHubSyncError:
            traceback.print_exc(file=sys.stderr)
            raise
    captured = capsys.readouterr()
    for sensitive in SENSITIVE_VALUES:
        assert sensitive not in captured.out + captured.err
    publisher.assert_not_called()


@pytest.mark.parametrize("error,category", [
    (RuntimeError(PRIVATE_MESSAGE), "unexpected error"),
    (sqlite3.OperationalError(PRIVATE_MESSAGE), "database error"),
    (ValueError(PRIVATE_MESSAGE), "invalid response or configuration"),
])
def test_database_or_unexpected_errors_cannot_echo_private_data(activity, capsys, error, category):
    manager, _, _ = activity
    manager.db.init_tables = MagicMock(side_effect=error)
    with pytest.raises(GitHubSyncError, match=category):
        try:
            manager.sync()
        except GitHubSyncError:
            traceback.print_exc(file=sys.stderr)
            raise
    assert PRIVATE_MESSAGE not in capsys.readouterr().err


def test_bulk_analyze_prints_only_sanitized_failure(activity, monkeypatch, capsys):
    _, api, _ = activity
    arrange_failure(api, "403", "next_page")
    for source in ("readwise", "foursquare", "letterboxd", "overcast", "strong",
                   "apple_health", "blog", "hardcover", "oura"):
        monkeypatch.setattr(
            main, f"cmd_{source}_sync", MagicMock(side_effect=RuntimeError("Fixture source skipped")),
        )
    monkeypatch.setattr(Config, "validate_oura", lambda: True)
    monkeypatch.setattr(Config, "validate_schwab", lambda: True)
    monkeypatch.setattr(main, "cmd_schwab_analyze", lambda: None)
    main.cmd_analyze()
    output = capsys.readouterr()
    assert "Error: GitHub activity sync failed (HTTP 403)" in output.out
    for sensitive in SENSITIVE_VALUES:
        assert sensitive not in output.out + output.err


def test_uncaught_cli_subprocess_stderr_does_not_expose_private_url(tmp_path):
    script = """
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import requests
import main
from src.config import Config
from src.github.api_client import GitHubActivityClient
from src.github.database import GitHubDatabase
from src.github.sync import GitHubSyncManager

root = Path(sys.argv[1])
private_name = sys.argv[2]
api = GitHubActivityClient(token=sys.argv[3], username='user')
api._min_request_interval = 0
repo = {'full_name': 'user/' + private_name, 'name': private_name,
        'owner': {'login': 'user'}, 'private': True, 'fork': False}
api.get_owned_repos = MagicMock(return_value=[repo])
error = requests.Response()
error.status_code = 403
error.reason = private_name
error.url = 'https://api.github.com/repos/user/' + private_name + '/commits'
api.session.get = MagicMock(return_value=error)
with patch.object(Config, 'DATA_DIR', root), patch.object(Config, 'CODEBASE_USERNAME', 'user'), \
     patch.object(Config, 'CODEBASE_GITHUB_TOKEN', sys.argv[3]):
    manager = GitHubSyncManager(db=GitHubDatabase(str(root / 'github.db')), api=api)
    with patch('src.github.sync.GitHubSyncManager', return_value=manager):
        sys.argv = ['main.py', 'github-analyze']
        main.main()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), PRIVATE_REPO, TOKEN],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "GitHubSyncError: GitHub activity sync failed (HTTP 403)" in result.stderr
    for sensitive in SENSITIVE_VALUES:
        assert sensitive not in result.stdout + result.stderr
