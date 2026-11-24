from dataclasses import replace
from unittest.mock import Mock

import pytest

import main
from src.blog.database import BlogDatabase
from src.config import Config
from src.schwab.analytics import SchwabAnalytics
from src.schwab.database import SchwabDatabase
from src.source_operations import Source, run_sources


@pytest.fixture
def source(tmp_path):
    database = BlogDatabase(str(tmp_path / "fixture.db"))
    database.init_tables()
    return Source("fixture", "Fixture", lambda: database, Mock(return_value={}), Mock(return_value=1))


def test_registered_source_commands_share_sync_and_local_analysis(monkeypatch, source):
    monkeypatch.setattr(main, "source_catalog", lambda: (source,))

    assert main.main(["fixture-sync"]) == 0
    source.sync.assert_called_once_with()
    source.analyze.assert_not_called()

    assert main.main(["fixture-analyze", "--local"]) == 0
    source.sync.assert_called_once_with()
    source.analyze.assert_called_once_with(source.database())

    assert main.main(["fixture-analyze"]) == 0
    assert source.sync.call_count == source.analyze.call_count == 2


def test_aggregate_failure_continues_and_has_failed_exit_status(monkeypatch, source, capsys):
    failure = replace(source, key="failing", name="Failing", sync=Mock(side_effect=ValueError("broken")),
                      analyze=Mock())
    monkeypatch.setattr(main, "source_catalog", lambda: (failure, source))

    assert main.main(["analyze"]) == 1
    failure.analyze.assert_not_called()
    source.analyze.assert_called_once()
    assert "Refresh failed for Failing" in capsys.readouterr().out


def test_unconfigured_optional_source_is_skipped_but_sync_failure_is_visible(source):
    optional = replace(source, optional_for_reporting=True,
                       validate=Mock(side_effect=ValueError("missing credentials")))
    assert run_sources([optional], "refresh", reporting=True)
    optional.sync.assert_not_called()

    optional.validate.side_effect = None
    optional.sync.side_effect = ValueError("bad provider response")
    assert not run_sources([optional], "refresh", reporting=True)
    optional.analyze.assert_not_called()


def test_pipeline_refreshes_once(monkeypatch, source):
    monkeypatch.setattr(main, "source_catalog", lambda: (source,))
    monkeypatch.setattr(main, "REPORT_SOURCES", (source.key,))
    publisher = Mock()
    publisher.publish_pipeline.return_value = {
        "draft": {"url": "draft"}, "data_repo": {"url": "data"},
        "blog_repo": {"url": "blog"}, "blog_start_year_month": "2025-11",
    }
    monkeypatch.setattr("src.publish.Publisher", lambda: publisher)

    assert main.main(["pipeline", "--last-month"]) == 0
    source.sync.assert_called_once_with()
    source.analyze.assert_called_once_with(source.database())
    publisher.publish_pipeline.assert_called_once_with(last_month=True)


def test_status_does_not_create_or_open_writable_database(monkeypatch, source, tmp_path, capsys):
    missing = tmp_path / "empty" / "source.db"
    source = replace(source, database=lambda: BlogDatabase(str(missing)))
    monkeypatch.setattr(main, "source_catalog", lambda: (source,))

    assert main.main(["status"]) == 0
    assert "database: not initialized" in capsys.readouterr().out
    assert not missing.parent.exists()
    source.sync.assert_not_called()


def test_status_reports_schwab_monthly_tables(monkeypatch, tmp_path, capsys):
    path = tmp_path / "schwab.db"
    monkeypatch.setattr(Config, "SCHWAB_DATABASE_PATH", path)
    db = SchwabDatabase()
    db.init_tables()
    schwab = next(source for source in main.source_catalog() if source.key == "schwab")
    monkeypatch.setattr(main, "source_catalog", lambda: (schwab,))

    assert main.main(["status"]) == 0
    assert "analysis: unavailable" in capsys.readouterr().out

    SchwabAnalytics(db).analyze_monthly_pnl()
    assert main.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "monthly_pnl records: 0" in output
    assert "monthly_account_snapshots records: 0" in output
    assert "analysis: unavailable" not in output
