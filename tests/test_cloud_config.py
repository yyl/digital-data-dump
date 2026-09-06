"""Tests for cloud configuration validation."""

import os
import pytest
from unittest.mock import patch


class TestConfigValidation:
    """Test configuration validation logic."""

    def test_env_or_default_treats_blank_values_as_unset(self):
        """Test blank optional env vars fall back to their defaults."""
        from src.config import _env_or_default

        with patch.dict(os.environ, {"EMPTY_BRANCH": "   "}, clear=False):
            assert _env_or_default("EMPTY_BRANCH", "main") == "main"

        with patch.dict(os.environ, {"SET_BRANCH": " release "}, clear=False):
            assert _env_or_default("SET_BRANCH", "main") == "release"

    def test_validate_readwise_missing_token(self):
        """Test that missing Readwise token raises ValueError."""
        from src.config import Config
        
        with patch.object(Config, 'READWISE_ACCESS_TOKEN', ''):
            with pytest.raises(ValueError, match="READWISE_ACCESS_TOKEN"):
                Config.validate_readwise()

    def test_validate_readwise_with_token(self):
        """Test that Readwise validation passes with token."""
        from src.config import Config
        
        with patch.object(Config, 'READWISE_ACCESS_TOKEN', 'test_token'):
            assert Config.validate_readwise() is True

    def test_validate_foursquare_missing_token(self):
        """Test that missing Foursquare access token raises ValueError."""
        from src.config import Config
        
        with patch.object(Config, 'FOURSQUARE_ACCESS_TOKEN', ''):
            with pytest.raises(ValueError, match="FOURSQUARE_ACCESS_TOKEN"):
                Config.validate_foursquare()

    def test_validate_foursquare_with_token(self):
        """Test that Foursquare validation passes with access token."""
        from src.config import Config
        
        with patch.object(Config, 'FOURSQUARE_ACCESS_TOKEN', 'test_token'):
            assert Config.validate_foursquare() is True

    def test_validate_hardcover_missing_token(self):
        """Test that missing Hardcover token raises ValueError."""
        from src.config import Config

        with patch.object(Config, 'HARDCOVER_ACCESS_TOKEN', ''):
            with pytest.raises(ValueError, match="HARDCOVER_ACCESS_TOKEN"):
                Config.validate_hardcover()

    def test_validate_hardcover_with_token(self):
        """Test that Hardcover validation passes with token."""
        from src.config import Config

        with patch.object(Config, 'HARDCOVER_ACCESS_TOKEN', 'test_token'):
            assert Config.validate_hardcover() is True

    def test_validate_github_missing_token(self):
        """Test that missing GitHub config raises ValueError."""
        from src.config import Config
        
        with patch.object(Config, 'BLOG_GITHUB_TOKEN', ''):
            with patch.object(Config, 'BLOG_REPO_OWNER', 'owner'):
                with patch.object(Config, 'BLOG_REPO_NAME', 'repo'):
                    with pytest.raises(ValueError, match="BLOG_GITHUB_TOKEN"):
                        Config.validate_github()

    def test_validate_github_with_config(self):
        """Test that GitHub validation passes with full config."""
        from src.config import Config
        
        with patch.object(Config, 'BLOG_GITHUB_TOKEN', 'test_token'):
            with patch.object(Config, 'BLOG_REPO_OWNER', 'owner'):
                with patch.object(Config, 'BLOG_REPO_NAME', 'repo'):
                    assert Config.validate_github() is True

    def test_validate_data_repo_github_with_defaults(self):
        """Test that data repo validation passes with the default repo slug."""
        from src.config import Config

        with patch.object(Config, 'DATA_REPO_GITHUB_TOKEN', 'test_token'):
            with patch.object(Config, 'BLOG_GITHUB_TOKEN', ''):
                with patch.object(Config, 'DATA_REPO_OWNER', 'yyl'):
                    with patch.object(Config, 'DATA_REPO_NAME', 'digital-data-vault'):
                        assert Config.validate_data_repo_github() is True

    def test_validate_data_repo_github_accepts_legacy_blog_token(self):
        """Test that data repo validation keeps the previous token name working."""
        from src.config import Config

        with patch.object(Config, 'DATA_REPO_GITHUB_TOKEN', ''):
            with patch.object(Config, 'BLOG_GITHUB_TOKEN', 'test_token'):
                with patch.object(Config, 'DATA_REPO_OWNER', 'yyl'):
                    with patch.object(Config, 'DATA_REPO_NAME', 'digital-data-vault'):
                        assert Config.validate_data_repo_github() is True

    def test_validate_data_repo_github_missing_token(self):
        """Test that missing data repo token raises ValueError."""
        from src.config import Config

        with patch.object(Config, 'DATA_REPO_GITHUB_TOKEN', ''):
            with patch.object(Config, 'BLOG_GITHUB_TOKEN', ''):
                with patch.object(Config, 'DATA_REPO_OWNER', 'yyl'):
                    with patch.object(Config, 'DATA_REPO_NAME', 'digital-data-vault'):
                        with pytest.raises(ValueError, match="DATA_REPO_GITHUB_TOKEN"):
                            Config.validate_data_repo_github()

    def test_validate_data_repo_github_with_blog_fallback(self):
        """Test that data repo validation passes with the backward-compatible blog token."""
        from src.config import Config

        with patch.object(Config, 'DATA_REPO_GITHUB_TOKEN', ''):
            with patch.object(Config, 'DATA_REPO_OWNER', 'yyl'):
                with patch.object(Config, 'DATA_REPO_NAME', 'digital-data-vault'):
                    with patch.object(Config, 'BLOG_GITHUB_TOKEN', 'test_token'):
                        assert Config.validate_data_repo_github() is True

    def test_validate_github_activity_missing_config(self):
        """Test that missing GitHub activity config raises ValueError."""
        from src.config import Config

        # Test missing username
        with patch.object(Config, 'CODEBASE_USERNAME', ''):
            with patch.object(Config, 'BLOG_GITHUB_TOKEN', 'token'):
                with pytest.raises(ValueError, match="CODEBASE_USERNAME"):
                    Config.validate_github_activity()

        # Test missing token
        with patch.object(Config, 'CODEBASE_USERNAME', 'user'):
            with patch.object(Config, 'BLOG_GITHUB_TOKEN', ''):
                with pytest.raises(ValueError, match="BLOG_GITHUB_TOKEN"):
                    Config.validate_github_activity()

    def test_validate_github_activity_with_config(self):
        """Test that GitHub activity validation passes with full config."""
        from src.config import Config

        with patch.object(Config, 'CODEBASE_USERNAME', 'test_user'):
            with patch.object(Config, 'BLOG_GITHUB_TOKEN', 'test_token'):
                assert Config.validate_github_activity() is True

    def test_validate_schwab_with_access_token(self):
        """Test that Schwab validation passes with a direct access token."""
        from src.config import Config

        with patch.object(Config, 'SCHWAB_ACCESS_TOKEN', 'test_token'):
            assert Config.validate_schwab() is True

    def test_validate_schwab_with_oauth_credentials(self):
        """Test that Schwab validation passes with OAuth credentials."""
        from src.config import Config

        with patch.object(Config, 'SCHWAB_ACCESS_TOKEN', ''):
            with patch.object(Config, 'SCHWAB_CLIENT_ID', 'client_id'):
                with patch.object(Config, 'SCHWAB_CLIENT_SECRET', 'client_secret'):
                    assert Config.validate_schwab() is True

    def test_validate_schwab_missing_config(self):
        """Test that missing Schwab configuration raises ValueError."""
        from src.config import Config

        with patch.object(Config, 'SCHWAB_ACCESS_TOKEN', ''):
            with patch.object(Config, 'SCHWAB_CLIENT_ID', ''):
                with patch.object(Config, 'SCHWAB_CLIENT_SECRET', ''):
                    with pytest.raises(ValueError, match="SCHWAB_CLIENT_ID"):
                        Config.validate_schwab()


class TestDatabasePaths:
    """Test database path resolution."""

    def test_database_paths_are_absolute(self):
        """Test that all database paths are absolute."""
        from src.config import Config
        
        assert Config.DATABASE_PATH.is_absolute()
        assert Config.FOURSQUARE_DATABASE_PATH.is_absolute()
        assert Config.LETTERBOXD_DATABASE_PATH.is_absolute()
        assert Config.OVERCAST_DATABASE_PATH.is_absolute()
        assert Config.APPLE_HEALTH_DATABASE_PATH.is_absolute()
        assert Config.BLOG_DATABASE_PATH.is_absolute()
        assert Config.SCHWAB_DATABASE_PATH.is_absolute()

    def test_database_paths_in_data_dir(self):
        """Test that all database paths are in the data directory."""
        from src.config import Config
        
        assert Config.DATABASE_PATH.parent == Config.DATA_DIR
        assert Config.FOURSQUARE_DATABASE_PATH.parent == Config.DATA_DIR
        assert Config.LETTERBOXD_DATABASE_PATH.parent == Config.DATA_DIR
        assert Config.OVERCAST_DATABASE_PATH.parent == Config.DATA_DIR
        assert Config.APPLE_HEALTH_DATABASE_PATH.parent == Config.DATA_DIR
        assert Config.BLOG_DATABASE_PATH.parent == Config.DATA_DIR
        assert Config.SCHWAB_DATABASE_PATH.parent == Config.DATA_DIR

    def test_blog_posts_index_url_has_default(self):
        """Test that blog posts JSON export URL has a default."""
        from src.config import Config

        assert Config.BLOG_POSTS_INDEX_URL == "https://www.mildlyjournaling.com/posts/index.json"

    def test_ensure_data_dir_creates_directory(self, tmp_path):
        """Test that ensure_data_dir creates the data directory."""
        from src.config import Config
        
        # Temporarily override DATA_DIR
        original_data_dir = Config.DATA_DIR
        Config.DATA_DIR = tmp_path / "test_data"
        
        try:
            assert not Config.DATA_DIR.exists()
            Config.ensure_data_dir()
            assert Config.DATA_DIR.exists()
        finally:
            Config.DATA_DIR = original_data_dir
