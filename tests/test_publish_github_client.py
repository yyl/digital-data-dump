import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.publish.github_client import GitHubClient, GitHubClientError


class FakeGithubException(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class TestPublishGitHubClient(unittest.TestCase):
    @patch("src.publish.github_client.Github")
    def test_binary_assets_and_markdown_are_committed_in_the_same_tree(self, mock_github):
        client = GitHubClient("token", "owner", "repo")
        client.repo.create_git_blob.return_value.sha = "png-blob-sha"
        with patch.dict("sys.modules", {"github": SimpleNamespace(InputGitTreeElement=SimpleNamespace)}):
            result = client.create_or_update_files(
                {"posts/report.md": "![Map](assets/map.png)", "posts/assets/map.png": b"\x89PNG\r\n"},
                "Publish report and map",
            )
        client.repo.create_git_blob.assert_called_once_with("iVBORw0K", "base64")
        elements = client.repo.create_git_tree.call_args.args[0]
        assert elements[0].content == "![Map](assets/map.png)"
        assert elements[1].sha == "png-blob-sha"
        assert result["file_paths"] == ["posts/report.md", "posts/assets/map.png"]

    @patch("src.publish.github_client.Github")
    @patch("src.publish.github_client.Auth")
    def test_init_uses_auth_token(self, mock_auth, mock_github):
        mock_auth.Token.return_value = "auth-token"
        mock_repo = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo

        client = GitHubClient("token", "owner", "repo")

        mock_auth.Token.assert_called_once_with("token")
        mock_github.assert_called_once_with(auth="auth-token")
        self.assertEqual(client.repo, mock_repo)

    @patch("src.publish.github_client.time.sleep")
    @patch("src.publish.github_client.Github")
    @patch("src.publish.github_client.Auth")
    def test_retries_non_fast_forward(self, mock_auth, mock_github, mock_sleep):
        mock_auth.Token.return_value = "auth-token"
        mock_repo = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo

        client = GitHubClient("token", "owner", "repo")
        expected = {
            "sha": "abc123",
            "url": "https://example.com/commit/abc123",
            "message": "msg",
            "file_paths": ["file.md"],
        }

        non_fast_forward = FakeGithubException(422, "Update is not a fast forward")

        attempts = {"count": 0}

        def side_effect(*args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise non_fast_forward
            return expected

        with patch("src.publish.github_client.GithubException", FakeGithubException):
            with patch.object(
                client,
                "_create_or_update_files_once",
                side_effect=side_effect,
            ) as mock_once:
                result = client.create_or_update_files({"file.md": "content"}, "msg")

        self.assertEqual(result, expected)
        self.assertEqual(mock_once.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("src.publish.github_client.time.sleep")
    @patch("src.publish.github_client.Github")
    @patch("src.publish.github_client.Auth")
    def test_raises_after_retry_budget_exhausted(self, mock_auth, mock_github, mock_sleep):
        mock_auth.Token.return_value = "auth-token"
        mock_repo = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo

        client = GitHubClient("token", "owner", "repo")
        non_fast_forward = FakeGithubException(422, "Update is not a fast forward")

        def side_effect(*args, **kwargs):
            raise non_fast_forward

        with patch("src.publish.github_client.GithubException", FakeGithubException):
            with patch.object(
                client,
                "_create_or_update_files_once",
                side_effect=side_effect,
            ):
                with self.assertRaises(GitHubClientError):
                    client.create_or_update_files({"file.md": "content"}, "msg")

        self.assertEqual(mock_sleep.call_count, client.MAX_NON_FAST_FORWARD_RETRIES)

    @patch("src.publish.github_client.Github")
    @patch("src.publish.github_client.Auth")
    def test_non_retryable_github_error_raises_immediately(self, mock_auth, mock_github):
        mock_auth.Token.return_value = "auth-token"
        mock_repo = MagicMock()
        mock_github.return_value.get_repo.return_value = mock_repo

        client = GitHubClient("token", "owner", "repo")
        error = FakeGithubException(500, "Internal Server Error")

        with patch("src.publish.github_client.GithubException", FakeGithubException):
            with patch.object(client, "_create_or_update_files_once", side_effect=error) as mock_once:
                with self.assertRaises(GitHubClientError):
                    client.create_or_update_files({"file.md": "content"}, "msg")

        self.assertEqual(mock_once.call_count, 1)

    @patch("src.publish.github_client.Github")
    @patch("src.publish.github_client.Auth")
    def test_missing_target_branch_error_names_branch_and_repo(self, mock_auth, mock_github):
        mock_auth.Token.return_value = "auth-token"
        mock_repo = MagicMock()
        mock_repo.get_git_ref.side_effect = FakeGithubException(404, "Not Found")
        mock_github.return_value.get_repo.return_value = mock_repo

        client = GitHubClient("token", "owner", "repo", target_branch="missing")

        with patch("src.publish.github_client.GithubException", FakeGithubException):
            with self.assertRaisesRegex(
                GitHubClientError,
                "Target branch 'missing' was not found in owner/repo",
            ):
                client.create_or_update_files({"file.md": "content"}, "msg")
