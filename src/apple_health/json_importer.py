"""Validated, replayable import of immutable DDU workout archives."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ..config import Config
from .database import AppleHealthDatabase
from .importer import _normalize_activity_type

CUTOFF = datetime(2026, 8, 1, tzinfo=ZoneInfo('America/Los_Angeles'))
EXCLUDED_BATCHES = {'a7dc2872eb888d24b61a27360ae6cac29e6c4dc10c4f9ab5b7fac01693b5ff73'}
ARCHIVE_DIRECTORY = Path('apple_health/actions/batches')
UUID_PATTERN = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
NUMBER = r'(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)(?:\.\d+)?'
RAW_FIELDS = set('identifier type start_date end_date duration elapsed_time energy_burned '
                 'active_calories average_heart_rate average_speed total_distance flights_climbed '
                 'source_name device_name device_model recording_method is_from_watch is_from_third_party'.split())
NORMALIZED_FIELDS = set('identifier type start end duration_seconds elapsed_seconds energy_burned '
                        'active_calories average_heart_rate total_distance average_speed flights_climbed '
                        'is_from_watch is_from_third_party'.split())


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f'{name}: expected object')
    return value


def _instant(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f'{name}: expected timezone-aware timestamp')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except ValueError:
        raise ValueError(f'{name}: invalid timezone-aware timestamp') from None


def _number(value: Any, name: str, maximum: float) -> float:
    if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value):
        raise ValueError(f'{name}: invalid nonnegative measurement')
    return value


def _raw_quantity(value: str | None, units: set[str], name: str) -> float | None:
    if value in (None, ''):
        return None
    match = re.fullmatch(f'({NUMBER})(?: ([A-Za-z/]+))?', value)
    if not match or (match[2] or '') not in units:
        raise ValueError(f'{name}: invalid raw measurement')
    return float(match[1].replace(',', ''))


def _quantity(value: Any, raw: str | None, name: str, units: set[str], maximum: float,
              *, assumed: bool = False, energy: bool = False) -> Any:
    number = _raw_quantity(raw, {''} if assumed else units, name)
    if number is None:
        if value is not None:
            raise ValueError(f'{name}: raw/normalized mismatch')
        return None
    obj = _object(value, name)
    normalized = _number(obj.get('value'), name, maximum)
    expected_unit = next(iter(units)) if assumed else raw.rsplit(' ', 1)[-1]
    if obj.get('unit') != expected_unit or not math.isclose(number, normalized, abs_tol=1e-8):
        raise ValueError(f'{name}: raw/normalized mismatch')
    if assumed and obj.get('unit_assumed') is not True:
        raise ValueError(f'{name}: missing unit assumption')
    if energy and obj.get('interpretation') != 'unverified':
        raise ValueError(f'{name}: unsupported energy interpretation')
    return obj


def _date(value: Any, raw: str, zone: str, name: str) -> dict:
    obj = _object(value, name)
    if obj.get('timezone_assumed') != zone or obj.get('timestamp_precision') != 'minute':
        raise ValueError(f'{name}: inconsistent timestamp provenance')
    match = re.fullmatch(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), '
                         r'(\d{4}) at (\d{2}):(\d{2})', raw)
    if not match:
        raise ValueError(f'{name}: invalid raw date')
    months = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
    try:
        wall = datetime(int(match[3]), months.index(match[1]) + 1, int(match[2]),
                        int(match[4]), int(match[5]))
        if not 1900 <= wall.year <= 2200:
            raise ValueError()
    except ValueError:
        raise ValueError(f'{name}: invalid calendar date') from None
    tz = ZoneInfo(zone)
    candidates = {wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc) for fold in (0, 1)
                  if wall.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc).astimezone(tz)
                  .replace(tzinfo=None) == wall}
    expected = 'assumed_timezone' if len(candidates) == 1 else 'ambiguous' if candidates else 'nonexistent'
    if obj.get('resolution') != expected:
        raise ValueError(f'{name}: invalid timestamp resolution')
    result = dict(obj)
    if expected == 'assumed_timezone':
        instant = _instant(obj.get('utc'), name)
        if instant not in candidates:
            raise ValueError(f'{name}: raw/normalized date mismatch')
        result['utc'] = instant.isoformat()
    elif obj.get('utc') is not None:
        raise ValueError(f'{name}: unresolved date must have null UTC')
    return result


def _snapshot(entry: Any, zone: str) -> tuple[str, dict]:
    entry = _object(entry, 'workout')
    raw = _object(entry.get('raw'), 'raw')
    norm = _object(entry.get('normalized'), 'normalized')
    if set(norm) != NORMALIZED_FIELDS:
        raise ValueError('normalized: missing or unsupported fields')
    if set(raw) - RAW_FIELDS or any(not isinstance(v, str) or len(v) > 1024 or
                                  re.search(r'[\x00-\x1f\x7f]', v) for v in raw.values()):
        raise ValueError('raw: unsupported field or value')
    for name in ('identifier', 'type', 'start_date', 'end_date', 'duration'):
        if not raw.get(name, '').strip():
            raise ValueError(f'raw.{name}: required')
    if not UUID_PATTERN.fullmatch(raw['identifier']):
        raise ValueError('identifier: invalid UUID')
    identifier = str(UUID(raw['identifier']))
    if not isinstance(norm.get('identifier'), str) or norm['identifier'].lower() != identifier:
        raise ValueError('identifier: raw/normalized mismatch')
    if norm.get('type') != raw['type']:
        raise ValueError('type: raw/normalized mismatch')
    result = dict(norm)
    result['identifier'] = identifier
    result['start'] = _date(norm.get('start'), raw['start_date'], zone, 'start')
    result['end'] = _date(norm.get('end'), raw['end_date'], zone, 'end')
    if result['start']['utc'] and result['end']['utc']:
        if _instant(result['end']['utc'], 'end') < _instant(result['start']['utc'], 'start'):
            raise ValueError('end: precedes start')
    for key, raw_key in (('duration_seconds', 'duration'), ('elapsed_seconds', 'elapsed_time')):
        amount = _raw_quantity(raw.get(raw_key), {'sec'}, key)
        if amount is None:
            if norm.get(key) is not None:
                raise ValueError(f'{key}: raw/normalized mismatch')
        elif not math.isclose(_number(norm.get(key), key, 604800), amount, abs_tol=1e-8):
            raise ValueError(f'{key}: raw/normalized mismatch')
        result[key] = amount
    for key, units, maximum, assumed, energy in (
        ('active_calories', {'kcal'}, 100000, True, False),
        ('energy_burned', {'kcal'}, 100000, False, True),
        ('average_heart_rate', {'bpm'}, 300, True, False),
        ('total_distance', {'m', 'km', 'mi', 'ft', 'yd'}, 1e9, False, False),
        ('average_speed', {'m/s', 'km/h', 'km/hr', 'mi/hr', 'mph', 'kph'}, 1e9, False, False),
    ):
        result[key] = _quantity(norm.get(key), raw.get(key), key, units, maximum,
                                assumed=assumed, energy=energy)
    flights = _raw_quantity(raw.get('flights_climbed'), {''}, 'flights_climbed')
    if flights is not None:
        _number(flights, 'flights_climbed', 100000)
        if not flights.is_integer():
            raise ValueError('flights_climbed: expected integer')
    if (norm.get('flights_climbed') != flights or
            (flights is not None and type(norm.get('flights_climbed')) not in (int, float))):
        raise ValueError('flights_climbed: raw/normalized mismatch')
    result['flights_climbed'] = flights
    for key in ('is_from_watch', 'is_from_third_party'):
        value = raw.get(key)
        if value not in (None, '', 'Yes', 'No'):
            raise ValueError(f'{key}: invalid flag')
        expected = None if not value else value == 'Yes'
        if norm.get(key) is not expected:
            raise ValueError(f'{key}: raw/normalized mismatch')
        result[key] = expected
    for key in ('source_name', 'device_name', 'device_model', 'recording_method'):
        result[key] = raw.get(key) or None
    return identifier, result


def _unique_keys(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON object key')
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError('nonfinite JSON value')


def _read_archive(path: Path, content: bytes) -> tuple[dict, dict[str, dict]]:
    try:
        envelope = json.loads(content, object_pairs_hook=_unique_keys,
                              parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('invalid JSON archive') from None
    envelope = _object(envelope, 'envelope')
    for key in ('schema_version', 'normalization_version'):
        if type(envelope.get(key)) is not int or envelope[key] != 1:
            raise ValueError(f'{key}: unsupported version')
    batch_id = envelope.get('batch_id')
    if not isinstance(batch_id, str) or not re.fullmatch('[0-9a-f]{64}', batch_id) or path.stem != batch_id:
        raise ValueError('batch_id: invalid or does not match filename')
    zone = envelope.get('timezone_assumed')
    if not isinstance(zone, str):
        raise ValueError('timezone_assumed: required')
    try:
        ZoneInfo(zone)
    except (KeyError, ValueError):
        raise ValueError('timezone_assumed: invalid timezone') from None
    _instant(envelope.get('received_at'), 'received_at')
    if not isinstance(envelope.get('warnings'), list) or any(not isinstance(w, str) for w in envelope['warnings']):
        raise ValueError('warnings: expected string array')
    if not isinstance(envelope.get('workouts'), list):
        raise ValueError('workouts: expected array')
    observations = {}
    for entry in envelope['workouts']:
        identifier, snapshot = _snapshot(entry, zone)
        if identifier in observations and snapshot != observations[identifier]:
            raise ValueError('identifier: conflicting duplicates within batch')
        observations[identifier] = snapshot
    return envelope, observations


class AppleHealthJSONImporter:
    """Stage immutable archives and reconcile their latest unique observations."""

    def __init__(self, db: AppleHealthDatabase):
        self.db = db

    @staticmethod
    def find_archives() -> list[Path]:
        return sorted((Config.FILES_DIR / ARCHIVE_DIRECTORY).glob('*.json'))

    def import_files(self, paths: list[Path]) -> dict:
        self.db.init_json_tables()
        stats = Counter(files_scanned=len(paths), unchanged_batches=0, observations=0, unique_uuids=0,
                        duplicates=0, inserted=0, updated=0, unchanged=0, matched=0, excluded=0,
                        skipped=0, pending=0, invalid_batches=0)
        errors = []
        with self.db.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TEMP TABLE affected_identifiers (identifier TEXT PRIMARY KEY)')
            for path in sorted(paths):
                try:
                    content = path.read_bytes()
                    digest = hashlib.sha256(content).hexdigest()
                    existing = conn.execute('SELECT * FROM json_batches WHERE batch_id = ?', (path.stem,)).fetchone()
                    if existing:
                        if existing['content_hash'] != digest:
                            raise ValueError('immutable archive content changed')
                        stats['unchanged_batches'] += 1
                        continue
                    envelope, observations = _read_archive(path, content)
                    excluded = envelope['batch_id'] in EXCLUDED_BATCHES
                    conn.execute('INSERT INTO json_batches VALUES (?, ?, ?, ?, ?, ?, ?)', (
                        envelope['batch_id'], digest, _instant(envelope['received_at'], 'received_at').isoformat(),
                        str(path), _canonical(envelope), len(envelope['workouts']),
                        'excluded' if excluded else 'pending'))
                    if not excluded:
                        conn.executemany('INSERT INTO json_observations VALUES (?, ?, ?)', [
                            (envelope['batch_id'], identifier, _canonical(snapshot))
                            for identifier, snapshot in observations.items()])
                        conn.executemany('INSERT OR IGNORE INTO affected_identifiers VALUES (?)',
                                         [(identifier,) for identifier in observations])
                except (ValueError, OSError) as exc:
                    stats['invalid_batches'] += 1
                    errors.append({'file': path.name, 'reason': str(exc)})

            # Retry held observations, but leave completed UUIDs untouched unless
            # a new snapshot arrived. Include history even if files are absent.
            conn.execute("INSERT OR IGNORE INTO affected_identifiers "
                         "SELECT s.identifier FROM json_import_state s WHERE s.status = 'pending' "
                         "OR (s.status = 'skipped' AND EXISTS (SELECT 1 FROM json_workout_aliases a "
                         "WHERE a.identifier = s.identifier)) "
                         "UNION SELECT identifier FROM json_observations WHERE identifier NOT IN "
                         "(SELECT identifier FROM json_import_state)")
            grouped = defaultdict(list)
            for row in conn.execute('SELECT o.*, b.received_at FROM json_observations o '
                                    'JOIN json_batches b USING (batch_id) '
                                    'JOIN affected_identifiers a USING (identifier) '
                                    'ORDER BY b.received_at, b.batch_id'):
                grouped[row['identifier']].append(dict(row))
            stats['observations'] = conn.execute(
                "SELECT COALESCE(SUM(workout_count), 0) FROM json_batches WHERE status != 'excluded'"
            ).fetchone()[0]
            stats['unique_uuids'] = conn.execute(
                'SELECT COUNT(DISTINCT identifier) FROM json_observations'
            ).fetchone()[0]
            stats['duplicates'] = stats['observations'] - stats['unique_uuids']
            stats['unchanged'] = conn.execute(
                "SELECT COUNT(*) FROM json_import_state s WHERE s.status = 'imported' "
                "AND NOT EXISTS (SELECT 1 FROM affected_identifiers a WHERE a.identifier = s.identifier)"
            ).fetchone()[0]
            stats['skipped'] = conn.execute(
                "SELECT COUNT(*) FROM json_import_state s WHERE s.status = 'skipped' "
                "AND NOT EXISTS (SELECT 1 FROM affected_identifiers a WHERE a.identifier = s.identifier)"
            ).fetchone()[0]
            stats['excluded'] = conn.execute(
                "SELECT COALESCE(SUM(workout_count), 0) FROM json_batches WHERE status = 'excluded'"
            ).fetchone()[0]
            legacy = None
            for identifier, observations in sorted(grouped.items()):
                merged, provenance, received_at, conflict = self._merge(observations)
                previous = conn.execute('SELECT * FROM json_import_state WHERE identifier = ?', (identifier,)).fetchone()
                alias = conn.execute('SELECT * FROM json_workout_aliases WHERE identifier = ?', (identifier,)).fetchone()
                reason = 'snapshot_conflict' if conflict else None
                if not reason and (not merged['start']['utc'] or not merged['end']['utc']):
                    reason = 'unresolved_timestamp'
                if not reason and not alias and _instant(merged['start']['utc'], 'start') < CUTOFF:
                    reason = 'before_cutoff'
                if reason:
                    self._hold(conn, identifier, reason, previous)
                    stats['skipped' if reason == 'before_cutoff' else 'pending'] += 1
                    continue
                if not alias:
                    if legacy is None:
                        legacy = self._legacy_candidates(conn)
                    candidates = self._match_candidates(merged, legacy)
                    if candidates is None:
                        self._hold(conn, identifier, 'ambiguous_legacy_match', previous)
                        stats['pending'] += 1
                        continue
                    if candidates:
                        target = candidates[0]['id']
                        if conn.execute('SELECT 1 FROM json_workout_aliases WHERE workout_id = ?', (target,)).fetchone():
                            self._hold(conn, identifier, 'legacy_row_already_claimed', previous)
                            stats['pending'] += 1
                            continue
                        origin = 'xml'
                        stats['matched'] += 1
                    else:
                        target, origin = identifier, 'json'
                        if conn.execute('SELECT 1 FROM workouts WHERE id = ?', (target,)).fetchone():
                            self._hold(conn, identifier, 'unmapped_identifier_collision', previous)
                            stats['pending'] += 1
                            continue
                    alias = {'workout_id': target, 'origin': origin}
                outcome = self._persist_workout(conn, alias, merged)
                conn.execute('INSERT OR IGNORE INTO json_workout_aliases VALUES (?, ?, ?)',
                             (identifier, alias['workout_id'], alias['origin']))
                stats[outcome] += 1
                conn.execute('INSERT OR REPLACE INTO json_import_state VALUES (?, ?, ?, ?, ?, ?)', (
                    identifier, 'imported', None, received_at, _canonical(merged), _canonical(provenance)))
            batch_status = ("CASE WHEN EXISTS (SELECT 1 FROM json_observations o "
                            "JOIN json_import_state s USING (identifier) "
                            "WHERE o.batch_id = json_batches.batch_id AND s.status = 'pending') "
                            "THEN 'pending' ELSE 'imported' END")
            conn.execute(f"UPDATE json_batches SET status = {batch_status} "
                         f"WHERE status != 'excluded' AND status != {batch_status}")
            coverage = self._coverage(conn)
        result = dict(stats)
        result.update(workouts=stats['inserted'] + stats['updated'], errors=errors, coverage=coverage,
                      success=not (stats['invalid_batches'] or stats['pending']))
        return result

    @staticmethod
    def _merge(observations: list[dict]) -> tuple[dict, dict, str, bool]:
        merged, provenance = {}, {}
        conflicts = set()
        by_time = defaultdict(list)
        for observation in observations:
            by_time[observation['received_at']].append(observation)
        for received_at, entries in sorted(by_time.items()):
            layer, layer_provenance = {}, {}
            layer_conflicts = set()
            for entry in entries:
                snapshot = json.loads(entry['snapshot_json'])
                for key, value in snapshot.items():
                    if value is None:
                        continue
                    if key in layer and layer[key] != value:
                        layer_conflicts.add(key)
                    layer[key] = value
                    layer_provenance[key] = {'batch_id': entry['batch_id'], 'received_at': received_at}
            for key in layer:
                if key in layer_conflicts:
                    conflicts.add(key)
                else:
                    conflicts.discard(key)
                    merged[key] = layer[key]
                    provenance[key] = layer_provenance[key]
        # Optional missing fields must still exist for the projection.
        for key in ('active_calories', 'energy_burned', 'average_heart_rate', 'source_name',
                    'device_name', 'device_model', 'elapsed_seconds'):
            merged.setdefault(key, None)
        return merged, provenance, max(by_time), bool(conflicts)

    @staticmethod
    def _hold(conn, identifier: str, reason: str, previous) -> None:
        conn.execute('INSERT OR REPLACE INTO json_import_state VALUES (?, ?, ?, ?, ?, ?)', (
            identifier, 'skipped' if reason == 'before_cutoff' else 'pending', reason,
            previous['received_at'] if previous else None,
            previous['snapshot_json'] if previous else None,
            previous['provenance_json'] if previous else None))

    @staticmethod
    def _legacy_candidates(conn) -> list[dict]:
        # SQLite's julianday compares instants rather than ISO strings with different offsets.
        return [dict(row) for row in conn.execute(
            "SELECT w.* FROM workouts w LEFT JOIN json_workout_aliases a ON a.workout_id = w.id "
            "WHERE julianday(w.started_at) >= julianday(?) AND (a.origin IS NULL OR a.origin = 'xml')",
            (CUTOFF.isoformat(),))]

    @staticmethod
    def _match_candidates(snapshot: dict, legacy: list[dict]) -> list[dict] | None:
        start = _instant(snapshot['start']['utc'], 'start')
        end = _instant(snapshot['end']['utc'], 'end')
        activity = _normalize_activity_type(snapshot['type'])
        plausible, confirmed = [], []
        for row in legacy:
            old_start = _instant(row['started_at'], 'legacy start')
            old_end = _instant(row['ended_at'], 'legacy end')
            # Omitted seconds and differing phone assumptions must not create a new
            # workout when a nearby legacy candidate cannot be ruled out.
            phone_wall = start.astimezone(ZoneInfo(snapshot['start']['timezone_assumed'])).replace(tzinfo=None)
            legacy_wall = datetime.fromisoformat(row['started_at']).replace(tzinfo=None)
            if (abs((old_start - start).total_seconds()) >= 120 and
                    abs((legacy_wall - phone_wall).total_seconds()) >= 120):
                continue
            plausible.append(row)
            same_minutes = (start <= old_start < start + timedelta(minutes=1) and
                            end <= old_end < end + timedelta(minutes=1))
            same_source = bool(snapshot['source_name'] and row['source_name'] and
                               snapshot['source_name'].strip().casefold() == row['source_name'].strip().casefold())
            same_type = row['activity_type'] == activity
            # Actions can expose wall-clock span as duration and XML's active
            # duration as elapsed_time. Either agreement is supporting identity
            # evidence; projection still preserves XML duration and uses duration
            # for new JSON rows, per the confirmed reporting policy.
            same_duration = any(value is not None and abs(row['duration_seconds'] - value) <= 1
                                for value in (snapshot['duration_seconds'], snapshot['elapsed_seconds']))
            same_zone = (old_start.astimezone(ZoneInfo(snapshot['start']['timezone_assumed'])).utcoffset()
                         == datetime.fromisoformat(row['started_at']).utcoffset())
            if same_minutes and same_source and same_type and same_duration and same_zone:
                confirmed.append(row)
        if not plausible:
            return []
        return confirmed if len(confirmed) == 1 and len(plausible) == 1 else None

    def _persist_workout(self, conn, alias: dict, snapshot: dict) -> str:
        target = alias['workout_id']
        existing = conn.execute('SELECT * FROM workouts WHERE id = ?', (target,)).fetchone()
        values = {
            'activity_type': _normalize_activity_type(snapshot['type']),
            'activity_type_raw': snapshot['type'], 'started_at': snapshot['start']['utc'],
            'ended_at': snapshot['end']['utc'], 'duration_seconds': round(snapshot['duration_seconds']),
            'active_calories': snapshot['active_calories']['value'] if snapshot['active_calories'] else None,
            'avg_heart_rate': snapshot['average_heart_rate']['value'] if snapshot['average_heart_rate'] else None,
            'total_calories': snapshot['energy_burned']['value'] if snapshot['energy_burned'] else None,
            'source_name': snapshot['source_name'],
            'device': _canonical({'name': snapshot['device_name'], 'model': snapshot['device_model']})
                      if snapshot['device_name'] or snapshot['device_model'] else None,
        }
        if existing:
            if alias['origin'] == 'xml':
                values = {key: value for key, value in values.items() if
                          key in ('active_calories', 'avg_heart_rate', 'total_calories', 'source_name')
                          and existing[key] is None and value is not None}
            else:
                values = {key: value for key, value in values.items() if value is not None and existing[key] != value}
            if not values:
                return 'unchanged'
            conn.execute('UPDATE workouts SET ' + ', '.join(f'{key} = ?' for key in values) + ' WHERE id = ?',
                         (*values.values(), target))
            return 'updated'
        conn.execute('INSERT INTO workouts (id, ' + ', '.join(values) + ') VALUES (' +
                     ', '.join('?' for _ in range(len(values) + 1)) + ')', (target, *values.values()))
        return 'inserted'

    @staticmethod
    def _coverage(conn) -> dict:
        row = conn.execute(
            "SELECT COUNT(*) AS workouts, SUM(w.total_calories IS NULL) AS missing_total_calories, "
            "SUM(w.active_calories IS NULL) AS missing_active_calories, "
            "SUM(w.avg_heart_rate IS NULL) AS missing_average_heart_rate, "
            "SUM(w.max_heart_rate IS NULL) AS missing_maximum_heart_rate, "
            "SUM(a.origin = 'xml' AND ABS(w.duration_seconds - "
            "json_extract(s.snapshot_json, '$.duration_seconds')) > 1) "
            "AS xml_duration_differs_from_json_duration "
            "FROM workouts w JOIN json_workout_aliases a ON a.workout_id = w.id "
            "JOIN json_import_state s ON s.identifier = a.identifier "
            "WHERE w.activity_type != 'walk'"
        ).fetchone()
        return {key: value or 0 for key, value in dict(row).items()}
