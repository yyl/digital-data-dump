"""Oura Ring API client with OAuth2 and daily data fetching."""

import os
import time
import webbrowser
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs, urlencode

import requests

from ..config import Config
from ..token_store import save_tokens_to_env


class OuraAPIClient:
    """Client for Oura Ring API v2 with OAuth2 support."""

    # API URLs
    BASE_URL = "https://api.ouraring.com"
    AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
    TOKEN_URL = "https://api.ouraring.com/oauth/token"

    # Rate limiting
    REQUEST_DELAY = 1.0
    MAX_RETRIES = 3

    # Daily data endpoint paths
    DAILY_ENDPOINTS = {
        "daily_activity": "/v2/usercollection/daily_activity",
        "daily_sleep": "/v2/usercollection/daily_sleep",
        "daily_readiness": "/v2/usercollection/daily_readiness",
        "daily_stress": "/v2/usercollection/daily_stress",
        "daily_resilience": "/v2/usercollection/daily_resilience",
        "daily_spo2": "/v2/usercollection/daily_spo2",
        "daily_cardiovascular_age": "/v2/usercollection/daily_cardiovascular_age",
    }

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ):
        """Initialize API client."""
        self.client_id = client_id or Config.OURA_CLIENT_ID
        self.client_secret = client_secret or Config.OURA_CLIENT_SECRET
        self.access_token = access_token or Config.OURA_ACCESS_TOKEN
        self.refresh_token = refresh_token or Config.OURA_REFRESH_TOKEN
        self.redirect_uri = redirect_uri or Config.OURA_REDIRECT_URI
        self.session = requests.Session()
        self._last_request_time = 0
        self._refresh_failed = False

    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _make_request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        retry_auth: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Make authenticated API request with retry logic.

        Args:
            url: Full URL to request.
            params: Query parameters.
            retry_auth: If True, attempt token refresh on 401.

        Returns:
            Parsed JSON response or None on failure.
        """
        headers = {"Authorization": f"Bearer {self.access_token}"}

        for attempt in range(self.MAX_RETRIES):
            try:
                self._rate_limit()
                response = self.session.get(
                    url, headers=headers, params=params, timeout=30
                )

                if response.status_code == 401:
                    if retry_auth and self.refresh_token and not self._refresh_failed:
                        print("  Access token expired, refreshing...")
                        if self.refresh_access_token():
                            headers = {"Authorization": f"Bearer {self.access_token}"}
                            return self._make_request(url, params, retry_auth=False)
                        else:
                            print("  Token refresh failed.")
                            self._refresh_failed = True
                            return None
                    else:
                        # 401 persists after refresh or refresh already failed
                        return None

                if response.status_code == 403:
                    # Access forbidden — usually means expired Oura subscription
                    return None

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                print(
                    f"  API request failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )
                if attempt >= self.MAX_RETRIES - 1:
                    return None
                time.sleep(1.5**attempt)
        return None

    # ==========================================================================
    # OAuth2 Authentication
    # ==========================================================================

    def needs_auth(self) -> bool:
        """Check if OAuth authentication is needed."""
        return not self.access_token

    def ensure_auth(self) -> bool:
        """Ensure a valid access token, proactively refreshing upfront if refresh token is available."""
        if self.refresh_token:
            if self.refresh_access_token():
                return True
            print("Oura token refresh failed; starting OAuth flow.")
            return self.run_oauth_flow() is not None

        if self.access_token:
            return True

        return self.run_oauth_flow() is not None

    def run_oauth_flow(self) -> Optional[str]:
        """Run OAuth2 authorization code flow to get tokens.

        Opens browser for user authorization, then prompts for redirect URL.
        Returns the access token if successful.
        """
        if not self.client_id or not self.client_secret:
            print(
                "Error: OURA_CLIENT_ID and OURA_CLIENT_SECRET must be set in .env"
            )
            return None

        import secrets
        state = secrets.token_urlsafe(16)

        # Build auth URL
        auth_params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": "daily personal spo2Daily",
            "state": state,
        }
        auth_url = f"{self.AUTH_URL}?{urlencode(auth_params)}"

        print("\n=== Oura Ring OAuth Authorization ===")
        print("Opening browser for authorization...")
        print(f"If browser doesn't open, visit: {auth_url}\n")
        webbrowser.open(auth_url)

        # Get redirect URL from user
        print(f"After authorizing, you'll be redirected to: {self.redirect_uri}")
        print("Copy the FULL URL from your browser's address bar and paste it here.\n")
        redirected_url = input("Paste redirect URL: ").strip()

        # Extract auth code
        parsed = urlparse(redirected_url)
        auth_code = parse_qs(parsed.query).get("code", [None])[0]

        if not auth_code:
            print("Error: Could not extract authorization code from URL")
            return None

        # Exchange code for tokens
        token_params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code": auth_code,
        }

        try:
            response = self.session.post(self.TOKEN_URL, data=token_params, timeout=30)
            response.raise_for_status()
            token_data = response.json()

            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")

            if access_token:
                self.access_token = access_token
                self.refresh_token = refresh_token or self.refresh_token
                self._refresh_failed = False
                print("\n✓ Access token obtained successfully!")
                self._save_tokens_to_env(self.access_token, self.refresh_token)
                return access_token
            else:
                print(f"Error: No access token in response: {token_data}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"Error during token exchange: {e}")
            return None

    def refresh_access_token(self) -> bool:
        """Use refresh token to get a new access token.

        Returns:
            True if refresh was successful.
        """
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return False

        old_suffix = self.refresh_token[-8:] if self.refresh_token else "(none)"
        print(f"Oura token refresh: attempting with refresh suffix ...{old_suffix}")

        token_params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        try:
            response = self.session.post(self.TOKEN_URL, data=token_params, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"Error refreshing Oura token (network): {e}")
            self._refresh_failed = True
            return False

        if not response.ok:
            print("Oura token refresh failed:")
            print(f"  Status: {response.status_code}")
            try:
                print(f"  Response: {response.json()}")
            except Exception:
                print(f"  Response text: {response.text[:500]}")
            self._refresh_failed = True
            return False

        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            print(f"Oura token refresh: no access_token in response. Keys: {sorted(token_data.keys())}")
            self._refresh_failed = True
            return False

        new_refresh = token_data.get("refresh_token")
        old_suffix = self.refresh_token[-8:] if self.refresh_token else "(none)"
        new_suffix = new_refresh[-8:] if new_refresh else "(none)"
        token_changed = new_refresh and new_refresh != self.refresh_token

        print("Oura token refresh succeeded:")
        print(f"  Response keys: {sorted(token_data.keys())}")
        print(f"  New refresh token returned: {bool(new_refresh)}")
        print(f"  Refresh token changed: {token_changed}")
        print(f"  Old refresh suffix: ...{old_suffix}")
        print(f"  New refresh suffix: ...{new_suffix}")

        self.access_token = access_token
        self.refresh_token = new_refresh or self.refresh_token
        self._refresh_failed = False
        self._save_tokens_to_env(self.access_token, self.refresh_token)
        return True

    # Alias for backward compatibility
    _refresh_access_token = refresh_access_token

    def _save_tokens_to_env(
        self, access_token: str, refresh_token: Optional[str]
    ) -> None:
        """Save OAuth tokens to .env file."""
        save_tokens_to_env("OURA", access_token, refresh_token)

    # ==========================================================================
    # Daily Data Fetching
    # ==========================================================================

    def fetch_daily_data(
        self,
        data_type: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch daily summary data with pagination.

        Args:
            data_type: One of the DAILY_ENDPOINTS keys (e.g., 'daily_activity').
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.

        Returns:
            List of daily summary records.
        """
        endpoint = self.DAILY_ENDPOINTS.get(data_type)
        if not endpoint:
            print(f"Error: Unknown data type: {data_type}")
            return []

        url = f"{self.BASE_URL}{endpoint}"
        all_records = []
        next_token = None

        while True:
            params = {}
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date
            if next_token:
                params["next_token"] = next_token

            data = self._make_request(url, params)
            if not data:
                break

            records = data.get("data", [])
            all_records.extend(records)

            next_token = data.get("next_token")
            if not next_token:
                break

        return all_records
