"""SQLite database manager for Strong workout data."""

import sqlite3
from typing import Optional, Dict, Any, List

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_TABLES, RAW_INDEXES


class StrongDatabase(BaseDatabase):
    """Manages SQLite database for Strong workout data."""

    source_name = 'Strong'
    raw_table_names = frozenset({'workouts', 'exercises'})
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager."""
        super().__init__(db_path or str(Config.STRONG_DATABASE_PATH))
        self.use_foreign_keys = True
    
    def init_tables(self) -> None:
        """Create raw sync tables if they don't exist."""
        is_new = not self.exists()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table_sql in RAW_TABLES:
                cursor.execute(table_sql)
            if 'started_at_utc' not in {row['name'] for row in cursor.execute('PRAGMA table_info(workouts)')}:
                cursor.execute('ALTER TABLE workouts ADD COLUMN started_at_utc TEXT')
            for index_sql in RAW_INDEXES:
                cursor.execute(index_sql)
        
        if is_new:
            print(f"Strong database initialized at: {self.db_path}")
    
    def upsert_workout(self, workout_data: Dict[str, Any]) -> bool:
        """Insert or update a workout session."""
        workout_id = workout_data.get("id")
        if not workout_id:
            return False
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO workouts (
                    id, workout_name, started_at, started_at_utc, duration_minutes, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    workout_name = excluded.workout_name,
                    started_at = excluded.started_at,
                    started_at_utc = excluded.started_at_utc,
                    duration_minutes = excluded.duration_minutes,
                    notes = excluded.notes
            """, (
                workout_id,
                workout_data.get("workout_name"),
                workout_data.get("started_at"),
                workout_data.get("started_at_utc"),
                workout_data.get("duration_minutes", 0),
                workout_data.get("notes"),
            ))
            return True
    
    def insert_exercises(self, workout_id: str, exercises: list) -> int:
        """Insert exercise sets for a workout, replacing any existing ones."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Remove existing exercises for this workout (full re-import)
            cursor.execute("DELETE FROM exercises WHERE workout_id = ?", (workout_id,))
            
            exercise_data = [(
                workout_id,
                ex.get("exercise_name"),
                ex.get("set_order"),
                ex.get("weight", 0),
                ex.get("reps", 0),
                ex.get("distance", 0),
                ex.get("seconds", 0),
                ex.get("notes"),
                ex.get("rpe"),
            ) for ex in exercises]

            cursor.executemany("""
                INSERT INTO exercises (
                    workout_id, exercise_name, set_order,
                    weight, reps, distance, seconds, notes, rpe
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, exercise_data)
            return len(exercise_data)
    
    def save_workouts(self, workouts: Dict[str, Dict], exercises: Dict[str, List[Dict]],
                      *, snapshot: Optional[Dict] = None) -> Dict[str, int]:
        """Upsert workouts, or atomically replace a validated complete snapshot.

        Snapshot replacement removes old CSV IDs and deleted API workouts,
        invalidates derived analysis, and records provenance in one transaction.
        """
        stats = {"workouts": 0, "exercises": 0}

        with self.get_connection() as conn:
            cursor = conn.cursor()

            if snapshot is not None:
                existing_count = cursor.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
                if not workouts and existing_count:
                    raise ValueError("Refusing to replace existing Strong history with an empty snapshot.")
                previous = cursor.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
                if (previous and previous['source'] == 'api' and snapshot['source'] == 'api'
                        and previous['user_id'] != snapshot.get('user_id')):
                    raise ValueError("Strong account changed; use a separate database for another account.")
                cursor.execute("DELETE FROM exercises")
                cursor.execute("DELETE FROM workouts")
                if cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                                  "AND name = 'analysis'").fetchone():
                    cursor.execute("DELETE FROM analysis")

            # Prepare workouts
            workout_params = []
            for w in workouts.values():
                if w.get("id"):
                    workout_params.append((
                        w.get("id"),
                        w.get("workout_name"),
                        w.get("started_at"),
                        w.get("started_at_utc"),
                        w.get("duration_minutes", 0),
                        w.get("notes"),
                    ))

            if workout_params:
                cursor.executemany("""
                    INSERT INTO workouts (
                        id, workout_name, started_at, started_at_utc, duration_minutes, notes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        workout_name = excluded.workout_name,
                        started_at = excluded.started_at,
                        started_at_utc = excluded.started_at_utc,
                        duration_minutes = excluded.duration_minutes,
                        notes = excluded.notes
                """, workout_params)
                stats["workouts"] = len(workout_params)

            # Prepare exercises
            all_exercises_data = []

            # Iterate over workouts to ensure we clear exercises for all imported sessions
            # (even those with no exercises in the current import)
            for workout_id in workouts.keys():
                cursor.execute("DELETE FROM exercises WHERE workout_id = ?", (workout_id,))

                if workout_id in exercises:
                    for ex in exercises[workout_id]:
                        all_exercises_data.append((
                            workout_id,
                            ex.get("exercise_name"),
                            ex.get("set_order"),
                            ex.get("weight", 0),
                            ex.get("reps", 0),
                            ex.get("distance", 0),
                            ex.get("seconds", 0),
                            ex.get("notes"),
                            ex.get("rpe"),
                        ))

            if all_exercises_data:
                cursor.executemany("""
                    INSERT INTO exercises (
                        workout_id, exercise_name, set_order,
                        weight, reps, distance, seconds, notes, rpe
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, all_exercises_data)
                stats["exercises"] = len(all_exercises_data)

            if snapshot is not None:
                cursor.execute("""
                    INSERT INTO sync_state
                        (id, source, user_id, weight_unit, timezone, last_successful_sync_at)
                    VALUES (1, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        source = excluded.source, user_id = excluded.user_id,
                        weight_unit = excluded.weight_unit, timezone = excluded.timezone,
                        last_successful_sync_at = excluded.last_successful_sync_at
                """, (snapshot['source'], snapshot.get('user_id'), snapshot.get('weight_unit'),
                      snapshot.get('timezone'), snapshot['last_successful_sync_at']))

        return stats

    def get_sync_state(self) -> Optional[Dict[str, Any]]:
        """Read optional provenance without creating or migrating a database."""
        with self.read_connection(required_tables=self.raw_table_names) as conn:
            if conn is None or not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sync_state'"
            ).fetchone():
                return None
            row = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
            return dict(row) if row else None

    def get_stats(self) -> Dict[str, int]:
        """Get counts of all entities."""
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table in ["workouts", "exercises"]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
        return stats
