"""Shared lifecycle for registered data sources."""

from argparse import ArgumentParser
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from sqlite3 import Connection

from .database import BaseDatabase


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    database: Callable[[], BaseDatabase]
    sync: Callable[..., dict | None]
    analyze: Callable[[BaseDatabase], int]
    validate: Callable[[], bool] | None = None
    initialize: bool = True
    optional_for_reporting: bool = False
    status_details: Callable[[Connection | None], dict] | None = None
    sync_options: Callable[[ArgumentParser], None] | None = None
    refresh_options: Callable[[ArgumentParser], None] | None = None

    def analyze_local(self) -> None:
        db = self.database()
        with db.read_connection(required_tables=()) as conn:
            if conn is None:
                print(f"Skipping {self.name} analysis: raw data is unavailable.")
                return
        count = self.analyze(db)
        print(f"{self.name}: {count:,} analysis records written.")

    def refresh(self, **options) -> None:
        """Sync and analyze, with local analysis also allowed for a skipped file import."""
        self.sync(**options)
        self.analyze_local()

    def status(self) -> dict:
        db = self.database()
        with db.read_connection(required_tables=()) as conn:
            if conn is None:
                result = {"database": "not initialized"}
            else:
                result = {
                    table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    for table in sorted(db.raw_table_names - {"sync_state"})
                }
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                analysis_tables = db.analysis_table_names & tables
                if not analysis_tables:
                    result["analysis"] = "unavailable"
                for table in sorted(analysis_tables):
                    count, month = conn.execute(f'SELECT COUNT(*), MAX(year_month) FROM "{table}"').fetchone()
                    result.update({f"{table} records": count, f"latest {table}": month})
            if self.status_details:
                result.update(self.status_details(conn))
            return result


def run_sources(sources: Iterable[Source], operation: str, *, reporting: bool = False) -> bool:
    """Run independent sources and return whether all selected operations succeeded."""
    failed = []
    for source in sources:
        print(f"\n--- {source.name} ---")
        try:
            if source.validate and operation in {"sync", "refresh"}:
                try:
                    source.validate()
                except ValueError as error:
                    if not reporting or source.optional_for_reporting:
                        print(f"Skipping {source.name}: {error}")
                        continue
                    raise

            if operation == "init":
                if source.initialize:
                    source.database().init_tables()
                else:
                    print("The importer initializes this database when it first runs.")
            elif operation == "sync":
                source.sync()
            elif operation == "analyze":
                source.analyze_local()
            elif operation == "refresh":
                source.refresh()
        except Exception as error:
            failed.append(source.name)
            print(f"Error: {error}")

    if failed:
        print(f"\n{operation.capitalize()} failed for {', '.join(failed)}.")
    return not failed
