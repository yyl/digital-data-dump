"""Database manager for GitHub activity data."""

from typing import Optional, Dict, Any, List, Iterable, Set

from ..config import Config
from ..database import BaseDatabase
from . import models


class GitHubDatabase(BaseDatabase):
    """SQLite database manager for GitHub commits."""

    source_name = 'GitHub'
    raw_table_names = frozenset({'commits'})
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager.
        
        Args:
            db_path: Path to SQLite database. Defaults to config value.
        """
        super().__init__(str(db_path or Config.CODEBASE_DATABASE_PATH))
    
    def init_tables(self) -> None:
        """Create raw sync tables if they don't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(models.CREATE_COMMITS_TABLE)
            columns = {row["name"] for row in cursor.execute("PRAGMA table_info(commits)")}
            if "is_private" not in columns:
                # Older versions synced public repositories only.
                cursor.execute(
                    "ALTER TABLE commits ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0"
                )
            if "is_discoverable" not in columns:
                cursor.execute(
                    "ALTER TABLE commits ADD COLUMN is_discoverable INTEGER NOT NULL DEFAULT 1"
                )
        print(f"GitHub database initialized at: {self.db_path}")

    def update_repo_visibility(self, repos: List[Dict[str, Any]]) -> None:
        """Refresh visibility for stored commits, even when no new commits exist.

        Hide details for repos no longer discoverable, preserving their last
        known visibility for public/private historical totals.
        """
        with self.get_connection() as conn:
            conn.execute("UPDATE commits SET is_discoverable = 0")
            conn.executemany(
                "UPDATE commits SET is_private = ?, is_discoverable = 1 "
                "WHERE repo = ? COLLATE NOCASE",
                ((int(repo.get("private", True)), repo["full_name"]) for repo in repos),
            )
    
    def upsert_commit(self, commit: Dict[str, Any]) -> None:
        """Insert or update a commit.
        
        Args:
            commit: Dictionary with sha, repo, message, author_date, date_month,
                and optional is_private (defaults to False for legacy callers).
        """
        self.upsert_commits([commit])

    def upsert_commits(self, commits: List[Dict[str, Any]]) -> None:
        """Insert or update multiple commits.

        Args:
            commits: List of dictionaries with sha, repo, message, author_date, date_month.
        """
        if not commits:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO commits (sha, repo, message, author_date, date_month, is_private)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha) DO UPDATE SET
                    repo = excluded.repo,
                    message = excluded.message,
                    author_date = excluded.author_date,
                    date_month = excluded.date_month,
                    is_private = excluded.is_private
            """, (
                (
                    c["sha"],
                    c["repo"],
                    c.get("message"),
                    c["author_date"],
                    c["date_month"],
                    int(c.get("is_private", False)),
                ) for c in commits
            ))
    
    def get_latest_commit_date(self, repo: str) -> Optional[str]:
        """Get the latest commit date for a repo (for incremental sync).
        
        Args:
            repo: Repository in owner/name format.
            
        Returns:
            ISO timestamp of latest commit, or None.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(author_date) FROM commits WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

    def get_existing_shas(self, shas: Iterable[str]) -> Set[str]:
        """Return the subset of commit SHAs already present in the database."""
        sha_list = [sha for sha in shas if sha]
        if not sha_list:
            return set()

        placeholders = ", ".join("?" for _ in sha_list)
        query = f"SELECT sha FROM commits WHERE sha IN ({placeholders})"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(sha_list))
            return {row[0] for row in cursor.fetchall()}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM commits")
            commits_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT repo) FROM commits")
            repos_count = cursor.fetchone()[0]
            
            return {
                "commits": commits_count,
                "repos": repos_count,
            }
