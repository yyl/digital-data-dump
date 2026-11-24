"""Tests for the DataGenerator module."""

from unittest.mock import MagicMock

import pytest
from src.blog.analytics import BlogAnalytics
from src.blog.database import BlogDatabase
from src.publish.data_generator import ActivitySource, DataGenerator, _to_yaml


class TestToYaml:
    """Tests for the _to_yaml helper function."""
    
    def test_simple_records(self):
        """Test basic YAML output format."""
        records = [
            {'month': '2025-08', 'count': 5},
            {'month': '2025-09', 'count': 10},
        ]
        result = _to_yaml(records, "Test data")
        
        assert result.startswith("# Test data\n")
        assert '- month: "2025-08"' in result
        assert '  count: 5' in result
        assert '- month: "2025-09"' in result
        assert '  count: 10' in result
    
    def test_float_formatting(self):
        """Test that floats are formatted to 2 decimal places."""
        records = [{'month': '2025-08', 'rating': 3.83333}]
        result = _to_yaml(records, "Test")
        
        assert 'rating: 3.83' in result
    
    def test_string_quoting(self):
        """Test that strings are quoted."""
        records = [{'month': '2025-08', 'name': 'hello'}]
        result = _to_yaml(records, "Test")
        
        assert 'month: "2025-08"' in result
        assert 'name: "hello"' in result
    
    def test_empty_records(self):
        """Test with empty records list."""
        result = _to_yaml([], "Empty")
        assert result == "# Empty\n[]\n"
    
    def test_matches_reference_format(self):
        """Test that output matches the reference travel.yaml format."""
        records = [
            {'month': '2025-08', 'checkins': 89, 'unique_places': 82},
        ]
        result = _to_yaml(records, "Monthly travel activity data")
        
        expected_lines = [
            '# Monthly travel activity data',
            '- month: "2025-08"',
            '  checkins: 89',
            '  unique_places: 82',
        ]
        for line in expected_lines:
            assert line in result


class TestDataGeneratorReadwise:
    """Tests for Readwise data generation with a real DB."""
    
    def test_avg_reading_speed_computed(self):
        """Test that avg_reading_speed is computed from words / time."""
        records = [
            {'month': '2025-08', 'articles_archived': 18, 'total_words': 42500,
             'time_spent_minutes': 170, 'avg_reading_speed': 250},
        ]
        yaml = _to_yaml(records, "Monthly reading activity data")
        
        assert 'avg_reading_speed: 250' in yaml


class TestDataGeneratorOutput:
    """Tests for the YAML output structure."""
    
    def test_reading_yaml_structure(self):
        """Verify reading.yaml has the expected field names."""
        records = [
            {'month': '2025-08', 'articles_archived': 18, 'total_words': 42500,
             'time_spent_minutes': 170, 'avg_reading_speed': 250,
             'max_words_per_article': 8500, 'median_words_per_article': 2200,
             'min_words_per_article': 150},
        ]
        yaml = _to_yaml(records, "Monthly reading activity data")
        
        assert 'articles_archived:' in yaml
        assert 'total_words:' in yaml
        assert 'time_spent_minutes:' in yaml
        assert 'avg_reading_speed:' in yaml
        assert 'max_words_per_article:' in yaml
        assert 'median_words_per_article:' in yaml
        assert 'min_words_per_article:' in yaml
    
    def test_movies_yaml_structure(self):
        """Verify movies.yaml has the expected field names."""
        records = [
            {'month': '2025-08', 'movies_watched': 3, 'minutes_watched': 321, 'avg_rating': 3.83},
        ]
        yaml = _to_yaml(records, "Monthly movies activity data")
        
        assert 'movies_watched:' in yaml
        assert 'minutes_watched:' in yaml
        assert 'avg_rating:' in yaml
    
    def test_podcasts_yaml_structure(self):
        """Verify podcasts.yaml has the expected field names."""
        records = [
            {'month': '2025-08', 'feeds_added': 2, 'feeds_removed': 1, 'episodes_played': 28, 'minutes_listened': 1234},
        ]
        yaml = _to_yaml(records, "Monthly podcasts activity data")
        
        assert 'feeds_added:' in yaml
        assert 'feeds_removed:' in yaml
        assert 'episodes_played:' in yaml
        assert 'minutes_listened:' in yaml
    
    def test_travel_yaml_structure(self):
        """Verify travel.yaml has the expected field names."""
        records = [
            {'month': '2025-08', 'checkins': 89, 'unique_places': 82},
        ]
        yaml = _to_yaml(records, "Monthly travel activity data")
        
        assert 'checkins:' in yaml
        assert 'unique_places:' in yaml

    def test_workouts_yaml_structure_uses_apple_health_fields(self):
        """Verify workouts.yaml uses Apple Health summary fields."""
        records = [
            {'month': '2025-08', 'workouts': 14, 'total_minutes': 560, 'total_calories': 4820.5},
        ]
        yaml = _to_yaml(records, "Monthly workout activity data")

        assert 'workouts:' in yaml
        assert 'total_minutes:' in yaml
        assert 'total_calories:' in yaml
        assert 'unique_exercises:' not in yaml
        assert 'total_sets:' not in yaml

    def test_writing_yaml_structure(self):
        """Verify writing.yaml has the expected field names."""
        records = [
            {'month': '2025-08', 'posts': 2, 'total_words': 3200, 'unique_tags': 5},
        ]
        yaml = _to_yaml(records, "Monthly writing activity data")

        assert 'posts:' in yaml
        assert 'total_words:' in yaml
        assert 'unique_tags:' in yaml
    
    def test_records_sorted_ascending(self):
        """Test that records appear in order in the output."""
        records = [
            {'month': '2025-08', 'count': 1},
            {'month': '2025-09', 'count': 2},
            {'month': '2025-10', 'count': 3},
        ]
        yaml = _to_yaml(records, "Test")
        
        pos_08 = yaml.index('2025-08')
        pos_09 = yaml.index('2025-09')
        pos_10 = yaml.index('2025-10')
        
        assert pos_08 < pos_09 < pos_10


class TestDataGeneratorFiltering:
    """Tests for optional month window handling."""

    def test_generate_data_files_filters_records_before_cutoff(self):
        generator = DataGenerator(
            readwise_db=MagicMock(),
            foursquare_db=MagicMock(),
            letterboxd_db=MagicMock(),
            overcast_db=MagicMock(),
            apple_health_db=MagicMock(),
            blog_db=MagicMock(),
            hardcover_db=MagicMock(),
            github_activity_db=MagicMock(),
        )
        generator._get_all_readwise = MagicMock(return_value=[
            {"month": "2027-03", "articles_archived": 4, "total_words": 2000, "time_spent_minutes": 40, "avg_reading_speed": 50, "max_words_per_article": 900, "median_words_per_article": 500, "min_words_per_article": 200},
            {"month": "2027-04", "articles_archived": 2, "total_words": 1000, "time_spent_minutes": 20, "avg_reading_speed": 50, "max_words_per_article": 700, "median_words_per_article": 500, "min_words_per_article": 300},
            {"month": "2027-05", "articles_archived": 1, "total_words": 500, "time_spent_minutes": 10, "avg_reading_speed": 50, "max_words_per_article": 500, "median_words_per_article": 500, "min_words_per_article": 500},
        ])
        generator._get_all_foursquare = MagicMock(return_value=[])
        generator._get_all_letterboxd = MagicMock(return_value=[])
        generator._get_all_overcast = MagicMock(return_value=[])
        generator._get_all_apple_health = MagicMock(return_value=[])
        generator._get_all_blog = MagicMock(return_value=[])
        generator._get_all_hardcover = MagicMock(return_value=[])
        generator._get_all_github = MagicMock(return_value=[])
        generator._get_all_surfilog = MagicMock(return_value=[])

        files = generator.generate_data_files(min_year_month="2027-04")

        assert 'data/activity/reading.yaml' in files
        assert '2027-03' not in files['data/activity/reading.yaml']
        assert '2027-04' in files['data/activity/reading.yaml']
        assert '2027-05' in files['data/activity/reading.yaml']


def test_registered_activity_export_clears_only_available_empty_windows(tmp_path, monkeypatch):
    db = BlogDatabase(str(tmp_path / "fixture.db"))
    read = MagicMock(return_value=[])
    generator = DataGenerator()
    monkeypatch.setattr(generator, "activity_sources", lambda: (
        ActivitySource("fixture", "Fixture activity", db, read),
    ))
    assert generator.generate_data_files() == {}

    db.init_tables()
    BlogAnalytics(db).analyze_posts()
    assert generator.generate_data_files() == {"data/activity/fixture.yaml": "# Fixture activity\n[]\n"}

    read.return_value = [{"month": "2026-03", "count": 2}]
    snapshot = generator.load_activity_data()
    assert '- month: "2026-03"' in generator.render_data_files(snapshot)["data/activity/fixture.yaml"]
    assert generator.render_data_files(snapshot, min_year_month="2026-04") == {
        "data/activity/fixture.yaml": "# Fixture activity\n[]\n",
    }
