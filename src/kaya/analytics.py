"""Summarize Kaya climbing days, sends, and recorded attempts by month."""

import json
import re
from collections import Counter, defaultdict

from ..time_utils import utc_now_iso
from .database import KayaDatabase

SEND_TYPES = {"redpoint", "onsight", "flash"}
COUNT_METRICS = ("climbing_days", "sends", "flashes", "onsights")


class KayaAnalytics:
    def __init__(self, db=None):
        self.db = db or KayaDatabase()

    def analyze_climbs(self):
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis (
                    year_month TEXT PRIMARY KEY,
                    year TEXT NOT NULL,
                    month TEXT NOT NULL,
                    climbing_days INTEGER NOT NULL,
                    sends INTEGER NOT NULL,
                    attempts INTEGER,
                    climbs_missing_attempts INTEGER,
                    flashes INTEGER NOT NULL,
                    onsights INTEGER NOT NULL,
                    hardest_v_grade INTEGER,
                    grade_counts TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis)")}
            for column in ("attempts", "climbs_missing_attempts"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE analysis ADD COLUMN {column} INTEGER")

            by_month = defaultdict(list)
            for row in conn.execute("SELECT local_date, ascent_type, grade, attempts FROM climbs"):
                by_month[row["local_date"][:7]].append(row)

            updated_at = utc_now_iso()
            records = []
            for year_month, climbs in by_month.items():
                days = {row["local_date"] for row in climbs}
                send_types = Counter()
                grade_counts = Counter()
                attempt_counts = []
                for row in climbs:
                    attempts = (row["attempts"] or "").strip()
                    if re.fullmatch(r"[0-9]+", attempts):
                        attempt_counts.append(int(attempts))
                    ascent_type = row["ascent_type"].strip().lower()
                    if ascent_type in SEND_TYPES:
                        send_types[ascent_type] += 1
                        grade_counts[row["grade"].strip().upper()] += 1

                v_grades = {
                    grade: int(grade[1:])
                    for grade in grade_counts if re.fullmatch(r"V[0-9]+", grade)
                }
                sorted_grades = sorted(
                    grade_counts, key=lambda grade: (v_grades.get(grade, float("inf")), grade)
                )
                records.append((
                    year_month, *year_month.split("-"), len(days), send_types.total(),
                    sum(attempt_counts) if attempt_counts else None,
                    len(climbs) - len(attempt_counts),
                    send_types["flash"], send_types["onsight"],
                    max(v_grades.values(), default=None),
                    json.dumps({grade: grade_counts[grade] for grade in sorted_grades}),
                    updated_at,
                ))

            conn.execute("DELETE FROM analysis")
            conn.executemany("""
                INSERT INTO analysis (
                    year_month, year, month, climbing_days, sends, attempts,
                    climbs_missing_attempts, flashes, onsights, hardest_v_grade,
                    grade_counts, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
        return len(records)
