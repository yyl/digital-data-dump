"""SQLite database manager for Oura Ring data."""

import time
from typing import Optional, Dict, Any, List

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_TABLES, RAW_INDEXES


class OuraDatabase(BaseDatabase):
    """Manages SQLite database for Oura Ring daily summaries."""

    source_name = 'Oura Ring'
    raw_table_names = frozenset({
        'daily_activity',
        'daily_sleep',
        'daily_readiness',
        'daily_stress',
        'daily_resilience',
        'daily_spo2',
        'daily_cardiovascular_age',
        'sync_state',
    })

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager."""
        super().__init__(db_path or str(Config.OURA_DATABASE_PATH))

    def init_tables(self) -> None:
        """Create all tables and indexes if they don't exist."""
        is_new = not self.exists()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table_sql in RAW_TABLES:
                cursor.execute(table_sql)
            for index_sql in RAW_INDEXES:
                cursor.execute(index_sql)

        if is_new:
            print(f"Oura database initialized at: {self.db_path}")

    # ==========================================================================
    # Sync State
    # ==========================================================================

    def get_last_sync_date(self, data_type: str) -> Optional[str]:
        """Get the last synced date for a data type.

        Returns:
            Date string in YYYY-MM-DD format, or None if never synced.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_sync_date FROM sync_state WHERE data_type = ?",
                (data_type,),
            )
            row = cursor.fetchone()
            return row["last_sync_date"] if row else None

    def set_last_sync_date(self, data_type: str, date: str) -> None:
        """Update the last synced date for a data type.

        Args:
            data_type: The data type key (e.g., 'daily_activity').
            date: Date string in YYYY-MM-DD format.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sync_state (data_type, last_sync_date, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(data_type) DO UPDATE SET
                    last_sync_date = excluded.last_sync_date,
                    updated_at = excluded.updated_at
                """,
                (data_type, date, int(time.time())),
            )

    # ==========================================================================
    # Daily Activity
    # ==========================================================================

    def upsert_daily_activity(self, record: Dict[str, Any]) -> bool:
        """Insert or update a daily activity record."""
        contributors = record.get("contributors", {})
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_activity (
                    id, day, timestamp, score, active_calories, average_met_minutes,
                    steps, total_calories, target_calories, target_meters,
                    meters_to_target, equivalent_walking_distance,
                    high_activity_met_minutes, high_activity_time,
                    medium_activity_met_minutes, medium_activity_time,
                    low_activity_met_minutes, low_activity_time,
                    sedentary_met_minutes, sedentary_time,
                    resting_time, non_wear_time, inactivity_alerts, class_5_min,
                    contributor_meet_daily_targets, contributor_move_every_hour,
                    contributor_recovery_time, contributor_stay_active,
                    contributor_training_frequency, contributor_training_volume
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                    day = excluded.day,
                    timestamp = excluded.timestamp,
                    score = excluded.score,
                    active_calories = excluded.active_calories,
                    average_met_minutes = excluded.average_met_minutes,
                    steps = excluded.steps,
                    total_calories = excluded.total_calories,
                    target_calories = excluded.target_calories,
                    target_meters = excluded.target_meters,
                    meters_to_target = excluded.meters_to_target,
                    equivalent_walking_distance = excluded.equivalent_walking_distance,
                    high_activity_met_minutes = excluded.high_activity_met_minutes,
                    high_activity_time = excluded.high_activity_time,
                    medium_activity_met_minutes = excluded.medium_activity_met_minutes,
                    medium_activity_time = excluded.medium_activity_time,
                    low_activity_met_minutes = excluded.low_activity_met_minutes,
                    low_activity_time = excluded.low_activity_time,
                    sedentary_met_minutes = excluded.sedentary_met_minutes,
                    sedentary_time = excluded.sedentary_time,
                    resting_time = excluded.resting_time,
                    non_wear_time = excluded.non_wear_time,
                    inactivity_alerts = excluded.inactivity_alerts,
                    class_5_min = excluded.class_5_min,
                    contributor_meet_daily_targets = excluded.contributor_meet_daily_targets,
                    contributor_move_every_hour = excluded.contributor_move_every_hour,
                    contributor_recovery_time = excluded.contributor_recovery_time,
                    contributor_stay_active = excluded.contributor_stay_active,
                    contributor_training_frequency = excluded.contributor_training_frequency,
                    contributor_training_volume = excluded.contributor_training_volume,
                    synced_at = strftime('%s', 'now')
                """,
                (
                    record["id"],
                    record["day"],
                    record["timestamp"],
                    record.get("score"),
                    record["active_calories"],
                    record["average_met_minutes"],
                    record["steps"],
                    record["total_calories"],
                    record["target_calories"],
                    record["target_meters"],
                    record["meters_to_target"],
                    record["equivalent_walking_distance"],
                    record["high_activity_met_minutes"],
                    record["high_activity_time"],
                    record["medium_activity_met_minutes"],
                    record["medium_activity_time"],
                    record["low_activity_met_minutes"],
                    record["low_activity_time"],
                    record["sedentary_met_minutes"],
                    record["sedentary_time"],
                    record["resting_time"],
                    record["non_wear_time"],
                    record["inactivity_alerts"],
                    record.get("class_5_min"),
                    contributors.get("meet_daily_targets"),
                    contributors.get("move_every_hour"),
                    contributors.get("recovery_time"),
                    contributors.get("stay_active"),
                    contributors.get("training_frequency"),
                    contributors.get("training_volume"),
                ),
            )
            return True

    # ==========================================================================
    # Daily Sleep
    # ==========================================================================

    def upsert_daily_sleep(self, record: Dict[str, Any]) -> bool:
        """Insert or update a daily sleep record."""
        contributors = record.get("contributors", {})
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_sleep (
                    id, day, timestamp, score,
                    contributor_deep_sleep, contributor_efficiency,
                    contributor_latency, contributor_rem_sleep,
                    contributor_restfulness, contributor_timing,
                    contributor_total_sleep
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day = excluded.day,
                    timestamp = excluded.timestamp,
                    score = excluded.score,
                    contributor_deep_sleep = excluded.contributor_deep_sleep,
                    contributor_efficiency = excluded.contributor_efficiency,
                    contributor_latency = excluded.contributor_latency,
                    contributor_rem_sleep = excluded.contributor_rem_sleep,
                    contributor_restfulness = excluded.contributor_restfulness,
                    contributor_timing = excluded.contributor_timing,
                    contributor_total_sleep = excluded.contributor_total_sleep,
                    synced_at = strftime('%s', 'now')
                """,
                (
                    record["id"],
                    record["day"],
                    record["timestamp"],
                    record.get("score"),
                    contributors.get("deep_sleep"),
                    contributors.get("efficiency"),
                    contributors.get("latency"),
                    contributors.get("rem_sleep"),
                    contributors.get("restfulness"),
                    contributors.get("timing"),
                    contributors.get("total_sleep"),
                ),
            )
            return True

    # ==========================================================================
    # Daily Readiness
    # ==========================================================================

    def upsert_daily_readiness(self, record: Dict[str, Any]) -> bool:
        """Insert or update a daily readiness record."""
        contributors = record.get("contributors", {})
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_readiness (
                    id, day, timestamp, score,
                    temperature_deviation, temperature_trend_deviation,
                    contributor_activity_balance, contributor_body_temperature,
                    contributor_hrv_balance, contributor_previous_day_activity,
                    contributor_previous_night, contributor_recovery_index,
                    contributor_resting_heart_rate, contributor_sleep_balance,
                    contributor_sleep_regularity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day = excluded.day,
                    timestamp = excluded.timestamp,
                    score = excluded.score,
                    temperature_deviation = excluded.temperature_deviation,
                    temperature_trend_deviation = excluded.temperature_trend_deviation,
                    contributor_activity_balance = excluded.contributor_activity_balance,
                    contributor_body_temperature = excluded.contributor_body_temperature,
                    contributor_hrv_balance = excluded.contributor_hrv_balance,
                    contributor_previous_day_activity = excluded.contributor_previous_day_activity,
                    contributor_previous_night = excluded.contributor_previous_night,
                    contributor_recovery_index = excluded.contributor_recovery_index,
                    contributor_resting_heart_rate = excluded.contributor_resting_heart_rate,
                    contributor_sleep_balance = excluded.contributor_sleep_balance,
                    contributor_sleep_regularity = excluded.contributor_sleep_regularity,
                    synced_at = strftime('%s', 'now')
                """,
                (
                    record["id"],
                    record["day"],
                    record["timestamp"],
                    record.get("score"),
                    record.get("temperature_deviation"),
                    record.get("temperature_trend_deviation"),
                    contributors.get("activity_balance"),
                    contributors.get("body_temperature"),
                    contributors.get("hrv_balance"),
                    contributors.get("previous_day_activity"),
                    contributors.get("previous_night"),
                    contributors.get("recovery_index"),
                    contributors.get("resting_heart_rate"),
                    contributors.get("sleep_balance"),
                    contributors.get("sleep_regularity"),
                ),
            )
            return True

    # ==========================================================================
    # Daily Stress
    # ==========================================================================

    def upsert_daily_stress(self, record: Dict[str, Any]) -> bool:
        """Insert or update a daily stress record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_stress (
                    id, day, day_summary, stress_high, recovery_high
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day = excluded.day,
                    day_summary = excluded.day_summary,
                    stress_high = excluded.stress_high,
                    recovery_high = excluded.recovery_high,
                    synced_at = strftime('%s', 'now')
                """,
                (
                    record["id"],
                    record["day"],
                    record.get("day_summary"),
                    record.get("stress_high"),
                    record.get("recovery_high"),
                ),
            )
            return True

    # ==========================================================================
    # Daily Resilience
    # ==========================================================================

    def upsert_daily_resilience(self, record: Dict[str, Any]) -> bool:
        """Insert or update a daily resilience record."""
        contributors = record.get("contributors", {})
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_resilience (
                    id, day, level,
                    contributor_sleep_recovery, contributor_daytime_recovery,
                    contributor_stress
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day = excluded.day,
                    level = excluded.level,
                    contributor_sleep_recovery = excluded.contributor_sleep_recovery,
                    contributor_daytime_recovery = excluded.contributor_daytime_recovery,
                    contributor_stress = excluded.contributor_stress,
                    synced_at = strftime('%s', 'now')
                """,
                (
                    record["id"],
                    record["day"],
                    record.get("level"),
                    contributors.get("sleep_recovery"),
                    contributors.get("daytime_recovery"),
                    contributors.get("stress"),
                ),
            )
            return True

    # ==========================================================================
    # Daily SpO2
    # ==========================================================================

    def upsert_daily_spo2(self, record: Dict[str, Any]) -> bool:
        """Insert or update a daily SpO2 record."""
        spo2_pct = record.get("spo2_percentage") or {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_spo2 (
                    id, day, spo2_average, breathing_disturbance_index
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day = excluded.day,
                    spo2_average = excluded.spo2_average,
                    breathing_disturbance_index = excluded.breathing_disturbance_index,
                    synced_at = strftime('%s', 'now')
                """,
                (
                    record["id"],
                    record["day"],
                    spo2_pct.get("average"),
                    record.get("breathing_disturbance_index"),
                ),
            )
            return True

    # ==========================================================================
    # Daily Cardiovascular Age
    # ==========================================================================

    def upsert_daily_cardiovascular_age(self, record: Dict[str, Any]) -> bool:
        """Insert or update a daily cardiovascular age record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_cardiovascular_age (
                    id, day, vascular_age, pulse_wave_velocity
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    day = excluded.day,
                    vascular_age = excluded.vascular_age,
                    pulse_wave_velocity = excluded.pulse_wave_velocity,
                    synced_at = strftime('%s', 'now')
                """,
                (
                    record["id"],
                    record["day"],
                    record.get("vascular_age"),
                    record.get("pulse_wave_velocity"),
                ),
            )
            return True

    # ==========================================================================
    # Statistics
    # ==========================================================================

    def get_stats(self) -> Dict[str, int]:
        """Get row counts for all tables."""
        tables = [
            "daily_activity",
            "daily_sleep",
            "daily_readiness",
            "daily_stress",
            "daily_resilience",
            "daily_spo2",
            "daily_cardiovascular_age",
        ]
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
        return stats

    def get_sync_dates(self) -> Dict[str, Optional[str]]:
        """Get last sync dates for all data types."""
        dates = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_type, last_sync_date FROM sync_state")
            for row in cursor.fetchall():
                dates[row["data_type"]] = row["last_sync_date"]
        return dates
