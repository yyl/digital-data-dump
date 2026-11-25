"""Foursquare API client with OAuth2 and Places API support."""

import os
import time
import webbrowser
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs, urlencode

import requests

from ..config import Config


class FoursquareAPIError(RuntimeError):
    """Foursquare could not complete a required operation."""


class FoursquareAPIClient:
    """Client for Foursquare APIs with OAuth2 support."""
    
    # API URLs
    AUTH_URL = "https://foursquare.com/oauth2/authenticate"
    TOKEN_URL = "https://foursquare.com/oauth2/access_token"
    V2_API_BASE = "https://api.foursquare.com/v2"
    PLACES_API_BASE = "https://places-api.foursquare.com"  # Not api.foursquare.com/v3!
    
    # API versions
    V2_VERSION = "20250617"
    PLACES_API_VERSION = "2025-06-17"
    
    # Rate limiting
    REQUEST_DELAY = 1.0
    MAX_RETRIES = 3
    CHECKINS_LIMIT = 200
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        redirect_uri: Optional[str] = None
    ):
        """Initialize API client."""
        self.client_id = client_id or Config.FOURSQUARE_CLIENT_ID
        self.client_secret = client_secret or Config.FOURSQUARE_CLIENT_SECRET
        self.api_key = api_key or Config.FOURSQUARE_API_KEY
        self.access_token = access_token or Config.FOURSQUARE_ACCESS_TOKEN
        self.redirect_uri = redirect_uri or Config.FOURSQUARE_REDIRECT_URI
        self.session = requests.Session()
        self._last_request_time = 0
    
    def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(
        self,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Make API request with retry logic."""
        for attempt in range(self.MAX_RETRIES):
            try:
                self._rate_limit()
                response = self.session.get(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                print(f"API request failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                if attempt >= self.MAX_RETRIES - 1:
                    return None
                time.sleep(1.5 ** attempt)
        return None
    
    # ==========================================================================
    # OAuth2 Authentication
    # ==========================================================================
    
    def needs_auth(self) -> bool:
        """Check if OAuth authentication is needed."""
        return not self.access_token
    
    def run_oauth_flow(self) -> Optional[str]:
        """Run OAuth2 flow to get access token.
        
        Opens browser for user authorization, then prompts for redirect URL.
        Returns the access token if successful.
        """
        if not self.client_id or not self.client_secret:
            print("Error: FOURSQUARE_CLIENT_ID and FOURSQUARE_CLIENT_SECRET must be set in .env")
            return None
        
        # Build auth URL
        auth_params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri
        }
        auth_url = f"{self.AUTH_URL}?{urlencode(auth_params)}"
        
        print("\n=== Foursquare OAuth Authorization ===")
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
        
        # Exchange code for token
        token_params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code": auth_code
        }
        
        try:
            response = self.session.post(self.TOKEN_URL, data=token_params, timeout=30)
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            
            if access_token:
                self.access_token = access_token
                print("\n✓ Access token obtained successfully!")
                self._save_token_to_env(access_token)
                return access_token
            else:
                print(f"Error: No access token in response: {token_data}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Error during token exchange: {e}")
            return None
    
    def _save_token_to_env(self, token: str) -> None:
        """Save access token to .env file."""
        env_path = Config.PROJECT_ROOT / ".env"
        
        # Read existing content
        lines = []
        token_found = False
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("FOURSQUARE_ACCESS_TOKEN="):
                        lines.append(f"FOURSQUARE_ACCESS_TOKEN={token}\n")
                        token_found = True
                    else:
                        lines.append(line)
        
        # Add token if not found
        if not token_found:
            lines.append(f"\nFOURSQUARE_ACCESS_TOKEN={token}\n")
        
        # Write back securely
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        # Ensure permissions are restricted (important if file already existed)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)

        print(f"✓ Token saved to {env_path}")
    
    # ==========================================================================
    # User API (v2)
    # ==========================================================================
    
    def get_user_id(self) -> Optional[str]:
        """Get the authenticated user's Foursquare ID."""
        if not self.access_token:
            return None
        
        headers = {"Authorization": f"OAuth {self.access_token}"}
        params = {"v": self.V2_VERSION}
        
        data = self._make_request(
            f"{self.V2_API_BASE}/users/self",
            headers,
            params
        )
        
        if data:
            return data.get("response", {}).get("user", {}).get("id")
        return None
    
    # ==========================================================================
    # Checkins API (v2)
    # ==========================================================================
    
    def fetch_checkins(
        self,
        after_timestamp: int = 0,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Fetch user checkins with pagination.
        
        Args:
            after_timestamp: Re-fetch checkins on the cursor second and later
            limit: Max checkins per request
            
        Returns:
            List of checkin objects
        """
        if not self.access_token:
            return []
        
        headers = {"Authorization": f"OAuth {self.access_token}"}
        all_checkins = []
        offset = 0
        
        while True:
            params = {
                "v": self.V2_VERSION,
                "limit": limit,
                "offset": offset
            }
            
            data = self._make_request(
                f"{self.V2_API_BASE}/users/self/checkins",
                headers,
                params
            )
            
            if data is None:
                raise FoursquareAPIError("Could not fetch a complete page of Foursquare checkins.")

            items = data.get("response", {}).get("checkins", {}).get("items")
            if not isinstance(items, list):
                raise FoursquareAPIError("Foursquare returned an invalid checkin page.")
            if not items:
                break
            
            # Filter by timestamp and collect
            for checkin in items:
                created_at = checkin.get("createdAt")
                if type(created_at) is not int:
                    raise FoursquareAPIError("A Foursquare checkin has an invalid timestamp.")
                if after_timestamp > 0 and created_at < after_timestamp:
                    # The cursor second can contain more than one checkin.
                    return all_checkins
                all_checkins.append(checkin)
            
            offset += len(items)
            
            # Check if we got fewer than requested (last page)
            if len(items) < limit:
                break
        
        return all_checkins
    
    # ==========================================================================
    # Places API
    # ==========================================================================
    
    def fetch_place_details(self, place_id: str) -> Optional[Dict[str, Any]]:
        """Fetch place details using Places API.
        
        Args:
            place_id: Foursquare place/venue ID
            
        Returns:
            Place details dict or None
        """
        if not self.api_key:
            # No API key, skip place details
            return None
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # Bearer prefix required!
            "Accept": "application/json",
            "X-Places-Api-Version": self.PLACES_API_VERSION
        }
        
        params = {
            "fields": "fsq_place_id,name,latitude,longitude,categories,location,website,tel,email"
        }
        
        # Try the request but don't fail hard - place details are optional
        try:
            self._rate_limit()
            response = self.session.get(
                f"{self.PLACES_API_BASE}/places/{place_id}",
                headers=headers,
                params=params,
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
            else:
                # Silently fail - we'll use venue data from checkin instead
                return None
        except Exception:
            return None
