"""All published sources obey the same policy in reports and activity exports."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from src.apple_health.database import AppleHealthDatabase
from src.blog.database import BlogDatabase
from src.config import Config
from src.database import DatabaseReadError
from src.foursquare.database import FoursquareDatabase
from src.github.analytics import GitHubAnalytics
from src.github.database import GitHubDatabase
from src.hardcover.database import HardcoverDatabase
from src.letterboxd.database import LetterboxdDatabase
from src.oura.database import OuraDatabase
from src.overcast.database import OvercastDatabase
from src.publish.data_generator import DataGenerator
from src.publish.markdown_generator import MarkdownGenerator
from src.publish.publisher import Publisher
from src.readwise.database import ReadwiseDatabase
from src.strong.database import StrongDatabase


SOURCES = {
    'readwise': ReadwiseDatabase, 'foursquare': FoursquareDatabase,
    'letterboxd': LetterboxdDatabase, 'overcast': OvercastDatabase,
    'strong': StrongDatabase, 'apple_health': AppleHealthDatabase, 'blog': BlogDatabase,
    'hardcover': HardcoverDatabase, 'github_activity': GitHubDatabase, 'oura': OuraDatabase,
}


@pytest.fixture
def readers(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', tmp_path)
    publisher = Publisher.__new__(Publisher)
    generator = DataGenerator.__new__(DataGenerator)
    for source, cls in SOURCES.items():
        db = cls(str(tmp_path / f'{source}.db'))
        setattr(publisher, f'{source}_db', db)
        setattr(generator, f'{source}_db', db)
    publisher.markdown_generator = MarkdownGenerator()
    return publisher, generator


def initialize_raw(db):
    if isinstance(db, OvercastDatabase):
        # Overcast's library owns table initialization; analysis is separate.
        with db.get_connection() as conn:
            for table in db.raw_table_names:
                conn.execute(f'CREATE TABLE {table} (id INTEGER)')
    else:
        db.init_tables()


def export_source(generator, source):
    method_source = 'github' if source == 'github_activity' else source
    return getattr(generator, f'_get_all_{method_source}')()


def test_all_missing_sources_are_optional_and_create_no_files(readers, tmp_path):
    publisher, generator = readers
    assert publisher._get_target_year_month() is None
    assert '## ' not in publisher.generate_markdown('2026-09')
    assert generator.generate_data_files() == {}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('source', SOURCES)
@pytest.mark.parametrize('state', ['empty', 'raw_only'])
def test_reports_and_exports_skip_unready_sources(readers, source, state):
    publisher, generator = readers
    db = getattr(publisher, f'{source}_db')
    if state == 'empty':
        with sqlite3.connect(db.db_path):
            pass
    else:
        initialize_raw(db)
    assert publisher._get_target_year_month() is None
    assert '## ' not in publisher.generate_markdown('2026-09')
    assert export_source(generator, source) == []


@pytest.mark.parametrize('source', SOURCES)
def test_unreadable_source_blocks_reports_month_selection_and_exports(readers, source):
    publisher, generator = readers
    db = getattr(publisher, f'{source}_db')
    with open(db.db_path, 'wb') as stream:
        stream.write(b'not a SQLite database')
    for operation in [publisher._get_target_year_month,
                      lambda: publisher.generate_markdown('2026-09'),
                      lambda: export_source(generator, source)]:
        with pytest.raises(DatabaseReadError, match=f'{db.source_name}: file is not a SQLite database'):
            operation()


@pytest.mark.parametrize('source', SOURCES)
def test_partial_source_schema_is_visible_in_all_read_paths(readers, source):
    publisher, generator = readers
    db = getattr(publisher, f'{source}_db')
    initialize_raw(db)
    # Keep a nonempty SQLite schema, but remove a source-owned raw table.
    with db.get_connection() as conn:
        conn.execute('CREATE TABLE analysis (year_month TEXT)')
        conn.execute(f'DROP TABLE {sorted(db.raw_table_names)[-1]}')
    for operation in [publisher._get_target_year_month,
                      lambda: publisher.generate_markdown('2026-09'),
                      lambda: export_source(generator, source)]:
        with pytest.raises(DatabaseReadError, match=f'{db.source_name}: incomplete source schema'):
            operation()


def test_initialized_source_survives_other_unready_sources_and_preserves_exports(readers):
    publisher, generator = readers
    for source in SOURCES:
        initialize_raw(getattr(publisher, f'{source}_db'))
    db = publisher.github_activity_db
    db.upsert_commit({
        'sha': 'public-sha', 'repo': 'user/project', 'message': 'Public update',
        'author_date': '2026-09-10T10:00:00Z', 'date_month': '2026-09',
    })
    GitHubAnalytics(db).analyze_commits()
    assert publisher._get_target_year_month() == '2026-09'
    markdown = publisher.generate_markdown()
    assert 'Wrap up September 2026' in markdown
    assert 'Public update' in markdown
    files = generator.generate_data_files()
    assert set(files) == {'data/activity/code.yaml'}
    assert '  public_commits: 1' in files['data/activity/code.yaml']


def test_backfill_does_not_write_either_repository_when_a_source_is_unreadable(readers):
    publisher, generator = readers
    with open(publisher.blog_db.db_path, 'wb') as stream:
        stream.write(b'not a SQLite database')
    publisher.data_generator = generator
    publisher._build_github_client = MagicMock()
    publisher._ensure_github_client = MagicMock()
    with pytest.raises(DatabaseReadError, match='Blog: file is not a SQLite database'):
        publisher.backfill()
    publisher._build_github_client.assert_not_called()
    publisher._ensure_github_client.assert_not_called()
