"""Base database class for SQLite connections."""

import logging
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from .config import Config

logger = logging.getLogger(__name__)


class DatabaseReadError(RuntimeError):
    """An existing source cannot be read safely; it must not become empty data."""


class BaseDatabase:
    """Base class for SQLite database managers."""

    source_name = "Database"
    raw_table_names: frozenset[str] = frozenset()
    analysis_table_names = frozenset({"analysis"})

    def __init__(self, db_path: str):
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database.
        """
        self.db_path = db_path
        self.use_foreign_keys = False
        self._reported_unavailability: set[str] = set()
        Config.ensure_data_dir()

    @contextmanager
    def get_connection(self):
        """Get a database connection as a context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if self.use_foreign_keys:
            conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def exists(self) -> bool:
        """Check if the database file exists."""
        return Path(self.db_path).exists()

    def _report_unavailable(self, reason: str) -> None:
        """Explain an omitted source once per reason on this database instance."""
        if reason not in self._reported_unavailability:
            logger.warning("%s: %s", self.source_name, reason)
            self._reported_unavailability.add(reason)

    @contextmanager
    def read_connection(
        self, *, required_tables: Iterable[str] = ("analysis",)
    ) -> Iterator[sqlite3.Connection | None]:
        """Open an existing source read-only, yielding None when it isn't ready.

        Missing files, an empty schema, and missing derived analysis are normal
        unavailable states. Partial raw schemas and all SQLite failures remain
        errors. This path never initializes, migrates, or commits source data.
        """
        conn = None
        try:
            path = Path(self.db_path).resolve()
            if not path.exists():
                self._report_unavailable("database is missing; sync this source first")
                yield None
                return

            conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            if not tables:
                self._report_unavailable("database is uninitialized; sync this source first")
                yield None
                return

            missing_raw = self.raw_table_names - tables
            if missing_raw:
                raise DatabaseReadError(
                    f"{self.source_name}: incomplete source schema; missing raw tables: "
                    + ", ".join(sorted(missing_raw))
                    + ". Run source sync to initialize or migrate it."
                )

            missing = set(required_tables) - tables
            if missing and missing <= self.analysis_table_names:
                self._report_unavailable("monthly analysis is unavailable; run source analysis first")
                yield None
                return
            if missing:
                raise DatabaseReadError(
                    f"{self.source_name}: incomplete source schema; missing required tables: "
                    + ", ".join(sorted(missing))
                )

            yield conn
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            reason = {
                sqlite3.SQLITE_NOTADB: "file is not a SQLite database",
                sqlite3.SQLITE_CORRUPT: "SQLite detected database corruption",
                sqlite3.SQLITE_CANTOPEN: "database could not be opened",
                sqlite3.SQLITE_READONLY: "a read operation attempted to modify the database",
                sqlite3.SQLITE_ERROR: "query failed or database schema is incompatible",
            }.get(code, "SQLite read failed")
            raise DatabaseReadError(f"{self.source_name}: {reason}.") from None
        except OSError:
            raise DatabaseReadError(f"{self.source_name}: database file could not be accessed.") from None
        finally:
            if conn is not None:
                conn.close()

    def fetch_rows(
        self,
        query: str,
        params: tuple = (),
        *,
        required_tables: Iterable[str] = ("analysis",),
    ) -> list[dict[str, Any]]:
        """Fetch report rows using the common readiness and error policy."""
        with self.read_connection(required_tables=required_tables) as conn:
            if conn is None:
                return []
            return [dict(row) for row in conn.execute(query, params).fetchall()]
