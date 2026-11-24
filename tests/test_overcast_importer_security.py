import subprocess
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from src.overcast.importer import OvercastImporter
from src.config import Config

@patch.object(OvercastImporter, 'get_authenticated_cookie', return_value=None)
def test_sync_timeout_handled(_cookie):
    """Test that subprocess.TimeoutExpired is handled gracefully."""
    importer = OvercastImporter()

    # Mock find_latest_export to return a dummy path
    with patch.object(OvercastImporter, 'find_latest_export', return_value=Path("dummy.opml")):
        # Mock subprocess.run to raise TimeoutExpired
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd=["overcast-to-sqlite"], timeout=60)):
            # Mock get_db_stats just in case, though it shouldn't be called on timeout
            with patch.object(OvercastImporter, 'get_db_stats') as mock_get_stats:
                with pytest.raises(RuntimeError, match="timed out after 60 seconds"):
                    importer.sync()
                mock_get_stats.assert_not_called()

@patch.object(OvercastImporter, 'get_authenticated_cookie', return_value=None)
def test_sync_called_process_error_handled(_cookie):
    """Test that subprocess.CalledProcessError is handled gracefully."""
    importer = OvercastImporter()

    with patch.object(OvercastImporter, 'find_latest_export', return_value=Path("dummy.opml")):
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, ["overcast-to-sqlite"], stderr="error")):
            with pytest.raises(RuntimeError, match="exited with status 1"):
                importer.sync()

@patch.object(OvercastImporter, 'get_authenticated_cookie', return_value=None)
def test_sync_file_not_found_handled(_cookie):
    """Test that FileNotFoundError is handled gracefully."""
    importer = OvercastImporter()

    with patch.object(OvercastImporter, 'find_latest_export', return_value=Path("dummy.opml")):
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            with pytest.raises(RuntimeError, match="unavailable"):
                importer.sync()


def test_sync_uses_direct_export_when_cookie_configured(monkeypatch):
    """Test that direct export skips the local OPML requirement."""
    importer = OvercastImporter()
    monkeypatch.setattr(Config, "OVERCAST_COOKIE", "cookie-value")
    monkeypatch.setattr(Config, "OVERCAST_EMAIL", "")
    monkeypatch.setattr(Config, "OVERCAST_PASSWORD", "")

    completed = subprocess.CompletedProcess(args=["overcast-to-sqlite"], returncode=0)

    with patch.object(OvercastImporter, 'find_latest_export') as mock_find_latest_export:
        with patch.object(OvercastImporter, 'get_db_stats', return_value={"feeds": 1, "episodes": 2, "playlists": 3}):
            with patch.object(OvercastImporter, '_enrich_durations'):
                with patch('subprocess.run', return_value=completed) as mock_run:
                    stats = importer.sync()

    assert stats == {"feeds": 1, "episodes": 2, "playlists": 3}
    mock_find_latest_export.assert_not_called()
    command = mock_run.call_args.args[0]
    kwargs = mock_run.call_args.kwargs
    assert "--load" not in command
    env = kwargs["env"]
    assert env["OVERCAST_COOKIE"] == "cookie-value"


def test_sync_falls_back_to_local_export_when_no_direct_auth(monkeypatch):
    """Test that local OPML import is still used when direct auth is unavailable."""
    importer = OvercastImporter()
    monkeypatch.setattr(Config, "OVERCAST_COOKIE", "")
    monkeypatch.setattr(Config, "OVERCAST_EMAIL", "")
    monkeypatch.setattr(Config, "OVERCAST_PASSWORD", "")

    completed = subprocess.CompletedProcess(args=["overcast-to-sqlite"], returncode=0)

    with patch.object(OvercastImporter, 'find_latest_export', return_value=Path("dummy.opml")):
        with patch.object(OvercastImporter, 'get_db_stats', return_value={"feeds": 1, "episodes": 2, "playlists": 3}):
            with patch.object(OvercastImporter, '_enrich_durations'):
                with patch('subprocess.run', return_value=completed) as mock_run:
                    importer.sync()

    command = mock_run.call_args.args[0]
    assert "--load" in command
    assert "dummy.opml" in command


def test_get_authenticated_cookie_logs_in_with_credentials(monkeypatch):
    """Test that credentials can be exchanged for an Overcast session cookie."""
    session = MagicMock()
    session.cookies.get.return_value = "cookie-value"
    session.post.return_value.text = "logged in"

    monkeypatch.setattr(Config, "OVERCAST_COOKIE", "")
    monkeypatch.setattr(Config, "OVERCAST_EMAIL", "user@example.com")
    monkeypatch.setattr(Config, "OVERCAST_PASSWORD", "secret")

    with patch("src.overcast.importer.requests.Session", return_value=session):
        cookie = OvercastImporter.get_authenticated_cookie()

    assert cookie == "cookie-value"
    session.post.assert_called_once_with(
        "https://overcast.fm/login",
        data={
            "then": "podcasts",
            "email": "user@example.com",
            "password": "secret",
        },
        allow_redirects=True,
        timeout=30,
    )
