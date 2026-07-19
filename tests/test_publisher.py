import unittest
from unittest.mock import MagicMock, patch
from src.publish.publisher import Publisher
from src.database import BaseDatabase

class TestPublisher(unittest.TestCase):
    def setUp(self):
        # Create mock databases
        self.mock_readwise_db = MagicMock(spec=BaseDatabase)
        self.mock_foursquare_db = MagicMock(spec=BaseDatabase)
        self.mock_letterboxd_db = MagicMock(spec=BaseDatabase)
        self.mock_overcast_db = MagicMock(spec=BaseDatabase)
        self.mock_strong_db = MagicMock(spec=BaseDatabase)
        self.mock_apple_health_db = MagicMock(spec=BaseDatabase)
        self.mock_blog_db = MagicMock(spec=BaseDatabase)
        self.mock_hardcover_db = MagicMock(spec=BaseDatabase)
        self.mock_github_activity_db = MagicMock(spec=BaseDatabase)
        self.mock_oura_db = MagicMock(spec=BaseDatabase)

        # Initialize publisher with mocks
        self.publisher = Publisher(
            readwise_db=self.mock_readwise_db,
            foursquare_db=self.mock_foursquare_db,
            letterboxd_db=self.mock_letterboxd_db,
            overcast_db=self.mock_overcast_db,
            strong_db=self.mock_strong_db,
            apple_health_db=self.mock_apple_health_db,
            blog_db=self.mock_blog_db,
            hardcover_db=self.mock_hardcover_db,
            github_activity_db=self.mock_github_activity_db,
            oura_db=self.mock_oura_db
        )

    # Test 1: No exists check, No suppression (Readwise style)
    def test_get_readwise_analysis_success(self):
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_readwise_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {'year_month': '2023-01', 'articles': 10}

        result = self.publisher._get_readwise_analysis('2023-01')
        self.assertEqual(result, {'year_month': '2023-01', 'articles': 10})

    def test_get_readwise_analysis_exception(self):
        # Should propagate exception
        self.mock_readwise_db.get_connection.side_effect = Exception("DB Error")
        with self.assertRaises(Exception):
            self.publisher._get_readwise_analysis('2023-01')

    # Test 2: No exists check, With suppression (Foursquare style)
    def test_get_foursquare_analysis_success(self):
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_foursquare_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {'year_month': '2023-01', 'checkins': 5}

        result = self.publisher._get_foursquare_analysis('2023-01')
        self.assertEqual(result, {'year_month': '2023-01', 'checkins': 5})

    def test_get_foursquare_analysis_exception(self):
        # Should suppress exception and return None
        self.mock_foursquare_db.get_connection.side_effect = Exception("DB Error")
        result = self.publisher._get_foursquare_analysis('2023-01')
        self.assertIsNone(result)

    # Test 3: With exists check, With suppression (Overcast style)
    def test_get_overcast_analysis_not_exists(self):
        self.mock_overcast_db.exists.return_value = False
        result = self.publisher._get_overcast_analysis('2023-01')
        self.assertIsNone(result)
        # Should not even try to connect
        self.mock_overcast_db.get_connection.assert_not_called()

    def test_get_overcast_analysis_exists_success(self):
        self.mock_overcast_db.exists.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_overcast_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {'year_month': '2023-01', 'episodes_played': 20}

        result = self.publisher._get_overcast_analysis('2023-01')
        self.assertEqual(result, {'year_month': '2023-01', 'episodes_played': 20})

    def test_get_overcast_analysis_exists_exception(self):
        self.mock_overcast_db.exists.return_value = True
        self.mock_overcast_db.get_connection.side_effect = Exception("DB Error")

        result = self.publisher._get_overcast_analysis('2023-01')
        self.assertIsNone(result)

    def test_get_apple_health_analysis_exists_success(self):
        self.mock_apple_health_db.exists.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_apple_health_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {'year_month': '2023-01', 'workouts': 8, 'total_duration_seconds': 5400, 'total_calories': 1234.5}

        result = self.publisher._get_apple_health_analysis('2023-01')
        self.assertEqual(result, {'year_month': '2023-01', 'workouts': 8, 'total_duration_seconds': 5400, 'total_calories': 1234.5})

    def test_get_apple_health_activity_breakdown(self):
        self.mock_apple_health_db.exists.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_apple_health_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {'activity_type': 'run', 'workouts': 3},
        ]

        result = self.publisher._get_apple_health_activity_breakdown('2023-01')
        self.assertEqual(result, [
            {'activity_type': 'run', 'workouts': 3},
        ])

    def test_get_blog_analysis_exists_success(self):
        self.mock_blog_db.exists.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_blog_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {'year_month': '2023-01', 'posts': 2, 'total_words': 1800, 'unique_tags': 3}

        result = self.publisher._get_blog_analysis('2023-01')
        self.assertEqual(result, {'year_month': '2023-01', 'posts': 2, 'total_words': 1800, 'unique_tags': 3})

    def test_get_blog_top_tags(self):
        self.mock_blog_db.exists.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_blog_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {'tag': 'python', 'posts': 2},
            {'tag': 'hugo', 'posts': 1},
        ]

        result = self.publisher._get_blog_top_tags('2023-01')
        self.assertEqual(result, [
            {'tag': 'python', 'posts': 2},
            {'tag': 'hugo', 'posts': 1},
        ])

    def test_get_target_year_month_uses_all_sources(self):
        self.mock_readwise_db.exists.return_value = True
        self.mock_foursquare_db.exists.return_value = True
        self.mock_letterboxd_db.exists.return_value = True
        self.mock_overcast_db.exists.return_value = True
        self.mock_strong_db.exists.return_value = True
        self.mock_apple_health_db.exists.return_value = True
        self.mock_blog_db.exists.return_value = True
        self.mock_hardcover_db.exists.return_value = True
        self.mock_github_activity_db.exists.return_value = True
        self.mock_oura_db.exists.return_value = True

        self.mock_readwise_db.get_connection.side_effect = Exception("readwise missing")
        self.mock_foursquare_db.get_connection.side_effect = Exception("foursquare missing")

        def make_conn(year_month):
            conn = MagicMock()
            cursor = MagicMock()
            conn.cursor.return_value = cursor
            cursor.fetchall.return_value = [] if year_month is None else [{"year_month": year_month}]
            manager = MagicMock()
            manager.__enter__.return_value = conn
            manager.__exit__.return_value = None
            return manager

        self.mock_letterboxd_db.get_connection.return_value = make_conn("2024-12")
        self.mock_overcast_db.get_connection.return_value = make_conn("2025-01")
        self.mock_strong_db.get_connection.return_value = make_conn("2025-12")
        self.mock_apple_health_db.get_connection.return_value = make_conn("2025-02")
        self.mock_blog_db.get_connection.return_value = make_conn("2025-04")
        self.mock_hardcover_db.get_connection.return_value = make_conn("2025-03")
        self.mock_github_activity_db.get_connection.return_value = make_conn("2025-01")
        self.mock_oura_db.get_connection.return_value = make_conn("2025-01")

        result = self.publisher._get_target_year_month()

        self.assertEqual(result, "2025-04")
        
        # Test last_month flag
        result_last = self.publisher._get_target_year_month(last_month=True)
        self.assertEqual(result_last, "2025-03")

    def test_get_new_github_repos_returns_repos(self):
        self.mock_github_activity_db.exists.return_value = True
        conn = MagicMock()
        cursor = MagicMock()
        self.mock_github_activity_db.get_connection.return_value.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {'repo': 'user/another-new'},
            {'repo': 'user/new-project'},
        ]

        result = self.publisher._get_new_github_repos('2025-04')
        self.assertEqual(result, ['user/another-new', 'user/new-project'])

    def test_get_new_github_repos_db_not_exists(self):
        self.mock_github_activity_db.exists.return_value = False

        result = self.publisher._get_new_github_repos('2025-04')
        self.assertEqual(result, [])
        self.mock_github_activity_db.get_connection.assert_not_called()

    def test_get_new_github_repos_exception_suppressed(self):
        self.mock_github_activity_db.exists.return_value = True
        self.mock_github_activity_db.get_connection.side_effect = Exception("DB Error")

        result = self.publisher._get_new_github_repos('2025-04')
        self.assertEqual(result, [])

    @patch("src.publish.publisher.Config")
    def test_publish_commits_report_post_to_data_repo(self, mock_config):
        self.publisher._get_target_year_month = MagicMock(return_value="2026-04")
        self.publisher.generate_markdown = MagicMock(return_value="# Report\n")

        data_repo_client = MagicMock()
        data_repo_client.create_or_update_files.return_value = {
            "sha": "data-sha",
            "url": "https://example.com/data-post",
            "message": "feat: Add monthly report draft for 04/2026",
            "file_paths": ["posts/wrap-up-04-2026.md"],
        }
        self.publisher._build_github_client = MagicMock(return_value=data_repo_client)

        mock_config.DATA_REPO_OWNER = "yyl"
        mock_config.DATA_REPO_NAME = "digital-footprint-data"
        mock_config.DATA_GITHUB_TARGET_BRANCH = "main"
        mock_config.DATA_REPO_POSTS_DIR = "posts"
        mock_config.validate_data_repo_github = MagicMock()

        result = self.publisher.publish()

        mock_config.validate_data_repo_github.assert_called_once_with()
        self.publisher._build_github_client.assert_called_once_with(
            repo_owner="yyl",
            repo_name="digital-footprint-data",
            target_branch="main",
        )
        data_repo_client.create_or_update_files.assert_called_once_with(
            files={"posts/wrap-up-04-2026.md": "# Report\n"},
            commit_message="feat: Add monthly report draft for 04/2026",
        )
        self.assertEqual(result["url"], "https://example.com/data-post")

    @patch.object(Publisher, "_one_year_lookback_year_month", return_value="2027-04")
    @patch("src.publish.publisher.Config")
    def test_backfill_commits_full_history_to_data_repo_and_lookback_history_to_blog_repo(
        self,
        mock_config,
        mock_cutoff,
    ):
        self.publisher.data_generator = MagicMock()
        full_history_files = {"data/activity/reading.yaml": "# full\n- month: \"2028-01\"\n"}
        capped_files = {"data/activity/reading.yaml": "# capped\n- month: \"2027-04\"\n"}
        self.publisher.data_generator.generate_data_files.side_effect = [
            full_history_files,
            capped_files,
        ]

        data_repo_client = MagicMock()
        data_repo_client.create_or_update_files.return_value = {
            "sha": "data-sha",
            "url": "https://example.com/data",
            "message": "data: Update activity data files",
            "file_paths": list(full_history_files.keys()),
        }
        blog_repo_client = MagicMock()
        blog_repo_client.create_or_update_files.return_value = {
            "sha": "blog-sha",
            "url": "https://example.com/blog",
            "message": "data: Update activity data files since 2027-04",
            "file_paths": list(capped_files.keys()),
        }
        self.publisher.github_client = blog_repo_client
        self.publisher._build_github_client = MagicMock(return_value=data_repo_client)

        mock_config.DATA_REPO_OWNER = "yyl"
        mock_config.DATA_REPO_NAME = "digital-footprint-data"
        mock_config.DATA_GITHUB_TARGET_BRANCH = "main"
        mock_config.validate_data_repo_github = MagicMock()

        result = self.publisher.backfill()

        self.assertEqual(
            self.publisher.data_generator.generate_data_files.call_args_list,
            [unittest.mock.call(), unittest.mock.call(min_year_month="2027-04")],
        )
        self.publisher._build_github_client.assert_called_once_with(
            repo_owner="yyl",
            repo_name="digital-footprint-data",
            target_branch="main",
        )
        data_repo_client.create_or_update_files.assert_called_once_with(
            files=full_history_files,
            commit_message="data: Update activity data files",
        )
        blog_repo_client.create_or_update_files.assert_called_once_with(
            files=capped_files,
            commit_message="data: Update activity data files since 2027-04",
        )
        self.assertEqual(result["data_repo"]["url"], "https://example.com/data")
        self.assertEqual(result["blog_repo"]["url"], "https://example.com/blog")
        self.assertEqual(result["blog_start_year_month"], "2027-04")
