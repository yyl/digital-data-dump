"""SQLite database manager for blog post tracking."""

from typing import Any, Dict, List, Optional

from ..config import Config
from ..database import BaseDatabase
from .models import RAW_INDEXES, RAW_TABLES


class BlogDatabase(BaseDatabase):
    """Manages SQLite storage for blog posts and tags."""

    source_name = 'Blog'
    raw_table_names = frozenset({'posts', 'post_tags'})

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager."""
        super().__init__(db_path or str(Config.BLOG_DATABASE_PATH))
        self.use_foreign_keys = True

    def init_tables(self) -> None:
        """Create raw sync tables if they do not exist."""
        is_new = not self.exists()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table_sql in RAW_TABLES:
                cursor.execute(table_sql)
            for index_sql in RAW_INDEXES:
                cursor.execute(index_sql)

        if is_new:
            print(f"Blog database initialized at: {self.db_path}")

    def replace_posts(self, posts: List[Dict[str, Any]]) -> int:
        """Replace the current raw snapshot with the latest published posts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM post_tags")
            cursor.execute("DELETE FROM posts")

            if not posts:
                return 0

            cursor.executemany(
                """
                INSERT INTO posts (
                    permalink, title, published_at, last_modified_at, slug,
                    word_count, reading_time, summary, section, draft
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        post["permalink"],
                        post["title"],
                        post["published_at"],
                        post.get("last_modified_at"),
                        post.get("slug"),
                        post.get("word_count", 0),
                        post.get("reading_time", 0),
                        post.get("summary"),
                        post.get("section"),
                        1 if post.get("draft") else 0,
                    )
                    for post in posts
                ],
            )

            tag_rows = []
            for post in posts:
                for tag in post.get("tags", []):
                    tag_rows.append((post["permalink"], tag))

            if tag_rows:
                cursor.executemany(
                    """
                    INSERT INTO post_tags (permalink, tag)
                    VALUES (?, ?)
                    """,
                    tag_rows,
                )

        return len(posts)

    def get_stats(self) -> Dict[str, int]:
        """Get raw table counts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            stats = {}
            for table in ["posts", "post_tags"]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            return stats
