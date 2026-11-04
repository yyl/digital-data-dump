from pathlib import Path

from src.readwise.database import ReadwiseDatabase
from src.readwise.analytics import ReadwiseAnalytics
from src.foursquare.database import FoursquareDatabase
from src.foursquare.analytics import FoursquareAnalytics
from src.letterboxd.database import LetterboxdDatabase
from src.letterboxd.analytics import LetterboxdAnalytics
from src.strong.database import StrongDatabase
from src.strong.analytics import StrongAnalytics
from src.blog.database import BlogDatabase
from src.blog.analytics import BlogAnalytics
from src.hardcover.database import HardcoverDatabase
from src.hardcover.analytics import HardcoverAnalytics
from src.github.database import GitHubDatabase
from src.github.analytics import GitHubAnalytics
from src.schwab.database import SchwabDatabase
from src.workflowy.database import WorkflowyDatabase
from src.workflowy.analytics import WorkflowyAnalytics
from src.surfilog.database import SurfilogDatabase
from src.surfilog.analytics import SurfilogAnalytics


def _table_exists(db, table_name: str) -> bool:
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return cursor.fetchone() is not None


def test_sync_side_init_only_creates_raw_tables(tmp_path):
    dbs = [
        ReadwiseDatabase(str(tmp_path / "readwise.db")),
        FoursquareDatabase(str(tmp_path / "foursquare.db")),
        LetterboxdDatabase(str(tmp_path / "letterboxd.db")),
        StrongDatabase(str(tmp_path / "strong.db")),
        BlogDatabase(str(tmp_path / "blog.db")),
        HardcoverDatabase(str(tmp_path / "hardcover.db")),
        GitHubDatabase(str(tmp_path / "github.db")),
        SchwabDatabase(str(tmp_path / "schwab.db")),
        WorkflowyDatabase(str(tmp_path / "workflowy.db")),
        SurfilogDatabase(str(tmp_path / "surfilog.db")),
    ]

    for db in dbs:
        db.init_tables()
        assert _table_exists(db, "analysis") is False
        if isinstance(db, SchwabDatabase):
            assert _table_exists(db, "monthly_pnl") is False
            assert _table_exists(db, "monthly_account_snapshots") is False


def test_analytics_creates_analysis_tables_when_missing(tmp_path):
    cases = [
        (ReadwiseDatabase(str(tmp_path / "readwise.db")), ReadwiseAnalytics),
        (FoursquareDatabase(str(tmp_path / "foursquare.db")), FoursquareAnalytics),
        (LetterboxdDatabase(str(tmp_path / "letterboxd.db")), LetterboxdAnalytics),
        (StrongDatabase(str(tmp_path / "strong.db")), StrongAnalytics),
        (BlogDatabase(str(tmp_path / "blog.db")), BlogAnalytics),
        (HardcoverDatabase(str(tmp_path / "hardcover.db")), HardcoverAnalytics),
        (GitHubDatabase(str(tmp_path / "github.db")), GitHubAnalytics),
        (WorkflowyDatabase(str(tmp_path / "workflowy.db")), WorkflowyAnalytics),
        (SurfilogDatabase(str(tmp_path / "surfilog.db")), SurfilogAnalytics),
    ]

    for db, analytics_cls in cases:
        db.init_tables()
        assert _table_exists(db, "analysis") is False
        analytics = analytics_cls(db=db)
        method_name = [name for name in dir(analytics) if name.startswith("analyze_")][0]
        getattr(analytics, method_name)()
        assert _table_exists(db, "analysis") is True


def test_schwab_analytics_creates_schwab_analysis_tables_when_missing(tmp_path):
    from src.schwab.analytics import SchwabAnalytics
    db = SchwabDatabase(str(tmp_path / "schwab.db"))
    db.init_tables()
    assert _table_exists(db, "monthly_pnl") is False
    assert _table_exists(db, "monthly_account_snapshots") is False

    analytics = SchwabAnalytics(db=db)
    analytics.analyze_monthly_pnl()
    assert _table_exists(db, "monthly_pnl") is True
    assert _table_exists(db, "monthly_account_snapshots") is True

