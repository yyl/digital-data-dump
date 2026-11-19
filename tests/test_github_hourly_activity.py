from src.github.analytics import GitHubAnalytics, hourly_activity
from src.github.database import GitHubDatabase
from src.publish.activity_chart import render_commit_hours
from src.publish.publisher import Publisher


def test_hourly_counts_follow_pacific_dst_and_retain_report_month(tmp_path):
    commits = [
        {'sha': 'winter', 'repo': 'user/public', 'author_date': '2026-03-01T07:30:00Z',
         'date_month': '2026-03', 'is_private': False},
        {'sha': 'summer', 'repo': 'user/secret', 'author_date': '2026-03-09T07:30:00Z',
         'date_month': '2026-03', 'is_private': True},
        {'sha': 'offset', 'repo': 'user/public', 'author_date': '2026-03-09T03:30:00-04:00',
         'date_month': '2026-03', 'is_private': False},
    ]
    expected = [
        {'year_month': '2026-03', 'hour': 0, 'public_commits': 1, 'private_commits': 1},
        {'year_month': '2026-03', 'hour': 23, 'public_commits': 1, 'private_commits': 0},
    ]
    assert hourly_activity(commits) == expected
    db = GitHubDatabase(str(tmp_path / 'github.db'))
    db.init_tables()
    db.upsert_commits(commits)
    GitHubAnalytics(db).analyze_commits()
    publisher = Publisher(github_activity_db=db)
    assert publisher._get_github_hourly_activity('2026-03') == [
        {k: v for k, v in row.items() if k != 'year_month'} for row in expected
    ]
    svg = render_commit_hours(expected)
    assert 'America/Los_Angeles' in svg and 'user/secret' not in svg
    assert '00:00 private: 1' in svg and '23:00 public: 1' in svg
    with db.get_connection() as conn:
        conn.execute("DELETE FROM commits WHERE sha = 'winter'")
    GitHubAnalytics(db).analyze_commits()
    assert len(publisher._get_github_hourly_activity('2026-03')) == 1


def test_hourly_counts_skip_unresolved_timestamps():
    assert hourly_activity([
        {'author_date': 'broken', 'date_month': '2026-01', 'is_private': False},
        {'author_date': '2026-01-01T12:00:00', 'date_month': '2026-01', 'is_private': True},
    ]) == []
