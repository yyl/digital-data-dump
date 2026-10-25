
import pytest
from unittest.mock import MagicMock, patch
from src.github.sync import GitHubSyncManager

class TestGitHubSyncManager:
    """Tests for GitHubSyncManager."""

    @pytest.fixture
    def mock_db(self):
        """Mock GitHubDatabase."""
        db = MagicMock()
        db.get_existing_shas.return_value = set()
        return db

    @pytest.fixture
    def mock_api(self):
        """Mock GitHubActivityClient."""
        return MagicMock()

    @pytest.fixture
    def manager(self, mock_db, mock_api):
        """Initialize GitHubSyncManager with mocks."""
        return GitHubSyncManager(db=mock_db, api=mock_api)

    def test_init_defaults(self):
        """Test initialization without arguments."""
        with patch('src.github.sync.GitHubDatabase') as mock_db_cls, \
             patch('src.github.sync.GitHubActivityClient') as mock_api_cls:
            manager = GitHubSyncManager()
            assert manager.db == mock_db_cls.return_value
            assert manager.api == mock_api_cls.return_value

    def test_sync_no_repos(self, manager, mock_api, mock_db):
        """Test sync when no repositories are returned."""
        # Setup
        mock_api.get_owned_repos.return_value = []

        # Execute
        stats = manager.sync()

        # Verify
        mock_db.init_tables.assert_called_once()
        mock_api.get_owned_repos.assert_called_once()
        assert stats == {"commits": 0, "repos": 0}

    def test_sync_repo_no_commits(self, manager, mock_api, mock_db):
        """Test sync when a repo has no new commits."""
        # Setup
        mock_api.get_owned_repos.return_value = [{
            "full_name": "user/repo",
            "owner": {"login": "user"},
            "name": "repo", "private": False
        }]
        mock_db.get_latest_commit_date.return_value = None
        mock_api.get_commits.return_value = []

        # Execute
        stats = manager.sync()

        # Verify
        mock_api.get_commits.assert_called_with("user", "repo", since=None)
        assert stats == {"commits": 0, "repos": 0}

    def test_sync_incremental_logic(self, manager, mock_api, mock_db):
        """Test incremental sync logic (since parameter)."""
        # Setup
        mock_api.get_owned_repos.return_value = [{
            "full_name": "user/repo",
            "owner": {"login": "user"},
            "name": "repo", "private": False
        }]
        # Previous commit was at 10:00:00
        mock_db.get_latest_commit_date.return_value = "2023-01-01T10:00:00Z"

        mock_api.get_commits.return_value = [] # No new commits

        # Execute
        manager.sync()

        # Verify since parameter uses the inclusive high-water mark
        mock_api.get_commits.assert_called_with(
            "user", "repo",
            since="2023-01-01T10:00:00Z"
        )

    def test_sync_filters_existing_shas_from_inclusive_fetch(self, manager, mock_api, mock_db):
        """Test that inclusive fetches do not re-upsert commits already stored."""
        mock_api.get_owned_repos.return_value = [{
            "full_name": "user/repo",
            "owner": {"login": "user"},
            "name": "repo", "private": False
        }]
        mock_db.get_latest_commit_date.return_value = "2023-01-01T10:00:00Z"
        mock_db.get_existing_shas.return_value = {"sha-existing"}
        mock_api.get_commits.return_value = [
            {
                "sha": "sha-existing",
                "commit": {
                    "author": {"date": "2023-01-01T10:00:00Z"},
                    "message": "feat: already synced"
                }
            },
            {
                "sha": "sha-new",
                "commit": {
                    "author": {"date": "2023-01-01T10:00:00Z"},
                    "message": "fix: newly discovered sibling commit"
                }
            },
        ]

        stats = manager.sync()

        assert stats == {"commits": 1, "repos": 1}
        mock_db.upsert_commits.assert_called_once_with([
            {
                "sha": "sha-new",
                "repo": "user/repo",
                "message": "fix: newly discovered sibling commit",
                "author_date": "2023-01-01T10:00:00Z",
                "date_month": "2023-01", "is_private": False
            }
        ])

    def test_sync_process_commits(self, manager, mock_api, mock_db):
        """Test that commits are correctly processed and upserted."""
        # Setup
        mock_api.get_owned_repos.return_value = [{
            "full_name": "user/repo",
            "owner": {"login": "user"},
            "name": "repo", "private": False
        }]
        mock_db.get_latest_commit_date.return_value = None

        mock_api.get_commits.return_value = [
            {
                "sha": "sha1",
                "commit": {
                    "author": {"date": "2023-01-02T12:00:00Z"},
                    "message": "feat: new feature\n\nDetails here"
                }
            },
            {
                "sha": "sha2", # Should be processed
                "commit": {
                    "author": {"date": "2023-01-03T12:00:00Z"},
                    "message": "fix: bug fix"
                }
            },
            {
                "sha": "", # Invalid, no sha
                "commit": {}
            }
        ]

        # Execute
        stats = manager.sync()

        # Verify
        assert stats == {"commits": 2, "repos": 1}
        assert mock_db.upsert_commits.call_count == 1

        # Check call args
        expected_commits = [
            {
                "sha": "sha1",
                "repo": "user/repo",
                "message": "feat: new feature", # First line
                "author_date": "2023-01-02T12:00:00Z",
                "date_month": "2023-01", "is_private": False
            },
            {
                "sha": "sha2",
                "repo": "user/repo",
                "message": "fix: bug fix", # First line
                "author_date": "2023-01-03T12:00:00Z",
                "date_month": "2023-01", "is_private": False
            }
        ]
        mock_db.upsert_commits.assert_called_with(expected_commits)

    def test_get_status_not_initialized(self, manager, mock_db):
        """Test get_status when database does not exist."""
        mock_db.exists.return_value = False
        status = manager.get_status()
        assert status == {"status": "not initialized"}

    def test_get_status_initialized(self, manager, mock_db):
        """Test get_status when database exists."""
        mock_db.exists.return_value = True
        mock_db.get_stats.return_value = {"commits": 10, "repos": 2}
        status = manager.get_status()
        assert status == {"commits": 10, "repos": 2}
