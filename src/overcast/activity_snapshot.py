"""Refresh the blog's latest played podcast from D3's Overcast sources."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from github import GithubException

from ..config import Config
from ..publish.github_client import GitHubClient
from .database import OvercastDatabase
from .importer import OvercastImporter


SNAPSHOT_PATH = "data/activity/latest_podcast.json"


def _episode_time(episode: dict) -> datetime:
    timestamp = datetime.fromisoformat(episode["date"])
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _refresh_snapshot() -> dict | None:
    with TemporaryDirectory() as directory:
        imported = OvercastDatabase(str(Path(directory) / "overcast.db"))
        stats = OvercastImporter(imported).sync(enrich_durations=False)
        latest_import = imported.latest_played_episode() if stats is not None else None
        candidates = (latest_import, OvercastDatabase().latest_played_episode())

    snapshot = max(
        (episode for episode in candidates if episode),
        key=_episode_time,
        default=None,
    )
    if snapshot:
        snapshot["date"] = _episode_time(snapshot).isoformat()
        if not re.fullmatch(r"https://overcast\.fm/\+[A-Za-z0-9_-]+", snapshot["url"] or ""):
            snapshot["url"] = ""
    return snapshot


def publish_latest_podcast(*, dry_run: bool = False) -> None:
    snapshot = _refresh_snapshot()
    if not snapshot:
        print("No played Overcast episode found.")
        return

    content = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if dry_run:
        print(content, end="")
        return

    Config.validate_github()
    client = GitHubClient(
        token=Config.BLOG_GITHUB_TOKEN,
        repo_owner=Config.BLOG_REPO_OWNER,
        repo_name=Config.BLOG_REPO_NAME,
        target_branch=Config.BLOG_GITHUB_TARGET_BRANCH,
    )
    try:
        existing = json.loads(client.repo.get_contents(SNAPSHOT_PATH, ref=client.target_branch).decoded_content)
    except GithubException as error:
        if error.status != 404:
            raise
        existing = {}

    if snapshot == existing:
        print("The latest podcast snapshot is up to date.")
        return
    if existing.get("date") and _episode_time(existing) > _episode_time(snapshot):
        print("The blog already has a newer Overcast episode.")
        return

    result = client.create_or_update_files({SNAPSHOT_PATH: content}, "chore: sync latest played podcast")
    print(f"Published the podcast snapshot to {result['url']}")
