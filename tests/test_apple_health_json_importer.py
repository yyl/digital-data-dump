"""Regression tests for DDU archives, legacy reconciliation, and safe replay."""

from datetime import datetime
import hashlib
import json
import sqlite3

import pytest

from src.apple_health.analytics import AppleHealthAnalytics
from src.apple_health.database import AppleHealthDatabase
from src.apple_health.importer import AppleHealthImporter
from src.apple_health.json_importer import AppleHealthJSONImporter, EXCLUDED_BATCHES
from src.config import Config


IDENTIFIER = 'abcdef00-0000-0000-0000-000000000001'


def workout(identifier=IDENTIFIER, start='2026-10-15T15:31:00+00:00',
            end='2026-10-15T16:30:00+00:00', activity='Climbing', duration=3488.907,
            energy=407.883, active=327.9, heart_rate=125.3, source='Synthetic Watch'):
    from zoneinfo import ZoneInfo
    def date(value):
        local = datetime.fromisoformat(value).astimezone(ZoneInfo('America/Los_Angeles'))
        return local.strftime('%b ') + str(local.day) + local.strftime(', %Y at %H:%M')
    def timestamp(value):
        return dict(utc=value, resolution='assumed_timezone', timezone_assumed='America/Los_Angeles',
                    timestamp_precision='minute')
    return {
        'raw': dict(identifier=identifier, type=activity, start_date=date(start), end_date=date(end),
                    duration=f'{duration} sec', elapsed_time='3408.581 sec',
                    energy_burned='' if energy is None else f'{energy} kcal',
                    active_calories='' if active is None else str(active),
                    average_heart_rate='' if heart_rate is None else str(heart_rate),
                    source_name=source, device_name='Apple Watch', device_model='Watch',
                    recording_method='Watch', is_from_watch='Yes', is_from_third_party='No',
                    average_speed='', total_distance='', flights_climbed=''),
        'normalized': dict(identifier=identifier.lower(), type=activity, start=timestamp(start), end=timestamp(end),
                           duration_seconds=duration, elapsed_seconds=3408.581,
                           energy_burned=None if energy is None else dict(value=energy, unit='kcal', interpretation='unverified'),
                           active_calories=None if active is None else dict(value=active, unit='kcal', unit_assumed=True),
                           average_heart_rate=None if heart_rate is None else dict(value=heart_rate, unit='bpm', unit_assumed=True),
                           total_distance=None, average_speed=None, flights_climbed=None,
                           is_from_watch=True, is_from_third_party=False),
    }


def archive(directory, workouts=None, received_at='2026-10-20T12:54:05Z', batch_id=None, **changes):
    envelope = dict(schema_version=1, normalization_version=1, received_at=received_at,
                    timezone_assumed='America/Los_Angeles', warnings=['dates_have_minute_precision'],
                    workouts=[workout()] if workouts is None else workouts)
    envelope.update(changes)
    envelope['batch_id'] = batch_id or hashlib.sha256(json.dumps(envelope, sort_keys=True).encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{envelope['batch_id']}.json"
    path.write_text(json.dumps(envelope), encoding='utf-8')
    return path


@pytest.fixture
def db(tmp_path):
    return AppleHealthDatabase(str(tmp_path / 'apple_health.db'))


def rows(db, table='workouts'):
    with db.get_connection() as conn:
        return [dict(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1')]


def legacy(db, id='legacy', start='2026-10-15T08:31:17-07:00', end='2026-10-15T09:30:29-07:00',
           duration=3489, source='Synthetic Watch', activity='climbing'):
    db.init_tables()
    db.save_workouts([dict(id=id, activity_type=activity, activity_type_raw='HKWorkoutActivityTypeClimbing',
                          started_at=start, ended_at=end, duration_seconds=duration, active_calories=333,
                          total_calories=444, avg_heart_rate=126, max_heart_rate=170,
                          source_name=source, source_version='10.0', device='Detailed XML device',
                          creation_date=end)])


def test_sync_json_preserves_baseline_excludes_test_and_publishes_verified_mapping(tmp_path, db, monkeypatch):
    legacy(db, start='2026-07-01T08:31:17-07:00', end='2026-07-01T09:30:29-07:00')
    baseline = rows(db)
    files = tmp_path / 'files'
    directory = files / 'apple_health/actions/batches'
    monkeypatch.setattr(Config, 'FILES_DIR', files)
    archive(directory)
    archive(directory, [workout(identifier='00000000-0000-0000-0000-000000000002', activity='Walking')])
    archive(directory, batch_id=next(iter(EXCLUDED_BATCHES)))
    (files / 'export.xml').write_text('This XML must not be opened')
    result = AppleHealthImporter(db).sync()
    assert result['success']
    assert result['inserted'] == 2
    assert result['excluded'] == 1
    assert len(rows(db)) == 3
    assert next(row for row in rows(db) if row['id'] == 'legacy') == baseline[0]
    new = next(row for row in rows(db) if row['id'] == IDENTIFIER)
    assert new['duration_seconds'] == 3489
    assert new['total_calories'] == 407.883
    assert new['active_calories'] == 327.9
    assert new['avg_heart_rate'] == 125.3
    assert new['max_heart_rate'] is None
    assert new['source_version'] is None
    assert new['creation_date'] is None
    AppleHealthAnalytics(db).analyze_workouts()
    with db.get_connection() as conn:
        october = dict(conn.execute("SELECT * FROM analysis WHERE year_month = '2026-10'").fetchone())
    assert october['workouts'] == 1
    assert october['total_duration_seconds'] == 3489
    assert october['total_calories'] == 407.88
    status = AppleHealthImporter(db).get_status()
    assert status['archive_count'] == 3
    backup = tmp_path / '.backups/apple_health.db.pre-json-v1.sqlite3'
    assert backup.is_file()
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT COUNT(*) FROM workouts').fetchone()[0] == 1
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='json_batches'").fetchone()


def test_uuid_case_dedup_older_replay_and_missing_fields_preserve_provenance(tmp_path, db):
    directory = tmp_path / 'archives'
    old = archive(directory, [workout(identifier=IDENTIFIER.upper())], received_at='2026-10-18T10:00:00Z')
    latest = archive(directory, [workout(energy=450, heart_rate=None)], received_at='2026-10-20T10:00:00Z')
    importer = AppleHealthJSONImporter(db)
    result = importer.import_files([latest, old])
    assert result['unique_uuids'] == 1
    assert result['duplicates'] == 1
    assert result['inserted'] == 1
    assert rows(db)[0]['total_calories'] == 450
    assert rows(db)[0]['avg_heart_rate'] == 125.3
    state = rows(db, 'json_import_state')[0]
    provenance = json.loads(state['provenance_json'])
    assert provenance['average_heart_rate']['batch_id'] == old.stem
    assert provenance['energy_burned']['batch_id'] == latest.stem
    latest.unlink()  # Persisted receipt/snapshot precedence survives absent archive files.
    replay = importer.import_files([old])
    assert replay['unchanged_batches'] == 1
    assert replay['unchanged'] == 1
    assert rows(db)[0]['total_calories'] == 450
    assert len(rows(db, 'json_workout_aliases')) == 1
    older = archive(directory, [workout(energy=100)], received_at='2026-10-17T10:00:00Z')
    importer.import_files([older])
    assert rows(db)[0]['total_calories'] == 450


def test_unique_legacy_match_aliases_without_replacing_richer_fields(tmp_path, db):
    legacy(db)
    baseline = rows(db)
    path = archive(tmp_path / 'archives')
    importer = AppleHealthJSONImporter(db)
    result = importer.import_files([path])
    assert result['success']
    assert result['matched'] == 1
    assert result['inserted'] == 0
    assert rows(db) == baseline
    assert rows(db, 'json_workout_aliases')[0] == dict(identifier=IDENTIFIER, workout_id='legacy', origin='xml')
    # Subsequent imports use the saved alias rather than searching for a match.
    importer._match_candidates = lambda *_: pytest.fail('alias must bypass matching')
    assert importer.import_files([path])['success']


def test_xml_duration_matching_json_elapsed_time_is_identity_evidence_only(tmp_path, db):
    legacy(db, duration=3409)
    baseline = rows(db)
    result = AppleHealthJSONImporter(db).import_files([archive(tmp_path / 'archives')])
    assert result['matched'] == 1
    assert result['pending'] == 0
    assert result['inserted'] == result['updated'] == 0
    assert rows(db) == baseline
    assert result['coverage']['xml_duration_differs_from_json_duration'] == 1


def test_legacy_duration_matching_neither_json_measurement_remains_held(tmp_path, db):
    legacy(db, duration=1000)
    result = AppleHealthJSONImporter(db).import_files([archive(tmp_path / 'archives')])
    assert result['matched'] == result['inserted'] == 0
    assert result['pending'] == 1
    assert not rows(db, 'json_workout_aliases')


@pytest.mark.parametrize('other_source,extra_row', [('Different source', False), ('Synthetic Watch', True), ('', False)])
def test_plausible_but_unconfirmed_legacy_candidates_are_held(tmp_path, db, other_source, extra_row):
    legacy(db, source=other_source)
    if extra_row:
        legacy(db, id='other')
    path = archive(tmp_path / 'archives')
    result = AppleHealthJSONImporter(db).import_files([path])
    assert not result['success']
    assert result['pending'] == 1
    assert result['inserted'] == 0
    assert rows(db, 'json_import_state')[0]['reason'] == 'ambiguous_legacy_match'
    assert not rows(db, 'json_workout_aliases')


def test_timezone_disagreement_does_not_create_duplicate(tmp_path, db):
    legacy(db, start='2026-10-15T08:31:17+00:00', end='2026-10-15T09:30:29+00:00')
    result = AppleHealthJSONImporter(db).import_files([archive(tmp_path / 'archives')])
    assert result['pending'] == 1
    assert len(rows(db)) == 1


def test_distinct_json_uuids_are_not_fuzzy_matched_to_one_another(tmp_path, db):
    path = archive(tmp_path / 'archives', [workout(), workout(identifier='00000000-0000-0000-0000-000000000002')])
    result = AppleHealthJSONImporter(db).import_files([path])
    assert result['inserted'] == 2
    assert len(rows(db)) == 2


def test_a_legacy_workout_cannot_be_claimed_by_two_json_uuids(tmp_path, db):
    legacy(db)
    path = archive(tmp_path / 'archives', [workout(), workout(identifier='00000000-0000-0000-0000-000000000002')])
    result = AppleHealthJSONImporter(db).import_files([path])
    assert result['matched'] == 1
    assert result['pending'] == 1
    assert len(rows(db)) == 1


@pytest.mark.parametrize('start,end,expected', [
    ('2026-08-01T06:59:00+00:00', '2026-08-01T07:30:00+00:00', 'skipped'),
    ('2026-08-01T07:00:00+00:00', '2026-08-01T07:30:00+00:00', 'inserted'),
])
def test_cutoff_uses_pacific_start_time(tmp_path, db, start, end, expected):
    path = archive(tmp_path / 'archives', [workout(start=start, end=end)])
    result = AppleHealthJSONImporter(db).import_files([path])
    assert result[expected] == 1
    assert result['success']  # A deliberate cutoff skip is not an unresolved match.


def test_pre_cutoff_skips_are_visible_without_blocking_or_reprocessing(tmp_path, db, monkeypatch):
    importer = AppleHealthJSONImporter(db)
    path = archive(tmp_path / 'archives', [workout(start='2026-07-01T15:31:00+00:00',
                                                end='2026-07-01T16:30:00+00:00')])
    assert importer.import_files([path])['success']
    assert rows(db, 'json_import_state')[0]['status'] == 'skipped'
    def fail(*_):
        pytest.fail('pre-cutoff skips should not be replayed without new evidence')
    monkeypatch.setattr(importer, '_merge', fail)
    result = importer.import_files([path])
    assert result['success'] and result['skipped'] == 1
    assert result['unchanged'] == result['pending'] == 0
    assert rows(db, 'json_batches')[0]['status'] == 'imported'
    assert db.get_stats()['json_skipped_before_cutoff'] == 1


def test_equal_receipt_conflict_preserves_accepted_state_and_later_snapshot_resolves(tmp_path, db):
    importer = AppleHealthJSONImporter(db)
    directory = tmp_path / 'archives'
    first = archive(directory, [workout(energy=400)])
    importer.import_files([first])
    conflict = archive(directory, [workout(energy=500)])
    result = importer.import_files([conflict])
    assert result['pending'] == 1
    assert rows(db)[0]['total_calories'] == 400
    assert rows(db, 'json_import_state')[0]['reason'] == 'snapshot_conflict'
    latest = archive(directory, [workout(energy=600)], received_at='2026-10-21T00:00:00Z')
    assert importer.import_files([latest])['success']
    assert rows(db)[0]['total_calories'] == 600


def test_fresh_equal_receipt_conflict_has_no_order_dependent_winner(tmp_path):
    directory = tmp_path / 'archives'
    paths = [archive(directory, [workout(energy=value)]) for value in (400, 500)]
    for index, ordered in enumerate((paths, paths[::-1])):
        db = AppleHealthDatabase(str(tmp_path / f'order-{index}.db'))
        result = AppleHealthJSONImporter(db).import_files(ordered)
        assert result['pending'] == 1
        assert not rows(db)


def test_immutable_change_is_rejected_and_previous_data_retained(tmp_path, db):
    path = archive(tmp_path / 'archives')
    importer = AppleHealthJSONImporter(db)
    importer.import_files([path])
    original = rows(db)
    envelope = json.loads(path.read_text())
    envelope['workouts'][0]['raw']['duration'] = '1 sec'
    path.write_text(json.dumps(envelope))
    result = importer.import_files([path])
    assert result['invalid_batches'] == 1
    assert not result['success']
    assert result['errors'][0]['reason'] == 'immutable archive content changed'
    assert rows(db) == original


@pytest.mark.parametrize('mutation', [
    lambda e: e.update(schema_version=2),
    lambda e: e.update(normalization_version=True),
    lambda e: e.update(received_at='2026-10-20T00:00:00'),
    lambda e: e.update(timezone_assumed='Invalid/Zone'),
    lambda e: e['workouts'][1]['normalized'].update(identifier='bad'),
    lambda e: e['workouts'][1]['normalized'].update(duration_seconds=float('nan')),
    lambda e: e['workouts'][1]['normalized'].update(duration_seconds=-1),
    lambda e: e['workouts'][1]['normalized']['start'].update(utc='2026-10-15T15:32:00Z'),
    lambda e: e['workouts'][1]['normalized']['end'].update(timestamp_precision='second'),
    lambda e: e['workouts'][1]['raw'].update(duration='3,48.9 sec'),
])
def test_invalid_batch_cannot_partially_import(tmp_path, db, mutation):
    path = archive(tmp_path / 'archives', [workout(), workout(identifier='00000000-0000-0000-0000-000000000002')])
    envelope = json.loads(path.read_text())
    mutation(envelope)
    path.write_text(json.dumps(envelope))
    result = AppleHealthJSONImporter(db).import_files([path])
    assert result['invalid_batches'] == 1
    assert not rows(db)
    assert not rows(db, 'json_batches')


def test_unresolved_dst_timestamp_is_persisted_for_review(tmp_path, db):
    entry = workout(start='2026-11-01T08:30:00+00:00', end='2026-11-01T10:30:00+00:00')
    entry['normalized']['start'].update(utc=None, resolution='ambiguous')
    result = AppleHealthJSONImporter(db).import_files([archive(tmp_path / 'archives', [entry])])
    assert result['invalid_batches'] == 0
    assert result['pending'] == 1
    assert rows(db, 'json_import_state')[0]['reason'] == 'unresolved_timestamp'
    assert not rows(db)


def test_missing_measurements_are_null_and_coverage_is_reported(tmp_path, db):
    path = archive(tmp_path / 'archives', [workout(energy=None, active=None, heart_rate=None,
                                                activity='Traditional Strength Training')])
    result = AppleHealthJSONImporter(db).import_files([path])
    assert rows(db)[0]['activity_type'] == 'strength training'
    assert rows(db)[0]['total_calories'] is None
    assert result['coverage']['missing_total_calories'] == 1
    assert result['coverage']['missing_average_heart_rate'] == 1


def test_failure_rolls_back_batch_alias_and_workout_together(tmp_path, db, monkeypatch):
    importer = AppleHealthJSONImporter(db)
    path = archive(tmp_path / 'archives')
    def fail(*_):
        raise sqlite3.OperationalError('simulated write failure')
    monkeypatch.setattr(importer, '_persist_workout', fail)
    with pytest.raises(sqlite3.OperationalError):
        importer.import_files([path])
    assert not rows(db)
    assert not rows(db, 'json_batches')
    assert not rows(db, 'json_workout_aliases')
    assert AppleHealthJSONImporter(db).import_files([path])['inserted'] == 1


def test_empty_archive_does_not_delete_workouts(tmp_path, db):
    legacy(db)
    original = rows(db)
    result = AppleHealthJSONImporter(db).import_files([archive(tmp_path / 'archives', [])])
    assert result['success']
    assert result['observations'] == 0
    assert rows(db) == original


def test_completed_batches_bypass_json_parsing_replay_and_legacy_search(tmp_path, db, monkeypatch):
    import src.apple_health.json_importer as module
    importer = AppleHealthJSONImporter(db)
    path = archive(tmp_path / 'archives')
    importer.import_files([path])
    def fail(*_):
        pytest.fail('completed UUIDs must not be reprocessed')
    monkeypatch.setattr(module, '_read_archive', fail)
    monkeypatch.setattr(importer, '_merge', fail)
    monkeypatch.setattr(importer, '_legacy_candidates', fail)
    result = importer.import_files([path])
    assert result['success']
    assert result['unchanged'] == result['unchanged_batches'] == 1


def test_pre_cutoff_alias_can_be_resolved_explicitly_without_fuzzy_matching(tmp_path, db, monkeypatch):
    legacy(db, start='2026-07-01T08:31:17-07:00', end='2026-07-01T09:30:29-07:00')
    baseline = rows(db)
    importer = AppleHealthJSONImporter(db)
    path = archive(tmp_path / 'archives', [workout(start='2026-07-01T15:31:00+00:00',
                                                end='2026-07-01T16:30:00+00:00')])
    assert importer.import_files([path])['skipped'] == 1
    with db.get_connection() as conn:
        conn.execute('INSERT INTO json_workout_aliases VALUES (?, ?, ?)', (IDENTIFIER, 'legacy', 'xml'))
    monkeypatch.setattr(importer, '_match_candidates', lambda *_: pytest.fail('must use explicit alias'))
    assert importer.import_files([path])['success']
    assert rows(db) == baseline


def test_cli_raises_on_unresolved_import(monkeypatch):
    import main
    monkeypatch.setattr(AppleHealthImporter, 'sync', lambda _: {'success': False})
    with pytest.raises(RuntimeError, match='requires attention'):
        main.cmd_apple_health_sync()


def test_month_grouping_uses_existing_utc_rule_and_corrections_remove_stale_months(tmp_path, db):
    importer = AppleHealthJSONImporter(db)
    directory = tmp_path / 'archives'
    first = archive(directory, [workout(start='2026-10-01T06:59:00+00:00', end='2026-10-01T07:30:00+00:00')])
    importer.import_files([first])
    analytics = AppleHealthAnalytics(db)
    analytics.analyze_workouts()
    with db.get_connection() as conn:
        assert conn.execute('SELECT year_month FROM analysis').fetchone()[0] == '2026-10'
    corrected = archive(directory, [workout(start='2026-11-01T07:00:00+00:00', end='2026-11-01T07:30:00+00:00')],
                        received_at='2026-11-02T00:00:00Z')
    assert importer.import_files([corrected])['success']
    analytics.analyze_workouts()
    with db.get_connection() as conn:
        assert [row[0] for row in conn.execute('SELECT year_month FROM analysis')] == ['2026-11']
