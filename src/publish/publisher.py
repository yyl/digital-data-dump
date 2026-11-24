"""Publisher module for generating and committing monthly summaries."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from ..config import Config
from ..comparison import compute_comparisons
from ..readwise.analytics import parse_reading_time_minutes, resolve_article_source
from ..readwise.database import ReadwiseDatabase
from ..foursquare.database import FoursquareDatabase
from ..letterboxd.database import LetterboxdDatabase
from ..overcast.database import OvercastDatabase
from ..strong.database import StrongDatabase
from ..strong.analytics import StrongAnalytics
from ..apple_health.database import AppleHealthDatabase
from ..apple_health.models import ACTIVITY_ROLLUP
from ..blog.database import BlogDatabase
from ..hardcover.database import HardcoverDatabase
from ..github.database import GitHubDatabase
from ..github.models import LINE_CHANGE_METRICS, VISIBILITY_METRICS
from ..github.analytics import hourly_activity
from ..oura.database import OuraDatabase
from ..oura.reporting import monthly_scores, report_months as oura_report_months
from ..surfilog.database import SurfilogDatabase
from ..surfilog.models import METRICS as SURFILOG_METRICS
from ..surfilog.models import WAVE_MEDIAN_METRICS
from ..kaya.database import KayaDatabase
from .github_client import GitHubClient
from .markdown_generator import MarkdownGenerator, ReportSection
from .data_generator import DataGenerator
from .activity_chart import render_commit_hours
from .travel_map import render_travel_map, valid_map_places

@dataclass(frozen=True)
class ReportSource:
    section: ReportSection
    available_months: Callable[[], Iterable[str]]
    read: Callable[[str], dict | None]


class Publisher:
    """Orchestrates the generation and publishing of monthly summaries."""
    
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
        github_client: Optional[GitHubClient] = None,
        surfilog_db: Optional[SurfilogDatabase] = None,
        kaya_db: Optional[KayaDatabase] = None,
    ):
        """Initialize publisher.
        
        Args:
            readwise_db: Readwise database manager for reading analysis data.
            foursquare_db: Foursquare database manager.
            letterboxd_db: Letterboxd database manager.
            overcast_db: Overcast database manager.
            strong_db: Strong database manager.
            apple_health_db: Apple Health database manager.
            blog_db: Blog database manager.
            hardcover_db: Hardcover database manager.
            github_activity_db: GitHub activity database manager.
            oura_db: Oura Ring database manager.
            github_client: GitHub client for committing files.
            surfilog_db: Surfilog session and wave database manager.
            kaya_db: Kaya climbing log database manager.
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
        self.surfilog_db = surfilog_db or SurfilogDatabase()
        self.kaya_db = kaya_db or KayaDatabase()
        self.github_client = github_client
        self.markdown_generator = MarkdownGenerator()
        self.report_assets: Dict[str, str | bytes] = {}
        self.data_generator = DataGenerator(
            readwise_db=self.readwise_db,
            foursquare_db=self.foursquare_db,
            letterboxd_db=self.letterboxd_db,
            overcast_db=self.overcast_db,
            apple_health_db=self.apple_health_db,
            blog_db=self.blog_db,
            hardcover_db=self.hardcover_db,
            github_activity_db=self.github_activity_db,
            oura_db=self.oura_db,
            surfilog_db=self.surfilog_db,
            kaya_db=self.kaya_db,
        )
    
    def _fetch_analysis(
        self,
        db: Any,
        query: str,
        params: tuple,
    ) -> Optional[Dict[str, Any]]:
        """Fetch one analysis row using the shared source-readiness policy."""
        rows = self._fetch_rows(db, query, params)
        return rows[0] if rows else None

    def _fetch_rows(
        self,
        db: Any,
        query: str,
        params: tuple,
        *,
        required_tables=("analysis",),
    ) -> List[Dict[str, Any]]:
        """Fetch report rows without suppressing database or schema failures."""
        return db.fetch_rows(query, params, required_tables=required_tables)

    def _get_source_time_analysis(self, db: Any, year_month: str) -> Optional[List[Dict[str, Any]]]:
        """Read source totals when the database has been analyzed with this schema."""
        with db.read_connection(required_tables=()) as conn:
            if conn is None or not conn.execute("""
                SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'analysis_by_source'
            """).fetchone():
                return None
            return [dict(row) for row in conn.execute("""
                SELECT source_name, items, timed_items, total_seconds
                FROM analysis_by_source WHERE year_month = ?
            """, (year_month,))]

    def _get_readwise_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get Readwise analysis for a specific month."""
        query = """
        SELECT year_month, year, month, articles, words, reading_time_mins,
               max_words_per_article, median_words_per_article, min_words_per_article
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(self.readwise_db, query, (year_month,))
    
    def _get_foursquare_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get Foursquare analysis for a specific month."""
        query = """
        SELECT year_month, year, month, checkins, unique_places
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(
            self.foursquare_db,
            query,
            (year_month,),
        )
    
    def _get_letterboxd_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get Letterboxd analysis for a specific month."""
        query = """
        SELECT year_month, year, month, movies_watched, avg_rating, min_rating, max_rating, avg_years_since_release
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(self.letterboxd_db, query, (year_month,))
    
    def _get_overcast_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get Overcast analysis for a specific month."""
        query = """
        SELECT year_month, year, month, feeds_added, feeds_removed, episodes_played, minutes_listened
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(
            self.overcast_db,
            query,
            (year_month,),
        )
    
    def _get_apple_health_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get Apple Health analysis for a specific month."""
        query = """
        SELECT year_month, year, month, workouts, total_duration_seconds, total_calories
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(
            self.apple_health_db,
            query,
            (year_month,),
        )

    def _get_blog_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get blog analysis for a specific month."""
        query = """
        SELECT year_month, year, month, posts, total_words, unique_tags
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(
            self.blog_db,
            query,
            (year_month,),
        )
    
    def _get_hardcover_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get Hardcover analysis for a specific month."""
        query = """
        SELECT year_month, year, month, books_finished, avg_rating
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(
            self.hardcover_db,
            query,
            (year_month,),
        )
    
    def _get_github_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Get GitHub analysis for a specific month."""
        query = """
        SELECT *
        FROM analysis
        WHERE year_month = ?
        """
        return self._fetch_analysis(
            self.github_activity_db,
            query,
            (year_month,),
        )

    def _get_github_hourly_activity(self, year_month: str) -> List[Dict[str, Any]]:
        """Read persisted hourly counts, with support for older local databases."""
        with self.github_activity_db.read_connection(required_tables=('commits',)) as conn:
            if conn is None:
                return []
            if conn.execute("""
                SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'analysis_by_hour'
            """).fetchone():
                return [dict(row) for row in conn.execute("""
                    SELECT hour, public_commits, private_commits FROM analysis_by_hour
                    WHERE year_month = ? ORDER BY hour
                """, (year_month,))]
            columns = {row['name'] for row in conn.execute("PRAGMA table_info(commits)")}
            visibility = 'is_private' if 'is_private' in columns else '0'
            return hourly_activity(conn.execute(f"""
                SELECT author_date, date_month, {visibility} AS is_private FROM commits
                WHERE date_month = ?
            """, (year_month,)))

    def _add_report_asset(self, year_month: str, name: str, content: str | bytes) -> str:
        year, month = year_month.split('-')
        path = f"assets/wrap-up-{month}-{year}/{name}"
        self.report_assets[path] = content
        return path

    def save_preview(self, markdown: str) -> Path:
        """Write the rendered post and its images together for local review."""
        directory = Config.PROJECT_ROOT / '.cache' / 'report-preview'
        directory.mkdir(parents=True, exist_ok=True)
        preview = directory / 'index.md'
        preview.write_text(markdown, encoding='utf-8')
        for name, content in self.report_assets.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding='utf-8')
        return preview

    def _get_surfilog_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        row = self._fetch_analysis(
            self.surfilog_db, "SELECT * FROM analysis WHERE year_month = ?", (year_month,),
        )
        if row and row['waves'] == 0:
            # A session with no counted waves has no wave records to compare.
            for metric in ('max_wave_seconds', 'max_speed_kmh', 'longest_wave_m'):
                row[metric] = None
        return row

    def _get_kaya_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        return self._fetch_analysis(
            self.kaya_db, "SELECT * FROM analysis WHERE year_month = ?", (year_month,),
        )

    def _get_oura_analysis(self, year_month: str) -> Optional[Dict[str, Any]]:
        scores = monthly_scores(self.oura_db, year_month)
        return scores[0] if scores else None

    def _get_readwise_articles(self, year_month: str) -> List[Dict[str, Any]]:
        """Get archived Readwise articles for a specific month."""
        query = """
        SELECT
            title,
            COALESCE(source_url, url) AS link,
            site_name,
            author,
            word_count,
            reading_time,
            last_moved_at
        FROM documents
        WHERE location = 'archive'
          AND last_moved_at IS NOT NULL
          AND strftime('%Y-%m', last_moved_at) = ?
        ORDER BY datetime(last_moved_at) DESC, title ASC
        """
        articles = self._fetch_rows(
            self.readwise_db, query, (year_month,), required_tables=("documents",)
        )
        for article in articles:
            minutes = parse_reading_time_minutes(article.get('reading_time'))
            words = article.get('word_count')
            article['reading_time_seconds'] = minutes * 60 if minutes is not None else None
            article['reading_speed_wpm'] = round(int(words) / minutes) if words and minutes else None
            article['site_name'] = resolve_article_source(article)
        return articles

    def _get_readwise_highlights(self, year_month: str) -> List[Dict[str, Any]]:
        """Get Readwise highlights grouped-able by source item for a specific month."""
        query = """
        SELECT
            b.title AS source_title,
            b.category AS source_category,
            COALESCE(b.source_url, b.readwise_url, b.unique_url) AS source_link,
            h.text,
            h.note,
            h.highlighted_at
        FROM highlights h
        JOIN books b ON b.user_book_id = h.book_id
        WHERE h.highlighted_at IS NOT NULL
          AND h.is_deleted = 0
          AND strftime('%Y-%m', h.highlighted_at) = ?
        ORDER BY datetime(h.highlighted_at) DESC, b.title ASC, h.id ASC
        """
        return self._fetch_rows(
            self.readwise_db, query, (year_month,), required_tables=("books", "highlights")
        )

    def _get_new_reading_sources(self, year_month: str) -> List[str]:
        """Get 'new' reading sources that appeared for the first time in the given month.

        Uses the same source resolution as ``resolve_article_source`` so that
        forwarded-email newsletters (which lack a ``site_name`` in the DB) are
        detected correctly.
        """
        query = """
        SELECT title, site_name, author, last_moved_at
        FROM documents
        WHERE location = 'archive'
          AND last_moved_at IS NOT NULL
        ORDER BY last_moved_at ASC
        """
        rows = self._fetch_rows(
            self.readwise_db, query, (), required_tables=("documents",)
        )

        # Track which resolved source names we've seen and their first month.
        first_seen: dict[str, str] = {}
        for row in rows:
            source = resolve_article_source(row)
            if not source:
                continue
            row_month = row['last_moved_at'][:7]  # "YYYY-MM"
            if source not in first_seen:
                first_seen[source] = row_month

        return sorted(s for s, m in first_seen.items() if m == year_month)

    def _get_movies_watched(self, year_month: str) -> List[Dict[str, Any]]:
        """Get movies watched in a specific month."""
        query = """
        SELECT
            w.movie_name,
            w.year,
            w.watched_at,
            w.letterboxd_uri,
            r.rating
        FROM watched w
        LEFT JOIN ratings r ON r.letterboxd_uri = w.letterboxd_uri
        WHERE strftime('%Y-%m', w.watched_at) = ?
        ORDER BY date(w.watched_at) DESC, w.movie_name ASC
        """
        return self._fetch_rows(
            self.letterboxd_db, query, (year_month,), required_tables=("watched", "ratings")
        )

    def _get_podcast_episodes(self, year_month: str) -> List[Dict[str, Any]]:
        """Get played podcast episodes in a specific month."""
        with self.overcast_db.read_connection(required_tables=('feeds', 'episodes')) as conn:
            if conn is None:
                return []
            columns = {row['name'] for row in conn.execute("PRAGMA table_info(episodes)")}
            duration = 'e.duration_seconds' if 'duration_seconds' in columns else 'NULL'
            return [dict(row) for row in conn.execute(f"""
                SELECT
                    f.title AS podcast_title,
                    f.htmlUrl AS podcast_link,
                    e.title AS episode_title,
                    e.overcastUrl AS episode_link,
                    e.userUpdatedDate,
                    {duration} AS duration_seconds
                FROM episodes e
                LEFT JOIN feeds f ON f.overcastId = e.feedId
                WHERE e.played = 1
                  AND e.userUpdatedDate IS NOT NULL
                  AND strftime('%Y-%m', e.userUpdatedDate) = ?
                ORDER BY datetime(e.userUpdatedDate) DESC, f.title ASC, e.title ASC
            """, (year_month,))]

    def _get_new_podcast_feeds(self, year_month: str) -> List[str]:
        """Get new podcast feeds subscribed in the given month."""
        query = """
        SELECT title
        FROM feeds
        WHERE overcastAddedDate IS NOT NULL
          AND strftime('%Y-%m', overcastAddedDate) = ?
        """
        rows = self._fetch_rows(
            self.overcast_db,
            query,
            (year_month,),
            required_tables=('feeds',),
        )
        return [row['title'] for row in rows if row.get('title')]

    def _get_new_places(self, year_month: str) -> List[str]:
        """Get places that were visited for the first time in the given month."""
        query = """
        SELECT p.name
        FROM checkins c
        JOIN places p ON c.place_fsq_id = p.fsq_place_id
        GROUP BY c.place_fsq_id
        HAVING strftime('%Y-%m', MIN(c.created_at), 'unixepoch') = ?
        ORDER BY p.name ASC
        """
        rows = self._fetch_rows(
            self.foursquare_db,
            query,
            (year_month,),
            required_tables=('places', 'checkins'),
        )
        return [row['name'] for row in rows if row.get('name')]

    def _get_foursquare_places(self, year_month: str) -> List[Dict[str, Any]]:
        """Get visited places ranked by monthly checkin count."""
        return self._fetch_rows(
            self.foursquare_db,
            """
            SELECT p.fsq_place_id, p.name, p.locality, p.region, p.country,
                   p.latitude, p.longitude, COUNT(*) AS visits
            FROM checkins c
            JOIN places p ON p.fsq_place_id = c.place_fsq_id
            WHERE strftime('%Y-%m', c.created_at, 'unixepoch') = ?
            GROUP BY p.fsq_place_id
            ORDER BY visits DESC, p.name COLLATE NOCASE ASC, p.fsq_place_id ASC
            """,
            (year_month,),
            required_tables=('places', 'checkins'),
        )

    def _get_new_github_repos(self, year_month: str) -> List[str]:
        """Get public repos that appear for the first time in the given month."""
        # SELECT * also supports legacy public-only databases without is_private.
        query = """
        SELECT *
        FROM commits
        GROUP BY repo
        HAVING MIN(date_month) = ?
        ORDER BY repo ASC
        """
        rows = self._fetch_rows(
            self.github_activity_db,
            query,
            (year_month,),
            required_tables=('commits',),
        )
        return [
            row['repo'] for row in rows
            if row.get('repo') and not row.get('is_private', False)
            and row.get('is_discoverable', True)
        ]

    def _get_github_commits(self, year_month: str) -> List[Dict[str, Any]]:
        """Get public GitHub commit details for a specific month."""
        query = """
        SELECT *
        FROM commits
        WHERE date_month = ?
          AND (
            message IS NULL
            OR message NOT LIKE 'Merge pull request #%'
          )
        ORDER BY datetime(author_date) DESC, repo ASC, sha ASC
        """
        rows = self._fetch_rows(
            self.github_activity_db,
            query,
            (year_month,),
            required_tables=('commits',),
        )
        return [
            row for row in rows
            if not row.get('is_private', False) and row.get('is_discoverable', True)
        ]

    def _get_apple_health_activity_breakdown(self, year_month: str) -> List[Dict[str, Any]]:
        """Read the monthly workout breakdown, including previews of legacy databases."""
        with self.apple_health_db.read_connection(required_tables=('workouts',)) as conn:
            if conn is None:
                return []
            has_analysis = conn.execute("""
                SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'analysis_by_activity'
            """).fetchone()
            source = "analysis_by_activity" if has_analysis else f"({ACTIVITY_ROLLUP})"
            return [dict(row) for row in conn.execute(f"""
                SELECT activity_type, workouts, total_duration_seconds, total_calories,
                       avg_heart_rate, max_heart_rate
                FROM {source}
                WHERE year_month = ?
                ORDER BY workouts DESC, activity_type ASC
            """, (year_month,))]

    def _get_blog_top_tags(self, year_month: str) -> List[Dict[str, Any]]:
        """Get blog tags ranked by number of posts in a month."""
        query = """
        SELECT pt.tag, COUNT(DISTINCT pt.permalink) AS posts
        FROM post_tags pt
        JOIN posts p ON p.permalink = pt.permalink
        WHERE strftime('%Y-%m', p.published_at) = ?
        GROUP BY pt.tag
        ORDER BY posts DESC, pt.tag ASC
        """
        return self._fetch_rows(
            self.blog_db,
            query,
            (year_month,),
            required_tables=('posts', 'post_tags'),
        )
    
    def _analysis_months(self, db) -> list[str]:
        rows = self._fetch_rows(db, "SELECT DISTINCT year_month FROM analysis", ())
        return [row["year_month"] for row in rows if row.get("year_month")]

    def report_sources(self) -> tuple[ReportSource, ...]:
        sections = {section.key: section for section in self.markdown_generator.report_sections()}
        return (
            ReportSource(sections['readwise'], partial(self._analysis_months, self.readwise_db), self._readwise_section),
            ReportSource(sections['hardcover'], partial(self._analysis_months, self.hardcover_db), self._hardcover_section),
            ReportSource(sections['overcast'], partial(self._analysis_months, self.overcast_db), self._overcast_section),
            ReportSource(sections['blog'], partial(self._analysis_months, self.blog_db), self._blog_section),
            ReportSource(sections['github'], partial(self._analysis_months, self.github_activity_db), self._github_section),
            ReportSource(sections['apple_health'], partial(self._analysis_months, self.apple_health_db), self._apple_health_section),
            ReportSource(sections['surfilog'], partial(self._analysis_months, self.surfilog_db), self._surfilog_section),
            ReportSource(sections['kaya'], partial(self._analysis_months, self.kaya_db), self._kaya_section),
            ReportSource(sections['strong'], self._strong_report_months, self._strong_section),
            ReportSource(sections['foursquare'], partial(self._analysis_months, self.foursquare_db), self._foursquare_section),
            ReportSource(sections['letterboxd'], partial(self._analysis_months, self.letterboxd_db), self._letterboxd_section),
            ReportSource(sections['oura'], partial(oura_report_months, self.oura_db), self._oura_section),
        )

    def _get_target_year_month(self, last_month: bool = False) -> Optional[str]:
        """Choose the latest available report month or the previous calendar month."""
        all_months = {month for source in self.report_sources() for month in source.available_months()}

        if not all_months:
            return None
            
        if last_month:
            previous_month = date.today().replace(day=1) - timedelta(days=1)
            target = previous_month.strftime("%Y-%m")
            if target not in all_months:
                raise ValueError(
                    f"No analysis data found for previous calendar month ({target}). "
                    "Run 'analyze' first."
                )
            return target
        return max(all_months)
    
    def _ensure_github_client(self):
        """Initialize GitHub client if not already provided."""
        if not self.github_client:
            Config.validate_github()
            self.github_client = GitHubClient(
                token=Config.BLOG_GITHUB_TOKEN,
                repo_owner=Config.BLOG_REPO_OWNER,
                repo_name=Config.BLOG_REPO_NAME,
                target_branch=Config.BLOG_GITHUB_TARGET_BRANCH
            )

    def _build_github_client(self, repo_owner: str, repo_name: str, target_branch: str) -> GitHubClient:
        """Build a GitHub client for a specific publishing target."""
        token = Config.BLOG_GITHUB_TOKEN
        if repo_owner == Config.DATA_REPO_OWNER and repo_name == Config.DATA_REPO_NAME:
            token = Config.DATA_REPO_GITHUB_TOKEN or Config.BLOG_GITHUB_TOKEN

        return GitHubClient(
            token=token,
            repo_owner=repo_owner,
            repo_name=repo_name,
            target_branch=target_branch,
        )

    def _one_year_lookback_year_month(self, today: Optional[date] = None) -> str:
        """Return the YYYY-MM corresponding to one year before today."""
        today = today or date.today()
        return f"{today.year - 1:04d}-{today.month:02d}"
    
    def _data_repo_client(self) -> GitHubClient:
        Config.validate_data_repo_github()
        return self._build_github_client(
            repo_owner=Config.DATA_REPO_OWNER,
            repo_name=Config.DATA_REPO_NAME,
            target_branch=Config.DATA_GITHUB_TARGET_BRANCH,
        )

    def _prepare_draft(self, last_month: bool) -> tuple[dict[str, str | bytes], str]:
        year_month = self._get_target_year_month(last_month)
        if not year_month:
            raise ValueError("No report data found. Run 'analyze' first.")

        year, month = year_month.split('-')
        markdown = self.generate_markdown(year_month)
        directory = Config.DATA_REPO_POSTS_DIR
        return {
            f"{directory}/wrap-up-{month}-{year}.md": markdown,
            **{f"{directory}/{path}": content for path, content in self.report_assets.items()},
        }, f"feat: Add monthly report draft for {month}/{year}"

    def publish(self, last_month: bool = False) -> Dict[str, Any]:
        """Render and deliver the monthly draft and its assets."""
        files, message = self._prepare_draft(last_month)
        return self._data_repo_client().create_or_update_files(files=files, commit_message=message)

    def _prepare_activity(self) -> tuple[dict[str, str], dict[str, str], str]:
        activity = self.data_generator.load_activity_data()
        if not activity:
            raise ValueError("No activity analysis available. Run 'analyze' first.")
        cutoff = self._one_year_lookback_year_month()
        full_history = self.data_generator.render_data_files(activity)
        blog = self.data_generator.render_data_files(activity, min_year_month=cutoff)
        return full_history, blog, cutoff

    def _deliver_activity(self, data_repo_client: GitHubClient, full_history: dict[str, str],
                          blog_files: dict[str, str], cutoff: str) -> Dict[str, Any]:
        data_result = data_repo_client.create_or_update_files(
            files=full_history, commit_message="data: Update activity data files",
        )
        blog_result = self.github_client.create_or_update_files(
            files=blog_files, commit_message=f"data: Update activity data files since {cutoff}",
        )
        return {"data_repo": data_result, "blog_repo": blog_result, "blog_start_year_month": cutoff}

    def backfill(self) -> Dict[str, Any]:
        """Render both activity windows before committing either of them."""
        activity = self._prepare_activity()
        data_repo_client = self._data_repo_client()
        self._ensure_github_client()
        return self._deliver_activity(data_repo_client, *activity)

    def publish_pipeline(self, last_month: bool = False) -> Dict[str, Any]:
        """Render all pipeline artifacts before starting delivery."""
        files, message = self._prepare_draft(last_month)
        activity = self._prepare_activity()
        data_repo_client = self._data_repo_client()
        self._ensure_github_client()
        draft = data_repo_client.create_or_update_files(files=files, commit_message=message)
        return {"draft": draft, **self._deliver_activity(data_repo_client, *activity)}

    def generate_markdown(self, year_month: Optional[str] = None, last_month: bool = False) -> str:
        self.report_assets = {}
        if not year_month:
            year_month = self._get_target_year_month(last_month)
        if not year_month:
            raise ValueError("No report data found. Run 'analyze' first.")

        year, month = year_month.split('-')
        data = {'year': year, 'month': month}
        sources = self.report_sources()
        for source in sources:
            section_data = source.read(year_month)
            if section_data:
                data[source.section.key] = section_data
        return self.markdown_generator.generate_monthly_summary(
            data, sections=(source.section for source in sources),
        )

    def _strong_report_months(self) -> list[str]:
        return StrongAnalytics(db=self.strong_db).get_weightlifting_months()

    def _readwise_section(self, year_month: str) -> dict | None:
        readwise = self._get_readwise_analysis(year_month)
        if not readwise:
            return None

        readwise_comparisons = compute_comparisons(
            current_stats=readwise,
            historical_getter=self._get_readwise_analysis,
            year_month=year_month,
            metrics=['articles', 'words', 'reading_time_mins']
        )
        section = {
            'articles': readwise['articles'],
            'words': readwise['words'],
            'reading_time_mins': readwise['reading_time_mins'],
            'max_words_per_article': readwise['max_words_per_article'],
            'median_words_per_article': readwise['median_words_per_article'],
            'min_words_per_article': readwise['min_words_per_article'],
            'article_list': self._get_readwise_articles(year_month),
            'source_time_analysis': self._get_source_time_analysis(self.readwise_db, year_month),
            'new_sources': self._get_new_reading_sources(year_month),
            'highlight_groups': self._group_readwise_highlights(
                self._get_readwise_highlights(year_month)
            ),
            'comparisons': readwise_comparisons
        }
        return section

    def _foursquare_section(self, year_month: str) -> dict | None:
        foursquare = self._get_foursquare_analysis(year_month)
        if not foursquare:
            return None

        foursquare_comparisons = compute_comparisons(
            current_stats=foursquare,
            historical_getter=self._get_foursquare_analysis,
            year_month=year_month,
            metrics=['checkins', 'unique_places']
        )
        section = {
            'checkins': foursquare['checkins'],
            'unique_places': foursquare['unique_places'],
            'places': self._get_foursquare_places(year_month),
            'new_places': self._get_new_places(year_month),
            'comparisons': foursquare_comparisons
        }
        places = section['places']
        if places:
            mapped = valid_map_places(places)
            image = render_travel_map(mapped)
            if image is not None:
                section['map_image'] = self._add_report_asset(
                    year_month, 'travel-map.png', image
                )
            section['map_coverage'] = (
                f"Mapped {len(mapped)} of {len(places)} visited places. "
                "Marker size reflects monthly visits."
                if mapped else "Map unavailable because the visited places have no valid coordinates."
            )
        return section

    def _letterboxd_section(self, year_month: str) -> dict | None:
        letterboxd = self._get_letterboxd_analysis(year_month)
        if not letterboxd:
            return None

        letterboxd_comparisons = compute_comparisons(
            current_stats=letterboxd,
            historical_getter=self._get_letterboxd_analysis,
            year_month=year_month,
            metrics=['movies_watched', 'avg_rating']
        )
        section = {
            'movies_watched': letterboxd['movies_watched'],
            'avg_rating': letterboxd['avg_rating'],
            'min_rating': letterboxd['min_rating'],
            'max_rating': letterboxd['max_rating'],
            'avg_years_since_release': letterboxd['avg_years_since_release'],
            'movies': self._get_movies_watched(year_month),
            'comparisons': letterboxd_comparisons
        }
        return section

    def _overcast_section(self, year_month: str) -> dict | None:
        overcast = self._get_overcast_analysis(year_month)
        if not overcast:
            return None

        overcast_comparisons = compute_comparisons(
            current_stats=overcast,
            historical_getter=self._get_overcast_analysis,
            year_month=year_month,
            metrics=['episodes_played', 'minutes_listened']
        )
        section = {
            'feeds_added': overcast['feeds_added'],
            'feeds_removed': overcast['feeds_removed'],
            'episodes_played': overcast['episodes_played'],
            'minutes_listened': overcast.get('minutes_listened', 0),
            'episodes': self._get_podcast_episodes(year_month),
            'source_time_analysis': self._get_source_time_analysis(self.overcast_db, year_month),
            'new_feeds': self._get_new_podcast_feeds(year_month),
            'comparisons': overcast_comparisons
        }
        return section

    def _apple_health_section(self, year_month: str) -> dict | None:
        apple_health = self._get_apple_health_analysis(year_month)
        if not apple_health:
            return None

        apple_health_comparisons = compute_comparisons(
            current_stats=apple_health,
            historical_getter=self._get_apple_health_analysis,
            year_month=year_month,
            metrics=['workouts', 'total_duration_seconds', 'total_calories']
        )
        section = {
            'workouts': apple_health['workouts'],
            'total_duration_seconds': apple_health['total_duration_seconds'],
            'total_calories': apple_health['total_calories'],
            'activity_breakdown': self._get_apple_health_activity_breakdown(year_month),
            'comparisons': apple_health_comparisons
        }
        return section

    def _strong_section(self, year_month: str) -> dict | None:
        return StrongAnalytics(db=self.strong_db).get_weightlifting_summary(year_month)

    def _blog_section(self, year_month: str) -> dict | None:
        blog = self._get_blog_analysis(year_month)
        if not blog:
            return None

        blog_comparisons = compute_comparisons(
            current_stats=blog,
            historical_getter=self._get_blog_analysis,
            year_month=year_month,
            metrics=['posts', 'total_words', 'unique_tags']
        )
        section = {
            'posts': blog['posts'],
            'total_words': blog['total_words'],
            'unique_tags': blog['unique_tags'],
            'top_tags': self._get_blog_top_tags(year_month),
            'comparisons': blog_comparisons,
        }
        return section

    def _hardcover_section(self, year_month: str) -> dict | None:
        hardcover = self._get_hardcover_analysis(year_month)
        if not hardcover:
            return None

        hardcover_comparisons = compute_comparisons(
            current_stats=hardcover,
            historical_getter=self._get_hardcover_analysis,
            year_month=year_month,
            metrics=['books_finished', 'avg_rating']
        )
        section = {
            'books_finished': hardcover['books_finished'],
            'avg_rating': hardcover['avg_rating'],
            'comparisons': hardcover_comparisons
        }
        return section

    def _github_section(self, year_month: str) -> dict | None:
        github = self._get_github_analysis(year_month)
        if not github:
            return None

        github_comparisons = compute_comparisons(
            current_stats=github,
            historical_getter=self._get_github_analysis,
            year_month=year_month,
            metrics=['commits', 'repos_touched', *VISIBILITY_METRICS, *LINE_CHANGE_METRICS]
        )
        section = {
            'commits': github['commits'],
            'repos_touched': github['repos_touched'],
            **{metric: github.get(metric) for metric in (*VISIBILITY_METRICS, *LINE_CHANGE_METRICS)},
            'commit_groups': self._group_commits_by_repo(
                self._get_github_commits(year_month)
            ),
            'new_repos': self._get_new_github_repos(year_month),
            'comparisons': github_comparisons
        }
        hours = self._get_github_hourly_activity(year_month)
        if hours:
            section['activity_chart'] = self._add_report_asset(
                year_month, 'commit-hours.svg', render_commit_hours(hours)
            )
        return section

    def _surfilog_section(self, year_month: str) -> dict | None:
        surfing = self._get_surfilog_analysis(year_month)
        if not surfing:
            return None

        metrics = [*SURFILOG_METRICS, *WAVE_MEDIAN_METRICS]
        section = {
            **{metric: surfing.get(metric) for metric in metrics},
            'comparisons': compute_comparisons(
                surfing, self._get_surfilog_analysis, year_month, metrics
            ),
        }
        return section

    def _kaya_section(self, year_month: str) -> dict | None:
        bouldering = self._get_kaya_analysis(year_month)
        if not bouldering:
            return None

        bouldering['grade_counts'] = json.loads(bouldering['grade_counts'])
        bouldering['comparisons'] = compute_comparisons(
            bouldering, self._get_kaya_analysis, year_month, ['climbing_days', 'sends']
        )
        section = bouldering
        return section

    def _oura_section(self, year_month: str) -> dict | None:
        oura = self._get_oura_analysis(year_month)
        if not oura:
            return None

        oura_comparisons = compute_comparisons(
            current_stats=oura,
            historical_getter=self._get_oura_analysis,
            year_month=year_month,
            metrics=['median_sleep_score', 'avg_sleep_score',
                     'median_readiness_score', 'avg_readiness_score']
        )
        section = {
            'median_sleep_score': oura.get('median_sleep_score'),
            'avg_sleep_score': oura.get('avg_sleep_score'),
            'median_readiness_score': oura.get('median_readiness_score'),
            'avg_readiness_score': oura.get('avg_readiness_score'),
            'comparisons': oura_comparisons
        }
        return section

    def _group_readwise_highlights(self, highlights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group Readwise highlights by article or book title."""
        groups: Dict[str, Dict[str, Any]] = {}

        for highlight in highlights:
            title = highlight.get('source_title') or "Untitled"
            if title not in groups:
                groups[title] = {
                    'title': title,
                    'category': highlight.get('source_category'),
                    'link': highlight.get('source_link'),
                    'highlights': [],
                }

            text = (highlight.get('text') or '').strip()
            note = (highlight.get('note') or '').strip()
            if text or note:
                groups[title]['highlights'].append({
                    'date': highlight.get('highlighted_at'),
                    'text': text,
                    'note': note,
                })

        return list(groups.values())

    def _group_commits_by_repo(self, commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group commits by repository."""
        groups: Dict[str, List[Dict[str, Any]]] = {}

        for commit in commits:
            repo = commit.get('repo') or "unknown"
            groups.setdefault(repo, []).append(commit)

        return [
            {'repo': repo, 'commits': repo_commits}
            for repo, repo_commits in groups.items()
        ]
