"""Generator for Hugo-compatible YAML data files from analysis databases."""

from datetime import date
import logging
from typing import Dict, List, Optional, Any

from ..readwise.database import ReadwiseDatabase
from ..foursquare.database import FoursquareDatabase
from ..letterboxd.database import LetterboxdDatabase
from ..overcast.database import OvercastDatabase
from ..strong.database import StrongDatabase
from ..apple_health.database import AppleHealthDatabase
from ..blog.database import BlogDatabase
from ..hardcover.database import HardcoverDatabase
from ..github.database import GitHubDatabase
from ..github.models import VISIBILITY_METRICS
from ..oura.database import OuraDatabase

logger = logging.getLogger(__name__)


def _year_month_to_date(year_month: str) -> date:
    """Convert a YYYY-MM string to the first day of that month."""
    year, month = year_month.split("-")
    return date(int(year), int(month), 1)


def _to_yaml(records: List[Dict[str, Any]], comment: str) -> str:
    """Serialize a list of flat dicts to YAML list format.
    
    Produces output like:
        # comment
        - month: "2025-08"
          key: value
    
    Args:
        records: List of dictionaries to serialize.
        comment: Comment line at the top of the file.
    
    Returns:
        YAML-formatted string.
    """
    lines = [f"# {comment}"]
    
    for record in records:
        first = True
        for key, value in record.items():
            prefix = "- " if first else "  "
            first = False
            
            # Format values
            if isinstance(value, str):
                formatted = f'"{value}"'
            elif isinstance(value, float):
                formatted = f"{value:.2f}"
            else:
                formatted = str(value)
            
            lines.append(f"{prefix}{key}: {formatted}")
        lines.append("")
    
    return "\n".join(lines) + "\n"


class DataGenerator:
    """Generates Hugo data files from analysis databases."""
    
    def __init__(
        self,
        readwise_db: Optional[ReadwiseDatabase] = None,
        foursquare_db: Optional[FoursquareDatabase] = None,
        letterboxd_db: Optional[LetterboxdDatabase] = None,
        overcast_db: Optional[OvercastDatabase] = None,
        strong_db: Optional[StrongDatabase] = None,
        apple_health_db: Optional[AppleHealthDatabase] = None,
        blog_db: Optional[BlogDatabase] = None,
        hardcover_db: Optional[HardcoverDatabase] = None,
        github_activity_db: Optional[GitHubDatabase] = None,
        oura_db: Optional[OuraDatabase] = None,
    ):
        """Initialize data generator.
        
        Args:
            readwise_db: Readwise database manager.
            foursquare_db: Foursquare database manager.
            letterboxd_db: Letterboxd database manager.
            overcast_db: Overcast database manager.
            strong_db: Strong database manager.
            apple_health_db: Apple Health database manager.
            blog_db: Blog database manager.
            hardcover_db: Hardcover database manager.
            github_activity_db: GitHub activity database manager.
            oura_db: Oura Ring database manager.
        """
        self.readwise_db = readwise_db or ReadwiseDatabase()
        self.foursquare_db = foursquare_db or FoursquareDatabase()
        self.letterboxd_db = letterboxd_db or LetterboxdDatabase()
        self.overcast_db = overcast_db or OvercastDatabase()
        self.strong_db = strong_db or StrongDatabase()
        self.apple_health_db = apple_health_db or AppleHealthDatabase()
        self.blog_db = blog_db or BlogDatabase()
        self.hardcover_db = hardcover_db or HardcoverDatabase()
        self.github_activity_db = github_activity_db or GitHubDatabase()
        self.oura_db = oura_db or OuraDatabase()

    def _limit_records_by_month(
        self,
        records: List[Dict[str, Any]],
        min_year_month: Optional[str] = None,
        max_year_month: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Filter records to an optional inclusive year-month window."""
        min_cutoff = _year_month_to_date(min_year_month) if min_year_month else None
        max_cutoff = _year_month_to_date(max_year_month) if max_year_month else None

        filtered_records = []
        for record in records:
            month = _year_month_to_date(record["month"])
            if min_cutoff and month < min_cutoff:
                continue
            if max_cutoff and month > max_cutoff:
                continue
            filtered_records.append(record)

        return filtered_records
    
    def _get_all_readwise(self) -> List[Dict[str, Any]]:
        """Get all Readwise analysis records, oldest first."""
        query = """
        SELECT year_month, articles, words, reading_time_mins,
               max_words_per_article, median_words_per_article, min_words_per_article
        FROM analysis
        ORDER BY year_month ASC
        """
        with self.readwise_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
        
        records = []
        for row in rows:
            row = dict(row)
            words = row['words']
            time_mins = row['reading_time_mins']
            avg_speed = round(words / time_mins) if time_mins and time_mins > 0 else 0
            records.append({
                'month': row['year_month'],
                'articles_archived': row['articles'],
                'total_words': words,
                'time_spent_minutes': time_mins,
                'avg_reading_speed': avg_speed,
                'max_words_per_article': row['max_words_per_article'],
                'median_words_per_article': row['median_words_per_article'],
                'min_words_per_article': row['min_words_per_article'],
            })
        return records
    
    def _get_all_foursquare(self) -> List[Dict[str, Any]]:
        """Get all Foursquare analysis records, oldest first."""
        query = """
        SELECT year_month, checkins, unique_places
        FROM analysis
        ORDER BY year_month ASC
        """
        try:
            with self.foursquare_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
            
            return [
                {
                    'month': dict(row)['year_month'],
                    'checkins': dict(row)['checkins'],
                    'unique_places': dict(row)['unique_places'],
                }
                for row in rows
            ]
        except Exception:
            return []
    
    def _get_all_letterboxd(self) -> List[Dict[str, Any]]:
        """Get all Letterboxd analysis records, oldest first."""
        query = """
        SELECT year_month, movies_watched, minutes_watched, avg_rating
        FROM analysis
        ORDER BY year_month ASC
        """
        with self.letterboxd_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
        
        return [
            {
                'month': dict(row)['year_month'],
                'movies_watched': dict(row)['movies_watched'],
                'minutes_watched': dict(row)['minutes_watched'],
                'avg_rating': dict(row)['avg_rating'],
            }
            for row in rows
        ]
    
    def _get_all_overcast(self) -> List[Dict[str, Any]]:
        """Get all Overcast analysis records, oldest first."""
        if not self.overcast_db.exists():
            return []
        
        query = """
        SELECT year_month, feeds_added, feeds_removed, episodes_played, minutes_listened
        FROM analysis
        ORDER BY year_month ASC
        """
        try:
            with self.overcast_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
            
            return [
                {
                    'month': dict(row)['year_month'],
                    'feeds_added': dict(row)['feeds_added'],
                    'feeds_removed': dict(row)['feeds_removed'],
                    'episodes_played': dict(row)['episodes_played'],
                    'minutes_listened': dict(row)['minutes_listened'],
                }
                for row in rows
            ]
        except Exception:
            return []
    
    def _get_all_strong(self) -> List[Dict[str, Any]]:
        """Get all Strong analysis records, oldest first."""
        if not self.strong_db.exists():
            return []
        
        query = """
        SELECT year_month, workouts, total_minutes, unique_exercises, total_sets
        FROM analysis
        ORDER BY year_month ASC
        """
        try:
            with self.strong_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
            
            return [
                {
                    'month': dict(row)['year_month'],
                    'workouts': dict(row)['workouts'],
                    'total_minutes': dict(row)['total_minutes'],
                    'unique_exercises': dict(row)['unique_exercises'],
                    'total_sets': dict(row)['total_sets'],
                }
                for row in rows
            ]
        except Exception:
            return []

    def _get_all_apple_health(self) -> List[Dict[str, Any]]:
        """Get all Apple Health analysis records, oldest first."""
        if not self.apple_health_db.exists():
            return []

        query = """
        SELECT year_month, workouts, total_duration_seconds, total_calories
        FROM analysis
        ORDER BY year_month ASC
        """
        try:
            with self.apple_health_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()

            return [
                {
                    'month': dict(row)['year_month'],
                    'workouts': dict(row)['workouts'],
                    'total_minutes': round((dict(row)['total_duration_seconds'] or 0) / 60),
                    'total_calories': dict(row)['total_calories'],
                }
                for row in rows
            ]
        except Exception:
            return []

    def _get_all_blog(self) -> List[Dict[str, Any]]:
        """Get all blog analysis records, oldest first."""
        if not self.blog_db.exists():
            return []

        query = """
        SELECT year_month, posts, total_words, unique_tags
        FROM analysis
        ORDER BY year_month ASC
        """
        try:
            with self.blog_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()

            return [
                {
                    'month': dict(row)['year_month'],
                    'posts': dict(row)['posts'],
                    'total_words': dict(row)['total_words'],
                    'unique_tags': dict(row)['unique_tags'],
                }
                for row in rows
            ]
        except Exception:
            return []
    
    def _get_all_hardcover(self) -> List[Dict[str, Any]]:
        """Get all Hardcover analysis records, oldest first."""
        if not self.hardcover_db.exists():
            return []
        
        query = """
        SELECT year_month, books_finished, avg_rating
        FROM analysis
        ORDER BY year_month ASC
        """
        try:
            with self.hardcover_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
            
            return [
                {
                    'month': dict(row)['year_month'],
                    'books_finished': dict(row)['books_finished'],
                    'avg_rating': dict(row)['avg_rating'],
                }
                for row in rows
            ]
        except Exception:
            return []
    
    def _get_all_github(self) -> List[Dict[str, Any]]:
        """Get all GitHub analysis records, oldest first."""
        if not self.github_activity_db.exists():
            return []
        
        query = """
        SELECT *
        FROM analysis
        ORDER BY year_month ASC
        """
        try:
            with self.github_activity_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
            
            records = []
            for row in rows:
                stats = dict(row)
                record = {
                    'month': stats['year_month'],
                    'commits': stats['commits'],
                    'repos_touched': stats['repos_touched'],
                }
                if all(stats.get(metric) is not None for metric in VISIBILITY_METRICS):
                    record.update({metric: stats[metric] for metric in VISIBILITY_METRICS})
                records.append(record)
            return records
        except Exception:
            return []
    
    def _get_all_oura(self) -> List[Dict[str, Any]]:
        """Get all Oura analysis records pivoted to one row per month."""
        if not self.oura_db.exists():
            return []

        query = """
        SELECT year_month, source_table, metric, median_value, avg_value
        FROM analysis
        WHERE source_table IN ('daily_sleep', 'daily_readiness')
          AND metric = 'score'
        ORDER BY year_month ASC, source_table ASC
        """
        try:
            with self.oura_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()

            # Pivot rows into one record per year_month
            monthly: dict = {}
            for row in rows:
                row = dict(row)
                ym = row['year_month']
                if ym not in monthly:
                    monthly[ym] = {'month': ym}
                table = row['source_table']
                if table == 'daily_sleep':
                    monthly[ym]['median_sleep_score'] = row['median_value']
                    monthly[ym]['avg_sleep_score'] = round(row['avg_value'], 2) if row['avg_value'] is not None else None
                elif table == 'daily_readiness':
                    monthly[ym]['median_readiness_score'] = row['median_value']
                    monthly[ym]['avg_readiness_score'] = round(row['avg_value'], 2) if row['avg_value'] is not None else None

            return list(monthly.values())
        except Exception:
            return []

    def generate_data_files(
        self,
        min_year_month: Optional[str] = None,
        max_year_month: Optional[str] = None,
    ) -> Dict[str, str]:
        """Generate all Hugo data files.
        
        Args:
            min_year_month: Optional inclusive YYYY-MM lower bound for generated records.
            max_year_month: Optional inclusive YYYY-MM cutoff for generated records.

        Returns:
            Dictionary mapping repo file paths to YAML content strings.
            Example: {"data/activity/reading.yaml": "# Monthly reading..."}
        """
        files = {}
        
        # Reading (Readwise)
        reading_records = self._limit_records_by_month(
            self._get_all_readwise(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if reading_records:
            files["data/activity/reading.yaml"] = _to_yaml(
                reading_records, "Monthly reading activity data"
            )
            logger.info(f"Generated reading.yaml with {len(reading_records)} records")
        
        # Travel (Foursquare)
        travel_records = self._limit_records_by_month(
            self._get_all_foursquare(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if travel_records:
            files["data/activity/travel.yaml"] = _to_yaml(
                travel_records, "Monthly travel activity data"
            )
            logger.info(f"Generated travel.yaml with {len(travel_records)} records")
        
        # Movies (Letterboxd)
        movies_records = self._limit_records_by_month(
            self._get_all_letterboxd(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if movies_records:
            files["data/activity/movies.yaml"] = _to_yaml(
                movies_records, "Monthly movies activity data"
            )
            logger.info(f"Generated movies.yaml with {len(movies_records)} records")
        
        # Podcasts (Overcast)
        podcasts_records = self._limit_records_by_month(
            self._get_all_overcast(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if podcasts_records:
            files["data/activity/podcasts.yaml"] = _to_yaml(
                podcasts_records, "Monthly podcasts activity data"
            )
            logger.info(f"Generated podcasts.yaml with {len(podcasts_records)} records")
        
        # Workouts (Apple Health)
        workouts_records = self._limit_records_by_month(
            self._get_all_apple_health(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if workouts_records:
            files["data/activity/workouts.yaml"] = _to_yaml(
                workouts_records, "Monthly workout activity data"
            )
            logger.info(f"Generated workouts.yaml with {len(workouts_records)} records")

        # Writing (Blog)
        writing_records = self._limit_records_by_month(
            self._get_all_blog(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if writing_records:
            files["data/activity/writing.yaml"] = _to_yaml(
                writing_records, "Monthly writing activity data"
            )
            logger.info(f"Generated writing.yaml with {len(writing_records)} records")
        
        # Books (Hardcover)
        books_records = self._limit_records_by_month(
            self._get_all_hardcover(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if books_records:
            files["data/activity/books.yaml"] = _to_yaml(
                books_records, "Monthly books activity data"
            )
            logger.info(f"Generated books.yaml with {len(books_records)} records")
        
        # Code (GitHub)
        code_records = self._limit_records_by_month(
            self._get_all_github(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if code_records:
            files["data/activity/code.yaml"] = _to_yaml(
                code_records, "Monthly code activity data"
            )
            logger.info(f"Generated code.yaml with {len(code_records)} records")
        
        # Sleep & Readiness (Oura)
        sleep_records = self._limit_records_by_month(
            self._get_all_oura(),
            min_year_month=min_year_month,
            max_year_month=max_year_month,
        )
        if sleep_records:
            files["data/activity/sleep.yaml"] = _to_yaml(
                sleep_records, "Monthly sleep and readiness data"
            )
            logger.info(f"Generated sleep.yaml with {len(sleep_records)} records")
        
        logger.info(f"Generated {len(files)} data files total")
        return files
