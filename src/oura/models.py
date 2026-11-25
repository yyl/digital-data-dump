"""SQL schema definitions for Oura Ring data."""

# ==========================================================================
# Daily Activity
# ==========================================================================

CREATE_DAILY_ACTIVITY_TABLE = """
CREATE TABLE IF NOT EXISTS daily_activity (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    score INTEGER,
    active_calories INTEGER NOT NULL,
    average_met_minutes REAL NOT NULL,
    steps INTEGER NOT NULL,
    total_calories INTEGER NOT NULL,
    target_calories INTEGER NOT NULL,
    target_meters INTEGER NOT NULL,
    meters_to_target INTEGER NOT NULL,
    equivalent_walking_distance INTEGER NOT NULL,
    high_activity_met_minutes INTEGER NOT NULL,
    high_activity_time INTEGER NOT NULL,
    medium_activity_met_minutes INTEGER NOT NULL,
    medium_activity_time INTEGER NOT NULL,
    low_activity_met_minutes INTEGER NOT NULL,
    low_activity_time INTEGER NOT NULL,
    sedentary_met_minutes INTEGER NOT NULL,
    sedentary_time INTEGER NOT NULL,
    resting_time INTEGER NOT NULL,
    non_wear_time INTEGER NOT NULL,
    inactivity_alerts INTEGER NOT NULL,
    class_5_min TEXT,
    -- Flattened contributors
    contributor_meet_daily_targets INTEGER,
    contributor_move_every_hour INTEGER,
    contributor_recovery_time INTEGER,
    contributor_stay_active INTEGER,
    contributor_training_frequency INTEGER,
    contributor_training_volume INTEGER,
    -- Metadata
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

# ==========================================================================
# Daily Sleep
# ==========================================================================

CREATE_DAILY_SLEEP_TABLE = """
CREATE TABLE IF NOT EXISTS daily_sleep (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    score INTEGER,
    -- Flattened contributors
    contributor_deep_sleep INTEGER,
    contributor_efficiency INTEGER,
    contributor_latency INTEGER,
    contributor_rem_sleep INTEGER,
    contributor_restfulness INTEGER,
    contributor_timing INTEGER,
    contributor_total_sleep INTEGER,
    -- Metadata
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

# ==========================================================================
# Daily Readiness
# ==========================================================================

CREATE_DAILY_READINESS_TABLE = """
CREATE TABLE IF NOT EXISTS daily_readiness (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    score INTEGER,
    temperature_deviation REAL,
    temperature_trend_deviation REAL,
    -- Flattened contributors
    contributor_activity_balance INTEGER,
    contributor_body_temperature INTEGER,
    contributor_hrv_balance INTEGER,
    contributor_previous_day_activity INTEGER,
    contributor_previous_night INTEGER,
    contributor_recovery_index INTEGER,
    contributor_resting_heart_rate INTEGER,
    contributor_sleep_balance INTEGER,
    contributor_sleep_regularity INTEGER,
    -- Metadata
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

# ==========================================================================
# Daily Stress
# ==========================================================================

CREATE_DAILY_STRESS_TABLE = """
CREATE TABLE IF NOT EXISTS daily_stress (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    day_summary TEXT,
    stress_high INTEGER,
    recovery_high INTEGER,
    -- Metadata
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    CONSTRAINT stress_day_summary_check CHECK (
        day_summary IS NULL OR day_summary IN ('restored', 'normal', 'stressful')
    )
);
"""

# ==========================================================================
# Daily Resilience
# ==========================================================================

CREATE_DAILY_RESILIENCE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_resilience (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    level TEXT,
    -- Flattened contributors
    contributor_sleep_recovery REAL,
    contributor_daytime_recovery REAL,
    contributor_stress REAL,
    -- Metadata
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    CONSTRAINT resilience_level_check CHECK (
        level IS NULL OR level IN ('limited', 'adequate', 'solid', 'strong', 'exceptional')
    )
);
"""

# ==========================================================================
# Daily SpO2
# ==========================================================================

CREATE_DAILY_SPO2_TABLE = """
CREATE TABLE IF NOT EXISTS daily_spo2 (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    spo2_average REAL,
    breathing_disturbance_index INTEGER,
    -- Metadata
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

# ==========================================================================
# Daily Cardiovascular Age
# ==========================================================================

CREATE_DAILY_CARDIOVASCULAR_AGE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_cardiovascular_age (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    vascular_age INTEGER,
    pulse_wave_velocity REAL,
    -- Metadata
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

# ==========================================================================
# Sleep Documents
# ==========================================================================

CREATE_SLEEP_PERIODS_TABLE = """
CREATE TABLE IF NOT EXISTS sleep_periods (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

CREATE_SLEEP_TIME_TABLE = """
CREATE TABLE IF NOT EXISTS sleep_time (
    id TEXT PRIMARY KEY NOT NULL,
    day TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

# ==========================================================================
# Sync State
# ==========================================================================

CREATE_SYNC_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS sync_state (
    data_type TEXT PRIMARY KEY NOT NULL,
    last_sync_date TEXT,
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

# ==========================================================================
# Aggregated lists for init
# ==========================================================================

RAW_TABLES = [
    CREATE_DAILY_ACTIVITY_TABLE,
    CREATE_DAILY_SLEEP_TABLE,
    CREATE_DAILY_READINESS_TABLE,
    CREATE_DAILY_STRESS_TABLE,
    CREATE_DAILY_RESILIENCE_TABLE,
    CREATE_DAILY_SPO2_TABLE,
    CREATE_DAILY_CARDIOVASCULAR_AGE_TABLE,
    CREATE_SLEEP_PERIODS_TABLE,
    CREATE_SLEEP_TIME_TABLE,
    CREATE_SYNC_STATE_TABLE,
]

RAW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_daily_activity_day ON daily_activity(day);",
    "CREATE INDEX IF NOT EXISTS idx_daily_sleep_day ON daily_sleep(day);",
    "CREATE INDEX IF NOT EXISTS idx_daily_readiness_day ON daily_readiness(day);",
    "CREATE INDEX IF NOT EXISTS idx_daily_stress_day ON daily_stress(day);",
    "CREATE INDEX IF NOT EXISTS idx_daily_resilience_day ON daily_resilience(day);",
    "CREATE INDEX IF NOT EXISTS idx_daily_spo2_day ON daily_spo2(day);",
    "CREATE INDEX IF NOT EXISTS idx_daily_cardiovascular_age_day ON daily_cardiovascular_age(day);",
    "CREATE INDEX IF NOT EXISTS idx_sleep_periods_day ON sleep_periods(day);",
    "CREATE INDEX IF NOT EXISTS idx_sleep_time_day ON sleep_time(day);",
]

# ==========================================================================
# Analysis Table
# ==========================================================================

CREATE_ANALYSIS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis (
    year_month TEXT NOT NULL,
    source_table TEXT NOT NULL,
    metric TEXT NOT NULL,
    min_value REAL,
    median_value REAL,
    avg_value REAL,
    max_value REAL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (year_month, source_table, metric)
);
"""

ANALYSIS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_analysis_year_month ON analysis(year_month);",
    "CREATE INDEX IF NOT EXISTS idx_analysis_source ON analysis(source_table);",
]
