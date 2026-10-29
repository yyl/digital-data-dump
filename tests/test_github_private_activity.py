"""Regression coverage for private activity totals and public report details."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from src.config import Config
from src.github.analytics import GitHubAnalytics
from src.github.database import GitHubDatabase
from src.github.sync import GitHubSyncManager
from src.publish.data_generator import DataGenerator
from src.publish.markdown_generator import MarkdownGenerator
from src.publish.publisher import Publisher


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    result = GitHubDatabase(str(tmp_path / "github.db"))
    result.init_tables()
    return result


def repository(name, private=False):
    return {
        "full_name": f"user/{name}", "name": name, "owner": {"login": "user"},
        "private": private, "fork": False,
    }


def api_commit(sha, message, date="2026-10-01T12:00:00Z"):
    return {"sha": sha, "commit": {"message": message, "author": {"date": date}}}


def publisher_for(db):
    # Exclude unrelated sources while exercising real GitHub queries and rendering.
    publisher = Publisher.__new__(Publisher)
    absent = MagicMock()
    absent.exists.return_value = False
    absent.fetch_rows.return_value = []
    absent.read_connection.return_value.__enter__.return_value = None
    for source in ("readwise", "foursquare", "letterboxd", "overcast", "strong", "apple_health",
                   "blog", "hardcover", "oura"):
        setattr(publisher, f"{source}_db", absent)
    publisher.github_activity_db = db
    publisher.markdown_generator = MarkdownGenerator()
    return publisher


def test_private_history_counts_without_publishing_details(db, capsys):
    api = MagicMock()
    api.get_owned_repos.return_value = [repository("public"), repository("secret", private=True)]
    private_commit = api_commit("private-sha", "Confidential project milestone")
    public_commit = api_commit("public-sha", "Public project update")
    api.get_commits.side_effect = [[public_commit], [private_commit]]
    manager = GitHubSyncManager(db=db, api=api)

    assert manager.sync() == {"commits": 2, "repos": 2}
    api.get_commits.assert_any_call("user", "secret", since=None)
    assert "user/secret" not in capsys.readouterr().out

    # An inclusive incremental fetch must not count either SHA twice.
    api.get_commits.side_effect = [[public_commit], [private_commit]]
    assert manager.sync() == {"commits": 0, "repos": 0}
    api.get_commits.assert_any_call("user", "secret", since="2026-10-01T12:00:00Z")
    assert db.get_stats() == {"commits": 2, "repos": 2}
    assert GitHubAnalytics(db=db).analyze_commits() == 1

    publisher = publisher_for(db)
    stats = publisher._get_github_analysis("2026-10")
    assert stats["commits"] == 2
    assert stats["repos_touched"] == 2
    details = publisher._get_github_commits("2026-10")
    assert [row["sha"] for row in details] == ["public-sha"]
    assert publisher._get_new_github_repos("2026-10") == ["user/public"]
    markdown = publisher.generate_markdown("2026-10")
    assert "- **Commits**:\n    - Public: 1 (N/A MoM, N/A YoY)\n    - Private: 1" in markdown
    assert "- **Repos Touched**:\n    - Public: 1 (N/A MoM, N/A YoY)\n    - Private: 1" in markdown
    assert "Public project update" in markdown
    assert "user/secret" not in markdown
    assert "Confidential" not in markdown
    assert "private-sha" not in markdown

    generator = DataGenerator.__new__(DataGenerator)
    generator.github_activity_db = db
    assert generator._get_all_github() == [
        {"month": "2026-10", "commits": 2, "repos_touched": 2,
         "public_commits": 1, "private_commits": 1,
         "public_repos_touched": 1, "private_repos_touched": 1},
    ]
    with db.get_connection() as conn:
        private = conn.execute("SELECT * FROM commits WHERE sha = 'private-sha'").fetchone()
        assert private["is_private"] == 1
        assert private["message"] == "Confidential project milestone"


@pytest.mark.parametrize("new_visibility", [True, False, None])
def test_visibility_updates_without_new_commits(db, new_visibility):
    api = MagicMock()
    api.get_owned_repos.return_value = [repository("project", private=new_visibility is False)]
    commit = api_commit("sha", "Project work")
    api.get_commits.return_value = [commit]
    manager = GitHubSyncManager(db=db, api=api)
    manager.sync()

    # None means the token can no longer discover the repository.
    api.get_owned_repos.return_value = (
        [] if new_visibility is None else [repository("project", private=new_visibility)]
    )
    api.get_commits.return_value = []
    assert manager.sync() == {"commits": 0, "repos": 0}
    publisher = publisher_for(db)
    assert bool(publisher._get_github_commits("2026-10")) is (new_visibility is False)
    assert bool(publisher._get_new_github_repos("2026-10")) is (new_visibility is False)
    assert db.get_stats() == {"commits": 1, "repos": 1}
    GitHubAnalytics(db=db).analyze_commits()
    stats = publisher._get_github_analysis("2026-10")
    # Losing discovery hides details without reclassifying public activity as private.
    assert stats["private_commits"] == int(new_visibility is True)
    assert stats["public_commits"] == int(new_visibility is not True)


def test_legacy_public_database_preview_and_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE commits (
                sha TEXT PRIMARY KEY, repo TEXT NOT NULL, message TEXT,
                author_date TEXT NOT NULL, date_month TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO commits VALUES (
                'old-sha', 'user/public', 'Existing public commit',
                '2026-10-01T12:00:00Z', '2026-10'
            )
        """)

    legacy = GitHubDatabase(str(path))
    publisher = publisher_for(legacy)
    assert publisher._get_new_github_repos("2026-10") == ["user/public"]
    assert publisher._get_github_commits("2026-10")[0]["sha"] == "old-sha"
    legacy.init_tables()
    legacy.init_tables()  # Migration is idempotent and preserves old data.
    with legacy.get_connection() as conn:
        row = conn.execute("SELECT * FROM commits").fetchone()
        assert row["is_private"] == 0
        assert row["message"] == "Existing public commit"
    assert publisher._get_new_github_repos("2026-10") == ["user/public"]


def test_bulk_upsert_preserves_private_flag(db):
    commit = {
        "sha": "sha", "repo": "user/project", "message": "Project update",
        "author_date": "2026-10-01T12:00:00Z", "date_month": "2026-10",
    }
    db.upsert_commit(commit)
    db.upsert_commit({**commit, "is_private": True})
    assert db.get_stats() == {"commits": 1, "repos": 1}
    assert publisher_for(db)._get_github_commits("2026-10") == []


def add_month(db, month, public_commits, private_commits, public_repos, private_repos):
    commits = []
    for private, count, repos in [(False, public_commits, public_repos),
                                  (True, private_commits, private_repos)]:
        visibility = "private" if private else "public"
        for i in range(count):
            commits.append({
                "sha": f"{month}-{visibility}-{i}",
                "repo": f"user/{visibility}-{i % repos}",
                "message": f"{visibility} work",
                "author_date": f"{month}-01T12:00:00Z",
                "date_month": month, "is_private": private,
            })
    db.upsert_commits(commits)


def test_visibility_counts_have_independent_mom_yoy_and_distinct_repos(db):
    add_month(db, "2025-10", 2, 4, 1, 2)
    add_month(db, "2026-09", 4, 2, 2, 1)
    add_month(db, "2026-10", 3, 6, 1, 3)
    assert GitHubAnalytics(db=db).analyze_commits() == 3
    publisher = publisher_for(db)
    stats = publisher._get_github_analysis("2026-10")
    assert stats["commits"] == 9
    assert stats["public_commits"] == 3
    assert stats["private_commits"] == 6
    assert stats["repos_touched"] == 4
    assert stats["public_repos_touched"] == 1
    assert stats["private_repos_touched"] == 3
    markdown = publisher.generate_markdown("2026-10")
    assert (
        "- **Commits**:\n"
        "    - Public: 3 (-25% MoM, +50% YoY)\n"
        "    - Private: 6 (+200% MoM, +50% YoY)\n"
        "- **Repos Touched**:\n"
        "    - Public: 1 (-50% MoM, +0% YoY)\n"
        "    - Private: 3 (+200% MoM, +50% YoY)"
    ) in markdown
    assert "user/private-" not in markdown
    assert "private work" not in markdown


def test_zero_category_and_zero_baseline_render_correctly(db):
    add_month(db, "2026-09", 0, 2, 0, 1)
    add_month(db, "2026-10", 3, 0, 1, 0)
    GitHubAnalytics(db=db).analyze_commits()
    publisher = publisher_for(db)
    stats = publisher._get_github_analysis("2026-10")
    assert stats["private_commits"] == 0
    assert stats["private_repos_touched"] == 0
    markdown = publisher.generate_markdown("2026-10")
    assert "Public: 3 (N/A MoM, N/A YoY)" in markdown
    assert "Private: 0 (-100% MoM, N/A YoY)" in markdown


def test_legacy_analysis_migration_recalculates_all_history(db):
    add_month(db, "2025-10", 2, 4, 1, 2)
    add_month(db, "2026-10", 3, 6, 1, 3)
    with db.get_connection() as conn:
        conn.execute("""
            CREATE TABLE analysis (
                year_month TEXT PRIMARY KEY, year TEXT, month TEXT,
                commits INTEGER, repos_touched INTEGER, updated_at TEXT
            )
        """)
        conn.execute("INSERT INTO analysis VALUES ('2026-10', '2026', '10', 9, 4, NULL)")

    publisher = publisher_for(db)
    assert "- **Commits**: 9" in publisher.generate_markdown("2026-10")
    generator = DataGenerator.__new__(DataGenerator)
    generator.github_activity_db = db
    assert generator._get_all_github() == [{"month": "2026-10", "commits": 9, "repos_touched": 4}]
    analytics = GitHubAnalytics(db=db)
    analytics._ensure_analysis_table()
    # Added nullable columns must not turn unknown splits into misleading zeros.
    assert "- **Commits**: 9" in publisher.generate_markdown("2026-10")
    assert analytics.analyze_commits() == 2
    assert analytics.analyze_commits() == 2
    assert "    - Private: 6" in publisher.generate_markdown("2026-10")
    assert publisher._get_github_analysis("2025-10")["private_repos_touched"] == 2
    records = generator._get_all_github()
    assert records[-1] == {
        "month": "2026-10", "commits": 9, "repos_touched": 4,
        "public_commits": 3, "private_commits": 6,
        "public_repos_touched": 1, "private_repos_touched": 3,
    }
