"""Tests for Foursquare API client."""

import sys
from unittest.mock import MagicMock

# Mock requests and dotenv before importing src modules if not available
try:
    import requests
except ImportError:
    mock_requests = MagicMock()
    class RequestException(Exception): pass
    mock_requests.exceptions.RequestException = RequestException
    sys.modules["requests"] = mock_requests
    sys.modules["requests.exceptions"] = mock_requests.exceptions

try:
    import dotenv
except ImportError:
    sys.modules["dotenv"] = MagicMock()

import pytest
from unittest.mock import patch, call
from src.foursquare.api_client import FoursquareAPIClient, FoursquareAPIError


@pytest.fixture
def mock_config():
    """Mock Config attributes."""
    with patch("src.foursquare.api_client.Config") as MockConfig:
        MockConfig.FOURSQUARE_CLIENT_ID = "test_client_id"
        MockConfig.FOURSQUARE_CLIENT_SECRET = "test_client_secret"
        MockConfig.FOURSQUARE_API_KEY = "test_api_key"
        MockConfig.FOURSQUARE_ACCESS_TOKEN = "test_access_token"
        yield MockConfig


@pytest.fixture
def mock_session():
    """Mock requests.Session."""
    with patch("src.foursquare.api_client.requests.Session") as MockSession:
        session = MockSession.return_value
        yield session


class TestFoursquareAPIClient:
    """Test FoursquareAPIClient methods."""

    def test_initialization(self, mock_config, mock_session):
        """Test client initialization with config values."""
        client = FoursquareAPIClient()
        assert client.client_id == "test_client_id"
        assert client.client_secret == "test_client_secret"
        assert client.api_key == "test_api_key"
        assert client.access_token == "test_access_token"
        assert client.session == mock_session

    def test_initialization_override(self, mock_config, mock_session):
        """Test client initialization with overridden values."""
        client = FoursquareAPIClient(
            client_id="custom_id",
            client_secret="custom_secret",
            api_key="custom_key",
            access_token="custom_token"
        )
        assert client.client_id == "custom_id"
        assert client.client_secret == "custom_secret"
        assert client.api_key == "custom_key"
        assert client.access_token == "custom_token"

    def test_fetch_checkins_no_token(self, mock_config, mock_session):
        """Test fetch_checkins returns empty list if no token."""
        mock_config.FOURSQUARE_ACCESS_TOKEN = None
        client = FoursquareAPIClient(access_token=None)
        checkins = client.fetch_checkins()
        assert checkins == []
        mock_session.get.assert_not_called()

    def test_fetch_checkins_single_page(self, mock_config, mock_session):
        """Test fetching a single page of checkins."""
        client = FoursquareAPIClient()

        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": {
                "checkins": {
                    "items": [
                        {"id": "1", "createdAt": 100},
                        {"id": "2", "createdAt": 200}
                    ]
                }
            }
        }
        mock_session.get.return_value = mock_response

        checkins = client.fetch_checkins(limit=10)

        assert len(checkins) == 2
        assert checkins[0]["id"] == "1"
        assert checkins[1]["id"] == "2"
        mock_session.get.assert_called_once()

    def test_fetch_checkins_pagination(self, mock_config, mock_session):
        """Test fetching multiple pages of checkins."""
        client = FoursquareAPIClient()

        # Mock API responses
        # Page 1: 2 items (limit=2), so it should fetch next page
        page1 = {
            "response": {
                "checkins": {
                    "items": [
                        {"id": "1", "createdAt": 200},
                        {"id": "2", "createdAt": 190}
                    ]
                }
            }
        }
        # Page 2: 1 item (limit=2), so it should stop
        page2 = {
            "response": {
                "checkins": {
                    "items": [
                        {"id": "3", "createdAt": 180}
                    ]
                }
            }
        }

        mock_response1 = MagicMock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = page1

        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = page2

        mock_session.get.side_effect = [mock_response1, mock_response2]

        checkins = client.fetch_checkins(limit=2)

        assert len(checkins) == 3
        assert [c["id"] for c in checkins] == ["1", "2", "3"]
        assert mock_session.get.call_count == 2

    def test_fetch_checkins_timestamp_filtering(self, mock_config, mock_session):
        """Test filtering checkins by timestamp."""
        client = FoursquareAPIClient()

        # Mock API response with items crossing the timestamp threshold
        response_data = {
            "response": {
                "checkins": {
                    "items": [
                        {"id": "1", "createdAt": 200},
                        {"id": "2", "createdAt": 120},  # Revisit the cursor second.
                        {"id": "3", "createdAt": 100}  # Should be filtered out if after_timestamp=120
                    ]
                }
            }
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        mock_session.get.return_value = mock_response

        checkins = client.fetch_checkins(after_timestamp=120)

        assert len(checkins) == 2
        assert [c["id"] for c in checkins] == ["1", "2"]
        # It should verify that it stops processing further items?
        # The implementation iterates and checks.

    @patch("time.sleep")
    def test_retry_logic(self, mock_sleep, mock_config, mock_session):
        """Test retry logic on failure."""
        client = FoursquareAPIClient()

        # Use the requests module from the api_client module to ensure exception classes match
        from src.foursquare.api_client import requests as api_requests

        # Fail twice, then succeed
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {"checkins": {"items": []}}}

        mock_session.get.side_effect = [
            api_requests.exceptions.RequestException("Fail 1"),
            api_requests.exceptions.RequestException("Fail 2"),
            mock_response
        ]

        client.fetch_checkins()

        assert mock_session.get.call_count == 3

    @patch("time.sleep")
    def test_max_retries_exceeded(self, mock_sleep, mock_config, mock_session):
        """Test behavior when max retries are exceeded."""
        client = FoursquareAPIClient()

        from src.foursquare.api_client import requests as api_requests

        # Always fail
        mock_session.get.side_effect = api_requests.exceptions.RequestException("Fail")

        with pytest.raises(FoursquareAPIError, match="complete page"):
            client.fetch_checkins()
        assert mock_session.get.call_count == client.MAX_RETRIES

    def test_failure_on_later_page_is_not_a_complete_fetch(self, mock_config, mock_session):
        client = FoursquareAPIClient()
        first = {"response": {"checkins": {"items": [{"id": "1", "createdAt": 150}]}}}
        with patch.object(client, "_make_request", side_effect=[first, None]):
            with pytest.raises(FoursquareAPIError, match="complete page"):
                client.fetch_checkins(limit=1)

    @patch("time.sleep")
    @patch("time.time")
    def test_rate_limiting(self, mock_time, mock_sleep, mock_config, mock_session):
        """Test rate limiting logic."""
        client = FoursquareAPIClient()

        # Setup time to simulate rapid requests
        # First call: time=100
        # Second call: time=100.5 (diff 0.5 < 1.0) -> should sleep
        mock_time.side_effect = [100, 100.5, 102]
        # Note: _rate_limit calls time.time() twice (start and end of elapsed check)
        # implementation:
        # elapsed = time.time() - self._last_request_time
        # ...
        # self._last_request_time = time.time()

        # Initial _last_request_time is 0.

        # Let's mock _make_request to be simpler or just trust _rate_limit is called.
        # But we want to test _rate_limit logic inside _make_request.

        # Override _rate_limit to verify it sleeps? No, test the logic.

        # More precise control over time:
        # 1. client init: _last_request_time = 0
        # 2. _make_request call 1:
        #    _rate_limit:
        #       now = 100
        #       elapsed = 100 - 0 = 100 > 1.0 -> no sleep
        #       _last_request_time = 100 (second time.time() call?)
        #       Wait, implementation:
        #       elapsed = time.time() - self._last_request_time
        #       if ...
        #       self._last_request_time = time.time()

        # So for one _make_request, time.time() is called twice.

        # Scenario:
        # call 1: time returns 100, 100. No sleep.
        # call 2: time returns 100.5. diff is 0.5. Sleep should be called with 0.5.
        #         then time returns 100.5 (or whatever) for setting last_request_time.

        mock_time.side_effect = [100, 100, 100.5, 100.5]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_session.get.return_value = mock_response

        # Call 1
        client._make_request("url", {})
        mock_sleep.assert_not_called()

        # Call 2
        client._make_request("url", {})
        mock_sleep.assert_called_with(client.REQUEST_DELAY - 0.5)

    def test_fetch_place_details_success(self, mock_config, mock_session):
        """Test successful place details fetch."""
        client = FoursquareAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"fsq_place_id": "venue1", "name": "Venue 1"}
        mock_session.get.return_value = mock_response

        details = client.fetch_place_details("venue1")

        assert details == {"fsq_place_id": "venue1", "name": "Venue 1"}

        # Verify headers
        args, kwargs = mock_session.get.call_args
        headers = kwargs["headers"]
        assert headers["Authorization"] == "Bearer test_api_key"
        fields = kwargs["params"]["fields"].split(",")
        assert "fsq_place_id" in fields
        assert "fsq_id" not in fields

    def test_fetch_place_details_no_key(self, mock_config, mock_session):
        """Test fetch_place_details returns None if no API key."""
        mock_config.FOURSQUARE_API_KEY = None
        client = FoursquareAPIClient(api_key=None)

        details = client.fetch_place_details("venue1")
        assert details is None
        mock_session.get.assert_not_called()

    def test_fetch_place_details_failure(self, mock_config, mock_session):
        """Test fetch_place_details returns None on failure."""
        client = FoursquareAPIClient()

        # API Error
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response

        details = client.fetch_place_details("venue1")
        assert details is None

        # Exception
        mock_session.get.side_effect = Exception("Network error")
        details = client.fetch_place_details("venue1")
        assert details is None
