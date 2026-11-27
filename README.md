# digital-data-dump

[![Tests](https://github.com/yyl/digital-data-dump/actions/workflows/tests.yml/badge.svg)](https://github.com/yyl/digital-data-dump/actions/workflows/tests.yml)

`digital-data-dump` collects data from personal services, analyzes it by month, and generates a draft markdown wrap-up post plus activity data files for a blog.

## What This Repo Does

- Syncs data from supported sources into local SQLite databases
- Computes monthly metrics for each source
- Generates a draft monthly report post
- Regenerates monthly activity YAML files used by the blog

If you want source-by-source setup details, see [docs/SOURCES.md](docs/SOURCES.md).

For the iPhone Apple Health, Strong, and Kaya upload workflows, see [docs/SHORTCUTS.md](docs/SHORTCUTS.md).

If you want the report format and layout, see [docs/SUMMARY.md](docs/SUMMARY.md).

For developer details, including how to register a source and its outputs, see
the [source integration guide](src/README.md#adding-or-changing-a-source).

For metric calculation rules and how changes are tracked, see
[metric definitions](src/README.md#metric-definitions-and-changes).

For a history of changes and their rationale, see [docs/JOURNAL.md](docs/JOURNAL.md).

## Setup

```bash
uv python install $(cat .python-version)
uv sync
cp .env.example .env
```

Then edit `.env` with the credentials for the sources you want to use.

## Basic Usage

Run commands with:

```bash
uv run main.py <command>
```

### Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize raw schemas that D3 manages |
| `sync` | Sync configured sources |
| `analyze` | Sync configured sources and recompute monthly analysis, or use `--local` to analyze existing data |
| `publish` | Generate and publish a draft monthly report |
| `backfill` | Refresh analysis and regenerate blog activity YAML files |
| `pipeline` | Refresh the reporting sources once and publish the draft and activity YAML files |
| `status` | Show current sync status |
| `{source}-sync` | Sync one source (see [docs/SOURCES.md](docs/SOURCES.md) for source names) |
| `{source}-analyze` | Sync and analyze one source, or use `--local` to analyze existing data |
| `overcast-publish-latest` | Refresh the blog’s latest played podcast card (`--dry-run` to preview) |
| `apple-health-publish-latest` | Refresh the blog’s latest workout card (`--dry-run` to preview) |
| `apple-health-import-heart-breathing [xml_path]` | Import individual heart and breathing samples from Apple Health XML |
| `surfilog-import-strava` | Import unimported Strava surfing sessions into Surfilog (`--dry-run`, `--since YYYY-MM-DD`, `--sport-type`) |
| `strong-sync --csv` | Replace Strong history from a complete local CSV export instead of API sync |
| `kaya-sync [csv_path]` / `kaya-analyze [csv_path]` | Import a specific Kaya CSV export (defaults to auto-discovered local/vault exports) |

## Common Workflows

### Sync Everything

```bash
uv run main.py sync
```

Aggregate `sync` and `analyze` attempt independent sources and return a nonzero
exit status if a selected operation fails. Check each source’s setup in
[SOURCES.md](docs/SOURCES.md).

### Recompute Monthly Analysis

```bash
uv run main.py analyze --local
```

Use `--local` to recompute from stored data without contacting providers. The
flag also works on individual commands such as `oura-analyze`.

### Preview the Monthly Report Locally

```bash
uv run main.py publish --dry-run
```

The dry run also saves the post and image assets to
`.cache/report-preview/index.md` for local review.

### Publish the Monthly Report

```bash
uv run main.py publish
```

Useful publish flags:

- `--dry-run`: render the report locally without publishing
- `--skip-sync-analysis`: publish from existing analysis data
- `--last-month`: publish the previous calendar month when report data is available for it

The dry run reads existing source databases and skips sync and analysis. See
[report data availability](docs/SUMMARY.md#high-level-layout) for how missing
or unreadable inputs affect generation.

### Regenerate Activity Data Files

```bash
uv run main.py backfill
```

`backfill` refreshes the reporting sources and publishes both
[activity export windows](docs/SUMMARY.md#activity-data-files).

Use `backfill --skip-sync-analysis` or `pipeline --skip-sync-analysis` to retry
delivery from existing analysis.

## Required Publishing Config

To publish the markdown report to the data repo, set:

- `DATA_REPO_GITHUB_TOKEN` (preferred), `DATA_REPO_PAT`, or `BLOG_GITHUB_TOKEN` (legacy fallback)
- `DATA_REPO_OWNER`
- `DATA_REPO_NAME`
- `DATA_GITHUB_TARGET_BRANCH` (optional, defaults to `main`)
- `DATA_REPO_POSTS_DIR` (optional, defaults to `posts`)

To also publish the rolling one-year activity files during `backfill`/`pipeline` and the daily homepage cards (`overcast-publish-latest`, `apple-health-publish-latest`) to the blog repo, set:

- `BLOG_GITHUB_TOKEN`
- `BLOG_REPO_OWNER`
- `BLOG_REPO_NAME`
- `BLOG_GITHUB_TARGET_BRANCH` (optional, defaults to `main`)

Optional:

- `BLOG_POSTS_INDEX_URL` for blog post tracking

## GitHub Actions

This repo includes GitHub Actions workflows for automated runs and manual triggers:

- **Monthly Pipeline** (`.github/workflows/monthly-pipeline.yml`): runs on the 1st of each month at `6:00 AM Pacific` (`America/Los_Angeles`, automatically adjusting for PDT/PST) with `pipeline --last-month`, and supports manual runs from the Actions tab via workflow inputs.
- **Daily Overcast Card** (`.github/workflows/overcast-activity.yml`): runs daily at `08:25 UTC` (`overcast-publish-latest`) to refresh the blog's latest played podcast card.
- **Daily Apple Health Card** (`.github/workflows/apple-health-activity.yml`): runs daily at `08:45 UTC` (`apple-health-sync` followed by `apple-health-publish-latest`) to refresh the blog's latest workout card.
- **Daily Surfilog Strava Import** (`.github/workflows/surfilog-strava-import.yml`): runs daily at `09:15 UTC` (`surfilog-import-strava`) to pull unimported Strava surfing sessions into Surfilog.
- **Schwab Sync** (`.github/workflows/schwab-sync.yml`): isolated manual (`workflow_dispatch`) workflow running `schwab-analyze` (scheduled runs are currently paused).

For source setup details, see [docs/SOURCES.md](docs/SOURCES.md). For developer-oriented deployment details, see [src/README.md](src/README.md).
