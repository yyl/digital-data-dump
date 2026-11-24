"""Generator for Hugo-compatible YAML data files from analysis databases."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Any

from ..readwise.database import ReadwiseDatabase
from ..foursquare.database import FoursquareDatabase
from ..letterboxd.database import LetterboxdDatabase
from ..overcast.database import OvercastDatabase
from ..database import BaseDatabase
from ..apple_health.database import AppleHealthDatabase
from ..blog.database import BlogDatabase
from ..hardcover.database import HardcoverDatabase
from ..github.database import GitHubDatabase
from ..github.models import LINE_CHANGE_METRICS, VISIBILITY_METRICS
from ..oura.database import OuraDatabase
from ..oura.reporting import monthly_scores
from ..surfilog.database import SurfilogDatabase
from ..surfilog.models import METRICS as SURFILOG_METRICS
from ..kaya.analytics import COUNT_METRICS as KAYA_COUNT_METRICS
from ..kaya.database import KayaDatabase

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
    if not records:
        return f"# {comment}\n[]\n"

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


@dataclass(frozen=True)
class ActivitySource:
    filename: str
    comment: str
    database: BaseDatabase
    read: Callable[[], list[dict]]


class DataGenerator:
    """Generates Hugo data files from analysis databases."""
    
    def __init__(
        self,
        readwise_db: Optional[ReadwiseDatabase] = None,
        foursquare_db: Optional[FoursquareDatabase] = None,
        letterboxd_db: Optional[LetterboxdDatabase] = None,
        overcast_db: Optional[OvercastDatabase] = None,
        apple_health_db: Optional[AppleHealthDatabase] = None,
        blog_db: Optional[BlogDatabase] = None,
        hardcover_db: Optional[HardcoverDatabase] = None,
        github_activity_db: Optional[GitHubDatabase] = None,
        oura_db: Optional[OuraDatabase] = None,
        surfilog_db: Optional[SurfilogDatabase] = None,
        kaya_db: Optional[KayaDatabase] = None,
    ):
        """Initialize data generator.
        
        Args:
            readwise_db: Readwise database manager.
            foursquare_db: Foursquare database manager.
            letterboxd_db: Letterboxd database manager.
            overcast_db: Overcast database manager.
            apple_health_db: Apple Health database manager.
            blog_db: Blog database manager.
            hardcover_db: Hardcover database manager.
            github_activity_db: GitHub activity database manager.
            oura_db: Oura Ring database manager.
            surfilog_db: Surfilog session and wave database manager.
            kaya_db: Kaya climbing log database manager.
        """
        self.readwise_db = readwise_db or ReadwiseDatabase()
        self.foursquare_db = foursquare_db or FoursquareDatabase()
        self.letterboxd_db = letterboxd_db or LetterboxdDatabase()
        self.overcast_db = overcast_db or OvercastDatabase()
        self.apple_health_db = apple_health_db or AppleHealthDatabase()
        self.blog_db = blog_db or BlogDatabase()
        self.hardcover_db = hardcover_db or HardcoverDatabase()
        self.github_activity_db = github_activity_db or GitHubDatabase()
        self.oura_db = oura_db or OuraDatabase()
        self.surfilog_db = surfilog_db or SurfilogDatabase()
        self.kaya_db = kaya_db or KayaDatabase()

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
        records = []
        for row in self.readwise_db.fetch_rows(query):
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
        return [
            {'month': row['year_month'], 'checkins': row['checkins'],
             'unique_places': row['unique_places']}
            for row in self.foursquare_db.fetch_rows(query)
        ]

    def _get_all_letterboxd(self) -> List[Dict[str, Any]]:
        """Get all Letterboxd analysis records, oldest first."""
        query = """
        SELECT year_month, movies_watched, minutes_watched, avg_rating
        FROM analysis
        ORDER BY year_month ASC
        """
        return [
            {'month': row['year_month'], 'movies_watched': row['movies_watched'],
             'minutes_watched': row['minutes_watched'], 'avg_rating': row['avg_rating']}
            for row in self.letterboxd_db.fetch_rows(query)
        ]

    def _get_all_overcast(self) -> List[Dict[str, Any]]:
        """Get all Overcast analysis records, oldest first."""
        query = """
        SELECT year_month, feeds_added, feeds_removed, episodes_played, minutes_listened
        FROM analysis
        ORDER BY year_month ASC
        """
        return [
            {'month': row['year_month'], 'feeds_added': row['feeds_added'],
             'feeds_removed': row['feeds_removed'], 'episodes_played': row['episodes_played'],
             'minutes_listened': row['minutes_listened']}
            for row in self.overcast_db.fetch_rows(query)
        ]

    def _get_all_apple_health(self) -> List[Dict[str, Any]]:
        """Get all Apple Health analysis records, oldest first."""
        query = """
        SELECT year_month, workouts, total_duration_seconds, total_calories
        FROM analysis
        ORDER BY year_month ASC
        """
        return [
            {'month': row['year_month'], 'workouts': row['workouts'],
             'total_minutes': round((row['total_duration_seconds'] or 0) / 60),
             'total_calories': row['total_calories']}
            for row in self.apple_health_db.fetch_rows(query)
        ]

    def _get_all_blog(self) -> List[Dict[str, Any]]:
        """Get all blog analysis records, oldest first."""
        query = """
        SELECT year_month, posts, total_words, unique_tags
        FROM analysis
        ORDER BY year_month ASC
        """
        return [
            {'month': row['year_month'], 'posts': row['posts'],
             'total_words': row['total_words'], 'unique_tags': row['unique_tags']}
            for row in self.blog_db.fetch_rows(query)
        ]

    def _get_all_hardcover(self) -> List[Dict[str, Any]]:
        """Get all Hardcover analysis records, oldest first."""
        query = """
        SELECT year_month, books_finished, avg_rating
        FROM analysis
        ORDER BY year_month ASC
        """
        return [
            {'month': row['year_month'], 'books_finished': row['books_finished'],
             'avg_rating': row['avg_rating']}
            for row in self.hardcover_db.fetch_rows(query)
        ]

    def _get_all_github(self) -> List[Dict[str, Any]]:
        """Get all GitHub analysis records, oldest first."""
        query = """
        SELECT *
        FROM analysis
        ORDER BY year_month ASC
        """
        records = []
        for row in self.github_activity_db.fetch_rows(query):
            record = {
                'month': row['year_month'], 'commits': row['commits'],
                'repos_touched': row['repos_touched'],
            }
            if all(row.get(metric) is not None for metric in VISIBILITY_METRICS):
                record.update({metric: row[metric] for metric in VISIBILITY_METRICS})
            record.update({metric: row[metric] for metric in LINE_CHANGE_METRICS
                           if row.get(metric) is not None})
            records.append(record)
        return records

    def _get_all_oura(self) -> List[Dict[str, Any]]:
        return [{"month": row.pop("year_month"), **row} for row in monthly_scores(self.oura_db)]

    def _get_all_surfilog(self) -> List[Dict[str, Any]]:
        """Publish monthly aggregates; raw GPS and wave records stay in SQLite."""
        return [
            {"month": row["year_month"], **{metric: row[metric] for metric in SURFILOG_METRICS}}
            for row in self.surfilog_db.fetch_rows("SELECT * FROM analysis ORDER BY year_month")
        ]

    def _get_all_kaya(self) -> List[Dict[str, Any]]:
        records = []
        for row in self.kaya_db.fetch_rows("SELECT * FROM analysis ORDER BY year_month"):
            record = {"month": row["year_month"]}
            record.update({metric: row[metric] for metric in KAYA_COUNT_METRICS})
            if row["hardest_v_grade"] is not None:
                record["hardest_v_grade"] = row["hardest_v_grade"]
            records.append(record)
        return records

    def activity_sources(self) -> tuple[ActivitySource, ...]:
        return (
            ActivitySource("reading", "Monthly reading activity data", self.readwise_db, self._get_all_readwise),
            ActivitySource("travel", "Monthly travel activity data", self.foursquare_db, self._get_all_foursquare),
            ActivitySource("movies", "Monthly movies activity data", self.letterboxd_db, self._get_all_letterboxd),
            ActivitySource("podcasts", "Monthly podcasts activity data", self.overcast_db, self._get_all_overcast),
            ActivitySource("workouts", "Monthly workout activity data", self.apple_health_db, self._get_all_apple_health),
            ActivitySource("writing", "Monthly writing activity data", self.blog_db, self._get_all_blog),
            ActivitySource("books", "Monthly books activity data", self.hardcover_db, self._get_all_hardcover),
            ActivitySource("code", "Monthly code activity data", self.github_activity_db, self._get_all_github),
            ActivitySource("sleep", "Monthly sleep and readiness data", self.oura_db, self._get_all_oura),
            ActivitySource("surfing", "Monthly surfing activity data", self.surfilog_db, self._get_all_surfilog),
            ActivitySource("bouldering", "Monthly bouldering activity data", self.kaya_db, self._get_all_kaya),
        )

    def load_activity_data(self) -> dict[str, tuple[str, list[dict]]]:
        """Load available monthly records, including sources with an empty analysis."""
        activity = {}
        for source in self.activity_sources():
            records = source.read()
            if not records:
                with source.database.read_connection() as conn:
                    if conn is None:
                        continue
            activity[f"data/activity/{source.filename}.yaml"] = (
                source.comment, records,
            )
        return activity

    def render_data_files(
        self,
        activity: dict[str, tuple[str, list[dict]]],
        min_year_month: Optional[str] = None,
        max_year_month: Optional[str] = None,
    ) -> Dict[str, str]:
        """Render a window of available data, with explicit empty files clearing old exports."""
        return {
            path: _to_yaml(self._limit_records_by_month(records, min_year_month, max_year_month), comment)
            for path, (comment, records) in activity.items()
        }

    def generate_data_files(
        self,
        min_year_month: Optional[str] = None,
        max_year_month: Optional[str] = None,
    ) -> Dict[str, str]:
        return self.render_data_files(self.load_activity_data(), min_year_month, max_year_month)
