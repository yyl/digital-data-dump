# digital-data-dump

[![Tests](https://github.com/yyl/digital-data-dump/actions/workflows/tests.yml/badge.svg)](https://github.com/yyl/digital-data-dump/actions/workflows/tests.yml)

`digital-data-dump` collects data from personal services, analyzes it by month, and generates a draft markdown wrap-up post plus activity data files for a blog.

## What This Repo Does

- Syncs data from supported sources into local SQLite databases
- Computes monthly metrics for each source
- Generates a draft monthly report post
- Regenerates monthly activity YAML files used by the blog

If you want source-by-source setup details, see [docs/SOURCES.md](docs/SOURCES.md).

If you want the report format and layout, see [docs/SUMMARY.md](docs/SUMMARY.md).

If you want developer and implementation details, see [src/README.md](src/README.md).

## Setup

```bash
uv python install $(cat .python-version)
uv sync
cp .env.example .env
```

Then edit `.env` with the credentials you need for the sources you want to use.

## Basic Usage

Run commands with:

```bash
uv run main.py <command>
```

### Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize all databases |
| `sync` | Sync all supported sources |
| `analyze` | Recompute monthly analysis for all supported sources |
| `publish` | Generate and publish a draft monthly report |
| `backfill` | Refresh analysis and regenerate blog activity YAML files |
| `status` | Show current sync status |
| `{source}-sync` | Sync one source |
| `{source}-analyze` | Analyze one source |

## Common Workflows

### Sync Everything

```bash
uv run main.py sync
```

### Recompute Monthly Analysis

```bash
uv run main.py analyze
```

### Preview the Monthly Report Locally

```bash
uv run main.py publish --dry-run
```

### Publish the Monthly Report

```bash
uv run main.py publish
```

Useful publish flags:

- `--dry-run`: render the report locally without publishing
- `--skip-sync-analysis`: publish from existing analysis data
- `--last-month`: publish the previous month instead of the latest available one

### Regenerate Activity Data Files

```bash
uv run main.py backfill
```

`backfill` refreshes source analysis, commits full-history activity files to the data repo, and commits a blog copy limited to the rolling one-year lookback window to the configured blog repo.

## Required Publishing Config

To publish the markdown report to the data repo, set:

- `DATA_REPO_GITHUB_TOKEN` (preferred), `DATA_REPO_PAT`, or `BLOG_GITHUB_TOKEN` (legacy fallback)
- `DATA_REPO_OWNER`
- `DATA_REPO_NAME`
- `DATA_GITHUB_TARGET_BRANCH` (optional, defaults to `main`)
- `DATA_REPO_POSTS_DIR` (optional, defaults to `posts`)

To also publish the rolling one-year activity files to the blog repo during `backfill`, set:

- `BLOG_GITHUB_TOKEN`
- `BLOG_REPO_OWNER`
- `BLOG_REPO_NAME`
- `BLOG_GITHUB_TARGET_BRANCH` (optional, defaults to `main`)

Optional:

- `BLOG_POSTS_INDEX_URL` for blog post tracking

## GitHub Actions

This repo includes a monthly GitHub Actions workflow so the pipeline can run automatically or on demand.

- Scheduled run: last day of each month at `11:00 AM UTC`
- Manual run: open the workflow in the Actions tab and use the workflow inputs

For source setup details, see [docs/SOURCES.md](docs/SOURCES.md). For developer-oriented deployment details, see [src/README.md](src/README.md).
