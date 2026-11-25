import json
from unittest.mock import Mock

import pytest

from src.config import Config
from src.overcast import activity_snapshot
from src.overcast.database import OvercastDatabase


def test_snapshot_uses_vault_history_without_overcast_credentials(tmp_path, monkeypatch):
    for setting in ("OVERCAST_COOKIE", "OVERCAST_EMAIL", "OVERCAST_PASSWORD"):
        monkeypatch.setattr(Config, setting, "")
    monkeypatch.setattr(Config, "FILES_DIR", tmp_path)
    db_path = tmp_path / "overcast.db"
    monkeypatch.setattr(Config, "OVERCAST_DATABASE_PATH", db_path)
    with OvercastDatabase().get_connection() as conn:
        conn.executescript("""
            CREATE TABLE feeds (overcastId INTEGER, title TEXT);
            CREATE TABLE episodes (feedId INTEGER, title TEXT, overcastUrl TEXT, played INTEGER, userUpdatedDate TEXT);
            CREATE TABLE playlists (id INTEGER);
            INSERT INTO feeds VALUES (1, 'Example Show');
            INSERT INTO episodes VALUES
                (1, 'Older', 'https://overcast.fm/+old', 1, '2026-11-24T10:00:00+00:00'),
                (1, 'Latest', 'https://overcast.fm/+latest', 1, '2026-11-24T06:00:00-05:00'),
                (1, 'Unplayed', 'https://overcast.fm/+other', 0, '2026-11-24T12:00:00+00:00');
        """)

    assert activity_snapshot._refresh_snapshot() == {
        "title": "Latest", "url": "https://overcast.fm/+latest", "detail": "Example Show",
        "date": "2026-11-24T11:00:00+00:00",
    }


@pytest.mark.parametrize("existing_date, should_publish", [("23", True), ("24", False), ("25", False)])
def test_snapshot_only_publishes_a_changed_record_without_going_backwards(monkeypatch, existing_date, should_publish):
    snapshot = {"title": "Latest", "url": "", "detail": "Example Show", "date": "2026-11-24T11:00:00+00:00"}
    existing = {**snapshot, "date": f"2026-11-{existing_date}T11:00:00+00:00"}
    client = Mock(target_branch="main")
    client.repo.get_contents.return_value.decoded_content = json.dumps(existing).encode()
    client.create_or_update_files.return_value = {"url": "https://github.com/example/blog/commit/latest"}
    monkeypatch.setattr(Config, "validate_github", Mock())
    monkeypatch.setattr(activity_snapshot, "_refresh_snapshot", lambda: snapshot)
    monkeypatch.setattr(activity_snapshot, "GitHubClient", Mock(return_value=client))

    activity_snapshot.publish_latest_podcast()

    client.repo.get_contents.assert_called_once_with(activity_snapshot.SNAPSHOT_PATH, ref="main")
    if should_publish:
        files = client.create_or_update_files.call_args.args[0]
        assert list(files) == [activity_snapshot.SNAPSHOT_PATH]
        assert json.loads(files[activity_snapshot.SNAPSHOT_PATH]) == snapshot
    else:
        client.create_or_update_files.assert_not_called()
