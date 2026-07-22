"""Charles Schwab API client with OAuth2 token handling."""

import base64
import os
import time
import webbrowser
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, urlencode, unquote, urlparse

import requests

from ..config import Config


class SchwabAPIClient:
    """Client for Charles Schwab Trader API account data."""

    API_BASE = "https://api.schwabapi.com/trader/v1"
    AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
    TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

    REQUEST_DELAY = 0.5
    MAX_RETRIES = 3

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        callback_url: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        """Initialize API client."""
        self.client_id = client_id or Config.SCHWAB_CLIENT_ID
        self.client_secret = client_secret or Config.SCHWAB_CLIENT_SECRET
        self.callback_url = callback_url or Config.SCHWAB_CALLBACK_URL
        self.access_token = access_token or Config.SCHWAB_ACCESS_TOKEN
        self.refresh_token = refresh_token or Config.SCHWAB_REFRESH_TOKEN
        self.session = requests.Session()
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        """Enforce light client-side rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _basic_auth_header(self) -> str:
        """Return Basic auth payload for token exchange."""
        raw = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(raw.encode()).decode()

    def needs_auth(self) -> bool:
        """Return True when no access token is configured."""
        return not self.access_token

    def ensure_auth(self) -> bool:
        """Ensure an access token exists, refreshing or running OAuth when needed."""
        if self.access_token:
            return True

        if self.refresh_token:
            if self.refresh_access_token():
                return True
            print("Schwab token refresh failed; starting OAuth flow.")

        return self.run_oauth_flow() is not None

    def _save_tokens_to_env(
        self, access_token: str, refresh_token: Optional[str]
    ) -> None:
        """Persist Schwab OAuth tokens into .env."""
        env_path = Config.PROJECT_ROOT / ".env"
        lines = []
        access_found = False
        refresh_found = False

        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("SCHWAB_ACCESS_TOKEN="):
                        lines.append(f"SCHWAB_ACCESS_TOKEN={access_token}\n")
                        access_found = True
                    elif line.startswith("SCHWAB_REFRESH_TOKEN="):
                        if refresh_token:
                            lines.append(f"SCHWAB_REFRESH_TOKEN={refresh_token}\n")
                        else:
                            lines.append(line)
                        refresh_found = True
                    else:
                        lines.append(line)

        if not access_found:
            lines.append(f"\nSCHWAB_ACCESS_TOKEN={access_token}\n")
        if refresh_token and not refresh_found:
            lines.append(f"SCHWAB_REFRESH_TOKEN={refresh_token}\n")

        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)

        print(f"✓ Schwab tokens saved to {env_path}")

    def run_oauth_flow(self) -> Optional[str]:
        """Run Schwab OAuth authorization code flow."""
        if not self.client_id or not self.client_secret:
            print("Error: SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET must be set.")
            return None

        auth_params = {
            "client_id": self.client_id,
            "redirect_uri": self.callback_url,
        }
        auth_url = f"{self.AUTH_URL}?{urlencode(auth_params)}"

        print("\n=== Charles Schwab OAuth Authorization ===")
        print("Opening browser for Schwab authorization...")
        print(f"If browser doesn't open, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)

        print(f"After authorizing, you'll be redirected to: {self.callback_url}")
        print("Copy the full redirect URL from the browser and paste it here.\n")
        redirected_url = input("Paste redirect URL: ").strip()

        parsed = urlparse(redirected_url)
        auth_code = parse_qs(parsed.query).get("code", [None])[0]
        if not auth_code:
            print("Error: Could not extract authorization code from URL.")
            return None

        try:
            response = self.session.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {self._basic_auth_header()}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": unquote(auth_code),
                    "redirect_uri": self.callback_url,
                },
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error during Schwab token exchange: {e}")
            return None

        token_data = response.json()
        self.access_token = token_data.get("access_token")
        self.refresh_token = token_data.get("refresh_token") or self.refresh_token

        if not self.access_token:
            print(f"Error: No Schwab access token in response: {token_data}")
            return None

        self._save_tokens_to_env(self.access_token, self.refresh_token)
        return self.access_token

    def refresh_access_token(self) -> bool:
        """Refresh the Schwab access token."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return False

        try:
            response = self.session.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {self._basic_auth_header()}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                },
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error refreshing Schwab token: {e}")
            return False

        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            print(f"Schwab token refresh: no access_token in response. Keys: {sorted(token_data.keys())}")
            return False

        new_refresh = token_data.get("refresh_token")
        old_suffix = self.refresh_token[-8:] if self.refresh_token else "(none)"
        new_suffix = new_refresh[-8:] if new_refresh else "(none)"
        token_changed = new_refresh and new_refresh != self.refresh_token

        print(f"Schwab token refresh succeeded:")
        print(f"  Response keys: {sorted(token_data.keys())}")
        print(f"  New refresh token returned: {bool(new_refresh)}")
        print(f"  Refresh token changed: {token_changed}")
        print(f"  Old refresh suffix: ...{old_suffix}")
        print(f"  New refresh suffix: ...{new_suffix}")

        self.access_token = access_token
        self.refresh_token = new_refresh or self.refresh_token
        self._save_tokens_to_env(self.access_token, self.refresh_token)
        return True

    def _make_request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        retry_auth: bool = True,
    ) -> Any:
        """Make an authenticated Schwab API request."""
        if not self.access_token:
            raise ValueError("Schwab access token is not configured.")

        url = f"{self.API_BASE}{path}"

        for attempt in range(self.MAX_RETRIES):
            self._rate_limit()
            response = self.session.get(
                url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                params=params,
                timeout=30,
            )

            if response.status_code == 401 and retry_auth and self.refresh_token:
                if self.refresh_access_token():
                    return self._make_request(path, params=params, retry_auth=False)

            try:
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                if attempt >= self.MAX_RETRIES - 1:
                    raise
                print(
                    f"Schwab API request failed "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )
                time.sleep(1.5**attempt)

        return None

    def get_account_numbers(self) -> List[Dict[str, Any]]:
        """Fetch plain and hashed Schwab account numbers."""
        data = self._make_request("/accounts/accountNumbers")
        return data if isinstance(data, list) else []

    def get_accounts(self) -> List[Dict[str, Any]]:
        """Fetch Schwab account balances and positions."""
        data = self._make_request("/accounts")
        return data if isinstance(data, list) else []

    def get_transactions(
        self,
        account_hash: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, Any]]:
        """Fetch transactions for a Schwab account hash."""
        encoded_account_hash = quote(account_hash, safe="")
        data = self._make_request(
            f"/accounts/{encoded_account_hash}/transactions",
            params={
                "types": "TRADE",
                "startDate": start_date,
                "endDate": end_date,
            },
        )
        return data if isinstance(data, list) else []
