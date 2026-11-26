"""Cookie-authenticated client for Surfilog's internal JSON API.

Uses the same login and session endpoints as the website. Tokens stay in memory.
"""

import json
import re
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener


API_URL = "https://surfilog.com/api"
# Cloudflare's Error 1010 guidance recommends identifying the application rather
# than using urllib's default signature. This does not impersonate a browser.
USER_AGENT = "digital-data-dump-surfilog-login/1.0"
_STRAVA_ACTIVITY_ID_RE = re.compile(r"^[1-9][0-9]*$")
_SAFE_ERROR_CODES = {
    "invalid_timestamps": "The activity's timestamps are corrupt and could not be read.",
    "invalid_gpx": "The activity GPS track could not be read or is incomplete.",
}


class SurfilogAPIError(Exception):
    """An expected login or data-access failure with a safe diagnostic."""


class SurfilogConflictError(SurfilogAPIError):
    """Raised when Surfilog reports HTTP 409 Conflict (e.g., already imported)."""


class SurfilogStravaDisconnectedError(SurfilogAPIError):
    """Raised when Surfilog reports the user's Strava connection is inactive."""


class NoRedirects(HTTPRedirectHandler):
    """Keep credentials and cookies on the requested endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_strava_activity_id(activity_id):
    if isinstance(activity_id, bool) or not isinstance(activity_id, (int, str)):
        raise SurfilogAPIError("Invalid Strava activity ID.")
    normalized = str(activity_id).strip()
    if not _STRAVA_ACTIVITY_ID_RE.match(normalized):
        raise SurfilogAPIError("Invalid Strava activity ID.")
    return normalized


def request_json(opener, method, path, timeout, payload=None):
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Origin": "https://surfilog.com",
        "Referer": "https://surfilog.com/login",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    elif method in ("POST", "PUT", "PATCH"):
        # Ensure Content-Length: 0 is sent on bodyless write requests.
        data = b""
    request = Request(API_URL + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Inspect only the known error code; never echo response bodies, which
        # could contain credentials or tokens.
        with exc:
            try:
                error = json.loads(exc.read(4096))
            except (ValueError, UnicodeError):
                error = {}
        error_code = error.get("code") if isinstance(error, dict) else None
        if (
            isinstance(error, dict)
            and error.get("cloudflare_error") is True
            and str(error.get("error_code")) == "1010"
        ):
            raise SurfilogAPIError(
                f"{method} {path}: HTTP {exc.code}. Cloudflare Error 1010 blocked "
                "this client signature before reaching Surfilog. "
                "If this persists, contact Surfilog support."
            ) from None
        if exc.headers.get("CF-Mitigated", "").lower() == "challenge":
            raise SurfilogAPIError(
                f"{method} {path}: HTTP {exc.code}. Cloudflare requires a browser "
                "challenge; use browser sign-in or contact Surfilog support."
            ) from None
        if error_code == "google_account":
            raise SurfilogAPIError(
                "This account uses Google sign-in; password login is unavailable. "
                "A Google password cannot be used with this endpoint."
            ) from None
        if error_code == "STRAVA_DISCONNECTED":
            raise SurfilogStravaDisconnectedError(
                f"{method} {path}: HTTP {exc.code}. Strava is disconnected in Surfilog; "
                "reconnect your Strava account at https://surfilog.com/upload."
            ) from None
        if exc.code == 409:
            raise SurfilogConflictError(
                f"{method} {path}: HTTP 409. Resource already exists."
            ) from None
        if error_code in _SAFE_ERROR_CODES:
            raise SurfilogAPIError(
                f"{method} {path}: HTTP {exc.code}. {_SAFE_ERROR_CODES[error_code]}"
            ) from None
        if exc.code == 429:
            detail = "Rate limited; wait before trying again."
        elif 300 <= exc.code < 400:
            detail = "Unexpected redirect; it was not followed."
        elif exc.code == 403:
            detail = "Access forbidden; credentials could not be verified."
        elif path == "/auth/login" and exc.code in (400, 401):
            detail = "Login rejected; check your credentials and sign-in method."
        elif exc.code == 401:
            detail = "Authenticated access was rejected."
        else:
            detail = "The server rejected the request."
        raise SurfilogAPIError(f"{method} {path}: HTTP {exc.code}. {detail}") from None
    except (URLError, TimeoutError, OSError):
        raise SurfilogAPIError(
            f"{method} {path}: connection failed or timed out."
        ) from None
    except (ValueError, UnicodeError):
        raise SurfilogAPIError(
            f"{method} {path}: expected a JSON response."
        ) from None
    if not isinstance(result, dict):
        raise SurfilogAPIError(f"{method} {path}: unexpected JSON response shape.")
    return result


class SurfilogAPIClient:
    """Authenticate afresh for each sync and read session/wave JSON."""

    def __init__(self, email, password, timeout=30):
        self._email = email
        self._password = password
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), NoRedirects())
        self.user_id = None
        self.token_expires = None

    def login(self):
        """Verify a fresh cookie against /auth/me; never persist credentials."""
        if not self._email or not self._password:
            raise SurfilogAPIError("Surfilog email and password are required.")
        self.cookies.clear()
        self.user_id = None
        self.token_expires = None
        request_json(self.opener, "POST", "/auth/login", self.timeout,
                     {"email": self._email, "password": self._password})
        token = next((cookie for cookie in self.cookies
                      if cookie.name == "token" and not cookie.is_expired()), None)
        if token is None:
            raise SurfilogAPIError("Login returned no usable 'token' cookie.")
        identity = request_json(self.opener, "GET", "/auth/me", self.timeout)
        user = identity.get("user")
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
            raise SurfilogAPIError("The login cookie did not authenticate /auth/me.")
        self.user_id = user["id"]
        self.token_expires = token.expires

    def get_sessions(self):
        """Return the full session list used by the website's dashboard."""
        if self.user_id is None:
            raise SurfilogAPIError("Log in to Surfilog before fetching sessions.")
        data = request_json(self.opener, "GET", "/sessions", self.timeout)
        sessions = data.get("sessions")
        if not isinstance(sessions, list):
            raise SurfilogAPIError("Surfilog returned no valid sessions list.")
        seen = set()
        for session in sessions:
            if (not isinstance(session, dict) or type(session.get("id")) is not int
                    or session["id"] <= 0 or session["id"] in seen):
                raise SurfilogAPIError("Surfilog returned an invalid or duplicate session ID.")
            seen.add(session["id"])
        return sessions

    def get_session(self, session_id):
        """Return session metadata, all detected waves, and the full GPS track."""
        if self.user_id is None:
            raise SurfilogAPIError("Log in to Surfilog before fetching session details.")
        if type(session_id) is not int or session_id <= 0:
            raise SurfilogAPIError("Invalid Surfilog session ID.")
        return request_json(self.opener, "GET", f"/sessions/{session_id}", self.timeout)

    def get_strava_status(self):
        """Return whether Strava is connected for the authenticated Surfilog account."""
        if self.user_id is None:
            raise SurfilogAPIError("Log in to Surfilog before checking Strava status.")
        data = request_json(self.opener, "GET", "/strava/status", self.timeout)
        connected = data.get("connected")
        if not isinstance(connected, bool):
            raise SurfilogAPIError("Surfilog returned an invalid Strava connection status.")
        return connected

    def get_strava_activities(self, *, page=1, per_page=30, after=None):
        """Return a page of Strava water-sport activities visible to Surfilog."""
        if self.user_id is None:
            raise SurfilogAPIError("Log in to Surfilog before listing Strava activities.")
        if type(page) is not int or page <= 0:
            raise SurfilogAPIError("Invalid Strava page number.")
        if type(per_page) is not int or not 1 <= per_page <= 200:
            raise SurfilogAPIError("Invalid Strava per_page size.")
        params = {"stravaPageFrom": page, "per_page": per_page}
        if after is not None:
            if type(after) is not int or after < 0:
                raise SurfilogAPIError("Invalid Strava 'after' timestamp.")
            params["after"] = after
        query = urlencode(params)
        data = request_json(self.opener, "GET", f"/strava/activities?{query}", self.timeout)
        activities = data.get("activities")
        has_more = data.get("hasMore")
        next_page = data.get("stravaPageNext")
        if not isinstance(activities, list) or not isinstance(has_more, bool):
            raise SurfilogAPIError("Surfilog returned an invalid Strava activities payload.")
        if next_page is not None and (type(next_page) is not int or next_page <= 0):
            raise SurfilogAPIError("Surfilog returned an invalid Strava pagination cursor.")
        if has_more and (next_page is None or next_page <= page):
            raise SurfilogAPIError("Surfilog returned a non-advancing Strava pagination cursor.")
        validated = []
        for activity in activities:
            if not isinstance(activity, dict):
                raise SurfilogAPIError("Surfilog returned an invalid Strava activity entry.")
            activity_id = _validate_strava_activity_id(activity.get("id"))
            already_imported = activity.get("already_imported")
            if not isinstance(already_imported, bool):
                raise SurfilogAPIError("Surfilog returned an invalid Strava import flag.")
            sport_type = activity.get("sport_type")
            if sport_type is not None and not isinstance(sport_type, str):
                raise SurfilogAPIError("Surfilog returned an invalid Strava sport type.")
            validated.append({**activity, "id": activity_id})
        return {"activities": validated, "has_more": has_more, "next_page": next_page}

    def import_strava_activity(self, activity_id):
        """Trigger Surfilog to import a Strava activity; treats HTTP 409 as already imported."""
        if self.user_id is None:
            raise SurfilogAPIError("Log in to Surfilog before importing Strava activities.")
        normalized_id = _validate_strava_activity_id(activity_id)
        try:
            data = request_json(
                self.opener,
                "POST",
                f"/strava/import/{normalized_id}",
                max(self.timeout, 60),
            )
        except SurfilogConflictError:
            return {"status": "already_imported", "session_id": None}
        session_id = data.get("session_id")
        if type(session_id) is not int or session_id <= 0:
            raise SurfilogAPIError("Surfilog returned an invalid session ID after Strava import.")
        return {"status": "imported", "session_id": session_id}
