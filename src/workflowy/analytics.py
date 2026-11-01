"""Monthly Workflowy activity from source dates and observed removals."""

from typing import Optional

from ..time_utils import utc_now_iso
from .database import WorkflowyDatabase
from .models import CREATE_ANALYSIS_TABLE


class WorkflowyAnalytics:
    """Count distinct nodes per activity type and UTC calendar month."""

    def __init__(self, db: Optional[WorkflowyDatabase] = None):
        self.db = db or WorkflowyDatabase()

    def analyze_nodes(self) -> int:
        """Rebuild monthly rows, preserving recorded edits across later syncs."""
        self.db.init_tables()
        with self.db.get_connection() as conn:
            conn.execute(CREATE_ANALYSIS_TABLE)
            events = conn.execute(
                """
                SELECT strftime('%Y-%m', created_at, 'unixepoch') AS year_month,
                       'nodes_added' AS metric, COUNT(DISTINCT id) AS count
                FROM nodes GROUP BY year_month
                UNION ALL
                SELECT strftime('%Y-%m', modified_at, 'unixepoch'),
                       'nodes_modified', COUNT(DISTINCT node_id)
                FROM node_modifications GROUP BY 1
                UNION ALL
                SELECT strftime('%Y-%m', removed_at),
                       'nodes_removed', COUNT(DISTINCT node_id)
                FROM node_removals GROUP BY 1
                """
            ).fetchall()
            months = {}
            for event in events:
                if event["year_month"]:
                    months.setdefault(event["year_month"], {})[event["metric"]] = event["count"]

            state = conn.execute(
                "SELECT strftime('%Y-%m', last_successful_sync_at) FROM sync_state WHERE entity_type = ?",
                (self.db.ENTITY_NODES,),
            ).fetchone()
            if state and state[0]:
                months.setdefault(state[0], {})

            # Include quiet months so a zero count is available to consumers.
            if months:
                year, month = map(int, min(months).split("-"))
                last_month = max(months)
                while (key := f"{year:04d}-{month:02d}") <= last_month:
                    months.setdefault(key, {})
                    year, month = (year + 1, 1) if month == 12 else (year, month + 1)

            conn.execute("DELETE FROM analysis")
            updated_at = utc_now_iso()
            for key, metrics in sorted(months.items()):
                year, month = key.split("-")
                conn.execute(
                    """
                    INSERT INTO analysis (
                        year_month, year, month, nodes_added, nodes_modified, nodes_removed, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (key, year, month, metrics.get("nodes_added", 0),
                     metrics.get("nodes_modified", 0), metrics.get("nodes_removed", 0), updated_at),
                )
        return len(months)
