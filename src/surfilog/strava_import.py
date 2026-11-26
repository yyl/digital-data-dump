"""Automate importing new Strava surf sessions into Surfilog via Surfilog's Strava API."""

from datetime import date, datetime, timedelta, timezone

from ..config import Config
from .api_client import (
    SurfilogAPIClient,
    SurfilogAPIError,
    SurfilogStravaDisconnectedError,
)

DEFAULT_SPORT_TYPES = ("Surfing",)
DEFAULT_PER_PAGE = 30
MAX_PAGES = 50


def parse_since_date(value):
    """Parse an optional YYYY-MM-DD lower bound."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("Invalid --since date; expected YYYY-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"Invalid --since date {value!r}; expected YYYY-MM-DD.") from None


def _activity_date(activity):
    started = activity.get("started_at")
    if not isinstance(started, str) or len(started) < 10:
        return None
    try:
        return date.fromisoformat(started[:10])
    except ValueError:
        return None


def _format_activity(activity):
    started = activity.get("started_at") or "unknown-date"
    date_label = started[:10] if isinstance(started, str) and len(started) >= 10 else str(started)
    sport = activity.get("sport_type") or "Unknown"
    name = activity.get("name") or "(untitled)"
    return f"{activity['id']} ({date_label}, {sport}, {name})"


class SurfilogStravaImporter:
    """List Strava activities through Surfilog and import unimported surf sessions."""

    def __init__(self, api=None, *, per_page=DEFAULT_PER_PAGE, max_pages=MAX_PAGES):
        self.api = api or SurfilogAPIClient(Config.SURFILOG_EMAIL, Config.SURFILOG_PASSWORD)
        self.per_page = per_page
        self.max_pages = max_pages

    def _fetch_all_activities(self, *, after_epoch=None):
        page = 1
        seen_ids = set()
        activities = []
        for _ in range(self.max_pages):
            result = self.api.get_strava_activities(
                page=page,
                per_page=self.per_page,
                after=after_epoch,
            )
            for activity in result["activities"]:
                activity_id = activity["id"]
                if activity_id in seen_ids:
                    continue
                seen_ids.add(activity_id)
                activities.append(activity)
            if not result["has_more"]:
                return activities
            page = result["next_page"]
        raise SurfilogAPIError(
            f"Stopped after {self.max_pages} Strava activity pages without reaching the end."
        )

    def import_new(self, *, dry_run=False, since=None, sport_types=None):
        """Import unimported matching Strava activities into Surfilog.

        Logs in afresh, verifies Strava is connected, paginates available Strava
        activities, and imports matching unimported sessions oldest-first.
        """
        since_date = parse_since_date(since)
        allowed_sports = tuple(sport_types) if sport_types else DEFAULT_SPORT_TYPES
        allowed_sports_lower = {sport.casefold() for sport in allowed_sports}

        self.api.login()
        if not self.api.get_strava_status():
            raise SurfilogStravaDisconnectedError(
                "Strava is not connected to this Surfilog account. "
                "Connect it once at https://surfilog.com/upload."
            )

        # Pad the server-side 'after' filter by one day so timezone differences
        # between UTC epoch and Strava local dates cannot drop sessions on `since`.
        after_epoch = None
        if since_date is not None:
            padded_start = datetime(
                since_date.year, since_date.month, since_date.day, tzinfo=timezone.utc
            ) - timedelta(days=1)
            after_epoch = max(0, int(padded_start.timestamp()))

        activities = self._fetch_all_activities(after_epoch=after_epoch)

        already_imported = 0
        skipped_sport = 0
        skipped_before_since = 0
        pending = []

        for activity in activities:
            sport = (activity.get("sport_type") or "").casefold()
            if sport not in allowed_sports_lower:
                skipped_sport += 1
                continue
            if since_date is not None:
                act_date = _activity_date(activity)
                if act_date is not None and act_date < since_date:
                    skipped_before_since += 1
                    continue
            if activity["already_imported"]:
                already_imported += 1
                continue
            pending.append(activity)

        # Import oldest-first so Surfilog session numbering and records progress chronologically.
        pending.reverse()

        summary = {
            "checked": len(activities),
            "already_imported": already_imported,
            "skipped_sport": skipped_sport,
            "skipped_before_since": skipped_before_since,
            "pending": len(pending),
            "imported": [],
            "conflicts": [],
            "failed": [],
            "dry_run": dry_run,
        }

        if dry_run:
            if not pending:
                details = [f"{already_imported} already imported", f"{skipped_sport} other sport"]
                if since_date is not None:
                    details.append(f"{skipped_before_since} before {since_date}")
                print(f"Surfilog Strava import (dry run): 0 new activities to import ({', '.join(details)}).")
            else:
                print(f"Surfilog Strava import (dry run): {len(pending)} activity(ies) would be imported:")
                for activity in pending:
                    print(f"  - {_format_activity(activity)}")
            return summary

        for activity in pending:
            activity_id = activity["id"]
            label = _format_activity(activity)
            try:
                outcome = self.api.import_strava_activity(activity_id)
            except SurfilogStravaDisconnectedError:
                raise
            except SurfilogAPIError as exc:
                message = str(exc)
                summary["failed"].append({"activity_id": activity_id, "error": message})
                print(f"  ✗ Failed {label}: {message}")
                # Stop immediately on rate limit, auth rejection, or Cloudflare blocks.
                if any(token in message for token in ("HTTP 429", "HTTP 401", "HTTP 403", "Cloudflare")):
                    break
                continue

            if outcome["status"] == "already_imported":
                summary["conflicts"].append(activity_id)
                print(f"  = Skipped {label}: already imported (HTTP 409)")
            else:
                summary["imported"].append({
                    "activity_id": activity_id,
                    "session_id": outcome["session_id"],
                })
                print(f"  ✓ Imported {label} -> Surfilog session {outcome['session_id']}")

        print(
            f"Surfilog Strava import: {len(summary['imported'])} imported, "
            f"{already_imported + len(summary['conflicts'])} already imported, "
            f"{skipped_sport + skipped_before_since} skipped, "
            f"{len(summary['failed'])} failed"
        )
        if summary["failed"]:
            raise SurfilogAPIError(
                f"Failed to import {len(summary['failed'])} Strava activity(ies) into Surfilog."
            )
        return summary
