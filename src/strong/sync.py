"""Normalize a complete Strong API history before atomically replacing raw data."""

from datetime import datetime, UTC
import math
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import Config
from ..time_utils import utc_now_iso
from .api_client import StrongAPIClient, StrongAPIError
from .database import StrongDatabase
from .importer import StrongImporter


WEIGHT_TYPES = {"OTHER_WEIGHT", "DUMBBELL_WEIGHT", "BARBELL_WEIGHT", "WEIGHTED_BODYWEIGHT"}
SET_TYPES = WEIGHT_TYPES | {"REPS", "RPE", "DISTANCE", "DURATION"}
KG_PER_LB = 0.45359237


def _number(value, field, default=0):
    if value is None or value == "":
        return default
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
        if not math.isfinite(number):
            raise ValueError
        return number
    except (TypeError, ValueError, OverflowError):
        raise StrongAPIError(f"Strong returned an invalid {field}.") from None


def _timestamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise ValueError
        return stamp
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise StrongAPIError("Strong returned an invalid workout timestamp.") from None


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise StrongAPIError("Set STRONG_TIMEZONE to a valid IANA timezone.") from None


def _name(value):
    if isinstance(value, dict):
        result = value.get("custom") or value.get("en")
        if isinstance(result, str) and result:
            return result
    raise StrongAPIError("Strong returned a missing or invalid exercise/workout name.")


def _visible(item):
    if (not isinstance(item, dict)
            or (item.get("isHidden") is not None and not isinstance(item["isHidden"], bool))):
        raise StrongAPIError("Strong returned an invalid visibility flag.")
    return item.get("isHidden") is not True


def _seconds(value):
    if isinstance(value, str) and ":" in value:
        parts = value.split(":")
        if len(parts) != 3:
            raise StrongAPIError("Strong returned an invalid set duration.")
        hours, minutes, seconds = [_number(part, "set duration") for part in parts]
        if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
            raise StrongAPIError("Strong returned an invalid set duration.")
        return hours * 3600 + minutes * 60 + seconds
    result = _number(value, "set duration")
    if result < 0:
        raise StrongAPIError("Strong returned an invalid set duration.")
    return result


def normalize_workouts(logs, measurements, *, weight_unit, timezone):
    """Match CSV semantics while retaining API UUIDs and local calendar dates.

    The observed API includes hidden/deleted exercises, sets, and cells. Only
    visible, completed sets contribute, including legacy sets without a flag.
    """
    if weight_unit not in ("lb", "kg"):
        raise StrongAPIError("STRONG_WEIGHT_UNIT must be 'lb' or 'kg'.")
    fallback_zone = _zone(timezone)
    workouts, exercises = {}, {}
    for log in logs:
        if not _visible(log) or log.get("logType") not in ("WORKOUT", "LOG"):
            continue
        workout_id = log.get("id")
        if not isinstance(workout_id, str) or not workout_id or workout_id in workouts:
            raise StrongAPIError("Strong returned an invalid or duplicate workout ID.")
        start, end = _timestamp(log.get("startDate")), _timestamp(log.get("endDate"))
        duration = (end - start).total_seconds()
        if duration < 0:
            raise StrongAPIError("Strong returned a workout ending before it started.")
        zone = _zone(log["timezoneId"]) if log.get("timezoneId") else fallback_zone
        local_start = start.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")
        embedded = log.get("_embedded")
        if not isinstance(embedded, dict) or not isinstance(embedded.get("cellSetGroup"), list):
            raise StrongAPIError("Strong returned invalid workout exercises.")
        workouts[workout_id] = {
            "id": workout_id, "workout_name": _name(log.get("name")),
            "started_at": local_start, "duration_minutes": int(duration // 60), "notes": None,
            "started_at_utc": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        exercises[workout_id] = []
        for group in embedded["cellSetGroup"]:
            if not _visible(group):
                continue
            if not isinstance(group.get("cellSets"), list):
                raise StrongAPIError("Strong returned invalid exercise sets.")
            parsed, notes = [], []
            for cell_set in group["cellSets"]:
                if not _visible(cell_set):
                    continue
                completed = cell_set.get("isCompleted")
                if completed is not None and not isinstance(completed, bool):
                    raise StrongAPIError("Strong returned an invalid set completion flag.")
                if not isinstance(cell_set.get("cells"), list):
                    raise StrongAPIError("Strong returned invalid set cells.")
                cells = {}
                for cell in cell_set["cells"]:
                    if not _visible(cell):
                        continue
                    kind = cell.get("cellType")
                    if kind not in SET_TYPES | {"NOTE", "REST_TIMER"} or kind in cells:
                        raise StrongAPIError("Strong returned an unsupported or duplicate set cell type.")
                    cells[kind] = cell.get("value")
                if "NOTE" in cells:
                    if cells["NOTE"]:
                        if not isinstance(cells["NOTE"], str):
                            raise StrongAPIError("Strong returned an invalid exercise note.")
                        notes.append(cells["NOTE"])
                    continue
                if completed is False:
                    continue
                if not cells or "REST_TIMER" in cells:
                    continue
                weights = [cells[key] for key in WEIGHT_TYPES if key in cells]
                if len(weights) > 1:
                    raise StrongAPIError("Strong returned multiple weights for one set.")
                weight = _number(weights[0] if weights else None, "set weight")
                if weight_unit == "lb":
                    weight = round(weight / KG_PER_LB, 8)
                parsed.append({
                    "set_order": len(parsed) + 1, "weight": weight,
                    "reps": _number(cells.get("REPS"), "set reps"),
                    "rpe": _number(cells.get("RPE"), "set RPE", None),
                    "distance": _number(cells.get("DISTANCE"), "set distance"),
                    "seconds": _seconds(cells.get("DURATION")), "notes": None,
                })
            if not parsed:
                continue
            try:
                href = group["_links"]["measurement"]["href"]
                measurement_id = urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1]
                name = _name(measurements[measurement_id]["name"])
            except (KeyError, TypeError, AttributeError, ValueError):
                raise StrongAPIError("Strong returned an unresolved exercise definition.") from None
            parsed[0]["notes"] = "\n".join(notes) or None
            for exercise in parsed:
                exercise["exercise_name"] = name
            exercises[workout_id].extend(parsed)
    return workouts, exercises


class StrongSyncManager:
    def __init__(self, db=None, api=None):
        self.db = db or StrongDatabase()
        self.api = api

    def sync(self, *, from_csv=False):
        configured = bool(Config.STRONG_USER or Config.STRONG_PASS)
        if from_csv or (self.api is None and not configured):
            state = self.db.get_sync_state()
            if not from_csv and state and state["source"] == "api":
                raise StrongAPIError(
                    "Set STRONG_USER and STRONG_PASS to refresh the API snapshot, "
                    "or use strong-sync --csv to replace it with a complete CSV export."
                )
            importer = StrongImporter(self.db)
            if not from_csv:
                return importer.sync()
            path = importer.find_latest_export()
            if path is None:
                raise StrongAPIError("No files/strong_workouts*.csv export was found.")
            stats = importer.import_from_file(path, replace=True)
            print(f"Strong CSV: replaced history with {stats['workouts']} workouts, "
                  f"{stats['exercises']} exercise sets")
            return stats
        api = self.api or StrongAPIClient(Config.STRONG_USER, Config.STRONG_PASS)
        try:
            api.login()
            measurements = api.get_measurements()
            logs = api.get_workout_logs()
            workouts, exercises = normalize_workouts(
                logs, measurements, weight_unit=Config.STRONG_WEIGHT_UNIT,
                timezone=Config.STRONG_TIMEZONE,
            )
            self.db.init_tables()
            stats = self.db.save_workouts(workouts, exercises, snapshot={
                "source": "api", "user_id": api.user_id,
                "weight_unit": Config.STRONG_WEIGHT_UNIT, "timezone": Config.STRONG_TIMEZONE,
                "last_successful_sync_at": utc_now_iso(),
            })
        finally:
            api.close()
        print(f"Strong API: synced {stats['workouts']} workouts, "
              f"{stats['exercises']} exercise sets ({Config.STRONG_WEIGHT_UNIT})")
        return stats
