"""Verify incremental Kaya imports, local month grouping, and published aggregates."""

from hashlib import sha256
from unittest.mock import MagicMock

import pytest

from main import cmd_kaya_analyze
from src.config import Config
from src.kaya.analytics import KayaAnalytics
from src.kaya.database import KayaDatabase
from src.kaya.importer import KayaImporter
from src.publish.publisher import Publisher

HEADER = "date,stiffness,rating,ascent_type,attempts,grade,color,climb_name,gym,location,country\n"
SEPTEMBER_SEND = (
    'Thu Oct 01 2026 03:00:00 GMT+0000 (GMT+00:00),0,,Redpoint,2,v4,Green,'
    '"Test climb, alpha",Test Gym,,\n'
)
OCTOBER_LOGS = (
    "Thu Oct 01 2026 20:00:00 GMT+0000 (GMT+00:00),0,3,Flash,1,v10,Blue,,Test Gym,,\n"
    "Thu Oct 01 2026 20:10:00 GMT+0000 (GMT+00:00),0,,Onsight,,v0,Red,,Test Gym,,\n"
    "Thu Oct 01 2026 20:12:00 GMT+0000 (GMT+00:00),0,,Redpoint,,,Green,,Test Gym,,\n"
    "Fri Oct 02 2026 20:00:00 GMT+0000 (GMT+00:00),0,,Attempt,3,v11,Blue,,Test Gym,,\n"
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(Config, "FILES_DIR", tmp_path)
    monkeypatch.setattr(Config, "KAYA_DATABASE_PATH", tmp_path / "kaya.db")
    monkeypatch.setattr(Config, "KAYA_TIMEZONE", "America/Los_Angeles")
    return KayaDatabase()


def test_newest_export_rebuilds_months_and_publishes_bouldering(db, tmp_path):
    earlier = tmp_path / "KAYA-Export-1790000000000.csv"
    earlier.write_text(HEADER + SEPTEMBER_SEND, encoding="utf-8")
    latest = tmp_path / "KAYA-Export-1791000000000.csv"
    latest.write_text("\ufeff" + HEADER + SEPTEMBER_SEND + OCTOBER_LOGS, encoding="utf-8")
    cmd_kaya_analyze(earlier)
    cmd_kaya_analyze()
    cmd_kaya_analyze()

    rows = db.fetch_rows(
        "SELECT local_date, climb_name, attempts FROM climbs ORDER BY logged_at",
        required_tables=("climbs",),
    )
    assert len(rows) == 5
    assert rows[0] == {
        "local_date": "2026-09-30", "climb_name": "Test climb, alpha", "attempts": "2",
    }
    assert rows[2]["attempts"] == ""

    absent = MagicMock()
    absent.fetch_rows.return_value = []
    absent.read_connection.return_value.__enter__.return_value = None
    other_sources = (
        "readwise", "foursquare", "letterboxd", "overcast", "strong", "apple_health",
        "blog", "hardcover", "github_activity", "oura", "surfilog",
    )
    publisher = Publisher(kaya_db=db, **{f"{source}_db": absent for source in other_sources})
    assert publisher._get_target_year_month() == "2026-10"
    report = publisher.generate_markdown()
    assert "## Bouldering" in report
    assert '"kaya"' in report
    assert "**Climbing Days**: 2 (+100% MoM, N/A YoY)" in report
    assert "**Sends**: 3 (+200% MoM, N/A YoY)" in report
    assert "**Recorded Attempts**: 4 (2 logs missing an attempt count)" in report
    assert "**Flashes**: 1" in report
    assert "**Onsights**: 1" in report
    assert "**Hardest V Grade**: V10" in report
    assert "| V0 | 1 |\n| V10 | 1 |\n| Ungraded | 1 |" in report
    assert "Test Gym" not in report

    files = publisher.data_generator.generate_data_files(min_year_month="2026-10")
    assert set(files) == {"data/activity/bouldering.yaml"}
    assert files["data/activity/bouldering.yaml"].splitlines()[1:8] == [
        '- month: "2026-10"', "  climbing_days: 2", "  sends: 3",
        "  flashes: 1", "  onsights: 1", "  hardest_v_grade: 10",
        '  grade_counts: {"V0": 1, "V10": 1, "": 1}',
    ]

    cmd_kaya_analyze(earlier)
    assert publisher._get_target_year_month() == "2026-10"
    assert "**Sends**: 3 (+200% MoM, N/A YoY)" in publisher.generate_markdown()


def test_reanalysis_backfills_attempt_counts_and_distinguishes_zero_from_missing(db, tmp_path):
    export = tmp_path / "export.csv"
    missing = SEPTEMBER_SEND.replace("Redpoint,2", "Redpoint,")
    zero = OCTOBER_LOGS.splitlines(keepends=True)[-1].replace("Attempt,3", "Attempt,0")
    export.write_text(HEADER + missing + zero, encoding="utf-8")
    cmd_kaya_analyze(export)
    with db.get_connection() as conn:
        conn.execute("ALTER TABLE analysis DROP COLUMN attempts")
        conn.execute("ALTER TABLE analysis DROP COLUMN climbs_missing_attempts")

    assert KayaAnalytics(db).analyze_climbs() == 2
    assert db.fetch_rows("""
        SELECT year_month, sends, attempts, climbs_missing_attempts
        FROM analysis ORDER BY year_month
    """) == [
        {"year_month": "2026-09", "sends": 1, "attempts": None, "climbs_missing_attempts": 1},
        {"year_month": "2026-10", "sends": 0, "attempts": 0, "climbs_missing_attempts": 0},
    ]


def test_invalid_export_preserves_existing_climbs(db, tmp_path):
    export = tmp_path / "export.csv"
    export.write_text(HEADER + SEPTEMBER_SEND, encoding="utf-8")
    importer = KayaImporter(db)
    assert importer.sync(export) == 1

    invalid = "bad timestamp,0,,Flash,1,v7,Red,,Test Gym,,\n"
    export.write_text(HEADER + OCTOBER_LOGS + invalid, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid date on line 6"):
        importer.sync(export)
    rows = db.fetch_rows("SELECT grade FROM climbs", required_tables=("climbs",))
    assert rows == [{"grade": "v4"}]


def test_analyze_imports_each_uploaded_archive(db, tmp_path):
    uploads = tmp_path / "kaya" / "exports"
    uploads.mkdir(parents=True)
    october = OCTOBER_LOGS.splitlines(keepends=True)
    for export in (HEADER + SEPTEMBER_SEND + october[0], HEADER + OCTOBER_LOGS):
        (uploads / f"{sha256(export.encode()).hexdigest()}.csv").write_text(export, encoding="utf-8")

    cmd_kaya_analyze()
    cmd_kaya_analyze()
    assert db.fetch_rows("SELECT year_month, sends FROM analysis ORDER BY year_month") == [
        {"year_month": "2026-09", "sends": 1},
        {"year_month": "2026-10", "sends": 3},
    ]
    assert db.fetch_rows("SELECT COUNT(*) AS climbs FROM climbs", required_tables=("climbs",)) == [
        {"climbs": 5},
    ]


def test_legacy_rows_get_stable_ids_without_losing_same_time_climbs(db, tmp_path):
    export = tmp_path / "export.csv"
    simultaneous = SEPTEMBER_SEND.replace("v4,Green", "v5,Blue")
    export.write_text(HEADER + SEPTEMBER_SEND * 2 + simultaneous, encoding="utf-8")
    importer = KayaImporter(db)
    assert importer.sync(export) == 3
    with db.get_connection() as conn:
        original = conn.execute("SELECT climb_id FROM climbs ORDER BY rowid").fetchall()
        conn.execute("DROP INDEX climbs_id")
        conn.execute("ALTER TABLE climbs DROP COLUMN climb_id")

    equivalent_offset = SEPTEMBER_SEND.replace(
        "Thu Oct 01 2026 03:00:00 GMT+0000 (GMT+00:00)",
        "Wed Sep 30 2026 20:00:00 GMT-0700 (Pacific Daylight Time)",
    )
    export.write_text(HEADER + simultaneous + equivalent_offset * 2, encoding="utf-8")
    assert importer.sync(export) == 0
    with db.get_connection() as conn:
        migrated = conn.execute("SELECT climb_id FROM climbs ORDER BY rowid").fetchall()
    assert migrated == original

    partial = OCTOBER_LOGS.splitlines(keepends=True)[0]
    export.write_text(HEADER + partial, encoding="utf-8")
    assert importer.sync(export) == 1
    assert importer.sync(export) == 0
    assert len(db.fetch_rows("SELECT climb_id FROM climbs", required_tables=("climbs",))) == 4
