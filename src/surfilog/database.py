"""Atomic storage of complete Surfilog session and wave snapshots."""

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_INDEXES, RAW_TABLES


class SurfilogDatabase(BaseDatabase):
    source_name = "Surfilog"
    raw_table_names = frozenset({"sessions", "waves", "sync_state"})

    def __init__(self, db_path=None):
        super().__init__(str(db_path or Config.SURFILOG_DATABASE_PATH))
        self.use_foreign_keys = True

    def init_tables(self):
        with self.get_connection() as conn:
            for statement in RAW_TABLES + RAW_INDEXES:
                conn.execute(statement)

    def replace_snapshot(self, sessions, waves, user_id, synced_at):
        """Commit a fully validated snapshot, including removals, in one transaction."""
        with self.get_connection() as conn:
            state = conn.execute("SELECT user_id FROM sync_state WHERE id = 1").fetchone()
            if state and state["user_id"] != user_id:
                raise ValueError("Surfilog account differs from the account stored in this database.")
            # Each payload contains the full current list, so deleted/reprocessed
            # rides cannot survive as stale rows. Rollback preserves the old snapshot.
            conn.execute("DELETE FROM waves")
            conn.execute("DELETE FROM sessions")
            conn.executemany("""
                INSERT INTO sessions (
                    id, name, started_at, utc_offset_min, local_started_at, date_month,
                    duration_sec, reported_wave_count, paddling_distance_m, board_id,
                    board_name, spot_id, spot_name, raw_json, track_points_json, synced_at
                ) VALUES (
                    :id, :name, :started_at, :utc_offset_min, :local_started_at, :date_month,
                    :duration_sec, :reported_wave_count, :paddling_distance_m, :board_id,
                    :board_name, :spot_id, :spot_name, :raw_json, :track_points_json, :synced_at
                )
            """, sessions)
            conn.executemany("""
                INSERT INTO waves (
                    id, session_id, wave_num, start_time, duration_sec, distance_m,
                    max_speed_kmh, start_lat, start_lon, is_excluded, coords_json, raw_json
                ) VALUES (
                    :id, :session_id, :wave_num, :start_time, :duration_sec, :distance_m,
                    :max_speed_kmh, :start_lat, :start_lon, :is_excluded, :coords_json, :raw_json
                )
            """, waves)
            conn.execute("""
                INSERT INTO sync_state (id, user_id, last_successful_sync_at) VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = excluded.user_id,
                    last_successful_sync_at = excluded.last_successful_sync_at
            """, (user_id, synced_at))

    def get_stats(self):
        with self.get_connection() as conn:
            return {
                "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                "waves": conn.execute("SELECT COUNT(*) FROM waves WHERE is_excluded = 0").fetchone()[0],
                "excluded_waves": conn.execute("SELECT COUNT(*) FROM waves WHERE is_excluded = 1").fetchone()[0],
            }
