"""SQL schema definitions for Apple Health workout data."""

CREATE_WORKOUTS_TABLE = """
CREATE TABLE IF NOT EXISTS workouts (
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
);
"""

CREATE_ANALYSIS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis (
    year_month TEXT PRIMARY KEY,
    year TEXT NOT NULL,
    month TEXT NOT NULL,
    workouts INTEGER DEFAULT 0,
    total_duration_seconds INTEGER DEFAULT 0,
    total_calories REAL DEFAULT 0,
    updated_at TEXT
);
"""

RAW_TABLES = [
    CREATE_WORKOUTS_TABLE,
]

RAW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_apple_health_workouts_started ON workouts(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_apple_health_workouts_activity_type ON workouts(activity_type);",
]

JSON_TABLES = [
    """CREATE TABLE IF NOT EXISTS json_batches (
        batch_id TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL,
        received_at TEXT NOT NULL,
        archive_path TEXT NOT NULL,
        envelope_json TEXT NOT NULL,
        workout_count INTEGER NOT NULL,
        status TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS json_observations (
        batch_id TEXT NOT NULL REFERENCES json_batches(batch_id),
        identifier TEXT NOT NULL,
        snapshot_json TEXT NOT NULL,
        PRIMARY KEY (batch_id, identifier)
    )""",
    """CREATE TABLE IF NOT EXISTS json_workout_aliases (
        identifier TEXT PRIMARY KEY,
        workout_id TEXT NOT NULL UNIQUE REFERENCES workouts(id),
        origin TEXT NOT NULL CHECK (origin IN ('xml', 'json'))
    )""",
    """CREATE TABLE IF NOT EXISTS json_import_state (
        identifier TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        reason TEXT,
        received_at TEXT,
        snapshot_json TEXT,
        provenance_json TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_json_observations_identifier ON json_observations(identifier)",
]

ANALYSIS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_apple_health_analysis_year_month ON analysis(year, month);",
]
