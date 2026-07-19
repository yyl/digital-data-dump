from src.apple_health.analytics import AppleHealthAnalytics
from src.apple_health.database import AppleHealthDatabase
import sqlite3


def test_analyze_workouts_groups_by_month_and_sums_duration_seconds_and_calories(tmp_path):
    db = AppleHealthDatabase(str(tmp_path / "apple_health.db"))
    db.init_tables()
    db.save_workouts([
        {
            "id": "w1",
            "activity_type": "run",
            "activity_type_raw": "HKWorkoutActivityTypeRunning",
            "started_at": "2026-04-01T07:00:00-07:00",
            "ended_at": "2026-04-01T07:30:00-07:00",
            "duration_seconds": 1800,
            "active_calories": 300,
            "total_calories": 320,
            "avg_heart_rate": 152,
            "max_heart_rate": 178,
            "source_name": "Apple Watch",
            "source_version": "10.0",
            "device": "Watch",
            "creation_date": "2026-04-01T07:31:00-07:00",
        },
        {
            "id": "w2",
            "activity_type": "walk",
            "activity_type_raw": "HKWorkoutActivityTypeWalking",
            "started_at": "2026-04-02T18:00:00-07:00",
            "ended_at": "2026-04-02T18:20:00-07:00",
            "duration_seconds": 1200,
            "active_calories": 50,
            "total_calories": None,
            "avg_heart_rate": 105,
            "max_heart_rate": 110,
            "source_name": "Apple Watch",
            "source_version": None,
            "device": None,
            "creation_date": "2026-04-02T18:21:00-07:00",
        },
        {
            "id": "w3",
            "activity_type": "cycling",
            "activity_type_raw": "HKWorkoutActivityTypeCycling",
            "started_at": "2026-05-03T08:00:00-07:00",
            "ended_at": "2026-05-03T08:45:00-07:00",
            "duration_seconds": 2700,
            "active_calories": 400,
            "total_calories": 450,
            "avg_heart_rate": 140,
            "max_heart_rate": 165,
            "source_name": "Apple Watch",
            "source_version": None,
            "device": None,
            "creation_date": "2026-05-03T08:46:00-07:00",
        },
    ])

    analytics = AppleHealthAnalytics(db=db)
    assert analytics.analyze_workouts() == 2

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT year_month, workouts, total_duration_seconds, total_calories FROM analysis ORDER BY year_month ASC"
        )
        rows = [dict(row) for row in cursor.fetchall()]

    assert rows == [
        {"year_month": "2026-04", "workouts": 1, "total_duration_seconds": 1800, "total_calories": 320.0},
        {"year_month": "2026-05", "workouts": 1, "total_duration_seconds": 2700, "total_calories": 450.0},
    ]


def test_analyze_recreates_old_analysis_schema(tmp_path):
    db_path = tmp_path / "apple_health.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE workouts (
            id TEXT PRIMARY KEY NOT NULL,
            activity_type TEXT NOT NULL,
            activity_type_raw TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            active_calories REAL,
            total_calories REAL,
            avg_heart_rate REAL,
            max_heart_rate REAL,
            source_name TEXT,
            source_version TEXT,
            device TEXT,
            creation_date TEXT,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        )
        """
    )
    conn.execute(
        """
        INSERT INTO workouts (
            id, activity_type, activity_type_raw, started_at, ended_at,
            duration_seconds, active_calories, total_calories
        ) VALUES (
            'w1', 'run', 'HKWorkoutActivityTypeRunning',
            '2026-04-01T07:00:00-07:00', '2026-04-01T07:30:00-07:00',
            1800, 300, 320
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE analysis (
            year_month TEXT PRIMARY KEY,
            year TEXT NOT NULL,
            month TEXT NOT NULL,
            workouts INTEGER DEFAULT 0,
            total_minutes INTEGER DEFAULT 0,
            total_calories REAL DEFAULT 0,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO analysis (year_month, year, month, workouts, total_minutes, total_calories, updated_at)
        VALUES ('2026-04', '2026', '04', 2, 50, 320, '2026-04-05T00:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    db = AppleHealthDatabase(str(db_path))
    db.init_tables()
    analytics = AppleHealthAnalytics(db=db)
    analytics.analyze_workouts()

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT workouts, total_duration_seconds, total_calories FROM analysis WHERE year_month = '2026-04'")
        row = cursor.fetchone()
        assert row[0] == 1
        assert row[1] == 1800
        assert row[2] == 320.0
