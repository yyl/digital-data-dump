#!/usr/bin/env python3
"""
Digital Footprint Dump - Main Entry Point

Export your digital footprints to local SQLite databases.

Usage:
    python main.py init              # Initialize all databases
    python main.py sync              # Sync all services
    python main.py analyze           # Analyze all sources
    python main.py readwise-sync     # Sync Readwise only
    python main.py readwise-analyze  # Analyze Readwise archive
    python main.py foursquare-sync   # Sync Foursquare only
    python main.py letterboxd-sync   # Import Letterboxd data
    python main.py letterboxd-analyze # Analyze Letterboxd movies
    python main.py overcast-sync     # Import Overcast data
    python main.py overcast-analyze  # Analyze Overcast podcasts
    python main.py strong-sync       # Import Strong workout data
    python main.py strong-analyze    # Analyze Strong workouts
    python main.py apple-health-sync # Import Apple Health workouts
    python main.py apple-health-analyze # Analyze Apple Health workouts
    python main.py blog-sync         # Sync public blog posts
    python main.py blog-analyze      # Analyze published blog posts
    python main.py hardcover-sync    # Sync Hardcover books
    python main.py hardcover-analyze # Analyze Hardcover books
    python main.py github-sync       # Sync GitHub commits
    python main.py github-analyze    # Analyze GitHub activity
    python main.py oura-sync         # Sync Oura Ring data
    python main.py oura-analyze      # Analyze Oura Ring daily summaries
    python main.py schwab-sync       # Sync Charles Schwab accounts
    python main.py schwab-analyze    # Analyze Schwab monthly P&L
    python main.py workflowy-sync    # Sync Workflowy nodes
    python main.py publish           # Publish monthly report to data repo
    python main.py publish --dry-run # Validate config without publishing
    python main.py publish --skip-sync-analysis # Publish from current analysis data
    python main.py backfill          # Commit activity data files to configured repos
    python main.py status            # Show sync status
"""

import sys
import argparse
from src.config import Config


def run_analysis(
    sync_func,
    db_cls,
    analytics_cls,
    service_name: str,
    analysis_method: str,
    db_filename: str,
    check_tables_exist: bool = False
):
    """Generic helper to run analysis for a service."""
    # Ensure latest data
    if sync_func:
        sync_func()

    print(f"Analyzing {service_name}...")

    db = db_cls() if db_cls else None

    if db and hasattr(db, 'init_tables'):
        db.init_tables()

    if check_tables_exist and db and hasattr(db, 'check_tables_exist'):
        if not db.check_tables_exist():
            print(f"Error: {service_name.split()[0]} database tables not found.")
            print(f"Please run 'python main.py {service_name.split()[0].lower()}-sync' first to populate the database.")
            sys.exit(1)

    if db:
        analytics = analytics_cls(db=db)
    else:
        analytics = analytics_cls()

    method = getattr(analytics, analysis_method)
    record_count = method()

    print(f"Analysis complete! {record_count} monthly records written to the analysis table in {db_filename}")


def cmd_init():
    """Initialize all databases."""
    print("Initializing databases...\n")
    
    # Readwise
    from src.readwise.database import ReadwiseDatabase
    db = ReadwiseDatabase()
    db.init_tables()
    
    # Foursquare
    from src.foursquare.database import FoursquareDatabase
    fsq_db = FoursquareDatabase()
    fsq_db.init_tables()
    
    # Letterboxd
    from src.letterboxd.database import LetterboxdDatabase
    lbxd_db = LetterboxdDatabase()
    lbxd_db.init_tables()
    
    # Strong
    from src.strong.database import StrongDatabase
    strong_db = StrongDatabase()
    strong_db.init_tables()

    # Apple Health
    from src.apple_health.database import AppleHealthDatabase
    apple_health_db = AppleHealthDatabase()
    apple_health_db.init_tables()

    # Blog
    from src.blog.database import BlogDatabase
    blog_db = BlogDatabase()
    blog_db.init_tables()
    
    # Hardcover
    from src.hardcover.database import HardcoverDatabase
    hc_db = HardcoverDatabase()
    hc_db.init_tables()
    
    # GitHub
    from src.github.database import GitHubDatabase
    gh_db = GitHubDatabase()
    gh_db.init_tables()
    
    # Oura
    from src.oura.database import OuraDatabase
    oura_db = OuraDatabase()
    oura_db.init_tables()

    # Charles Schwab
    from src.schwab.database import SchwabDatabase
    schwab_db = SchwabDatabase()
    schwab_db.init_tables()

    # Workflowy
    from src.workflowy.database import WorkflowyDatabase
    workflowy_db = WorkflowyDatabase()
    workflowy_db.init_tables()
    
    print("\nDone!")


def cmd_readwise_sync():
    """Sync Readwise data only."""
    try:
        Config.validate_readwise()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    from src.readwise.api_client import ReadwiseAPIClient
    from src.readwise.database import ReadwiseDatabase
    from src.readwise.sync import SyncManager
    
    api = ReadwiseAPIClient()
    
    print("Validating Readwise access token...")
    if not api.validate_token():
        print("Error: Invalid Readwise access token. Please check your .env file.")
        sys.exit(1)
    print("Token validated!\n")
    
    db = ReadwiseDatabase()
    db.init_tables()
    
    sync_manager = SyncManager(db=db, api=api)
    sync_manager.sync_all()


def cmd_readwise_analyze():
    """Analyze Readwise archived articles."""
    from src.readwise.database import ReadwiseDatabase
    from src.readwise.analytics import ReadwiseAnalytics

    run_analysis(
        sync_func=cmd_readwise_sync,
        db_cls=ReadwiseDatabase,
        analytics_cls=ReadwiseAnalytics,
        service_name="Readwise archive",
        analysis_method="analyze_archived",
        db_filename="readwise.db",
        check_tables_exist=True
    )


def cmd_publish(dry_run: bool = False, skip_sync_analysis: bool = False, last_month: bool = False):
    """Publish monthly summary to the data repository.
    
    Args:
        dry_run: If True, validate config and sync data but skip actual publish.
        skip_sync_analysis: If True, reuse current analysis data without rerunning sync/analyze.
        last_month: If True, publish the summary for the previous month.
    """
    if dry_run:
        print("=== DRY RUN MODE ===")
        print("Generating markdown preview...\n")
        
        from src.publish import Publisher
        
        try:
            publisher = Publisher()
            markdown = publisher.generate_markdown(last_month=last_month)
            
            print("=" * 60)
            print(markdown)
            print("=" * 60)
            print("\n=== DRY RUN COMPLETE ===")
            print("No changes were made. Use 'publish' without --dry-run to publish.")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
        return

    if not skip_sync_analysis:
        # First ensure we have the latest analysis from all sources
        print("=== Updating Analysis ===\n")

        print("--- Readwise ---")
        cmd_readwise_analyze()

        print("\n--- Letterboxd ---")
        cmd_letterboxd_analyze()

        print("\n--- Foursquare ---")
        cmd_foursquare_analyze()

        print("\n--- Overcast ---")
        cmd_overcast_analyze()

        print("\n--- Strong ---")
        cmd_strong_analyze()

        print("\n--- Apple Health ---")
        cmd_apple_health_analyze()

        print("\n--- Blog ---")
        cmd_blog_analyze()

        print("\n--- Hardcover ---")
        cmd_hardcover_analyze()

        print("\n--- GitHub ---")
        cmd_github_analyze()

        print("\n--- Oura ---")
        try:
            Config.validate_oura()
            cmd_oura_analyze()
        except ValueError as e:
            print(f"Skipping Oura: {e}\n")
    else:
        print("=== Skipping Sync And Analysis ===")
        print("Publishing from current analysis data...\n")
    
    print("\n=== Publishing ===")
    print("Publishing monthly summary...")
    
    from src.publish import Publisher
    
    try:
        publisher = Publisher()
        result = publisher.publish(last_month=last_month)
        print(f"\nPublished successfully!")
        print(f"Commit: {result['url']}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_backfill():
    """Generate and commit Hugo data files to configured repositories."""
    # First ensure we have the latest analysis from all sources
    print("=== Updating Analysis ===\n")
    
    print("--- Readwise ---")
    cmd_readwise_analyze()
    
    print("\n--- Letterboxd ---")
    cmd_letterboxd_analyze()
    
    print("\n--- Foursquare ---")
    cmd_foursquare_analyze()
    
    print("\n--- Overcast ---")
    cmd_overcast_analyze()
    
    print("\n--- Strong ---")
    cmd_strong_analyze()

    print("\n--- Apple Health ---")
    cmd_apple_health_analyze()

    print("\n--- Blog ---")
    cmd_blog_analyze()

    print("\n--- Hardcover ---")
    cmd_hardcover_analyze()
    
    print("\n--- GitHub ---")
    cmd_github_analyze()
    
    print("\n--- Oura ---")
    try:
        Config.validate_oura()
        cmd_oura_analyze()
    except ValueError as e:
        print(f"Skipping Oura: {e}\n")
    
    print("\n=== Backfilling Data ===")
    print("Generating and committing data files...")
    
    from src.publish import Publisher
    
    try:
        publisher = Publisher()
        result = publisher.backfill()
        print(f"\nBackfill complete!")
        print(
            "Full-history data repo commit "
            f"({result['data_repo']['message']}): {result['data_repo']['url']}"
        )
        print(f"Files: {', '.join(result['data_repo']['file_paths'])}")
        print(
            "Blog repo commit "
            f"(since {result['blog_start_year_month']}): {result['blog_repo']['url']}"
        )
        print(f"Files: {', '.join(result['blog_repo']['file_paths'])}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_foursquare_sync():
    """Sync Foursquare data only."""
    from src.foursquare.sync import FoursquareSyncManager
    
    sync_manager = FoursquareSyncManager()
    sync_manager.sync()


def cmd_foursquare_analyze():
    """Analyze Foursquare checkins."""
    from src.foursquare.database import FoursquareDatabase
    from src.foursquare.analytics import FoursquareAnalytics

    run_analysis(
        sync_func=cmd_foursquare_sync,
        db_cls=FoursquareDatabase,
        analytics_cls=FoursquareAnalytics,
        service_name="Foursquare checkins",
        analysis_method="analyze_checkins",
        db_filename="foursquare.db"
    )


def cmd_letterboxd_sync():
    """Import Letterboxd data from CSV export."""
    from src.letterboxd.importer import LetterboxdImporter
    
    importer = LetterboxdImporter()
    importer.sync()


def cmd_letterboxd_analyze():
    """Analyze Letterboxd watched movies."""
    from src.letterboxd.database import LetterboxdDatabase
    from src.letterboxd.analytics import LetterboxdAnalytics

    run_analysis(
        sync_func=cmd_letterboxd_sync,
        db_cls=LetterboxdDatabase,
        analytics_cls=LetterboxdAnalytics,
        service_name="Letterboxd movies",
        analysis_method="analyze_watched",
        db_filename="letterboxd.db"
    )


def cmd_analyze():
    """Analyze all sources."""
    print("=== Analyzing All Sources ===\n")
    
    # Readwise
    print("--- Readwise ---")
    try:
        from src.readwise.database import ReadwiseDatabase
        from src.readwise.analytics import ReadwiseAnalytics
        
        # Sync first
        cmd_readwise_sync()
        
        db = ReadwiseDatabase()
        analytics = ReadwiseAnalytics(db=db)
        count = analytics.analyze_archived()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Foursquare
    print("--- Foursquare ---")
    try:
        from src.foursquare.database import FoursquareDatabase
        from src.foursquare.analytics import FoursquareAnalytics
        
        # Sync first
        cmd_foursquare_sync()
        
        db = FoursquareDatabase()
        db.init_tables()
        analytics = FoursquareAnalytics(db=db)
        count = analytics.analyze_checkins()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Letterboxd
    print("--- Letterboxd ---")
    try:
        from src.letterboxd.database import LetterboxdDatabase
        from src.letterboxd.analytics import LetterboxdAnalytics
        
        # Sync first
        cmd_letterboxd_sync()
        
        db = LetterboxdDatabase()
        db.init_tables()
        analytics = LetterboxdAnalytics(db=db)
        count = analytics.analyze_watched()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Overcast
    print("--- Overcast ---")
    try:
        from src.overcast.analytics import OvercastAnalytics
        
        # Sync first
        cmd_overcast_sync()
        
        analytics = OvercastAnalytics()
        count = analytics.analyze_podcasts()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Strong
    print("--- Strong ---")
    try:
        from src.strong.database import StrongDatabase
        from src.strong.analytics import StrongAnalytics
        
        # Sync first
        cmd_strong_sync()
        
        db = StrongDatabase()
        db.init_tables()
        analytics = StrongAnalytics(db=db)
        count = analytics.analyze_workouts()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()

    # Apple Health
    print("--- Apple Health ---")
    try:
        from src.apple_health.database import AppleHealthDatabase
        from src.apple_health.analytics import AppleHealthAnalytics

        cmd_apple_health_sync()

        db = AppleHealthDatabase()
        db.init_tables()
        analytics = AppleHealthAnalytics(db=db)
        count = analytics.analyze_workouts()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()

    # Blog
    print("--- Blog ---")
    try:
        from src.blog.analytics import BlogAnalytics
        from src.blog.database import BlogDatabase

        cmd_blog_sync()

        db = BlogDatabase()
        db.init_tables()
        analytics = BlogAnalytics(db=db)
        count = analytics.analyze_posts()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")

    print()
    
    # Hardcover
    print("--- Hardcover ---")
    try:
        from src.hardcover.database import HardcoverDatabase
        from src.hardcover.analytics import HardcoverAnalytics
        
        # Sync first
        cmd_hardcover_sync()
        
        db = HardcoverDatabase()
        analytics = HardcoverAnalytics(db=db)
        count = analytics.analyze_books()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # GitHub
    print("--- GitHub ---")
    try:
        from src.github.database import GitHubDatabase
        from src.github.analytics import GitHubAnalytics
        
        # Sync first
        cmd_github_sync()
        
        gh_db = GitHubDatabase()
        gh_analytics = GitHubAnalytics(db=gh_db)
        count = gh_analytics.analyze_commits()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    print("\n--- Oura ---")
    try:
        from src.oura.database import OuraDatabase
        from src.oura.analytics import OuraAnalytics

        # Sync first
        Config.validate_oura()
        cmd_oura_sync()

        oura_db = OuraDatabase()
        oura_analytics = OuraAnalytics(db=oura_db)
        count = oura_analytics.analyze_daily_summaries()
        print(f"  {count} monthly records written")
    except Exception as e:
        print(f"  Error/skip: {e}")

    print("\n--- Charles Schwab ---")
    try:
        Config.validate_schwab()
        cmd_schwab_analyze()
    except Exception as e:
        print(f"  Error/skip: {e}")

    print("\nAnalysis complete!")


def cmd_overcast_sync():
    """Import Overcast data from OPML export."""
    from src.overcast.importer import OvercastImporter
    
    importer = OvercastImporter()
    importer.sync()


def cmd_overcast_analyze():
    """Analyze Overcast podcast data."""
    from src.overcast.analytics import OvercastAnalytics

    run_analysis(
        sync_func=cmd_overcast_sync,
        db_cls=None,
        analytics_cls=OvercastAnalytics,
        service_name="Overcast podcasts",
        analysis_method="analyze_podcasts",
        db_filename="overcast.db"
    )


def cmd_strong_sync():
    """Import Strong workout data from CSV export."""
    from src.strong.importer import StrongImporter
    
    importer = StrongImporter()
    importer.sync()


def cmd_strong_analyze():
    """Analyze Strong workout data."""
    from src.strong.database import StrongDatabase
    from src.strong.analytics import StrongAnalytics

    run_analysis(
        sync_func=cmd_strong_sync,
        db_cls=StrongDatabase,
        analytics_cls=StrongAnalytics,
        service_name="Strong workouts",
        analysis_method="analyze_workouts",
        db_filename="strong.db"
    )


def cmd_apple_health_sync():
    """Import Apple Health workout data from export.xml."""
    from src.apple_health.importer import AppleHealthImporter

    importer = AppleHealthImporter()
    importer.sync()


def cmd_apple_health_analyze():
    """Analyze Apple Health workout data."""
    from src.apple_health.database import AppleHealthDatabase
    from src.apple_health.analytics import AppleHealthAnalytics

    run_analysis(
        sync_func=cmd_apple_health_sync,
        db_cls=AppleHealthDatabase,
        analytics_cls=AppleHealthAnalytics,
        service_name="Apple Health workouts",
        analysis_method="analyze_workouts",
        db_filename="apple_health.db"
    )


def cmd_blog_sync():
    """Sync public blog posts from the Hugo JSON export."""
    from src.blog.sync import BlogSyncManager

    sync_manager = BlogSyncManager()
    sync_manager.sync()


def cmd_blog_analyze():
    """Analyze published blog posts."""
    from src.blog.analytics import BlogAnalytics
    from src.blog.database import BlogDatabase

    run_analysis(
        sync_func=cmd_blog_sync,
        db_cls=BlogDatabase,
        analytics_cls=BlogAnalytics,
        service_name="Blog posts",
        analysis_method="analyze_posts",
        db_filename="blog.db",
    )


def cmd_hardcover_sync():
    """Sync Hardcover book data."""
    try:
        Config.validate_hardcover()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    from src.hardcover.sync import HardcoverSyncManager
    
    sync_manager = HardcoverSyncManager()
    sync_manager.sync()


def cmd_hardcover_analyze():
    """Analyze Hardcover book data."""
    from src.hardcover.database import HardcoverDatabase
    from src.hardcover.analytics import HardcoverAnalytics

    run_analysis(
        sync_func=cmd_hardcover_sync,
        db_cls=HardcoverDatabase,
        analytics_cls=HardcoverAnalytics,
        service_name="Hardcover books",
        analysis_method="analyze_books",
        db_filename="hardcover.db"
    )


def cmd_github_sync():
    """Sync GitHub commit data."""
    try:
        Config.validate_github_activity()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    from src.github.sync import GitHubSyncManager
    
    sync_manager = GitHubSyncManager()
    sync_manager.sync()


def cmd_oura_sync():
    """Sync Oura Ring data."""
    try:
        Config.validate_oura()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    from src.oura.sync import OuraSyncManager
    
    sync_manager = OuraSyncManager()
    sync_manager.sync()


def cmd_schwab_sync():
    """Sync Charles Schwab account data."""
    try:
        Config.validate_schwab()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    from src.schwab.sync import SchwabSyncManager

    sync_manager = SchwabSyncManager()
    sync_manager.sync()


def cmd_workflowy_sync():
    """Sync Workflowy nodes."""
    try:
        Config.validate_workflowy()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    from src.workflowy.sync import WorkflowySyncManager

    WorkflowySyncManager().sync()


def cmd_schwab_analyze():
    """Analyze Schwab monthly P&L and account snapshots from transactions."""
    from src.schwab.database import SchwabDatabase
    from src.schwab.analytics import SchwabAnalytics

    cmd_schwab_sync()

    print("Analyzing Schwab monthly P&L and account snapshots...")
    db = SchwabDatabase()
    db.init_tables()
    analytics = SchwabAnalytics(db=db)

    pnl_count = analytics.analyze_monthly_pnl()
    snap_count = analytics.analyze_monthly_snapshots()

    print(
        f"Analysis complete! {pnl_count} P&L records and "
        f"{snap_count} snapshot records written to schwab.db"
    )


def cmd_oura_analyze():
    """Analyze Oura Ring daily summaries."""
    from src.oura.database import OuraDatabase
    from src.oura.analytics import OuraAnalytics

    run_analysis(
        sync_func=cmd_oura_sync,
        db_cls=OuraDatabase,
        analytics_cls=OuraAnalytics,
        service_name="Oura Ring daily summaries",
        analysis_method="analyze_daily_summaries",
        db_filename="oura.db"
    )


def cmd_github_analyze():
    """Analyze GitHub commit data."""
    from src.github.database import GitHubDatabase
    from src.github.analytics import GitHubAnalytics

    run_analysis(
        sync_func=cmd_github_sync,
        db_cls=GitHubDatabase,
        analytics_cls=GitHubAnalytics,
        service_name="GitHub commits",
        analysis_method="analyze_commits",
        db_filename="github.db"
    )


def cmd_sync():
    """Sync all services."""
    print("=== Syncing All Services ===\n")
    
    # Readwise
    print("--- Readwise ---")
    try:
        Config.validate_readwise()
        cmd_readwise_sync()
    except ValueError as e:
        print(f"Skipping Readwise: {e}\n")
    
    print()
    
    # Foursquare
    print("--- Foursquare ---")
    cmd_foursquare_sync()
    
    print()
    
    # Letterboxd
    print("--- Letterboxd ---")
    cmd_letterboxd_sync()
    
    print()
    
    # Overcast
    print("--- Overcast ---")
    cmd_overcast_sync()
    
    print()
    
    # Strong
    print("--- Strong ---")
    cmd_strong_sync()
    
    print()

    # Apple Health
    print("--- Apple Health ---")
    cmd_apple_health_sync()

    print()

    # Blog
    print("--- Blog ---")
    cmd_blog_sync()

    print()
    
    # Hardcover
    print("--- Hardcover ---")
    try:
        Config.validate_hardcover()
        cmd_hardcover_sync()
    except ValueError as e:
        print(f"Skipping Hardcover: {e}\n")
    
    print()
    
    # GitHub
    print("--- GitHub ---")
    try:
        Config.validate_github_activity()
        cmd_github_sync()
    except ValueError as e:
        print(f"Skipping GitHub: {e}\n")
    
    print()
    
    # Oura
    print("--- Oura ---")
    try:
        Config.validate_oura()
        cmd_oura_sync()
    except ValueError as e:
        print(f"Skipping Oura: {e}\n")

    print()

    # Charles Schwab
    print("--- Charles Schwab ---")
    try:
        Config.validate_schwab()
        cmd_schwab_sync()
    except ValueError as e:
        print(f"Skipping Charles Schwab: {e}\n")

    print()

    # Workflowy
    print("--- Workflowy ---")
    try:
        Config.validate_workflowy()
        cmd_workflowy_sync()
    except ValueError as e:
        print(f"Skipping Workflowy: {e}\n")


def cmd_status():
    """Show sync status for all services."""
    print("=== Digital Footprint Status ===\n")
    
    # Readwise
    print("--- Readwise ---")
    try:
        from src.readwise.database import ReadwiseDatabase
        from src.readwise.sync import SyncManager
        
        db = ReadwiseDatabase()
        db.init_tables()
        sync_manager = SyncManager(db=db)
        status = sync_manager.get_sync_status()
        
        for entity, count in status["database_stats"].items():
            print(f"  {entity}: {count}")
        for entity, state in status["sync_states"].items():
            if state:
                print(f"  {entity} last synced: {state['last_sync_at']}")
            else:
                print(f"  {entity}: never synced")
        
        # Analysis status
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM analysis")
                analysis_count = cursor.fetchone()[0]
                cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                latest = cursor.fetchone()
            
            if analysis_count > 0 and latest:
                print(f"  analysis records: {analysis_count}")
                print(f"  latest analysis: {latest['year_month']} (updated: {latest['updated_at']})")
            else:
                print(f"  analysis: no records")
        except Exception:
            print(f"  analysis: no records")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Foursquare
    print("--- Foursquare ---")
    try:
        from src.foursquare.sync import FoursquareSyncManager
        
        sync_manager = FoursquareSyncManager()
        status = sync_manager.get_status()
        
        if "error" in status:
            print(f"  Error: {status['error']}")
        else:
            for entity, count in status.get("database_stats", {}).items():
                print(f"  {entity}: {count}")
            print(f"  has_token: {status.get('has_token', False)}")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Letterboxd
    print("--- Letterboxd ---")
    try:
        from src.letterboxd.importer import LetterboxdImporter
        from src.letterboxd.database import LetterboxdDatabase
        
        importer = LetterboxdImporter()
        status = importer.get_status()
        
        if "error" in status:
            print(f"  Error: {status['error']}")
        else:
            for entity, count in status.get("database_stats", {}).items():
                print(f"  {entity}: {count}")
            latest = status.get("latest_export")
            if latest:
                print(f"  latest_export: {latest.name}")
        
        # Analysis status
        db = LetterboxdDatabase()
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM analysis")
                analysis_count = cursor.fetchone()[0]
                cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                latest_analysis = cursor.fetchone()
            
            if analysis_count > 0 and latest_analysis:
                print(f"  analysis records: {analysis_count}")
                print(f"  latest analysis: {latest_analysis['year_month']} (updated: {latest_analysis['updated_at']})")
            else:
                print(f"  analysis: no records")
        except Exception:
            print(f"  analysis: no records")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Overcast
    print("--- Overcast ---")
    try:
        from src.overcast.importer import OvercastImporter
        
        importer = OvercastImporter()
        status = importer.get_status()
        
        for entity, count in status.get("database_stats", {}).items():
            print(f"  {entity}: {count}")
        latest = status.get("latest_export")
        if latest:
            print(f"  latest_export: {latest.name}")
        
        # Analysis status
        import sqlite3
        db_path = Config.OVERCAST_DATABASE_PATH
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM analysis")
                analysis_count = cursor.fetchone()[0]
                cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                latest_analysis = cursor.fetchone()
                
                if analysis_count > 0 and latest_analysis:
                    print(f"  analysis records: {analysis_count}")
                    print(f"  latest analysis: {latest_analysis['year_month']} (updated: {latest_analysis['updated_at']})")
                else:
                    print(f"  analysis: no records")
            except sqlite3.OperationalError:
                print(f"  analysis: no records")
            conn.close()
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Strong
    print("--- Strong ---")
    try:
        from src.strong.importer import StrongImporter
        from src.strong.database import StrongDatabase
        
        importer = StrongImporter()
        status = importer.get_status()
        
        if "error" in status:
            print(f"  Error: {status['error']}")
        else:
            for entity, count in status.get("database_stats", {}).items():
                print(f"  {entity}: {count}")
            latest = status.get("latest_export")
            if latest:
                print(f"  latest_export: {latest.name}")
        
        # Analysis status
        db = StrongDatabase()
        if db.exists():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM analysis")
                    analysis_count = cursor.fetchone()[0]
                    cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                    latest_analysis = cursor.fetchone()
                    
                    if analysis_count > 0 and latest_analysis:
                        print(f"  analysis records: {analysis_count}")
                        print(f"  latest analysis: {latest_analysis['year_month']} (updated: {latest_analysis['updated_at']})")
                    else:
                        print(f"  analysis: no records")
                except Exception:
                    print(f"  analysis: no records")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()

    # Apple Health
    print("--- Apple Health ---")
    try:
        from src.apple_health.importer import AppleHealthImporter
        from src.apple_health.database import AppleHealthDatabase

        importer = AppleHealthImporter()
        status = importer.get_status()

        if "error" in status:
            print(f"  Error: {status['error']}")
        else:
            for entity, count in status.get("database_stats", {}).items():
                print(f"  {entity}: {count}")
            latest = status.get("latest_export")
            if latest:
                print(f"  latest_export: {latest.name}")

        db = AppleHealthDatabase()
        if db.exists():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM analysis")
                    analysis_count = cursor.fetchone()[0]
                    cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                    latest_analysis = cursor.fetchone()

                    if analysis_count > 0 and latest_analysis:
                        print(f"  analysis records: {analysis_count}")
                        print(f"  latest analysis: {latest_analysis['year_month']} (updated: {latest_analysis['updated_at']})")
                    else:
                        print("  analysis: no records")
                except Exception:
                    print("  analysis: no records")
    except Exception as e:
        print(f"  Error: {e}")

    print()

    # Blog
    print("--- Blog ---")
    try:
        from src.blog.database import BlogDatabase
        from src.blog.sync import BlogSyncManager

        sync_manager = BlogSyncManager()
        status = sync_manager.get_status()

        for entity, count in status.get("database_stats", {}).items():
            print(f"  {entity}: {count}")
        print(f"  source_url: {status.get('source_url')}")
        latest_post = status.get("latest_post")
        if latest_post:
            print(f"  latest post: {latest_post['published_at']} — {latest_post['title']}")

        db = BlogDatabase()
        if db.exists():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM analysis")
                    analysis_count = cursor.fetchone()[0]
                    cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                    latest_analysis = cursor.fetchone()

                    if analysis_count > 0 and latest_analysis:
                        print(f"  analysis records: {analysis_count}")
                        print(f"  latest analysis: {latest_analysis['year_month']} (updated: {latest_analysis['updated_at']})")
                    else:
                        print("  analysis: no records")
                except Exception:
                    print("  analysis: no records")
    except Exception as e:
        print(f"  Error: {e}")

    print()
    
    # Hardcover
    print("--- Hardcover ---")
    try:
        from src.hardcover.database import HardcoverDatabase
        
        db = HardcoverDatabase()
        if db.exists():
            stats = db.get_stats()
            for entity, count in stats.items():
                print(f"  {entity}: {count}")
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM analysis")
                    analysis_count = cursor.fetchone()[0]
                    cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                    latest_analysis = cursor.fetchone()
                    
                    if analysis_count > 0 and latest_analysis:
                        print(f"  analysis records: {analysis_count}")
                        print(f"  latest analysis: {latest_analysis['year_month']} (updated: {latest_analysis['updated_at']})")
                    else:
                        print(f"  analysis: no records")
                except Exception:
                    print(f"  analysis: no records")
        else:
            print("  not initialized")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # GitHub
    print("--- GitHub ---")
    try:
        from src.github.database import GitHubDatabase
        
        db = GitHubDatabase()
        if db.exists():
            stats = db.get_stats()
            for entity, count in stats.items():
                print(f"  {entity}: {count}")
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM analysis")
                    analysis_count = cursor.fetchone()[0]
                    cursor.execute("SELECT year_month, updated_at FROM analysis ORDER BY year_month DESC LIMIT 1")
                    latest_analysis = cursor.fetchone()
                    
                    if analysis_count > 0 and latest_analysis:
                        print(f"  analysis records: {analysis_count}")
                        print(f"  latest analysis: {latest_analysis['year_month']} (updated: {latest_analysis['updated_at']})")
                    else:
                        print(f"  analysis: no records")
                except Exception:
                    print(f"  analysis: no records")
        else:
            print("  not initialized")
    except Exception as e:
        print(f"  Error: {e}")
    
    print()
    
    # Oura
    print("--- Oura ---")
    try:
        from src.oura.sync import OuraSyncManager
        
        sync_manager = OuraSyncManager()
        status = sync_manager.get_status()
        
        if "error" in status:
            print(f"  Error: {status['error']}")
        else:
            for entity, count in status.get("database_stats", {}).items():
                print(f"  {entity}: {count}")
            print(f"  has_token: {status.get('has_token', False)}")
            sync_dates = status.get("sync_dates", {})
            if sync_dates:
                for dtype, last_date in sync_dates.items():
                    print(f"  {dtype} last synced: {last_date}")
    except Exception as e:
        print(f"  Error: {e}")

    print()

    # Charles Schwab
    print("--- Charles Schwab ---")
    try:
        from src.schwab.sync import SchwabSyncManager

        sync_manager = SchwabSyncManager()
        status = sync_manager.get_status()

        if "error" in status:
            print(f"  Error: {status['error']}")
        else:
            for entity, count in status.get("database_stats", {}).items():
                print(f"  {entity}: {count}")
            print(f"  has_token: {status.get('has_token', False)}")
    except Exception as e:
        print(f"  Error: {e}")

    print()

    # Workflowy
    print("--- Workflowy ---")
    try:
        from src.workflowy.sync import WorkflowySyncManager

        status = WorkflowySyncManager().get_status()
        print(f"  active nodes: {status['active_nodes']}")
        print(f"  tombstoned nodes: {status['tombstoned_nodes']}")
        state = status["sync_state"]
        if state and state["last_successful_sync_at"]:
            print(f"  last synced: {state['last_successful_sync_at']}")
        else:
            print("  last synced: never")
    except Exception as e:
        print(f"  Error: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Digital Footprint Dump - Export your digital footprints to local SQLite databases.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Simple commands (no arguments)
    subparsers.add_parser("init", help="Initialize all databases")
    subparsers.add_parser("sync", help="Sync all services")
    subparsers.add_parser("analyze", help="Analyze all sources")
    subparsers.add_parser("readwise-sync", help="Sync Readwise only")
    subparsers.add_parser("readwise-analyze", help="Analyze Readwise archive")
    subparsers.add_parser("foursquare-sync", help="Sync Foursquare only")
    subparsers.add_parser("foursquare-analyze", help="Analyze Foursquare checkins")
    subparsers.add_parser("letterboxd-sync", help="Import Letterboxd data")
    subparsers.add_parser("letterboxd-analyze", help="Analyze Letterboxd movies")
    subparsers.add_parser("overcast-sync", help="Import Overcast data")
    subparsers.add_parser("overcast-analyze", help="Analyze Overcast podcasts")
    subparsers.add_parser("strong-sync", help="Import Strong workout data")
    subparsers.add_parser("strong-analyze", help="Analyze Strong workouts")
    subparsers.add_parser("apple-health-sync", help="Import Apple Health workout data")
    subparsers.add_parser("apple-health-analyze", help="Analyze Apple Health workouts")
    subparsers.add_parser("blog-sync", help="Sync public blog posts")
    subparsers.add_parser("blog-analyze", help="Analyze published blog posts")
    subparsers.add_parser("hardcover-sync", help="Sync Hardcover books")
    subparsers.add_parser("hardcover-analyze", help="Analyze Hardcover books")
    subparsers.add_parser("github-sync", help="Sync GitHub commits")
    subparsers.add_parser("github-analyze", help="Analyze GitHub activity")
    subparsers.add_parser("oura-sync", help="Sync Oura Ring data")
    subparsers.add_parser("oura-analyze", help="Analyze Oura Ring daily summaries")
    subparsers.add_parser("schwab-sync", help="Sync Charles Schwab accounts")
    subparsers.add_parser("schwab-analyze", help="Analyze Schwab monthly P&L")
    subparsers.add_parser("workflowy-sync", help="Sync Workflowy nodes")
    subparsers.add_parser("status", help="Show sync status")
    subparsers.add_parser("backfill", help="Commit activity data files to configured repos")
    
    # Publish command with --dry-run flag
    publish_parser = subparsers.add_parser("publish", help="Publish monthly summary to data repo")
    publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate markdown from current analysis data without syncing or publishing"
    )
    publish_parser.add_argument(
        "--skip-sync-analysis",
        action="store_true",
        help="Publish using the current analysis data without rerunning sync or analysis"
    )
    publish_parser.add_argument(
        "--last-month",
        action="store_true",
        help="Publish the report for the last month instead of the latest"
    )
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    commands = {
        "init": cmd_init,
        "sync": cmd_sync,
        "analyze": cmd_analyze,
        "readwise-sync": cmd_readwise_sync,
        "readwise-analyze": cmd_readwise_analyze,
        "foursquare-sync": cmd_foursquare_sync,
        "foursquare-analyze": cmd_foursquare_analyze,
        "letterboxd-sync": cmd_letterboxd_sync,
        "letterboxd-analyze": cmd_letterboxd_analyze,
        "overcast-sync": cmd_overcast_sync,
        "overcast-analyze": cmd_overcast_analyze,
        "strong-sync": cmd_strong_sync,
        "strong-analyze": cmd_strong_analyze,
        "apple-health-sync": cmd_apple_health_sync,
        "apple-health-analyze": cmd_apple_health_analyze,
        "blog-sync": cmd_blog_sync,
        "blog-analyze": cmd_blog_analyze,
        "hardcover-sync": cmd_hardcover_sync,
        "hardcover-analyze": cmd_hardcover_analyze,
        "github-sync": cmd_github_sync,
        "github-analyze": cmd_github_analyze,
        "oura-sync": cmd_oura_sync,
        "oura-analyze": cmd_oura_analyze,
        "schwab-sync": cmd_schwab_sync,
        "schwab-analyze": cmd_schwab_analyze,
        "workflowy-sync": cmd_workflowy_sync,
        "status": cmd_status,
    }
    
    if args.command == "publish":
        cmd_publish(
            dry_run=args.dry_run,
            skip_sync_analysis=args.skip_sync_analysis,
            last_month=args.last_month
        )
    elif args.command == "backfill":
        cmd_backfill()
    elif args.command in commands:
        commands[args.command]()
    else:
        print(f"Unknown command: {args.command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
