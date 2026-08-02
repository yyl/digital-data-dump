# Source Modules

This document is the developer-oriented guide to how the codebase works.

It covers architecture, storage layout, per-source implementation patterns, analysis tables, publishing, backfill behavior, and deployment details that are useful when modifying the repo.

## Project Structure

Note: the tree below is shown from the repository root.

```text
├── main.py                 # CLI entry point
├── src/
│   ├── config.py           # Environment configuration and storage resolution
│   ├── database.py         # Base SQLite connection manager
│   ├── comparison.py       # Shared MoM/YoY comparison helpers
│   ├── time_utils.py       # UTC timestamp helpers
│   ├── readwise/
│   ├── foursquare/
│   ├── letterboxd/
│   ├── overcast/
│   ├── strong/
│   ├── apple_health/
│   ├── blog/
│   ├── hardcover/
│   ├── github/
│   ├── oura/
│   └── publish/
├── docs/
├── tests/
└── .github/workflows/
```

## Storage Resolution

The app does not always read and write data from this repo directly.

It resolves a storage root, then uses:

- `<storage-root>/data/` for SQLite databases
- `<storage-root>/files/` for file imports

Resolution order:

1. `DATA_REPO_LOCAL_PATH` if set
2. sibling repo `../digital-footprint-data` if it exists
3. this repo itself

That means local development often uses:

- `/.../digital-footprint-data/data/*.db`
- `/.../digital-footprint-data/files/*`

GitHub Actions checks out the private data repo separately and links its `data/` and `files/` into the workspace.

## Local and CI Consistency

The repo pins Python in `.python-version`.

Recommended validation:

```bash
make test-ci
```

That command installs the pinned Python version with `uv`, syncs dependencies, and runs `pytest` with the same interpreter used by CI.

For markdown generation changes, also run:

```bash
uv run main.py publish --dry-run
```

## Module Pattern

Each source generally follows the same structure:

| File | Purpose |
|------|---------|
| `models.py` | SQL schema definitions |
| `database.py` | Source-specific database manager |
| `api_client.py` | External API wrapper for API-backed sources |
| `sync.py` | Sync orchestration for API-backed sources |
| `importer.py` | File import path for file-backed sources |
| `analytics.py` | Monthly rollups written into `analysis` |

Raw data tables are created during sync/import setup. Derived monthly `analysis` tables are owned by each source's `analytics.py`.

## Source Types

| Type | Sources | Ingestion Path |
|------|---------|----------------|
| API-backed | Readwise, Foursquare, Blog, Hardcover, GitHub, Oura, Schwab | `api_client.py` + `sync.py` |
| File-backed | Letterboxd, Overcast, Strong, Apple Health | `importer.py` |

Letterboxd is hybrid in practice: it uses RSS for incremental sync, plus CSV export seeding when the DB is empty.

## Publish Module

The `src/publish/` package contains the publishing layer.

| File | Purpose |
|------|---------|
| `publisher.py` | Orchestrates data fetch, comparisons, report assembly, and publish flow |
| `markdown_generator.py` | Renders the monthly markdown report |
| `data_generator.py` | Generates `data/activity/*.yaml` files from analysis tables |
| `github_client.py` | Writes report/data files to GitHub using PyGithub |

## Publish and Backfill Flows

### Publish

Supported paths:

- `publish`: sync all sources, analyze all sources, generate the report, commit the draft post to the data repo under `posts/`
- `publish --skip-sync-analysis`: generate the report from existing analysis data
- `publish --dry-run`: render the report locally only
- `publish --last-month`: publish the previous month instead of the latest available month

The publish flow scans the available analysis DBs and chooses the latest available `YYYY-MM`, while tolerating optional sources that may be missing. Report drafts are written to `DATA_REPO_POSTS_DIR` in the data repo, which defaults to `posts`.

### Backfill

`backfill` regenerates activity data files twice: the full-history set goes to the data repo, and a second set limited to the rolling one-year lookback window goes to the blog repo under `data/activity/`.

It does that by running each source's analyze command, and those analyze commands in turn refresh raw source data first through their paired sync path.

Current activity files:

| File | Source | Fields |
|------|--------|--------|
| `reading.yaml` | Readwise | `articles_archived`, `total_words`, `time_spent_minutes`, `avg_reading_speed`, `max_words_per_article`, `median_words_per_article`, `min_words_per_article` |
| `travel.yaml` | Foursquare | `checkins`, `unique_places` |
| `movies.yaml` | Letterboxd | `movies_watched`, `minutes_watched`, `avg_rating` |
| `podcasts.yaml` | Overcast | `feeds_added`, `feeds_removed`, `episodes_played`, `minutes_listened` |
| `workouts.yaml` | Apple Health | `workouts`, `total_minutes`, `total_calories` |
| `writing.yaml` | Blog | `posts`, `total_words`, `unique_tags` |
| `books.yaml` | Hardcover | `books_finished`, `avg_rating` |
| `code.yaml` | GitHub | `commits`, `repos_touched` |
| `sleep.yaml` | Oura Ring | `median_sleep_score`, `avg_sleep_score`, `median_readiness_score`, `avg_readiness_score` |

Published workout metrics come from Apple Health monthly analysis. Strong is still importable and analyzable, but it is not the published workout source.

## Source-Specific Technical Notes

### Readwise

- Syncs Reader documents plus associated metadata into `readwise.db`
- Analysis computes article counts, total words, reading time, and article-length stats
- Reading speed comparison in the published report is derived rather than stored directly in the analysis table

#### Source Resolution

The published report groups articles by source name. Readwise populates `site_name` for web articles, but forwarded-email newsletters (e.g. Money Stuff, Benedict's Newsletter) arrive with `site_name = NULL`. Rather than maintaining a hardcoded mapping, the publisher resolves source names with a fallback chain:

1. **`site_name`** — use the Readwise-provided value when present
2. **Title prefix** — the substring before the first `:` in the title. Newsletter emails almost always follow a `Name: Subject` pattern (e.g. `Money Stuff: SpaceX Crash Insurance` → `Money Stuff`)
3. **`author`** — the raw author string as a last resort (works for clean names like `Emma Goto`)
4. **`None`** — falls through to the "Other" bucket

This is zero-maintenance: any new forwarded newsletter with a `Name: Subject` title pattern is automatically recognized without code changes.

### Foursquare

- Uses the Foursquare v2 API for core checkin/user data
- Can optionally enrich venue details through the Places API when `FOURSQUARE_API_KEY` is configured

### Letterboxd

Letterboxd uses a hybrid ingestion model:

- historical seed from CSV export in `files/letterboxd-*`
- incremental updates from public RSS via `LETTERBOXD_RSS_URL`

Important implementation details:

- CSV and RSS data are deduplicated by checking whether the same movie name already exists within a `+/- 2 day` watch-date window
- RSS entries are normalized from user-specific film links to canonical film URLs when possible
- `watched` stores enriched metadata fields:
  - `tmdb_id`
  - `runtime_minutes`
  - `metadata_updated_at`
- If `TMDB_ACCESS_TOKEN` or `TMDB_API_KEY` is configured, `letterboxd-sync` performs a TMDB enrichment pass after import/sync
- The TMDB enrichment path prefers exact title plus exact year, then falls back to exact title with a `+/- 1` year window
- If runtime enrichment still fails, sync prints the unmatched movie titles

Letterboxd analysis writes:

- `movies_watched`
- `minutes_watched`
- `avg_rating`
- `min_rating`
- `max_rating`
- `avg_years_since_release`

`minutes_watched` is computed from the summed `watched.runtime_minutes` values available for that month.

### Overcast

- Supports direct OPML export fetch when `OVERCAST_COOKIE` or `OVERCAST_EMAIL` plus `OVERCAST_PASSWORD` are configured
- `OVERCAST_COOKIE` is the `o` cookie from an authenticated Overcast browser session; alternatively, `OVERCAST_EMAIL` and `OVERCAST_PASSWORD` let the importer log in and obtain that cookie
- Falls back to `files/overcast*.opml` import otherwise
- `overcast-sync` also fetches missing episode durations from live RSS feeds using title matching
- Those duration lookups populate `episodes.duration_seconds`, which enables monthly `minutes_listened`

### Strong

- Imports Strong CSV workout exports into `strong.db`
- Still has its own analysis path for workout/exercise/set metrics
- No longer drives the published workout section

### Apple Health

- Imports workouts from `export.xml`
- Monthly analysis is the source of truth for the published workout section and `workouts.yaml`

### Blog

- Syncs from a public Hugo JSON index rather than writing to the blog repo directly
- The `Writing` report section and `writing.yaml` come from blog analysis

### Hardcover

- Uses the Hardcover GraphQL API
- Tracks finished books and monthly average rating

### GitHub

- Syncs commit history from owned public repositories
- Uses an inclusive timestamp cursor plus SHA deduplication so same-second commits are not skipped
- Publishing uses PyGithub and retries branch update races when necessary

### Oura Ring

- Syncs daily health summaries from the Oura v2 REST API into `oura.db`
- Uses OAuth2 authorization code flow; tokens are persisted to `.env` and refreshed automatically on 401
- Fetches seven daily summary types: activity, sleep, readiness, stress, resilience, SpO2, cardiovascular age
- Nested `contributors` objects in the API response are flattened into columns (e.g., `contributors.deep_sleep` → `contributor_deep_sleep`)
- Incremental sync uses a `sync_state` table tracking the last synced date per data type
- **Gen 2 vs Gen 3 hardware limitation**: Resilience, SpO2, and cardiovascular age endpoints return 401 on Gen 2 rings or accounts without an active Oura membership. These are detected after one token-refresh attempt and skipped gracefully with a user-facing message instead of retrying
- Cursor-based pagination via `next_token` query parameter handles large historical fetches
- Analysis aggregates daily sleep and readiness scores into monthly medians and averages
- `publish` includes a "Sleep & Readiness" section with MoM/YoY comparisons
- `backfill` generates `sleep.yaml` activity files

### Charles Schwab

- Syncs account balance snapshots and trade transactions from the Schwab Trader API into `schwab.db`
- Uses OAuth2 authorization code flow; tokens are persisted to `.env` and refreshed automatically on 401 when a refresh token is available
- Calls `/accounts/accountNumbers` to map plain account numbers to Schwab account hashes, then uses those hashes for account-scoped transaction requests
- Calls `/accounts` once per sync and inserts a new `account_snapshots` row for each returned account
- **Snapshot dedup**: skips writing a new snapshot if the most recent one for that account is less than 24 hours old, so repeated same-day syncs don't create redundant rows (controlled by `SNAPSHOT_MIN_INTERVAL_HOURS`)
- Calls `/accounts/{accountNumber}/transactions` per account hash and upserts transactions by account hash plus `activityId`
- Fetches a one-year transaction window for a new account hash, then uses the latest stored transaction timestamp with a one-day overlap for later syncs
- Stores common searchable transaction fields as columns and preserves the full transaction response as JSON for later analysis
- This source is sync-only for now; no monthly analysis or publish output is generated yet

## Database Schemas

Each source has a separate SQLite database under `<storage-root>/data/`.

### Common Analysis Table Shape

Every source's `analysis` table has:

- `year_month` as a `YYYY-MM` primary key
- `year`
- `month`
- source-specific metrics
- `updated_at`

### Per-Source Databases

#### Readwise (`readwise.db`)

Data tables:

- `books`
- `highlights`
- `highlight_tags`
- `book_tags`
- `documents`
- `document_tags`
- `sync_state`

Analysis fields:

- `articles`
- `words`
- `reading_time_mins`
- `max_words_per_article`
- `median_words_per_article`
- `min_words_per_article`

#### Foursquare (`foursquare.db`)

Data tables:

- `users`
- `places`
- `checkins`
- `sync_state`

Views:

- `checkins_with_places`
- `user_stats`

Analysis fields:

- `checkins`
- `unique_places`

#### Letterboxd (`letterboxd.db`)

Data tables:

- `users`
- `watched`
- `ratings`

`watched` also stores:

- `tmdb_id`
- `runtime_minutes`
- `metadata_updated_at`

Analysis fields:

- `movies_watched`
- `minutes_watched`
- `avg_rating`
- `min_rating`
- `max_rating`
- `avg_years_since_release`

#### Overcast (`overcast.db`)

Primary tables are created by `overcast-to-sqlite`:

- `feeds`
- `episodes`
- `playlists`

Analysis fields:

- `feeds_added`
- `feeds_removed`
- `episodes_played`
- `minutes_listened`

#### Strong (`strong.db`)

Data tables:

- `workouts`
- `exercises`

Analysis fields:

- `workouts`
- `total_duration_seconds`
- `unique_exercises`
- `total_sets`

#### Apple Health (`apple_health.db`)

Data tables:

- `workouts`

Analysis fields:

- `workouts`
- `total_duration_seconds`
- `total_calories`

#### Blog (`blog.db`)

Data tables:

- `posts`
- `post_tags`

Analysis fields:

- `posts`
- `total_words`
- `unique_tags`

#### Hardcover (`hardcover.db`)

Data tables:

- `books`

Analysis fields:

- `books_finished`
- `avg_rating`

#### GitHub (`github.db`)

Data tables:

- `commits`

Analysis fields:

- `commits`
- `repos_touched`

#### Oura Ring (`oura.db`)

Data tables:

- `daily_activity`
- `daily_sleep`
- `daily_readiness`
- `daily_stress`
- `daily_resilience`
- `daily_spo2`
- `daily_cardiovascular_age`
- `sync_state`

`daily_activity`, `daily_sleep`, `daily_readiness`, and `daily_resilience` flatten nested `contributors` objects into `contributor_*` columns.

`daily_resilience`, `daily_spo2`, and `daily_cardiovascular_age` may remain empty on Gen 2 hardware or accounts without an active Oura membership.

Analysis fields:

- `median_sleep_score`
- `avg_sleep_score`
- `median_readiness_score`
- `avg_readiness_score`

(Uses a normalized schema with `year_month`, `source_table`, `metric` as composite primary key, pivoted into these columns during publish/backfill.)

#### Charles Schwab (`schwab.db`)

Data tables:

- `account_snapshots`
- `transactions`
- `transaction_items`
- `sync_state`

`account_snapshots` is append-only by design. Each sync run writes one dated snapshot per account hash with balance JSON blobs and a few common balance fields such as equity, liquidation value, cash balance, and buying power.

`transactions` stores one row per `(account_hash, activityId)` with top-level fields extracted and the full Schwab response in `raw_json`. No column changes are needed here — the child table carries the detail.

`transaction_items` explodes the `transferItems` array from each transaction into individual rows. Each row is keyed by `(account_hash, transaction_id, item_index)` with a `FOREIGN KEY` back to `transactions`. Extracted columns:

| Column | Source | Notes |
|---|---|---|
| `asset_type` | `instrument.assetType` | EQUITY, COLLECTIVE_INVESTMENT, CURRENCY, … |
| `instrument_id` | `instrument.instrumentId` | Schwab internal ID |
| `symbol` | `instrument.symbol` | Ticker; CURRENCY_USD for fee legs |
| `description` | `instrument.description` | Human-readable name |
| `instrument_type` | `instrument.type` | EXCHANGE_TRADED_FUND, COMMON_STOCK, … |
| `closing_price` | `instrument.closingPrice` | Previous close at time of trade |
| `amount` | `amount` | Shares / units |
| `cost` | `cost` | Dollar cost of this leg (negative = outflow) |
| `price` | `price` | Execution price per unit; NULL for fee legs |
| `fee_type` | `feeType` | COMMISSION, SEC_FEE, TAF_FEE, OPT_REG_FEE; NULL for trade legs |
| `position_effect` | `positionEffect` | OPENING / CLOSING; NULL for fee legs |
| `raw_json` | — | Full JSON of this `transferItems` element |

Fee legs (COMMISSION, SEC_FEE, etc.) are stored with `asset_type = CURRENCY` and `fee_type` populated. Filter them out in queries with `WHERE fee_type IS NULL`.

Analysis fields (`monthly_pnl` table, keyed by `(year_month, account_hash)`):

| Column | Description |
|---|---|
| `total_buy_cost` | Sum of `cost` for OPENING trade legs (negative = cash out) |
| `total_sell_proceeds` | Sum of `cost` for CLOSING trade legs (positive = cash in) |
| `net_cash_flow` | `total_sell_proceeds + total_buy_cost` — net cash flow for the month |
| `total_fees` | Sum of `ABS(cost)` for fee legs (COMMISSION, SEC_FEE, TAF_FEE, …) |
| `trade_count` | Number of non-fee trade legs this month |
| `opening_count` | Number of OPENING (buy) legs |
| `closing_count` | Number of CLOSING (sell) legs |
| `unique_symbols` | Distinct tickers traded this month |

Run `uv run main.py schwab-analyze` to populate. `net_cash_flow` is a cash-flow approximation of realized P&L; true P&L would require a separate cost-basis ledger.

## Comparisons

`src/comparison.py` contains the shared MoM and YoY comparison helpers used by publish.

Sources currently surfaced in the published report use comparisons for these metrics:

| Source | Metrics |
|--------|---------|
| Readwise | articles, words, reading time, derived reading speed |
| Foursquare | checkins, unique places |
| Letterboxd | movies watched, average rating |
| Overcast | episodes played, minutes listened |
| Apple Health | workouts, total duration, total calories |
| Blog | posts, total words, unique tags |
| Hardcover | books finished, average rating |
| GitHub | commits, repos touched |
| Oura Ring | median/avg sleep score, median/avg readiness score |

## Database Access Pattern

All DB managers inherit from `BaseDatabase` in [`src/database.py`](/Users/yulong/Documents%20(local)/coding/digital-footprint-dump/src/database.py).

Typical usage:

```python
with self.db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT ...")
    rows = cursor.fetchall()
```

Connections use `sqlite3.Row`, so rows are accessed by column name.

## Time and Timestamps

`src/time_utils.py` provides UTC timestamp helpers, including `utc_now_iso()`, which is used for `updated_at` values in analysis tables.

## Configuration

`src/config.py` loads `.env`, resolves the storage root, and exposes validation methods.

Key config areas:

| Area | Variables |
|------|-----------|
| Readwise | `READWISE_ACCESS_TOKEN` |
| Foursquare | `FOURSQUARE_ACCESS_TOKEN`, `FOURSQUARE_CLIENT_ID`, `FOURSQUARE_CLIENT_SECRET`, `FOURSQUARE_API_KEY` |
| Letterboxd | `LETTERBOXD_RSS_URL`, `TMDB_ACCESS_TOKEN`, `TMDB_API_KEY` |
| Overcast | `OVERCAST_COOKIE`, `OVERCAST_EMAIL`, `OVERCAST_PASSWORD` |
| Blog tracking | `BLOG_POSTS_INDEX_URL` |
| Hardcover | `HARDCOVER_ACCESS_TOKEN` |
| GitHub activity | `CODEBASE_USERNAME`, `BLOG_GITHUB_TOKEN` |
| Oura Ring | `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, `OURA_REDIRECT_URI`, `OURA_ACCESS_TOKEN`, `OURA_REFRESH_TOKEN` |
| Charles Schwab | `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SCHWAB_CALLBACK_URL`, `SCHWAB_ACCESS_TOKEN`, `SCHWAB_REFRESH_TOKEN` |
| GitHub publishing | `DATA_REPO_GITHUB_TOKEN`, `DATA_REPO_OWNER`, `DATA_REPO_NAME`, `DATA_GITHUB_TARGET_BRANCH`, `DATA_REPO_POSTS_DIR`, `BLOG_GITHUB_TOKEN`, `BLOG_REPO_OWNER`, `BLOG_REPO_NAME`, `BLOG_GITHUB_TARGET_BRANCH` |
| Storage override | `DATA_REPO_LOCAL_PATH` |

Optional publishing variables that have defaults treat blank strings as unset. This matters in GitHub Actions, where an absent secret can be passed through as an empty environment variable; blank `DATA_GITHUB_TARGET_BRANCH` and `BLOG_GITHUB_TARGET_BRANCH` values fall back to `main`.

## Testing

Useful commands:

```bash
uv run pytest
make test-ci
uv run main.py publish --dry-run
```

When docs or behavior change around the monthly report or activity files, `publish --dry-run` is the most useful end-to-end validation step.

## Cloud Deployment

This repo includes GitHub Actions for tests and monthly pipeline automation.

For the monthly pipeline, the common deployment model is:

1. public repo for this code
2. private repo for `data/` and `files/`
3. PAT/secrets for the source APIs, private data repo, and optional target blog repo

Common Actions secrets include:

- `DATA_REPO_OWNER`
- `DATA_REPO_NAME`
- `DATA_REPO_GITHUB_TOKEN` (preferred) or `DATA_REPO_PAT`
- `DATA_GITHUB_TARGET_BRANCH`
- `DATA_REPO_POSTS_DIR`
- `READWISE_ACCESS_TOKEN`
- `FOURSQUARE_ACCESS_TOKEN`
- `FOURSQUARE_API_KEY`
- `OVERCAST_COOKIE`
- `OVERCAST_EMAIL`
- `OVERCAST_PASSWORD`
- `HARDCOVER_ACCESS_TOKEN`
- `CODEBASE_USERNAME`
- `BLOG_GITHUB_TOKEN`
- `OURA_CLIENT_ID`
- `OURA_CLIENT_SECRET`
- `OURA_ACCESS_TOKEN`
- `OURA_REFRESH_TOKEN`
- `BLOG_REPO_OWNER`
- `BLOG_REPO_NAME`
- `BLOG_GITHUB_TARGET_BRANCH`
- `TMDB_ACCESS_TOKEN` or `TMDB_API_KEY` if you want Letterboxd runtime enrichment in Actions too

### Per-Source Job Isolation and Workflows

Sources with sensitive credentials run in separate workflows or jobs so that a compromised dependency in one job cannot access another job's secrets.

Currently isolated:

| Workflow/Job | Secrets | Schedule / Strategy |
|---|---|---|
| `schwab` (workflow) | `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SCHWAB_ACCESS_TOKEN`, `SCHWAB_REFRESH_TOKEN`, `SCHWAB_CALLBACK_URL` | Every 5 days (`schwab-sync.yml`) to maintain OAuth tokens within 7-day TTL |

#### Schwab Sync Workflow & Token Persistence

The Schwab API refresh tokens expire after 7 days. To automate this without giving CI write access to GitHub Secrets (which would require a highly privileged PAT and expand the security blast radius), we use the **private data repository** to persist updated tokens:

1. **Schedule**: Runs every 5 days (`0 10 */5 * *`) via `schwab-sync.yml`.
2. **Bootstrap/Fallback**: Checks for `data/.schwab_tokens.json` in the checked-out data repository. If it doesn't exist, it falls back to the static `SCHWAB_ACCESS_TOKEN` and `SCHWAB_REFRESH_TOKEN` environment secrets.
3. **Execution**: Runs `schwab-analyze` (which handles sync).
4. **Token Refresh**: If the API client refreshes the access token, the new access and refresh tokens are written to `.env`.
5. **Persistence**: The workflow extracts these tokens from `.env` and writes them to `data/.schwab_tokens.json`.
6. **Commit**: Commits and pushes both `data/schwab.db` and `data/.schwab_tokens.json` back to the private data repository.

Since both the main pipeline and Schwab workflows commit to the same private data repo, push conflicts are managed via git rebase and retries.



## CI Supply-Chain Hardening

The CI workflows apply several measures to reduce the risk of a compromised dependency or action exfiltrating secrets.

### SHA-Pinned Actions

All third-party GitHub Actions (`actions/checkout`, `astral-sh/setup-uv`) are referenced by full commit SHA rather than a mutable tag like `@v6`. Tags can be force-pushed by the action maintainer (or an attacker who compromises their account), silently changing what code runs in CI. A commit SHA is immutable.

Each pinned line includes a trailing comment with the human-readable version for maintainability:

```yaml
uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
```

### Locked Dependency Installs

CI runs `uv sync --locked` instead of plain `uv sync`. This makes the install fail if `uv.lock` is out of sync with `pyproject.toml`, preventing CI from silently re-resolving dependencies to different (potentially compromised) versions.

When adding or updating a dependency locally, run `uv lock` and commit the updated `uv.lock` alongside the `pyproject.toml` change.

### Dependabot

`.github/dependabot.yml` configures two Dependabot ecosystems:

| Ecosystem | What it does |
|---|---|
| `pip` | Opens PRs when a Python dependency has a known CVE |
| `github-actions` | Opens PRs to bump pinned action SHAs when new releases are available |

Both run on a weekly schedule. Dependabot does not auto-merge; it opens PRs for manual review.

