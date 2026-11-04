"""SQLite schemas for Surfilog raw snapshots and monthly surfing analysis."""

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    name TEXT,
    started_at TEXT NOT NULL,
    utc_offset_min INTEGER,
    local_started_at TEXT NOT NULL,
    date_month TEXT NOT NULL,
    duration_sec REAL NOT NULL,
    reported_wave_count INTEGER NOT NULL,
    paddling_distance_m REAL,
    board_id INTEGER,
    board_name TEXT,
    spot_id INTEGER,
    spot_name TEXT,
    raw_json TEXT NOT NULL,
    track_points_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
)
"""

CREATE_WAVES_TABLE = """
CREATE TABLE IF NOT EXISTS waves (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    wave_num INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    duration_sec REAL NOT NULL,
    distance_m REAL NOT NULL,
    max_speed_kmh REAL NOT NULL,
    start_lat REAL,
    start_lon REAL,
    is_excluded INTEGER NOT NULL CHECK (is_excluded IN (0, 1)),
    coords_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE (session_id, wave_num)
)
"""

CREATE_SYNC_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    user_id INTEGER NOT NULL,
    last_successful_sync_at TEXT NOT NULL
)
"""

RAW_TABLES = [CREATE_SESSIONS_TABLE, CREATE_WAVES_TABLE, CREATE_SYNC_STATE_TABLE]
RAW_INDEXES = ["CREATE INDEX IF NOT EXISTS idx_sessions_month ON sessions(date_month)"]

CREATE_ANALYSIS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis (
    year_month TEXT PRIMARY KEY,
    year TEXT NOT NULL,
    month TEXT NOT NULL,
    sessions INTEGER NOT NULL,
    waves INTEGER NOT NULL,
    total_duration_seconds REAL NOT NULL,
    surf_time_seconds REAL NOT NULL,
    surf_distance_m REAL NOT NULL,
    paddling_distance_m REAL NOT NULL,
    max_speed_kmh REAL NOT NULL,
    longest_wave_m REAL NOT NULL,
    max_wave_seconds REAL NOT NULL,
    updated_at TEXT NOT NULL
)
"""

METRICS = (
    "sessions", "waves", "total_duration_seconds", "surf_time_seconds",
    "surf_distance_m", "paddling_distance_m", "max_speed_kmh", "longest_wave_m",
    "max_wave_seconds",
)
