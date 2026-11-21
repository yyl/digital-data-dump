"""Storage for climbs recorded in a Kaya CSV export."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime

from ..config import Config
from ..database import BaseDatabase


EXPORT_FIELDS = (
    "stiffness", "rating", "ascent_type", "attempts", "grade", "color",
    "climb_name", "gym", "location", "country",
)
CLIMB_FIELDS = ("logged_at", "local_date", *EXPORT_FIELDS)


def _identify_climbs(rows):
    """Identify source rows consistently across exports, including exact repeats."""
    occurrences = Counter()
    for row in rows:
        timestamp = datetime.fromisoformat(row["logged_at"]).astimezone(UTC).isoformat()
        values = [timestamp, *(row[field] for field in EXPORT_FIELDS)]
        fingerprint = hashlib.sha256(json.dumps(values).encode("utf-8")).hexdigest()
        occurrences[fingerprint] += 1
        yield f"{fingerprint}:{occurrences[fingerprint]}", row


class KayaDatabase(BaseDatabase):
    source_name = "Kaya"
    raw_table_names = frozenset({"climbs"})

    def __init__(self, db_path=None):
        super().__init__(str(db_path or Config.KAYA_DATABASE_PATH))

    def init_tables(self):
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_climbs_schema(conn)

    def _ensure_climbs_schema(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS climbs (
                climb_id TEXT NOT NULL,
                logged_at TEXT NOT NULL,
                local_date TEXT NOT NULL,
                stiffness TEXT,
                rating TEXT,
                ascent_type TEXT NOT NULL,
                attempts TEXT,
                grade TEXT NOT NULL,
                color TEXT,
                climb_name TEXT,
                gym TEXT,
                location TEXT,
                country TEXT
            )
        """)
        if "climb_id" not in {row["name"] for row in conn.execute("PRAGMA table_info(climbs)")}:
            conn.execute("ALTER TABLE climbs ADD COLUMN climb_id TEXT NOT NULL DEFAULT ''")
            old_rows = conn.execute("SELECT rowid, * FROM climbs ORDER BY rowid").fetchall()
            conn.executemany(
                "UPDATE climbs SET climb_id = ? WHERE rowid = ?",
                ((climb_id, row["rowid"]) for climb_id, row in _identify_climbs(old_rows)),
            )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS climbs_id ON climbs (climb_id)")

    def add_climbs(self, rows):
        """Insert only climbs that are new to the stored history."""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_climbs_schema(conn)
            fields = ("climb_id", *CLIMB_FIELDS)
            placeholders = ", ".join("?" for _ in fields)
            inserted = conn.executemany(
                f"INSERT INTO climbs ({', '.join(fields)}) VALUES ({placeholders}) "
                "ON CONFLICT(climb_id) DO NOTHING",
                ((climb_id, *(row[field] for field in CLIMB_FIELDS))
                 for climb_id, row in _identify_climbs(rows)),
            )
            return inserted.rowcount
