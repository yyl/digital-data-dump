"""Fetch and validate every Surfilog session before replacing the local snapshot."""

from datetime import datetime, timedelta, timezone
import json
import math

from ..config import Config
from ..time_utils import utc_now_iso
from .api_client import SurfilogAPIClient, SurfilogAPIError
from .database import SurfilogDatabase


def _integer(value, field, minimum=0):
    if type(value) is not int or value < minimum:
        raise SurfilogAPIError(f"Surfilog returned an invalid {field}.")
    return value


def _number(value, field, minimum=0, maximum=None, optional=False):
    if value is None and optional:
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (TypeError, ValueError):
        raise SurfilogAPIError(f"Surfilog returned an invalid {field}.") from None
    if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
        raise SurfilogAPIError(f"Surfilog returned an invalid {field}.")
    return number


def _timestamp(value, field):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise SurfilogAPIError(f"Surfilog returned an invalid {field}.") from None


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def normalize_session(payload, session_id, synced_at):
    """Normalize the observed API schema; preserve excluded waves and GPS samples."""
    if not isinstance(payload, dict) or not isinstance(payload.get("session"), dict):
        raise SurfilogAPIError("Surfilog returned invalid session details.")
    source = payload["session"]
    if _integer(source.get("id"), "session ID", 1) != session_id:
        raise SurfilogAPIError("Surfilog session detail ID does not match the requested session.")
    waves = payload.get("waves")
    track = payload.get("trackPoints", [])
    if not isinstance(waves, list) or not isinstance(track, list):
        raise SurfilogAPIError("Surfilog returned invalid waves or track points.")
    started = _timestamp(source.get("started_at"), "session started_at")
    offset = source.get("utc_offset_min")
    if offset is not None and (type(offset) is not int or not -840 <= offset <= 840):
        raise SurfilogAPIError("Surfilog returned an invalid UTC offset.")
    local = started.astimezone(timezone(timedelta(minutes=offset or 0)))
    metrics = source.get("session_metrics") or {}
    if not isinstance(metrics, dict):
        raise SurfilogAPIError("Surfilog returned invalid session metrics.")
    # Share tokens are capability credentials, not session measurements.
    raw_session = {key: value for key, value in source.items() if key != "public_token"}
    session = {
        "id": session_id, "name": source.get("name"),
        "started_at": started.isoformat(), "utc_offset_min": offset,
        "local_started_at": local.isoformat(), "date_month": local.strftime("%Y-%m"),
        "duration_sec": _number(source.get("duration_sec"), "session duration"),
        "reported_wave_count": _integer(source.get("wave_count"), "reported wave count"),
        "paddling_distance_m": _number(metrics.get("paddlingDistanceM"), "paddling distance", optional=True),
        "board_id": source.get("board_id"), "board_name": source.get("board_name"),
        "spot_id": source.get("spot_id"), "spot_name": source.get("spot_name"),
        "raw_json": _json(raw_session), "track_points_json": _json(track),
        "synced_at": synced_at,
    }
    normalized_waves = []
    numbers = set()
    for wave in waves:
        if not isinstance(wave, dict) or wave.get("session_id") != session_id:
            raise SurfilogAPIError("Surfilog returned a wave belonging to another session.")
        wave_id = _integer(wave.get("id"), "wave ID", 1)
        number = _integer(wave.get("wave_num"), "wave number", 1)
        if number in numbers:
            raise SurfilogAPIError("Surfilog returned duplicate wave numbers.")
        numbers.add(number)
        excluded = wave.get("is_excluded")
        if not isinstance(excluded, bool):
            raise SurfilogAPIError("Surfilog returned an invalid wave exclusion flag.")
        coords = wave.get("coords_json")
        if coords is None:
            coords = []
        if not isinstance(coords, list):
            raise SurfilogAPIError("Surfilog returned invalid wave coordinates.")
        normalized_waves.append({
            "id": wave_id, "session_id": session_id, "wave_num": number,
            "start_time": _timestamp(wave.get("start_time"), "wave start_time").isoformat(),
            "duration_sec": _number(wave.get("duration_sec"), "wave duration"),
            "distance_m": _number(wave.get("distance_m"), "wave distance"),
            "max_speed_kmh": _number(wave.get("max_speed_kmh"), "wave speed"),
            "start_lat": _number(wave.get("start_lat"), "wave latitude", -90, 90, optional=True),
            "start_lon": _number(wave.get("start_lon"), "wave longitude", -180, 180, optional=True),
            "is_excluded": int(excluded), "coords_json": _json(coords), "raw_json": _json(wave),
        })
    return session, normalized_waves


class SurfilogSyncManager:
    def __init__(self, db=None, api=None):
        self.db = db or SurfilogDatabase()
        self.api = api or SurfilogAPIClient(Config.SURFILOG_EMAIL, Config.SURFILOG_PASSWORD)

    def sync(self):
        self.api.login()
        listed = self.api.get_sessions()
        sessions, waves, seen_sessions, seen_waves = [], [], set(), set()
        synced_at = utc_now_iso()
        for item in listed:
            session_id = _integer(item.get("id"), "session ID", 1)
            if session_id in seen_sessions:
                raise SurfilogAPIError("Surfilog returned duplicate sessions.")
            seen_sessions.add(session_id)
            payload = self.api.get_session(session_id)
            session, rides = normalize_session(payload, session_id, synced_at)
            owner = payload["session"].get("user_id")
            if owner is not None and owner != self.api.user_id:
                raise SurfilogAPIError("Surfilog returned session data for a different account.")
            for ride in rides:
                if ride["id"] in seen_waves:
                    raise SurfilogAPIError("Surfilog returned duplicate wave IDs.")
                seen_waves.add(ride["id"])
            sessions.append(session)
            waves.extend(rides)
        self.db.init_tables()
        self.db.replace_snapshot(sessions, waves, self.api.user_id, synced_at)
        stats = self.db.get_stats()
        print(f"Surfilog: synced {stats['sessions']} sessions, {stats['waves']} waves "
              f"and {stats['excluded_waves']} excluded waves")
        return stats

    def get_status(self):
        with self.db.read_connection(required_tables=("sessions", "waves", "sync_state")) as conn:
            if conn is None:
                return {"sessions": 0, "waves": 0, "excluded_waves": 0, "last_successful_sync_at": None}
            state = conn.execute("SELECT last_successful_sync_at FROM sync_state WHERE id = 1").fetchone()
            return {
                "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                "waves": conn.execute("SELECT COUNT(*) FROM waves WHERE is_excluded = 0").fetchone()[0],
                "excluded_waves": conn.execute("SELECT COUNT(*) FROM waves WHERE is_excluded = 1").fetchone()[0],
                "last_successful_sync_at": state[0] if state else None,
            }
