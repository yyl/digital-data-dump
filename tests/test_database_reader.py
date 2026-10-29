"""Readiness, read-only access, and visible failures in the common read layer."""

import sqlite3
from pathlib import Path

import pytest

from src.config import Config
from src.database import BaseDatabase, DatabaseReadError


class ExampleDatabase(BaseDatabase):
    source_name = 'Example'
    raw_table_names = frozenset({'events', 'labels'})


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', tmp_path)
    return ExampleDatabase(str(tmp_path / 'source #1?.db'))


def initialize(db, *, analysis=True):
    with db.get_connection() as conn:
        conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)')
        conn.execute('CREATE TABLE labels (id INTEGER PRIMARY KEY)')
        conn.execute("INSERT INTO events VALUES (1, 'hello')")
        if analysis:
            conn.execute('CREATE TABLE analysis (year_month TEXT, total INTEGER)')
            conn.execute("INSERT INTO analysis VALUES ('2026-09', 1)")


def test_missing_source_does_not_create_database_or_parent_and_logs_once(db, tmp_path, caplog):
    db.db_path = str(tmp_path / 'absent' / 'source.db')
    assert db.fetch_rows('SELECT * FROM analysis') == []
    assert db.fetch_rows('SELECT * FROM analysis') == []
    assert not (tmp_path / 'absent').exists()
    assert caplog.text.count('Example: database is missing') == 1


def test_empty_file_is_uninitialized_without_modifying_it(db, caplog):
    path = Path(db.db_path)
    path.touch()
    assert db.fetch_rows('SELECT * FROM analysis') == []
    assert path.read_bytes() == b''
    assert 'Example: database is uninitialized' in caplog.text


def test_raw_only_source_skips_analysis_but_can_read_raw_rows(db, caplog):
    initialize(db, analysis=False)
    assert db.fetch_rows('SELECT * FROM analysis') == []
    assert 'run source analysis first' in caplog.text
    assert db.fetch_rows('SELECT * FROM events', required_tables=('events',)) == [
        {'id': 1, 'value': 'hello'},
    ]
    with db.get_connection() as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='analysis'").fetchone() is None


def test_unavailable_state_is_rechecked_after_source_becomes_ready(db):
    assert db.fetch_rows('SELECT * FROM analysis') == []
    initialize(db)
    assert db.fetch_rows('SELECT * FROM analysis') == [{'year_month': '2026-09', 'total': 1}]


def test_partial_raw_schema_does_not_masquerade_as_missing_analysis(db):
    with db.get_connection() as conn:
        conn.execute('CREATE TABLE events (id INTEGER)')
    with pytest.raises(DatabaseReadError, match='Example: incomplete source schema.*labels'):
        db.fetch_rows('SELECT * FROM analysis')


def test_missing_required_detail_table_is_a_schema_error(db):
    initialize(db)
    with pytest.raises(DatabaseReadError, match='Example: incomplete source schema.*details'):
        db.fetch_rows('SELECT * FROM details', required_tables=('details',))


def test_missing_columns_are_visible_with_source_context(db):
    initialize(db)
    with pytest.raises(DatabaseReadError, match='Example: query failed or database schema is incompatible'):
        db.fetch_rows('SELECT absent_column FROM analysis')


def test_non_database_file_is_reported_without_echoing_file_contents(db):
    Path(db.db_path).write_text('private-repository-name and token text')
    with pytest.raises(DatabaseReadError, match='Example: file is not a SQLite database') as failure:
        db.fetch_rows('SELECT * FROM analysis')
    assert 'private-repository-name' not in str(failure.value)
    assert failure.value.__suppress_context__


def test_damaged_sqlite_pages_fail_when_rows_are_read(db):
    initialize(db)
    with db.get_connection() as conn:
        root_page = conn.execute("SELECT rootpage FROM sqlite_master WHERE name='events'").fetchone()[0]
        page_size = conn.execute('PRAGMA page_size').fetchone()[0]
    path = Path(db.db_path)
    contents = bytearray(path.read_bytes())
    contents[(root_page - 1) * page_size] = 255  # Invalid B-tree page type; retain the SQLite header.
    path.write_bytes(contents)
    with pytest.raises(DatabaseReadError, match='Example: SQLite detected database corruption'):
        db.fetch_rows('SELECT * FROM events', required_tables=('events',))


def test_read_connection_rejects_writes_and_closes_after_failure(db):
    initialize(db)
    with pytest.raises(DatabaseReadError, match='Example: a read operation attempted to modify'):
        with db.read_connection(required_tables=('events',)) as conn:
            connection = conn
            conn.execute("INSERT INTO events VALUES (2, 'must not be saved')")
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
    assert db.fetch_rows('SELECT COUNT(*) AS total FROM events', required_tables=('events',)) == [
        {'total': 1},
    ]


def test_reads_preserve_database_bytes_and_bind_parameters(db):
    initialize(db)
    path = Path(db.db_path)
    original = path.read_bytes()
    assert db.fetch_rows('SELECT total FROM analysis WHERE year_month = ?', ('2026-09',)) == [{'total': 1}]
    assert db.fetch_rows('SELECT total FROM analysis WHERE year_month = ?', ("' OR 1=1 --",)) == []
    assert path.read_bytes() == original


def test_permission_and_open_failures_are_not_unavailable_sources(db, monkeypatch):
    initialize(db)

    def denied(*args, **kwargs):
        raise PermissionError('private filesystem details')

    monkeypatch.setattr(sqlite3, 'connect', denied)
    with pytest.raises(DatabaseReadError, match='Example: database file could not be accessed'):
        db.fetch_rows('SELECT * FROM analysis')


def test_missing_file_race_never_creates_a_database(db, monkeypatch):
    initialize(db)
    connect = sqlite3.connect
    path = Path(db.db_path)

    def disappeared(*args, **kwargs):
        path.unlink()
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', disappeared)
    with pytest.raises(DatabaseReadError, match='Example: database could not be opened'):
        db.fetch_rows('SELECT * FROM analysis')
    assert not path.exists()
