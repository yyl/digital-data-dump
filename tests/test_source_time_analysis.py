from src.overcast.analytics import OvercastAnalytics
from src.overcast.database import OvercastDatabase
from src.publish.publisher import Publisher
from src.readwise.analytics import ReadwiseAnalytics
from src.readwise.database import ReadwiseDatabase


def test_readwise_persists_resolved_source_time_and_refreshes_moved_articles(tmp_path):
    db = ReadwiseDatabase(str(tmp_path / "readwise.db"))
    db.init_tables()
    with db.get_connection() as conn:
        conn.executescript("""
            INSERT INTO documents (id, title, site_name, location, last_moved_at, reading_time)
            VALUES ('a', 'Newsletter: Issue 1', NULL, 'archive', '2026-03-10', '5 minutes'),
                   ('b', 'Issue 2', 'Newsletter', 'archive', '2026-03-25', NULL),
                   ('c', 'Unread', 'Newsletter', 'later', '2026-03-25', '25 minutes');
        """)
    publisher = Publisher(readwise_db=db)
    assert publisher._get_source_time_analysis(db, "2026-03") is None
    analytics = ReadwiseAnalytics(db)
    assert analytics.analyze_archived() == 1
    assert publisher._get_source_time_analysis(db, "2026-03") == [
        {"source_name": "Newsletter", "items": 2, "timed_items": 1, "total_seconds": 300}
    ]
    with db.get_connection() as conn:
        conn.execute("UPDATE documents SET location = 'later' WHERE id IN ('a', 'b')")
    assert analytics.analyze_archived() == 0
    assert publisher._get_source_time_analysis(db, "2026-03") == []


def test_overcast_persists_known_seconds_and_explicit_missing_duration_counts(tmp_path):
    db = OvercastDatabase(str(tmp_path / "overcast.db"))
    with db.get_connection() as conn:
        conn.executescript("""
            CREATE TABLE feeds (overcastId, title, overcastAddedDate, dateRemoveDetected);
            CREATE TABLE episodes (feedId, played, userUpdatedDate, duration_seconds);
            CREATE TABLE playlists (title);
            INSERT INTO feeds VALUES (1, 'First Show', '2026-02-10', NULL), (2, 'Second Show', NULL, NULL);
            INSERT INTO episodes VALUES (1, 1, '2026-03-01', 91),
                                        (1, 1, '2026-03-01', NULL),
                                        (1, 0, '2026-03-01', 600),
                                        (2, 1, '2026-03-01', NULL);
        """)
    publisher = Publisher(overcast_db=db)
    assert OvercastAnalytics(db).analyze_podcasts() == 2
    source_rows = publisher._get_source_time_analysis(db, "2026-03")
    assert {row["source_name"]: row for row in source_rows} == {
        "First Show": {"source_name": "First Show", "items": 2, "timed_items": 1, "total_seconds": 91},
        "Second Show": {"source_name": "Second Show", "items": 1, "timed_items": 0, "total_seconds": None},
    }
    report = publisher.markdown_generator._generate_podcasts_block([], source_analysis=source_rows)
    assert "| First Show | 2 | 2m (partial) |" in report
    assert "| Other | 1 | N/A |" in report
    assert publisher._get_overcast_analysis("2026-03")["minutes_listened"] == 2
