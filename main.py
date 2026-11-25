#!/usr/bin/env python3
"""Collect, analyze, and publish personal activity data."""

import argparse
from functools import partial

from src.config import Config
from src.source_operations import Source, run_sources


def cmd_readwise_sync():
    """Sync Readwise data only."""
    Config.validate_readwise()

    from src.readwise.api_client import ReadwiseAPIClient
    from src.readwise.database import ReadwiseDatabase
    from src.readwise.sync import SyncManager

    api = ReadwiseAPIClient()

    print("Validating Readwise access token...")
    if not api.validate_token():
        raise ValueError("Invalid Readwise access token. Check your .env file.")
    print("Token validated!\n")

    db = ReadwiseDatabase()
    db.init_tables()

    sync_manager = SyncManager(db=db, api=api)
    return sync_manager.sync_all()


def cmd_foursquare_sync():
    """Sync Foursquare data only."""
    from src.foursquare.sync import FoursquareSyncManager

    sync_manager = FoursquareSyncManager()
    return sync_manager.sync()


def cmd_letterboxd_sync():
    """Import Letterboxd data from CSV export."""
    from src.letterboxd.importer import LetterboxdImporter

    importer = LetterboxdImporter()
    return importer.sync()


def cmd_overcast_sync():
    """Import Overcast data from OPML export."""
    from src.overcast.importer import OvercastImporter

    importer = OvercastImporter()
    return importer.sync()


def cmd_strong_sync(from_csv=False):
    """Sync Strong through the API, with explicit complete-CSV recovery."""
    from src.strong.sync import StrongSyncManager

    return StrongSyncManager().sync(from_csv=from_csv)


def cmd_apple_health_sync():
    """Import Apple Health workouts from immutable DDU JSON archives."""
    from src.apple_health.importer import AppleHealthImporter

    importer = AppleHealthImporter()
    stats = importer.sync()
    if not stats['success']:
        raise RuntimeError('Apple Health JSON sync requires attention; see the import summary and json_import_state.')
    return stats


def cmd_blog_sync():
    """Sync public blog posts from the Hugo JSON export."""
    from src.blog.sync import BlogSyncManager

    sync_manager = BlogSyncManager()
    return sync_manager.sync()


def cmd_hardcover_sync():
    """Sync Hardcover book data."""
    Config.validate_hardcover()

    from src.hardcover.sync import HardcoverSyncManager

    sync_manager = HardcoverSyncManager()
    return sync_manager.sync()


def cmd_github_sync():
    """Sync GitHub commit data."""
    Config.validate_github_activity()

    from src.github.sync import GitHubSyncManager

    sync_manager = GitHubSyncManager()
    return sync_manager.sync()


def cmd_oura_sync():
    """Sync Oura Ring data."""
    Config.validate_oura()

    from src.oura.sync import OuraSyncManager

    sync_manager = OuraSyncManager()
    return sync_manager.sync()


def cmd_schwab_sync():
    """Sync Charles Schwab account data."""
    Config.validate_schwab()

    from src.schwab.sync import SchwabSyncManager

    sync_manager = SchwabSyncManager()
    return sync_manager.sync()


def cmd_workflowy_sync():
    """Sync Workflowy nodes."""
    Config.validate_workflowy()

    from src.workflowy.sync import WorkflowySyncManager

    return WorkflowySyncManager().sync()


def cmd_surfilog_sync():
    """Log in and sync every session, individual wave, and GPS track."""
    from src.surfilog.sync import SurfilogSyncManager

    Config.validate_surfilog()
    return SurfilogSyncManager().sync()


def cmd_kaya_sync(csv_path=None):
    """Import an explicit Kaya export or discover local and DDU exports."""
    from src.kaya.importer import KayaImporter

    importer = KayaImporter()
    exports = [csv_path] if csv_path else importer.find_exports()
    if not exports:
        print("Skipping Kaya import: no local or DDU exports found in the files directory.")
        return
    count = sum(importer.sync(path) for path in exports)
    print(f"Added {count:,} new Kaya climbs.")
    return {"climbs": count}


def _analyze_schwab(db):
    from src.schwab.analytics import SchwabAnalytics

    analytics = SchwabAnalytics(db=db)
    return analytics.analyze_monthly_pnl() + analytics.analyze_monthly_snapshots()


def _status_row(conn, query):
    return dict(conn.execute(query).fetchone() or {}) if conn is not None else {}


def _status_export(path):
    return {"latest_export": path.name} if path is not None else {}


def _status_apple_health(conn):
    from src.apple_health.importer import AppleHealthImporter

    result = {"json_archives": len(AppleHealthImporter.find_json_archives())}
    if conn is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'json_import_state'").fetchone():
        result.update({f"workouts {state}": count for state, count in conn.execute(
            "SELECT status, COUNT(*) FROM json_import_state GROUP BY status ORDER BY status"
        )})
    return result


def _status_strong(conn):
    from src.strong.importer import StrongImporter

    result = _status_export(StrongImporter.find_latest_export())
    if conn is not None:
        result["source"] = "csv"
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sync_state'").fetchone():
            result.update(_status_row(conn, "SELECT source, last_successful_sync_at, weight_unit, timezone FROM sync_state"))
    return result


def _status_sync_dates(conn, query):
    if conn is None:
        return {}
    return {f"{name} last synced": timestamp for name, timestamp in conn.execute(query)}


def _strong_sync_options(parser):
    parser.add_argument("--csv", dest="from_csv", action="store_true",
                        help="Replace Strong history with the latest complete CSV export")


def _kaya_options(parser):
    parser.add_argument("csv_path", nargs="?", help="Path to a Kaya CSV export")


def source_catalog() -> tuple[Source, ...]:
    from src.apple_health.analytics import AppleHealthAnalytics
    from src.apple_health.database import AppleHealthDatabase
    from src.blog.analytics import BlogAnalytics
    from src.blog.database import BlogDatabase
    from src.foursquare.analytics import FoursquareAnalytics
    from src.foursquare.database import FoursquareDatabase
    from src.github.analytics import GitHubAnalytics
    from src.github.database import GitHubDatabase
    from src.hardcover.analytics import HardcoverAnalytics
    from src.hardcover.database import HardcoverDatabase
    from src.kaya.analytics import KayaAnalytics
    from src.kaya.database import KayaDatabase
    from src.letterboxd.analytics import LetterboxdAnalytics
    from src.letterboxd.database import LetterboxdDatabase
    from src.letterboxd.importer import LetterboxdImporter
    from src.oura.analytics import OuraAnalytics
    from src.oura.database import OuraDatabase
    from src.overcast.analytics import OvercastAnalytics
    from src.overcast.database import OvercastDatabase
    from src.overcast.importer import OvercastImporter
    from src.readwise.analytics import ReadwiseAnalytics
    from src.readwise.database import ReadwiseDatabase
    from src.schwab.database import SchwabDatabase
    from src.strong.analytics import StrongAnalytics
    from src.strong.database import StrongDatabase
    from src.surfilog.analytics import SurfilogAnalytics
    from src.surfilog.database import SurfilogDatabase
    from src.workflowy.analytics import WorkflowyAnalytics
    from src.workflowy.database import WorkflowyDatabase

    return (
        Source("readwise", "Readwise", ReadwiseDatabase, cmd_readwise_sync,
               lambda db: ReadwiseAnalytics(db).analyze_archived(), Config.validate_readwise,
               status_details=lambda conn: _status_sync_dates(
                   conn, "SELECT entity_type, last_sync_at FROM sync_state ORDER BY entity_type")),
        Source("foursquare", "Foursquare", FoursquareDatabase, cmd_foursquare_sync,
               lambda db: FoursquareAnalytics(db).analyze_checkins(),
               status_details=lambda _: {"has_token": bool(Config.FOURSQUARE_ACCESS_TOKEN)}),
        Source("letterboxd", "Letterboxd", LetterboxdDatabase, cmd_letterboxd_sync,
               lambda db: LetterboxdAnalytics(db).analyze_watched(),
               status_details=lambda _: _status_export(LetterboxdImporter.find_latest_export())),
        Source("overcast", "Overcast", OvercastDatabase, cmd_overcast_sync,
               lambda db: OvercastAnalytics(db).analyze_podcasts(), initialize=False,
               status_details=lambda _: _status_export(OvercastImporter.find_latest_export())),
        Source("strong", "Strong", StrongDatabase, cmd_strong_sync,
               lambda db: StrongAnalytics(db).analyze_workouts(), status_details=_status_strong,
               sync_options=_strong_sync_options),
        Source("apple-health", "Apple Health", AppleHealthDatabase, cmd_apple_health_sync,
               lambda db: AppleHealthAnalytics(db).analyze_workouts(), status_details=_status_apple_health),
        Source("blog", "Blog", BlogDatabase, cmd_blog_sync,
               lambda db: BlogAnalytics(db).analyze_posts(),
               status_details=lambda conn: {
                   "source_url": Config.BLOG_POSTS_INDEX_URL,
                   **_status_row(conn, """
                       SELECT published_at AS latest_post_date, title AS latest_post
                       FROM posts ORDER BY datetime(published_at) DESC, permalink ASC LIMIT 1
                   """),
               }),
        Source("hardcover", "Hardcover", HardcoverDatabase, cmd_hardcover_sync,
               lambda db: HardcoverAnalytics(db).analyze_books(), Config.validate_hardcover),
        Source("github", "GitHub", GitHubDatabase, cmd_github_sync,
               lambda db: GitHubAnalytics(db).analyze_commits(), Config.validate_github_activity),
        Source("oura", "Oura", OuraDatabase, cmd_oura_sync,
               lambda db: OuraAnalytics(db).analyze_daily_summaries(), Config.validate_oura,
               optional_for_reporting=True, status_details=lambda conn: {
                   "has_token": bool(Config.OURA_ACCESS_TOKEN),
                   **_status_sync_dates(conn, "SELECT data_type, last_sync_date FROM sync_state ORDER BY data_type"),
               }),
        Source("schwab", "Charles Schwab", SchwabDatabase, cmd_schwab_sync,
               _analyze_schwab, Config.validate_schwab,
               status_details=lambda _: {"has_token": bool(Config.SCHWAB_ACCESS_TOKEN)}),
        Source("workflowy", "Workflowy", WorkflowyDatabase, cmd_workflowy_sync,
               lambda db: WorkflowyAnalytics(db).analyze_nodes(), Config.validate_workflowy,
               status_details=lambda conn: {
                   **_status_row(conn, "SELECT last_successful_sync_at FROM sync_state"),
                   **_status_row(conn, "SELECT COUNT(*) FILTER (WHERE is_deleted = 0) AS active_nodes, "
                                      "COUNT(*) FILTER (WHERE is_deleted = 1) AS tombstoned_nodes FROM nodes"),
               }),
        Source("surfilog", "Surfilog", SurfilogDatabase, cmd_surfilog_sync,
               lambda db: SurfilogAnalytics(db).analyze_sessions(), Config.validate_surfilog,
               optional_for_reporting=True, status_details=lambda conn: {
                   **_status_row(conn, "SELECT last_successful_sync_at FROM sync_state"),
                   **_status_row(conn, "SELECT COUNT(*) FILTER (WHERE is_excluded = 0) AS waves, "
                                      "COUNT(*) FILTER (WHERE is_excluded = 1) AS excluded_waves FROM waves"),
               }),
        Source("kaya", "Kaya", KayaDatabase, cmd_kaya_sync,
               lambda db: KayaAnalytics(db).analyze_climbs(),
               status_details=lambda conn: _status_row(conn, "SELECT MAX(local_date) AS latest_climb FROM climbs"),
               sync_options=_kaya_options, refresh_options=_kaya_options),
    )


def cmd_github_analyze():
    next(source for source in source_catalog() if source.key == "github").refresh()


def cmd_kaya_analyze(csv_path=None):
    next(source for source in source_catalog() if source.key == "kaya").refresh(csv_path=csv_path)


def cmd_analyze(*, local=False):
    return run_sources(source_catalog(), "analyze" if local else "refresh")


REPORT_SOURCES = (
    "readwise", "letterboxd", "foursquare", "overcast", "strong", "apple-health",
    "blog", "hardcover", "github", "oura", "surfilog", "kaya",
)


def refresh_report_sources() -> bool:
    sources = {source.key: source for source in source_catalog()}
    return run_sources((sources[key] for key in REPORT_SOURCES), "refresh", reporting=True)


def cmd_publish(*, dry_run=False, skip_sync_analysis=False, last_month=False):
    from src.publish import Publisher

    if dry_run:
        publisher = Publisher()
        markdown = publisher.generate_markdown(last_month=last_month)
        preview = publisher.save_preview(markdown)
        print(markdown)
        print(f"Preview saved to {preview}")
        return True

    if not skip_sync_analysis and not refresh_report_sources():
        return False
    result = Publisher().publish(last_month=last_month)
    print(f"Published draft: {result['url']}")
    return True


def cmd_backfill(*, skip_sync_analysis=False):
    from src.publish import Publisher

    if not skip_sync_analysis and not refresh_report_sources():
        return False
    result = Publisher().backfill()
    print(f"Full-history data repo commit: {result['data_repo']['url']}")
    print(f"Blog repo commit (since {result['blog_start_year_month']}): {result['blog_repo']['url']}")
    return True


def cmd_pipeline(*, last_month=False, skip_sync_analysis=False):
    from src.publish import Publisher

    if not skip_sync_analysis and not refresh_report_sources():
        return False
    result = Publisher().publish_pipeline(last_month=last_month)
    print(f"Published draft: {result['draft']['url']}")
    print(f"Full-history data repo commit: {result['data_repo']['url']}")
    print(f"Blog repo commit (since {result['blog_start_year_month']}): {result['blog_repo']['url']}")
    return True


def cmd_status(*, sources):
    success = True
    for source in sources:
        print(f"\n--- {source.name} ---")
        try:
            for key, value in source.status().items():
                if value is not None:
                    print(f"  {key}: {value}")
        except Exception as error:
            success = False
            print(f"  Error: {error}")
    return success


def _add_source_commands(subparsers, source):
    for suffix, operation, verb, add_options in (
        ("sync", source.sync, "Sync", source.sync_options),
        ("analyze", source.refresh, "Sync and analyze", source.refresh_options),
    ):
        command = subparsers.add_parser(f"{source.key}-{suffix}", help=f"{verb} {source.name}")
        command.set_defaults(operation=operation)
        if add_options:
            add_options(command)
        if suffix == "analyze":
            command.add_argument("--local", dest="local_only", action="store_true",
                                 help="Recompute from local data without syncing")
            command.set_defaults(local_analysis=source.analyze_local)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect, analyze, and publish personal activity data.")
    commands = parser.add_subparsers(required=True)
    sources = source_catalog()

    for name, help_text, operation in (
        ("init", "Initialize source databases", partial(run_sources, sources, "init")),
        ("sync", "Sync configured sources", partial(run_sources, sources, "sync")),
        ("status", "Show source database and sync status", partial(cmd_status, sources=sources)),
    ):
        commands.add_parser(name, help=help_text).set_defaults(operation=operation)

    analyze = commands.add_parser("analyze", help="Sync and analyze configured sources")
    analyze.add_argument("--local", action="store_true", help="Recompute from local data without syncing")
    analyze.set_defaults(operation=cmd_analyze)

    publish = commands.add_parser("publish", help="Publish the monthly draft report")
    publish.add_argument("--dry-run", action="store_true", help="Write a preview from local data")
    publish.add_argument("--skip-sync-analysis", action="store_true", help="Use current analysis")
    publish.add_argument("--last-month", action="store_true", help="Select the previous calendar month")
    publish.set_defaults(operation=cmd_publish)

    backfill = commands.add_parser("backfill", help="Publish the activity data files")
    backfill.add_argument("--skip-sync-analysis", action="store_true", help="Use current analysis")
    backfill.set_defaults(operation=cmd_backfill)

    pipeline = commands.add_parser("pipeline", help="Refresh once and publish the draft and activity files")
    pipeline.add_argument("--last-month", action="store_true", help="Select the previous calendar month")
    pipeline.add_argument("--skip-sync-analysis", action="store_true", help="Use current analysis")
    pipeline.set_defaults(operation=cmd_pipeline)

    from src.overcast.activity_snapshot import publish_latest_podcast

    overcast_latest = commands.add_parser("overcast-publish-latest", help="Publish the latest played episode to the blog")
    overcast_latest.add_argument("--dry-run", action="store_true", help="Preview the snapshot without updating GitHub")
    overcast_latest.set_defaults(operation=publish_latest_podcast)

    for source in sources:
        _add_source_commands(commands, source)

    options = vars(parser.parse_args(argv))
    operation = options.pop("operation")
    local_analysis = options.pop("local_analysis", None)
    local_only = options.pop("local_only", False)
    try:
        if local_only:
            if options.get("csv_path") is not None:
                parser.error("a CSV path requires a sync and cannot be used with --local")
            local_analysis()
            return 0
        return int(operation(**options) is False)
    except Exception as error:
        print(f"Error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
