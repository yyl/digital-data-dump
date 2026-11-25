"""Publish the latest Apple Health workout to the blog homepage."""

import json

from github import GithubException

from ..config import Config
from ..publish.github_client import GitHubClient
from .database import AppleHealthDatabase


SNAPSHOT_PATH = "data/activity/latest_workout.json"


def latest_workout_snapshot(db: AppleHealthDatabase) -> dict | None:
    """Read the latest public workout from the canonical workout table."""
    with db.read_connection(required_tables=("workouts",)) as conn:
        if conn is None:
            return None
        workout = conn.execute("""
            SELECT activity_type, duration_seconds, date(started_at) AS day
            FROM workouts
            WHERE activity_type != 'walk' AND julianday(started_at) IS NOT NULL
            ORDER BY julianday(started_at) DESC, id DESC
            LIMIT 1
        """).fetchone()
    if workout is None:
        return None

    activity = workout["activity_type"]
    title = "HIIT" if activity == "hiit" else activity.capitalize()
    seconds = workout["duration_seconds"]
    detail = ""
    if seconds >= 60:
        detail = f"{seconds // 60} min"
    elif seconds > 0:
        detail = f"{seconds} sec"
    return {"title": title, "detail": detail, "date": workout["day"]}


def publish_latest_workout(*, dry_run: bool = False) -> None:
    snapshot = latest_workout_snapshot(AppleHealthDatabase())
    if snapshot is None:
        print("No Apple Health workout eligible for the blog.")
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
    message = "chore: sync latest Apple Health workout"
    try:
        current = client.repo.get_contents(SNAPSHOT_PATH, ref=client.target_branch)
    except GithubException as error:
        if error.status != 404:
            raise
        result = client.repo.create_file(SNAPSHOT_PATH, message, content, branch=client.target_branch)
    else:
        if json.loads(current.decoded_content) == snapshot:
            print("The latest workout snapshot is up to date.")
            return
        result = client.repo.update_file(SNAPSHOT_PATH, message, content, current.sha, branch=client.target_branch)
    print(f"Published the workout snapshot to {result['commit'].html_url}")
