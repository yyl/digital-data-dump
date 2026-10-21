"""Apple Health JSON sync with an explicit legacy XML baseline reader."""

from __future__ import annotations

import hashlib
from bisect import insort
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import xml.etree.ElementTree as ET

from ..config import Config
from .database import AppleHealthDatabase

HEART_RATE_TYPE = "HKQuantityTypeIdentifierHeartRate"
ACTIVE_ENERGY_TYPE = "HKQuantityTypeIdentifierActiveEnergyBurned"
BASAL_ENERGY_TYPE = "HKQuantityTypeIdentifierBasalEnergyBurned"

HEART_RATE_UNITS = {"count/min", "beats/min", "bpm"}
ENERGY_TO_KCAL = {
    "kcal": 1.0,
    "cal": 1.0,
    "largecalorie": 1.0,
    "kilocalorie": 1.0,
    "kj": 0.239005736,
    "j": 0.000239005736,
}

ACTIVITY_TYPE_ALIASES = {
    "running": "run",
    "walking": "walk",
    "cycling": "cycling",
    "hiking": "hike",
    "traditional strength training": "strength training",
    "functional strength training": "functional strength training",
    "high intensity interval training": "hiit",
    "mixed cardio": "mixed cardio",
}


@dataclass
class RecordSample:
    """Normalized quantity sample used for workout fallbacks."""

    sample_type: str
    start: datetime
    end: datetime
    value: float


@dataclass
class WorkoutRecord:
    """Normalized Apple Health workout row before DB persistence."""

    id: str
    activity_type: str
    activity_type_raw: str
    started_at: str
    ended_at: str
    duration_seconds: int
    active_calories: Optional[float]
    total_calories: Optional[float]
    avg_heart_rate: Optional[float]
    max_heart_rate: Optional[float]
    source_name: Optional[str]
    source_version: Optional[str]
    device: Optional[str]
    creation_date: Optional[str]
    start_dt: datetime = field(repr=False)
    end_dt: datetime = field(repr=False)
    fallback_heart_rates: List[float] = field(default_factory=list, repr=False)
    fallback_active_calories: float = field(default=0.0, repr=False)
    fallback_basal_calories: float = field(default=0.0, repr=False)

    def to_db_row(self) -> Dict[str, Any]:
        """Convert to DB-ready dictionary."""
        return {
            "id": self.id,
            "activity_type": self.activity_type,
            "activity_type_raw": self.activity_type_raw,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "active_calories": _rounded_or_none(self.active_calories),
            "total_calories": _rounded_or_none(self.total_calories),
            "avg_heart_rate": _rounded_or_none(self.avg_heart_rate),
            "max_heart_rate": _rounded_or_none(self.max_heart_rate),
            "source_name": self.source_name,
            "source_version": self.source_version,
            "device": self.device,
            "creation_date": self.creation_date,
        }


class AppleHealthImporter:
    """Imports DDU archives; retains explicit XML import for historical baselines."""

    def __init__(self, db: Optional[AppleHealthDatabase] = None):
        """Initialize importer."""
        self.db = db or AppleHealthDatabase()

    @staticmethod
    def find_latest_export() -> Optional[Path]:
        """Find the newest Apple Health export.xml under files/."""
        files_dir = Config.FILES_DIR
        if not files_dir.exists():
            return None

        xml_files = sorted(
            {
                path.resolve()
                for pattern in ("export.xml", "*/export.xml", "*/*/export.xml")
                for path in files_dir.glob(pattern)
                if path.is_file()
            },
            key=lambda file_path: file_path.stat().st_mtime,
            reverse=True,
        )
        return xml_files[0] if xml_files else None

    def import_from_file(self, xml_path: Path) -> Dict[str, Any]:
        """Import a JSON archive or explicitly restore a legacy XML baseline."""
        if xml_path.suffix.lower() == '.json':
            from .json_importer import AppleHealthJSONImporter
            return AppleHealthJSONImporter(self.db).import_files([xml_path])
        self.db.init_tables()
        self._validate_xml_input(xml_path)
        workouts, samples = self._parse_export(xml_path)
        self._apply_record_fallbacks(workouts, samples)
        saved = self.db.save_workouts([workout.to_db_row() for workout in workouts])
        return {"workouts": saved}

    def sync(self) -> Dict[str, Any]:
        """Import all immutable JSON archives without reading XML."""
        from .json_importer import AppleHealthJSONImporter
        importer = AppleHealthJSONImporter(self.db)
        paths = importer.find_archives()
        if not paths:
            print('No Apple Health JSON archives found in files/apple_health/actions/batches/')
        stats = importer.import_files(paths)
        for key in ('files_scanned', 'unchanged_batches', 'observations', 'unique_uuids', 'duplicates',
                    'inserted', 'updated', 'unchanged', 'matched', 'excluded', 'skipped', 'pending', 'invalid_batches'):
            print(f'  {key}: {stats[key]}')
        for key, value in stats['coverage'].items():
            print(f'  coverage.{key}: {value}')
        for error in stats['errors']:
            print(f"  Error: {error['file']}: {error['reason']}")
        if stats['skipped']:
            print('  Pre-cutoff workouts were skipped by policy; recorded in json_import_state.')
        if stats['pending']:
            print('  Attention required: inspect json_import_state for held workout identifiers and reasons.')
        return stats

    def get_status(self) -> Dict[str, Any]:
        """Get importer status."""
        try:
            self.db.init_tables()
            return {
                "database_stats": self.db.get_stats(),
                "archive_count": len(self.find_json_archives()),
            }
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def find_json_archives() -> List[Path]:
        from .json_importer import AppleHealthJSONImporter
        return AppleHealthJSONImporter.find_archives()

    def _validate_xml_input(self, xml_path: Path) -> None:
        """Fail fast with clearer errors for common non-XML inputs."""
        with xml_path.open("rb") as handle:
            prefix = handle.read(128)

        trimmed = prefix.lstrip()
        if trimmed.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise ValueError(
                f"{xml_path} is a Git LFS pointer, not the real Apple Health export.xml. "
                "Fetch LFS objects before running apple-health-sync."
            )

        if not (trimmed.startswith(b"<?xml") or trimmed.startswith(b"<HealthData")):
            raise ValueError(
                f"{xml_path} does not appear to be an Apple Health export.xml file."
            )

    def _parse_export(self, xml_path: Path) -> tuple[List[WorkoutRecord], List[RecordSample]]:
        """Parse export.xml into workouts plus relevant fallback samples."""
        workouts: List[WorkoutRecord] = []
        samples: List[RecordSample] = []
        tag_stack: List[str] = []

        for event, elem in ET.iterparse(str(xml_path), events=("start", "end")):
            if event == "start":
                tag_stack.append(elem.tag)
                continue

            parent_tag = tag_stack[-2] if len(tag_stack) > 1 else None
            if elem.tag == "Workout" and parent_tag == "HealthData":
                workout = self._parse_workout(elem)
                if workout:
                    workouts.append(workout)
            elif elem.tag == "Record" and parent_tag == "HealthData":
                sample = self._parse_record_sample(elem)
                if sample:
                    samples.append(sample)

            tag_stack.pop()
            if parent_tag == "HealthData" or elem.tag == "HealthData":
                elem.clear()

        return workouts, sorted(samples, key=lambda sample: sample.start)

    def _parse_workout(self, elem: ET.Element) -> Optional[WorkoutRecord]:
        """Parse a Workout element."""
        raw_activity_type = (elem.attrib.get("workoutActivityType") or "").strip()
        start_dt = _parse_health_datetime(elem.attrib["startDate"])
        end_dt = _parse_health_datetime(elem.attrib["endDate"])
        metadata = _extract_metadata_entries(elem)

        duration_seconds = _parse_duration_seconds(
            elem.attrib.get("duration"),
            elem.attrib.get("durationUnit"),
            start_dt,
            end_dt,
        )

        active_calories: Optional[float] = None
        total_calories = _convert_energy(elem.attrib.get("totalEnergyBurned"), elem.attrib.get("totalEnergyBurnedUnit"))
        avg_heart_rate: Optional[float] = None
        max_heart_rate: Optional[float] = None
        basal_calories: Optional[float] = None

        for child in elem:
            if child.tag != "WorkoutStatistics":
                continue

            stat_type = (child.attrib.get("type") or "").strip()
            unit = child.attrib.get("unit")

            if stat_type == HEART_RATE_TYPE:
                avg_heart_rate = avg_heart_rate if avg_heart_rate is not None else _convert_heart_rate(child.attrib.get("average"), unit)
                max_heart_rate = max_heart_rate if max_heart_rate is not None else _convert_heart_rate(child.attrib.get("maximum"), unit)
            elif stat_type == ACTIVE_ENERGY_TYPE:
                if active_calories is None:
                    active_calories = _convert_energy(child.attrib.get("sum"), unit)
            elif stat_type == BASAL_ENERGY_TYPE:
                if basal_calories is None:
                    basal_calories = _convert_energy(child.attrib.get("sum"), unit)

        if total_calories is None and active_calories is not None and basal_calories is not None:
            total_calories = active_calories + basal_calories

        workout_id = (
            metadata.get("HKExternalUUID")
            or _make_workout_id(
                raw_activity_type=raw_activity_type,
                start_date=elem.attrib["startDate"],
                end_date=elem.attrib["endDate"],
                source_name=elem.attrib.get("sourceName"),
                creation_date=elem.attrib.get("creationDate"),
            )
        )

        return WorkoutRecord(
            id=workout_id,
            activity_type=_normalize_activity_type(raw_activity_type),
            activity_type_raw=raw_activity_type,
            started_at=_format_datetime(start_dt),
            ended_at=_format_datetime(end_dt),
            duration_seconds=duration_seconds,
            active_calories=active_calories,
            total_calories=total_calories,
            avg_heart_rate=avg_heart_rate,
            max_heart_rate=max_heart_rate,
            source_name=elem.attrib.get("sourceName"),
            source_version=elem.attrib.get("sourceVersion"),
            device=elem.attrib.get("device"),
            creation_date=_format_optional_datetime(elem.attrib.get("creationDate")),
            start_dt=start_dt,
            end_dt=end_dt,
        )

    def _parse_record_sample(self, elem: ET.Element) -> Optional[RecordSample]:
        """Parse a top-level Record element when it can help fill workout gaps."""
        sample_type = (elem.attrib.get("type") or "").strip()
        if sample_type not in {HEART_RATE_TYPE, ACTIVE_ENERGY_TYPE, BASAL_ENERGY_TYPE}:
            return None

        if sample_type == HEART_RATE_TYPE:
            value = _convert_heart_rate(elem.attrib.get("value"), elem.attrib.get("unit"))
        else:
            value = _convert_energy(elem.attrib.get("value"), elem.attrib.get("unit"))

        if value is None:
            return None

        return RecordSample(
            sample_type=sample_type,
            start=_parse_health_datetime(elem.attrib["startDate"]),
            end=_parse_health_datetime(elem.attrib["endDate"]),
            value=value,
        )

    def _apply_record_fallbacks(self, workouts: List[WorkoutRecord], samples: List[RecordSample]) -> None:
        """Fill missing workout metrics from overlapping top-level records."""
        if not workouts or not samples:
            return

        workouts_by_start = sorted(workouts, key=lambda workout: workout.start_dt)
        active_workouts: List[WorkoutRecord] = []
        next_workout_idx = 0

        for sample in samples:
            while next_workout_idx < len(workouts_by_start) and workouts_by_start[next_workout_idx].start_dt <= sample.end:
                active_workouts.append(workouts_by_start[next_workout_idx])
                next_workout_idx += 1

            active_workouts = [
                workout for workout in active_workouts
                if workout.end_dt >= sample.start
            ]

            best_match = _select_best_overlap(active_workouts, sample.start, sample.end)
            if not best_match:
                continue

            if sample.sample_type == HEART_RATE_TYPE:
                if best_match.avg_heart_rate is None or best_match.max_heart_rate is None:
                    insort(best_match.fallback_heart_rates, sample.value)
            elif sample.sample_type == ACTIVE_ENERGY_TYPE:
                if best_match.active_calories is None:
                    best_match.fallback_active_calories += sample.value
                elif best_match.total_calories is None:
                    best_match.fallback_active_calories += sample.value
            elif sample.sample_type == BASAL_ENERGY_TYPE and best_match.total_calories is None:
                best_match.fallback_basal_calories += sample.value

        for workout in workouts:
            if workout.avg_heart_rate is None and workout.fallback_heart_rates:
                workout.avg_heart_rate = sum(workout.fallback_heart_rates) / len(workout.fallback_heart_rates)
            if workout.max_heart_rate is None and workout.fallback_heart_rates:
                workout.max_heart_rate = max(workout.fallback_heart_rates)
            if workout.active_calories is None and workout.fallback_active_calories > 0:
                workout.active_calories = workout.fallback_active_calories
            if workout.total_calories is None:
                total_fallback = (workout.active_calories or 0) + workout.fallback_basal_calories
                if total_fallback > 0:
                    workout.total_calories = total_fallback


def _parse_health_datetime(value: str) -> datetime:
    """Parse Apple Health export datetimes."""
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def _format_datetime(value: datetime) -> str:
    """Format datetime as ISO 8601 with timezone."""
    return value.isoformat(timespec="seconds")


def _format_optional_datetime(value: Optional[str]) -> Optional[str]:
    """Format optional datetime strings."""
    if not value:
        return None
    return _format_datetime(_parse_health_datetime(value))


def _parse_duration_seconds(
    duration_value: Optional[str],
    duration_unit: Optional[str],
    start_dt: datetime,
    end_dt: datetime,
) -> int:
    """Convert workout duration into whole seconds."""
    if duration_value and duration_unit:
        try:
            duration = float(duration_value)
            unit = duration_unit.strip().lower()
            if unit in {"s", "sec", "second", "seconds"}:
                return int(round(duration))
            if unit in {"min", "minute", "minutes"}:
                return int(round(duration * 60))
            if unit in {"h", "hr", "hour", "hours"}:
                return int(round(duration * 3600))
        except ValueError:
            pass
    return max(int(round((end_dt - start_dt).total_seconds())), 0)


def _convert_energy(value: Optional[str], unit: Optional[str]) -> Optional[float]:
    """Convert energy values to kilocalories."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None

    normalized_unit = (unit or "kcal").strip().lower()
    factor = ENERGY_TO_KCAL.get(normalized_unit)
    if factor is None:
        return None
    return numeric * factor


def _convert_heart_rate(value: Optional[str], unit: Optional[str]) -> Optional[float]:
    """Convert heart rate values to BPM."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None

    normalized_unit = (unit or "count/min").strip().lower()
    if normalized_unit in HEART_RATE_UNITS:
        return numeric
    if normalized_unit in {"count/s", "beats/s"}:
        return numeric * 60
    return None


def _normalize_activity_type(raw_activity_type: str) -> str:
    """Normalize HealthKit workout activity names for display/grouping."""
    value = raw_activity_type.replace("HKWorkoutActivityType", "")
    if any(char.isspace() for char in value):
        normalized = ' '.join(value.lower().split())
        return ACTIVITY_TYPE_ALIASES.get(normalized, normalized)
    words: List[str] = []
    current = []
    for char in value:
        if char.isupper() and current:
            words.append("".join(current))
            current = [char.lower()]
        else:
            current.append(char.lower())
    if current:
        words.append("".join(current))
    normalized = " ".join(filter(None, words)).strip() or raw_activity_type
    return ACTIVITY_TYPE_ALIASES.get(normalized, normalized)


def _extract_metadata_entries(elem: ET.Element) -> Dict[str, str]:
    """Extract workout metadata entries into a dict."""
    metadata: Dict[str, str] = {}
    for child in elem:
        if child.tag != "MetadataEntry":
            continue
        key = child.attrib.get("key")
        value = child.attrib.get("value")
        if key and value and key not in metadata:
            metadata[key] = value
    return metadata


def _make_workout_id(
    raw_activity_type: str,
    start_date: str,
    end_date: str,
    source_name: Optional[str],
    creation_date: Optional[str],
) -> str:
    """Generate a deterministic workout identifier."""
    payload = "|".join([
        raw_activity_type,
        start_date,
        end_date,
        source_name or "",
        creation_date or "",
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _select_best_overlap(
    workouts: Iterable[WorkoutRecord],
    sample_start: datetime,
    sample_end: datetime,
) -> Optional[WorkoutRecord]:
    """Pick the overlapping workout with the greatest overlap duration."""
    best_workout: Optional[WorkoutRecord] = None
    best_overlap = -1.0
    for workout in workouts:
        overlap = (
            min(workout.end_dt, sample_end) - max(workout.start_dt, sample_start)
        ).total_seconds()
        if overlap >= best_overlap and overlap >= 0:
            best_workout = workout
            best_overlap = overlap
    return best_workout


def _rounded_or_none(value: Optional[float]) -> Optional[float]:
    """Round floats consistently for storage/output."""
    if value is None:
        return None
    return round(value, 2)
