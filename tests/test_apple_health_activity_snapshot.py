import json
from unittest.mock import Mock

import pytest
from github import GithubException

from src.apple_health import activity_snapshot
from src.apple_health.database import AppleHealthDatabase
from src.config import Config


def test_workout_preview_uses_latest_instant_and_only_public_fields(tmp_path, monkeypatch, capsys):
    path = tmp_path / "apple_health.db"
    monkeypatch.setattr(Config, "APPLE_HEALTH_DATABASE_PATH", path)
    db = AppleHealthDatabase()
    db.init_tables()
    with db.get_connection() as conn:
        conn.executescript("""
            INSERT INTO workouts
                (id, activity_type, activity_type_raw, started_at, ended_at,
                 duration_seconds, avg_heart_rate, device)
            VALUES
                ('older', 'run', 'Running', '2026-11-24T20:00:00+00:00',
                 '2026-11-24T20:30:00+00:00', 1800, 140, 'watch'),
                ('latest', 'strength training', 'Traditional Strength Training',
                 '2026-11-24T17:00:00-08:00', '2026-11-24T17:40:45-08:00', 2445, 125, 'watch'),
                ('walk', 'walk', 'Walking', '2026-11-25T03:00:00+00:00',
                 '2026-11-25T03:30:00+00:00', 1800, 100, 'watch');
        """)
    monkeypatch.setattr(activity_snapshot, "GitHubClient", Mock(side_effect=AssertionError))
    capsys.readouterr()

    activity_snapshot.publish_latest_workout(dry_run=True)

    assert json.loads(capsys.readouterr().out) == {
        "title": "Strength training", "detail": "40 min", "date": "2026-11-25",
    }
    activity_snapshot.GitHubClient.assert_not_called()


@pytest.mark.parametrize("state", ["missing", "matching", "changed"])
def test_only_changes_the_blog_when_needed(monkeypatch, state):
    snapshot = {"title": "Cycling", "detail": "20 min", "date": "2026-11-25"}
    client = Mock(target_branch="main")
    get_contents = client.repo.get_contents
    if state == "missing":
        get_contents.side_effect = GithubException(status=404)
    else:
        existing = snapshot if state == "matching" else {**snapshot, "date": "2026-11-24"}
        get_contents.return_value = Mock(decoded_content=json.dumps(existing).encode(), sha="current-sha")
    commit = Mock(html_url="https://github.com/example/blog/commit/workout")
    client.repo.create_file.return_value = client.repo.update_file.return_value = {"commit": commit}
    monkeypatch.setattr(Config, "validate_github", Mock())
    monkeypatch.setattr(activity_snapshot, "latest_workout_snapshot", Mock(return_value=snapshot))
    monkeypatch.setattr(activity_snapshot, "GitHubClient", Mock(return_value=client))

    activity_snapshot.publish_latest_workout()

    get_contents.assert_called_once_with(activity_snapshot.SNAPSHOT_PATH, ref="main")
    assert client.repo.create_file.call_count == (state == "missing")
    assert client.repo.update_file.call_count == (state == "changed")
    if state == "changed":
        args, kwargs = client.repo.update_file.call_args
        assert args[0] == activity_snapshot.SNAPSHOT_PATH
        assert json.loads(args[2]) == snapshot
        assert args[3] == "current-sha"
        assert kwargs == {"branch": "main"}
