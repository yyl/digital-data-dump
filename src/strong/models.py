"""SQL schema definitions for Strong workout data tables."""

CREATE_WORKOUTS_TABLE = """
CREATE TABLE IF NOT EXISTS workouts (
    id TEXT PRIMARY KEY NOT NULL,
    workout_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    started_at_utc TEXT,
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

CREATE_EXERCISES_TABLE = """
CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id TEXT NOT NULL,
    exercise_name TEXT NOT NULL,
    set_order INTEGER NOT NULL,
    weight REAL DEFAULT 0,
    reps REAL DEFAULT 0,
    distance REAL DEFAULT 0,
    seconds REAL DEFAULT 0,
    notes TEXT,
    rpe REAL,
    FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);
"""

CREATE_ANALYSIS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis (
    year_month TEXT PRIMARY KEY,
    year TEXT NOT NULL,
    month TEXT NOT NULL,
    workouts INTEGER DEFAULT 0,
    total_minutes INTEGER DEFAULT 0,
    unique_exercises INTEGER DEFAULT 0,
    total_sets INTEGER DEFAULT 0,
    updated_at TEXT
);
"""

RAW_TABLES = [
    CREATE_WORKOUTS_TABLE,
    CREATE_EXERCISES_TABLE,
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        source TEXT NOT NULL,
        user_id TEXT,
        weight_unit TEXT,
        timezone TEXT,
        last_successful_sync_at TEXT NOT NULL
    );
    """,
]

RAW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_exercises_workout_id ON exercises(workout_id);",
    "CREATE INDEX IF NOT EXISTS idx_exercises_name ON exercises(exercise_name);",
    "CREATE INDEX IF NOT EXISTS idx_workouts_started ON workouts(started_at);",
]

ANALYSIS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_analysis_year_month ON analysis(year, month);",
]
