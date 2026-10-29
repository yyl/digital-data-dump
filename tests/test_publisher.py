import unittest
from datetime import date
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

    def test_get_readwise_analysis_success(self):
        row = {'year_month': '2023-01', 'articles': 10}
        self.mock_readwise_db.fetch_rows.return_value = [row]
        self.assertEqual(self.publisher._get_readwise_analysis('2023-01'), row)
        args, kwargs = self.mock_readwise_db.fetch_rows.call_args
        self.assertEqual(args[1], ('2023-01',))
        self.assertEqual(kwargs['required_tables'], ('analysis',))

    def test_analysis_failures_propagate_for_every_source(self):
        for source in ('readwise', 'foursquare', 'letterboxd', 'overcast', 'strong',
                       'apple_health', 'blog', 'hardcover', 'github', 'oura'):
            with self.subTest(source=source):
                db_name = 'github_activity' if source == 'github' else source
                db = getattr(self, f'mock_{db_name}_db')
                db.fetch_rows.side_effect = RuntimeError('source read failed')
                with self.assertRaisesRegex(RuntimeError, 'source read failed'):
                    getattr(self.publisher, f'_get_{source}_analysis')('2023-01')

    def test_get_foursquare_analysis_success(self):
        row = {'year_month': '2023-01', 'checkins': 5}
        self.mock_foursquare_db.fetch_rows.return_value = [row]
        self.assertEqual(self.publisher._get_foursquare_analysis('2023-01'), row)

    def test_unavailable_analysis_returns_none_for_every_source(self):
        for source in ('readwise', 'foursquare', 'letterboxd', 'overcast', 'strong',
                       'apple_health', 'blog', 'hardcover', 'github', 'oura'):
            with self.subTest(source=source):
                db_name = 'github_activity' if source == 'github' else source
                getattr(self, f'mock_{db_name}_db').fetch_rows.return_value = []
                self.assertIsNone(getattr(self.publisher, f'_get_{source}_analysis')('2023-01'))

    def test_get_overcast_analysis_success(self):
        row = {'year_month': '2023-01', 'episodes_played': 20}
        self.mock_overcast_db.fetch_rows.return_value = [row]
        self.assertEqual(self.publisher._get_overcast_analysis('2023-01'), row)

    def test_get_apple_health_analysis_success(self):
        row = {'year_month': '2023-01', 'workouts': 8,
               'total_duration_seconds': 5400, 'total_calories': 1234.5}
        self.mock_apple_health_db.fetch_rows.return_value = [row]
        self.assertEqual(self.publisher._get_apple_health_analysis('2023-01'), row)

    def test_get_apple_health_activity_breakdown(self):
        rows = [{'activity_type': 'run', 'workouts': 3}]
        self.mock_apple_health_db.fetch_rows.return_value = rows
        self.assertEqual(self.publisher._get_apple_health_activity_breakdown('2023-01'), rows)
        self.assertEqual(
            self.mock_apple_health_db.fetch_rows.call_args.kwargs['required_tables'], ('workouts',)
        )

    def test_get_blog_analysis_success(self):
        row = {'year_month': '2023-01', 'posts': 2, 'total_words': 1800, 'unique_tags': 3}
        self.mock_blog_db.fetch_rows.return_value = [row]
        self.assertEqual(self.publisher._get_blog_analysis('2023-01'), row)

    def test_get_blog_top_tags(self):
        rows = [{'tag': 'python', 'posts': 2}, {'tag': 'hugo', 'posts': 1}]
        self.mock_blog_db.fetch_rows.return_value = rows
        self.assertEqual(self.publisher._get_blog_top_tags('2023-01'), rows)
        self.assertEqual(
            self.mock_blog_db.fetch_rows.call_args.kwargs['required_tables'], ('posts', 'post_tags')
        )

    def test_get_target_year_month_uses_all_sources(self):
        months = {
            'readwise': None, 'foursquare': None, 'letterboxd': '2024-12',
            'overcast': '2025-01', 'strong': '2025-12', 'apple_health': '2025-02',
            'blog': '2025-04', 'hardcover': '2025-03', 'github_activity': '2025-01',
            'oura': '2025-01',
        }
        for source, month in months.items():
            getattr(self, f'mock_{source}_db').fetch_rows.return_value = (
                [{'year_month': month}] if month else []
            )
        self.assertEqual(self.publisher._get_target_year_month(), '2025-12')

    def test_last_month_selects_previous_calendar_month(self):
        cases = [
            # Current-month data must not be required to select last month.
            (date(2026, 11, 1), ["2026-09", "2026-10"], "2026-10"),
            (date(2026, 11, 1), ["2026-10", "2026-11"], "2026-10"),
            (date(2027, 1, 1), ["2026-12"], "2026-12"),
            (date(2028, 3, 1), ["2028-02", "2028-03"], "2028-02"),
            (date(2027, 3, 1), ["2027-02"], "2027-02"),
        ]
        for today, months, expected in cases:
            with self.subTest(today=today, months=months):
                self.publisher._fetch_rows = MagicMock(
                    return_value=[{"year_month": month} for month in months]
                )
                with patch("src.publish.publisher.date") as mock_date:
                    mock_date.today.return_value = today
                    self.assertEqual(
                        self.publisher._get_target_year_month(last_month=True), expected
                    )

    def test_last_month_does_not_publish_another_month_when_target_is_missing(self):
        self.publisher._fetch_rows = MagicMock(
            return_value=[{"year_month": "2026-09"}, {"year_month": "2026-11"}]
        )
        self.publisher._build_github_client = MagicMock()
        with patch("src.publish.publisher.date") as mock_date:
            mock_date.today.return_value = date(2026, 11, 1)
            with self.assertRaisesRegex(ValueError, "previous calendar month \\(2026-10\\)"):
                self.publisher.publish(last_month=True)
        self.publisher._build_github_client.assert_not_called()

    def test_get_new_github_repos_returns_repos(self):
        self.mock_github_activity_db.fetch_rows.return_value = [
            {'repo': 'user/another-new'}, {'repo': 'user/new-project'},
        ]
        self.assertEqual(self.publisher._get_new_github_repos('2025-04'),
                         ['user/another-new', 'user/new-project'])

    def test_get_new_github_repos_unavailable(self):
        self.mock_github_activity_db.fetch_rows.return_value = []
        self.assertEqual(self.publisher._get_new_github_repos('2025-04'), [])

    def test_get_new_github_repos_failures_propagate(self):
        self.mock_github_activity_db.fetch_rows.side_effect = RuntimeError('source read failed')
        with self.assertRaisesRegex(RuntimeError, 'source read failed'):
            self.publisher._get_new_github_repos('2025-04')

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
        mock_config.DATA_REPO_NAME = "digital-data-vault"
        mock_config.DATA_GITHUB_TARGET_BRANCH = "main"
        mock_config.DATA_REPO_POSTS_DIR = "posts"
        mock_config.validate_data_repo_github = MagicMock()

        result = self.publisher.publish()

        mock_config.validate_data_repo_github.assert_called_once_with()
        self.publisher._build_github_client.assert_called_once_with(
            repo_owner="yyl",
            repo_name="digital-data-vault",
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
        mock_config.DATA_REPO_NAME = "digital-data-vault"
        mock_config.DATA_GITHUB_TARGET_BRANCH = "main"
        mock_config.validate_data_repo_github = MagicMock()

        result = self.publisher.backfill()

        self.assertEqual(
            self.publisher.data_generator.generate_data_files.call_args_list,
            [unittest.mock.call(), unittest.mock.call(min_year_month="2027-04")],
        )
        self.publisher._build_github_client.assert_called_once_with(
            repo_owner="yyl",
            repo_name="digital-data-vault",
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
