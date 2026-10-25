
import sys
import unittest
import time
from unittest.mock import MagicMock, patch

# Mock dependencies if not available
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    mock_requests = MagicMock()
    class RequestException(Exception): pass
    class HTTPError(Exception): pass
    mock_requests.exceptions.RequestException = RequestException
    mock_requests.HTTPError = HTTPError
    sys.modules["requests"] = mock_requests
    sys.modules["requests.exceptions"] = mock_requests.exceptions
    HAS_REQUESTS = False

try:
    import dotenv
except ImportError:
    sys.modules["dotenv"] = MagicMock()

from src.github.api_client import GitHubActivityClient

# Define exception for testing if requests is not available
if not HAS_REQUESTS:
    HTTPErrorClass = HTTPError
else:
    HTTPErrorClass = requests.HTTPError

class TestGitHubActivityClient(unittest.TestCase):
    def setUp(self):
        # We need to patch requests.Session BEFORE client init so self.client.session is a mock
        self.session_patcher = patch("src.github.api_client.requests.Session")
        self.mock_session_cls = self.session_patcher.start()
        self.mock_session = self.mock_session_cls.return_value
        self.mock_session.headers = {} # Use a real dict for headers

        # Mock Config
        self.config_patcher = patch("src.github.api_client.Config")
        self.mock_config = self.config_patcher.start()
        self.mock_config.CODEBASE_GITHUB_TOKEN = ""
        self.mock_config.BLOG_GITHUB_TOKEN = "test_token"
        self.mock_config.CODEBASE_USERNAME = "test_user"

        self.client = GitHubActivityClient()

    def tearDown(self):
        self.session_patcher.stop()
        self.config_patcher.stop()

    def test_init_defaults(self):
        """Test initialization with default config values."""
        self.assertEqual(self.client.token, "test_token")
        self.assertEqual(self.client.username, "test_user")
        self.assertEqual(self.client.session.headers["Accept"], "application/vnd.github+json")
        self.assertEqual(self.client.session.headers["X-GitHub-Api-Version"], "2022-11-28")
        self.assertEqual(self.client.session.headers["Authorization"], "Bearer test_token")

    def test_init_override(self):
        """Test initialization with overridden values."""
        with patch("src.github.api_client.requests.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.headers = {}
            client = GitHubActivityClient(token="custom_token", username="custom_user")
            self.assertEqual(client.token, "custom_token")
            self.assertEqual(client.username, "custom_user")
            self.assertEqual(client.session.headers["Authorization"], "Bearer custom_token")

    def test_activity_token_takes_precedence_over_publishing_token(self):
        self.mock_config.CODEBASE_GITHUB_TOKEN = "read_only_token"
        client = GitHubActivityClient()
        self.assertEqual(client.token, "read_only_token")
        self.assertEqual(client.session.headers["Authorization"], "Bearer read_only_token")

        overridden = GitHubActivityClient(token="explicit_token")
        self.assertEqual(overridden.token, "explicit_token")

    def test_init_no_token(self):
        """Test initialization without a token."""
        with patch("src.github.api_client.requests.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.headers = {}
            self.mock_config.BLOG_GITHUB_TOKEN = None
            client = GitHubActivityClient(token=None)
            self.assertIsNone(client.token)
            self.assertNotIn("Authorization", client.session.headers)

    @patch("time.sleep")
    @patch("time.time")
    def test_rate_limit_interval(self, mock_time, mock_sleep):
        """Test rate limiting based on minimum request interval."""
        mock_time.return_value = 100.0
        self.client._rate_limit()
        mock_sleep.assert_not_called()
        self.assertEqual(self.client._last_request_time, 100.0)

        mock_time.return_value = 100.05
        self.client._rate_limit()
        mock_sleep.assert_called_once()
        args, _ = mock_sleep.call_args
        self.assertAlmostEqual(args[0], 0.05)

    @patch("time.sleep")
    @patch("time.time")
    def test_rate_limit_header_low(self, mock_time, mock_sleep):
        """Test rate limiting when X-RateLimit-Remaining is low."""
        mock_time.return_value = 1000.0
        mock_response = MagicMock()
        mock_response.headers = {
            "X-RateLimit-Remaining": "5",
            "X-RateLimit-Reset": "1060"
        }
        self.client._rate_limit(mock_response)
        mock_sleep.assert_called_with(61)

    @patch("time.sleep")
    @patch("time.time")
    def test_rate_limit_header_sufficient(self, mock_time, mock_sleep):
        """Test rate limiting when X-RateLimit-Remaining is sufficient."""
        mock_time.return_value = 1000.0
        mock_response = MagicMock()
        mock_response.headers = {
            "X-RateLimit-Remaining": "150",
            "X-RateLimit-Reset": "1060"
        }
        self.client._rate_limit(mock_response)
        mock_sleep.assert_not_called()

    def test_get_success(self):
        """Test successful GET request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        self.mock_session.get.return_value = mock_response

        res = self.client._get("/repos/test")

        self.assertEqual(res, mock_response)
        self.mock_session.get.assert_called_with(
            "https://api.github.com/repos/test",
            params=None,
            timeout=60
        )

    @patch("time.sleep")
    @patch("time.time")
    def test_get_rate_limit_retry(self, mock_time, mock_sleep):
        """Test automatic retry on 403 rate limit error."""
        mock_time.return_value = 1000.0

        # First response is 403 with no remaining limit
        resp1 = MagicMock()
        resp1.status_code = 403
        resp1.headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1100"}

        # Second response is 200
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.headers = {"X-RateLimit-Remaining": "5000"}

        self.mock_session.get.side_effect = [resp1, resp2]

        res = self.client._get("/test")

        self.assertEqual(res, resp2)
        self.assertEqual(self.mock_session.get.call_count, 2)
        mock_sleep.assert_any_call(101) # 1100 - 1000 + 1

    def test_get_error(self):
        """Test that _get raises error for other status codes."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = HTTPErrorClass("404 Client Error")
        self.mock_session.get.return_value = mock_response

        with self.assertRaises(HTTPErrorClass):
            self.client._get("/invalid")

    def test_paginate_multiple_pages(self):
        """Test pagination across multiple pages."""
        # Page 1
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = [{"id": 1}, {"id": 2}]
        resp1.headers = {"Link": '<https://api.github.com/test?page=2>; rel="next"'}

        # Page 2
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = [{"id": 3}]
        resp2.headers = {}

        self.mock_session.get.side_effect = [resp1, resp2]

        results = self.client._paginate("/test")

        self.assertEqual(len(results), 3)
        self.assertEqual([r["id"] for r in results], [1, 2, 3])
        self.assertEqual(self.mock_session.get.call_count, 2)

        # Verify second call used the URL from Link header
        self.mock_session.get.assert_called_with(
            "https://api.github.com/test?page=2",
            params=None,
            timeout=60
        )

    def test_paginate_single_page(self):
        """Test pagination with only one page."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = [{"id": 1}]
        resp.headers = {}
        self.mock_session.get.return_value = resp

        results = self.client._paginate("/test")
        self.assertEqual(len(results), 1)
        self.mock_session.get.assert_called_once()

    def test_get_public_repos(self):
        """Test fetching and filtering public repos."""
        repos_data = [
            {"name": "repo1", "fork": False, "private": False},
            {"name": "repo2", "fork": True, "private": False}, # fork
            {"name": "repo3", "fork": False, "private": True},  # private
            {"name": "repo4", "fork": False, "private": False},
        ]

        with patch.object(self.client, "_paginate", return_value=repos_data) as mock_paginate:
            repos = self.client.get_public_repos()

            self.assertEqual(len(repos), 2)
            self.assertEqual([r["name"] for r in repos], ["repo1", "repo4"])
            mock_paginate.assert_called_with(
                f"/users/test_user/repos",
                params={"type": "owner", "sort": "updated"}
            )

    def test_get_commits(self):
        """Test fetching commits for a repo."""
        commits_data = [{"sha": "abc"}, {"sha": "def"}]

        with patch.object(self.client, "_paginate", return_value=commits_data) as mock_paginate:
            # Test without 'since'
            commits = self.client.get_commits("owner", "repo")
            self.assertEqual(commits, commits_data)
            mock_paginate.assert_called_with(
                "/repos/owner/repo/commits",
                params={"author": "test_user"}
            )

            # Test with 'since'
            commits = self.client.get_commits("owner", "repo", since="2023-01-01T00:00:00Z")
            mock_paginate.assert_called_with(
                "/repos/owner/repo/commits",
                params={"author": "test_user", "since": "2023-01-01T00:00:00Z"}
            )

    def test_owned_discovery_preserves_public_repos_with_private_only_token(self):
        def repo(name, private=False, fork=False, owner="test_user"):
            return {
                "name": name, "full_name": f"{owner}/{name}",
                "owner": {"login": owner}, "private": private, "fork": fork,
            }

        public = repo("public")
        private = repo("private", private=True)
        self.client._get = MagicMock()
        self.client._get.return_value.json.return_value = {"login": "TEST_USER"}
        self.client._paginate = MagicMock(side_effect=[
            [public],
            [private, repo("fork", private=True, fork=True), repo("other", owner="other")],
        ])

        self.assertEqual(self.client.get_owned_repos(), [public, private])
        self.client._get.assert_called_once_with("/user")
        self.client._paginate.assert_any_call(
            "/user/repos",
            params={"visibility": "all", "affiliation": "owner", "sort": "updated"},
        )

    def test_authenticated_visibility_wins_for_duplicate_repos(self):
        public = {
            "full_name": "test_user/repo", "owner": {"login": "test_user"},
            "fork": False, "private": False,
        }
        private = {**public, "private": True}
        self.client._get = MagicMock()
        self.client._get.return_value.json.return_value = {"login": "test_user"}
        self.client._paginate = MagicMock(side_effect=[[public], [private]])
        self.assertEqual(self.client.get_owned_repos(), [private])

    def test_owned_discovery_rejects_wrong_token_owner(self):
        self.client._get = MagicMock()
        self.client._get.return_value.json.return_value = {"login": "other_user"}
        with patch.object(self.client, "_paginate") as paginate:
            with self.assertRaisesRegex(ValueError, "owner must match CODEBASE_USERNAME"):
                self.client.get_owned_repos()
            paginate.assert_not_called()

    def test_owned_discovery_paginates_both_endpoints(self):
        def response(data, next_url=None):
            result = MagicMock()
            result.json.return_value = data
            result.headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
            return result

        def repo(name, private):
            return {"full_name": f"test_user/{name}", "owner": {"login": "test_user"},
                    "private": private, "fork": False}

        self.client._get = MagicMock(side_effect=[
            response({"login": "test_user"}),
            response([repo("public1", False)], "https://api.github.com/public?page=2"),
            response([repo("public2", False)]),
            response([repo("private1", True)], "https://api.github.com/private?page=2"),
            response([repo("private2", True)]),
        ])
        self.assertEqual(len(self.client.get_owned_repos()), 4)
        self.assertEqual(self.client._get.call_count, 5)

    def test_empty_repo_is_skipped_but_permission_errors_propagate(self):
        for status, message in [(409, "Git Repository is empty."), (403, "Forbidden"),
                                (404, "Not Found"), (409, "Other conflict")]:
            with self.subTest(status=status, message=message):
                response = MagicMock()
                response.status_code = status
                response.json.return_value = {"message": message}
                error = HTTPErrorClass(message, response=response)
                with patch.object(self.client, "_paginate", side_effect=error):
                    if message == "Git Repository is empty.":
                        self.assertEqual(self.client.get_commits("test_user", "empty"), [])
                    else:
                        with self.assertRaises(HTTPErrorClass):
                            self.client.get_commits("test_user", "repo")

    def test_get_timeout_enforced(self):
        """Test that requests.get is called with a timeout."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        self.mock_session.get.return_value = mock_response

        self.client._get("/test")

        args, kwargs = self.mock_session.get.call_args
        self.assertEqual(kwargs.get('timeout'), 60)

if __name__ == "__main__":
    unittest.main()
