"""TMDB client for enriching Letterboxd films with stable metadata."""

import re
import time
from typing import Any, Dict, Optional, Tuple

import requests

from ..config import Config


class TMDBAPIError(RuntimeError):
    """Sanitized error raised when TMDB cannot satisfy a runtime lookup."""


class TMDBClient:
    """Small TMDB client focused on movie runtime enrichment."""

    API_BASE = "https://api.themoviedb.org/3"
    REQUEST_DELAY = 0.25
    MAX_RETRIES = 3
    FALLBACK_YEAR_DELTA = 1

    def __init__(
        self,
        access_token: Optional[str] = None,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self.access_token = access_token if access_token is not None else Config.TMDB_ACCESS_TOKEN
        self.api_key = api_key if api_key is not None else Config.TMDB_API_KEY
        self.session = session or requests.Session()
        self._last_request_time = 0.0

    def is_configured(self) -> bool:
        """Return whether TMDB credentials are available."""
        return bool(self.access_token or self.api_key)

    def _rate_limit(self) -> None:
        """Avoid bursting the free API harder than needed."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers for TMDB authentication."""
        headers = {"accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _build_params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build query params, including the API key when needed."""
        params = dict(extra or {})
        if self.api_key and not self.access_token:
            params["api_key"] = self.api_key
        return params

    def _make_request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make a TMDB request with retries on transient errors and loud failures."""
        if not self.is_configured():
            raise TMDBAPIError(
                "TMDB credentials are not configured; set TMDB_ACCESS_TOKEN or TMDB_API_KEY."
            )

        url = f"{self.API_BASE}{path}"
        headers = self._build_headers()
        query = self._build_params(params)

        for attempt in range(self.MAX_RETRIES):
            try:
                self._rate_limit()
                response = self.session.get(url, headers=headers, params=query, timeout=30)
            except requests.exceptions.Timeout:
                if attempt >= self.MAX_RETRIES - 1:
                    raise TMDBAPIError(f"TMDB API request timed out for {path}.") from None
                time.sleep(1.5 ** attempt)
                continue
            except requests.exceptions.RequestException:
                if attempt >= self.MAX_RETRIES - 1:
                    raise TMDBAPIError(f"TMDB API network error for {path}.") from None
                time.sleep(1.5 ** attempt)
                continue

            status = response.status_code
            if status == 404 and path.startswith("/movie/"):
                return None
            if status in (401, 403):
                raise TMDBAPIError(
                    f"TMDB API authentication failed (HTTP {status}) for {path}; "
                    "check TMDB_ACCESS_TOKEN or TMDB_API_KEY."
                )
            if status == 429 or status >= 500:
                if attempt >= self.MAX_RETRIES - 1:
                    raise TMDBAPIError(f"TMDB API request failed (HTTP {status}) for {path}.")
                time.sleep(1.5 ** attempt)
                continue
            if status >= 400:
                raise TMDBAPIError(f"TMDB API request failed (HTTP {status}) for {path}.")

            try:
                payload = response.json()
            except ValueError:
                raise TMDBAPIError(f"TMDB API returned invalid JSON for {path}.") from None
            if not isinstance(payload, dict):
                raise TMDBAPIError(f"TMDB API returned an unexpected payload for {path}.")
            return payload

        raise TMDBAPIError(f"TMDB API request failed after retries for {path}.")

    @staticmethod
    def _normalize_title(title: Optional[str]) -> str:
        """Normalize movie titles for conservative comparisons."""
        if not title:
            return ""
        normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        return re.sub(r"\s+", " ", normalized)

    @staticmethod
    def _release_year(movie: Dict[str, Any]) -> Optional[int]:
        """Extract the release year from a TMDB movie payload."""
        release_date = movie.get("release_date")
        if not release_date or len(release_date) < 4:
            return None
        try:
            return int(release_date[:4])
        except ValueError:
            return None

    def _is_strong_match(
        self,
        result: Dict[str, Any],
        title: str,
        year: Optional[int],
        year_tolerance: int = 0,
    ) -> bool:
        """Require an exact normalized title match and a conservative year check."""
        expected_title = self._normalize_title(title)
        candidate_titles = {
            self._normalize_title(result.get("title")),
            self._normalize_title(result.get("original_title")),
        }
        if expected_title not in candidate_titles:
            return False

        if year is None:
            return True

        release_year = self._release_year(result)
        if release_year is None:
            return False

        return abs(release_year - year) <= year_tolerance

    def _find_match(
        self,
        results: list[Dict[str, Any]],
        title: str,
        year: Optional[int],
        year_tolerance: int = 0,
    ) -> Optional[Tuple[int, int]]:
        """Pick the first safe TMDB match from a result set."""
        for result in results:
            if not self._is_strong_match(result, title, year, year_tolerance=year_tolerance):
                continue

            movie_id = result.get("id")
            if movie_id is None:
                continue

            details = self.get_movie_details(int(movie_id))
            if details:
                return details

        return None

    def search_movie(self, title: str, year: Optional[int]) -> Optional[Tuple[int, int]]:
        """Find a TMDB movie ID and runtime using a conservative title/year search."""
        data = self._make_request("/search/movie", {"query": title, "year": year} if year else {"query": title})
        if not data:
            return None

        strict_match = self._find_match(data.get("results", []), title, year)
        if strict_match:
            return strict_match

        if year is None:
            return None

        fallback_data = self._make_request("/search/movie", {"query": title})
        if not fallback_data:
            return None

        return self._find_match(
            fallback_data.get("results", []),
            title,
            year,
            year_tolerance=self.FALLBACK_YEAR_DELTA,
        )

    def get_movie_details(self, tmdb_id: int) -> Optional[Tuple[int, int]]:
        """Fetch runtime for a known TMDB movie."""
        data = self._make_request(f"/movie/{tmdb_id}")
        if not data:
            return None

        runtime = data.get("runtime")
        if isinstance(runtime, int) and runtime > 0:
            return tmdb_id, runtime
        return None

    def get_runtime(
        self,
        title: str,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
    ) -> Optional[Tuple[int, int]]:
        """Return `(tmdb_id, runtime_minutes)` for a movie when TMDB can match it safely."""
        if tmdb_id is not None:
            return self.get_movie_details(tmdb_id)
        return self.search_movie(title, year)
