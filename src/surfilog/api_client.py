"""Cookie-authenticated client for Surfilog's internal JSON API.

Uses the same login and session endpoints as the website. Tokens stay in memory.
"""

import json
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener


API_URL = "https://surfilog.com/api"
# Cloudflare's Error 1010 guidance recommends identifying the application rather
# than using urllib's default signature. This does not impersonate a browser.
USER_AGENT = "digital-data-dump-surfilog-login/1.0"


class SurfilogAPIError(Exception):
    """An expected login or data-access failure with a safe diagnostic."""


class NoRedirects(HTTPRedirectHandler):
    """Keep credentials and cookies on the requested endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
        if isinstance(error, dict) and error.get("code") == "google_account":
            raise SurfilogAPIError(
                "This account uses Google sign-in; password login is unavailable. "
                "A Google password cannot be used with this endpoint."
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
