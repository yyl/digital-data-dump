"""Strong latest-session weights, calendar comparisons, and report integration."""

import csv
from unittest.mock import MagicMock

import pytest

from src.config import Config
from src.publish.markdown_generator import MarkdownGenerator
from src.publish.publisher import Publisher
from src.strong.analytics import StrongAnalytics
from src.strong.database import StrongDatabase
from src.strong.importer import StrongImporter


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', tmp_path)
    database = StrongDatabase(str(tmp_path / 'strong.db'))
    database.init_tables()
    return database


def add_workout(db, date, sets, name='Full'):
    db.save_workouts(
        {date: {'id': date, 'workout_name': name, 'started_at': date}},
        {date: [
            {'exercise_name': exercise, 'weight': weight, 'set_order': order, 'reps': 5}
            for order, (exercise, weight) in enumerate(sets, start=1)
        ]},
    )


def publisher_for(db):
    publisher = Publisher.__new__(Publisher)
    absent = MagicMock()
    absent.exists.return_value = False
    absent.fetch_rows.return_value = []
    absent.read_connection.return_value.__enter__.return_value = None
    for source in ('readwise', 'foursquare', 'letterboxd', 'overcast', 'apple_health',
                   'blog', 'hardcover', 'github_activity', 'oura'):
        setattr(publisher, f'{source}_db', absent)
    publisher.strong_db = db
    publisher.markdown_generator = MarkdownGenerator()
    return publisher


def test_best_weights_use_latest_workout_and_latest_session_per_historical_exercise(db):
    add_workout(db, '2026-10-01 09:00:00', [('Squat', 200), ('Earlier only', 90)])
    add_workout(db, '2026-10-20 08:00:00', [('Squat', 150)])
    add_workout(db, '2026-10-20 10:00:00', [
        ('Squat', 100), ('Squat', 110), ('Press', 50), ('Press', 55),
        ('Bodyweight', 0), ('New', 12.5), ('Unknown', None),
    ])
    add_workout(db, '2026-11-01 09:00:00', [('Squat', 300)])
    add_workout(db, '2026-09-01 09:00:00', [('Squat', 190)])
    add_workout(db, '2026-09-15 09:00:00', [
        ('Squat', 95), ('Squat', 100), ('Press', 0), ('Bodyweight', 0), ('Unknown', 10),
    ])
    # The month's final workout need not contain the exercise being compared.
    add_workout(db, '2026-09-30 09:00:00', [('Other exercise', 900)])
    add_workout(db, '2025-10-01 09:00:00', [('Squat', 250)])
    add_workout(db, '2025-10-28 09:00:00', [('Squat', 80), ('Bodyweight', 10)])

    summary = StrongAnalytics(db).get_weightlifting_summary('2026-10')

    assert summary['started_at'] == '2026-10-20 10:00:00'
    assert summary['workout_name'] == 'Full'
    assert summary['exercises'] == [
        {'exercise_name': 'Squat', 'weight': 110, 'comparisons': {'mom': 10.0, 'yoy': 37.5}},
        {'exercise_name': 'Press', 'weight': 55, 'comparisons': {'mom': None, 'yoy': None}},
        {'exercise_name': 'Bodyweight', 'weight': 0, 'comparisons': {'mom': None, 'yoy': -100.0}},
        {'exercise_name': 'New', 'weight': 12.5, 'comparisons': {'mom': None, 'yoy': None}},
        {'exercise_name': 'Unknown', 'weight': None, 'comparisons': {'mom': None, 'yoy': None}},
    ]


def test_calendar_comparisons_roll_january_back_to_december(db):
    add_workout(db, '2027-01-10 09:00:00', [('Squat', 100)])
    add_workout(db, '2026-12-31 09:00:00', [('Squat', 125)])
    add_workout(db, '2026-01-31 09:00:00', [('Squat', 80)])
    summary = StrongAnalytics(db).get_weightlifting_summary('2027-01')
    assert summary['exercises'][0]['comparisons'] == {'mom': -20.0, 'yoy': 25.0}


def test_missing_comparison_months_do_not_fall_back_to_other_history(db):
    add_workout(db, '2026-10-10 09:00:00', [('Squat', 100)])
    add_workout(db, '2026-08-31 09:00:00', [('Squat', 80)])
    add_workout(db, '2025-09-30 09:00:00', [('Squat', 60)])
    summary = StrongAnalytics(db).get_weightlifting_summary('2026-10')
    assert summary['exercises'][0]['comparisons'] == {'mom': None, 'yoy': None}


def test_missing_month_and_empty_latest_workout_are_omitted(db):
    add_workout(db, '2026-10-10 09:00:00', [('Squat', 100)])
    assert StrongAnalytics(db).get_weightlifting_summary('2026-09') is None
    add_workout(db, '2026-10-31 09:00:00', [])
    assert StrongAnalytics(db).get_weightlifting_summary('2026-10') is None
    assert '## Weightlifting' not in publisher_for(db).generate_markdown('2026-10')


def test_absent_database_is_optional_and_not_created(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', tmp_path)
    db = StrongDatabase(str(tmp_path / 'absent.db'))
    assert StrongAnalytics(db).get_weightlifting_summary('2026-10') is None
    assert not db.exists()


def test_csv_import_reimport_and_publish_use_latest_export_weights(db, tmp_path, monkeypatch):
    export = tmp_path / 'strong_workouts.csv'
    columns = ['Date', 'Workout Name', 'Duration', 'Exercise Name', 'Set Order', 'Weight', 'Reps']
    rows = [
        ['2026-09-10 09:00:00', 'Full', '1h', 'Squat', '1', 80, 5],
        ['2025-10-10 09:00:00', 'Full', '1h', 'Squat', '1', 50, 5],
        ['2026-10-20 09:00:00', 'Full', '1h', 'Squat', '1', 90, 5],
        ['2026-10-20 09:00:00', 'Full', '1h', 'Squat', '2', 100, 5],
        ['2026-10-20 09:00:00', 'Full', '1h', 'Squat', 'Rest Timer', 999, 0],
    ]
    with export.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)
    monkeypatch.setattr(Config, 'FILES_DIR', tmp_path)
    importer = StrongImporter(db)
    assert importer.sync() == {'workouts': 3, 'exercises': 4}
    assert importer.sync() == {'workouts': 3, 'exercises': 4}
    assert db.get_stats() == {'workouts': 3, 'exercises': 4}
    assert StrongAnalytics(db).analyze_workouts() == 3

    publisher = publisher_for(db)
    assert publisher._get_target_year_month() == '2026-10'
    markdown = publisher.generate_markdown()
    assert '## Weightlifting' in markdown
    assert '**Latest workout**: 2026-10-20 — Full' in markdown
    assert '| Squat | 100 | +25% | +100% |' in markdown
    assert '"strong"' in markdown
    assert '## Workout\n' not in markdown
    assert '## Weightlifting' not in publisher.generate_markdown('2026-08')


def test_weightlifting_table_preserves_fractional_weights_and_escapes_names():
    markdown = MarkdownGenerator().generate_monthly_summary({
        'year': '2026', 'month': '10',
        'apple_health': {'workouts': 5},
        'strong': {
            'workout_name': 'Full', 'started_at': '2026-10-20 09:00:00',
            'exercises': [
                {'exercise_name': 'Dumbbell | Press\nSeated', 'weight': 12.5},
                {'exercise_name': 'Unknown', 'weight': None},
                {'exercise_name': 'Bodyweight', 'weight': 0,
                 'comparisons': {'mom': 0, 'yoy': None}},
            ],
        },
    })
    assert '| Dumbbell \\| Press Seated | 12.5 | N/A | N/A |' in markdown
    assert '| Unknown | N/A | N/A | N/A |' in markdown
    assert '| Bodyweight | 0 | +0% | N/A |' in markdown
    assert 'units used in the Strong export' in markdown
    assert markdown.index('## Workout\n') < markdown.index('## Weightlifting\n')


def test_empty_weightlifting_data_does_not_add_section_or_tag():
    markdown = MarkdownGenerator().generate_monthly_summary({
        'year': '2026', 'month': '10', 'strong': {'exercises': []},
    })
    assert '## Weightlifting' not in markdown
    assert '"strong"' not in markdown
