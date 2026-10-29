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
2. sibling repo `../digital-data-vault` if it exists
3. this repo itself

That means local development often uses:

- `/.../digital-data-vault/data/*.db`
- `/.../digital-data-vault/files/*`

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

## Metric Definitions and Changes

Keep calculation rules in this guide's per-source technical notes, starting with
the [GitHub metric definitions](#github-metric-definitions). These rules describe
what a number means: its input population, identity, month boundary, filters,
formula, missing-data behavior, and whether later syncs can change past results.

When changing a metric, update its definition in the same change as the code and
record a dated entry in [the change journal](../docs/JOURNAL.md). Include:

- The old and new meaning, affected database/YAML fields, and reason for changing.
- Effects on historical values and comparisons, including migration or recomputation.
- Compatibility with existing consumers and any limits on coverage or reproducibility.
- Regression fixtures for the changed calculation, missing/zero data, and migration.

Keep source credentials and user-facing sync setup in
[SOURCES.md](../docs/SOURCES.md), report layout in
[SUMMARY.md](../docs/SUMMARY.md), and command usage in the
[main README](../README.md). Link those documents to the calculation rules rather
than maintaining separate definitions of the same formula.

The journal tracks changes in meaning; it does not freeze previously calculated
data. Analysis rows currently store `updated_at`, not a metric-definition version
or the token's repository selection. Reproducing an older result requires the
matching code and data snapshots; a date in the journal alone is insufficient.

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
- `publish --last-month`: publish the previous calendar month based on the process's local date; fail if that month has no analysis data

The publish flow scans the available analysis DBs and chooses the latest available `YYYY-MM`, while tolerating optional sources that may be missing. With `--last-month`, it selects the previous calendar month even if current-month analysis is absent. The scheduled workflow sets `TZ=America/Los_Angeles` so this selection follows Pacific time. Report drafts are written to `DATA_REPO_POSTS_DIR` in the data repo, which defaults to `posts`.

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
| `code.yaml` | GitHub | `commits`, `repos_touched` (combined), `public_commits`, `private_commits`, `public_repos_touched`, `private_repos_touched` |
| `sleep.yaml` | Oura Ring | `median_sleep_score`, `avg_sleep_score`, `median_readiness_score`, `avg_readiness_score` |

Published workout metrics come from Apple Health monthly analysis. Strong is still importable and analyzable, but it is not the published workout source.

## Source-Specific Technical Notes

### Workflowy

- Syncs the complete `GET /api/v1/nodes-export` response into `workflowy.db`; Workflowy does not document a delta endpoint, cursor, or modified-since filter.
- `nodes` preserves source fields, the complete raw JSON object, and local audit fields (`first_seen_at`, `last_seen_at`, `is_deleted`). Missing IDs from a validated export are retained as tombstones rather than deleted.
- `sync_state` records the last successful snapshot and counts. A file lock prevents overlapping Workflowy syncs from applying stale snapshots.
- Workflowy has no analysis or publishing integration yet.

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
- Computes monthly workout/exercise/set metrics and supplies the published
  `Weightlifting` section through `StrongAnalytics.get_weightlifting_summary()`

### Strong metric definitions

The Weightlifting section reads raw `workouts` and `exercises` without changing
the existing monthly `analysis` schema or activity YAML files. Strong analysis
months participate in publish's latest-month selection. Apple Health continues
to supply the separate Workout section and `workouts.yaml`.

- **Session selection:** the latest `started_at` inside the report's calendar
  month, interpreted as the local timestamp recorded in the CSV. Ties use the
  greatest workout ID. No fallback to an earlier month or workout with sets.
- **Exercise identity and population:** exact, case-sensitive `exercise_name`;
  only exercises in the selected session, displayed in their first imported set
  order. The importer groups sessions by CSV `Date` and skips Rest Timer and
  other nonnumeric set-order rows. Every imported numeric set participates,
  without adjusting for reps, equipment, assisted weight, or bodyweight.
- **Best weight:** `MAX(weight)` across the exercise's sets in that session.
  It is a session maximum, not a monthly best, all-time record, estimated 1RM,
  or volume measure. Zero remains zero; SQL NULL weights display as `N/A` when
  no set has a recorded weight. The importer represents blank CSV weights as
  zero. No unit conversion occurs because the CSV contains no unit metadata;
  comparable history requires consistent Strong export units.
- **Historical baseline:** the same exercise's maximum set weight in its latest
  session within the previous calendar month (MoM) or the same calendar month
  one year earlier (YoY). That session may precede the comparison month's final
  workout if the exercise was absent from the final workout. Never substitute
  an older month or a different exercise.
- **Change:** `(current - baseline) / baseline * 100`, rounded to one decimal
  by the shared comparison helper and displayed as a whole percentage like
  other report metrics. Missing exercises/months/weights and zero baselines
  yield `N/A`. A current zero against a positive baseline yields `-100%`.

The query path is read-only, so reimporting a corrected/new export changes a
subsequently regenerated report without a schema migration. Previously published
posts are unchanged until regenerated. An absent database, a month without
workouts, or a latest workout without sets yields no Weightlifting section.
Coverage is limited to imported exports; regression tests cover session versus
monthly maxima, calendar boundaries, sparse history, zero/missing weights,
timer exclusion, repeat imports, and end-to-end markdown generation in
[`test_strong_weightlifting.py`](../tests/test_strong_weightlifting.py).

### Apple Health

- Sync discovers every `files/apple_health/actions/batches/*.json` archive under
  the configured storage root. `json_importer.py` validates schema and normalization
  version 1, raw/normalized consistency, UUIDs, finite quantities, and date provenance.
  `importer.py` retains explicit XML file import for restoring a historical baseline;
  routine sync never discovers or reads XML.
- Workout UUIDs are case-insensitive. They must be stable across exports; their
  originating UUID namespace does not need to be HealthKit's. `duration_seconds`
  maps from DDU's `duration`, while `energy_burned.value` maps to total kcal, per
  the user's confirmed measurement policy. `elapsed_seconds` remains separate.
- Immutable batch byte fingerprints avoid reparsing unchanged archives. Only new
  snapshots and held UUIDs are replayed from retained observations, using receipt
  time for precedence. Missing optional fields retain older measurements and their
  field-level provenance. Equal-time conflicts are held until a later snapshot
  resolves the conflicting fields. Older files cannot overwrite newer observations.
- A persisted UUID alias resolves subsequent imports directly. Otherwise legacy
  matching searches only rows at or after `2026-08-01T00:00:00-07:00`, comparing
  activity, source, start/end minute windows, agreement with either JSON duration
  or elapsed time (within one second of XML's rounded duration), and compatible
  offsets. Elapsed time is identity evidence only: XML durations are preserved,
  and new JSON rows still use `duration`. Coverage flags matched non-walk rows
  whose XML duration differs from JSON duration. Nearby candidates without a unique,
  fully supported match are held. One legacy row cannot be claimed by two UUIDs;
  JSON-only rows are never fuzzy-matched to other UUIDs.
- Matched XML rows keep their IDs, precise timestamps, durations, and nonmissing
  measurements. JSON can fill missing active calories, total calories, average
  heart rate, and source. New JSON rows keep absent measurements null. Complete
  envelopes preserve device information, extra measurements, and uploader warnings.
- First migration uses SQLite backup to preserve an existing database in
  `data/.backups/apple_health.db.pre-json-v1.sqlite3`. All validated batch writes,
  observations, projections, aliases, and outcomes share one SQLite transaction.
  Invalid batches are not persisted; valid batches may remain pending if an
  observation needs review. The CLI reports failure when any input is invalid or
  unresolved, while retaining valid imported data. Intentional pre-cutoff skips
  have a separate `skipped` status and do not fail sync or retry until a new
  snapshot or explicit alias arrives. No source data is deleted.
- Monthly analysis is the source of truth for the published workout section and `workouts.yaml`
- Analysis preserves the existing UTC month grouping and walk exclusion, and
  rebuilds derived rows so corrected workout dates cannot leave stale months.

Inspect held observations without exposing whole payloads:

```sql
SELECT identifier, reason FROM json_import_state WHERE status != 'imported';
SELECT batch_id, status FROM json_batches WHERE status != 'imported';
```

Pending observations retry automatically. To resolve an identity ambiguity, review
the retained envelopes and baseline first, then explicitly insert a confirmed
`json_workout_aliases` mapping with `origin = 'xml'` for an existing baseline row.
There is no automatic historical backfill before August 2026. Restoring a baseline
through `AppleHealthImporter.import_from_file(Path('.../export.xml'))` is an
explicit recovery operation and must precede JSON replay on a fresh database.
See `docs/design/AH_JSON.md` for the agreed scope and audited coverage.

### Blog

- Syncs from a public Hugo JSON index rather than writing to the blog repo directly
- The `Writing` report section and `writing.yaml` come from blog analysis

### Hardcover

- Uses the Hardcover GraphQL API
- Tracks finished books and monthly average rating

### GitHub

- Prefers `CODEBASE_GITHUB_TOKEN` for activity, falling back to `BLOG_GITHUB_TOKEN`
- Verifies the token owner matches `CODEBASE_USERNAME`, merges public user-repo discovery with authenticated owned-repo discovery, and excludes forks
- Syncs authored commit history on default branches from owned public and accessible private repositories
- Uses an inclusive timestamp cursor plus SHA deduplication so same-second commits are not skipped
- Migrates `commits.is_private` and `commits.is_discoverable` on sync and refreshes stored visibility even when no new commits exist; undiscoverable repos retain their last known visibility for counts but have their details hidden
- Monthly analysis and activity YAML include separate public/private counts alongside combined totals; Markdown renders nested Public/Private counts with independent MoM/YoY comparisons
- Analysis migrates existing monthly tables and recalculates all stored months; until recalculation, legacy combined totals remain available without guessing a split
- Report detail queries exclude private and undiscoverable rows and also support legacy public-only databases
- Publishing uses PyGithub and retries branch update races when necessary

#### GitHub metric definitions

Definition updated **2026-10-25**. See the
[dated change entry](../docs/JOURNAL.md#2026-10-25--github-private-activity-and-metric-definitions)
for the change from public-only metrics to public/private metrics.

**Input population and identity**

- Discover owned, non-fork repositories by combining the public user-repository
  endpoint with authenticated owned-repository discovery. Private coverage is
  limited to repositories allowed by the activity token. Organization-owned and
  collaborator repositories are excluded, even when the token can read them.
- Fetch commits with `author=CODEBASE_USERNAME` and no branch argument, so the
  starting branch is the repository's default branch. This measures authored
  commits in the returned history; it is not an all-branch activity count or a
  reproduction of GitHub's contribution graph. A squash commit is one commit,
  rather than the original branch's individual commits.
- The raw table has a **global SHA primary key**, not `(repo, SHA)`. A SHA found
  in multiple repositories is stored once; ordinary sync retains its existing
  repository association. Repo counts therefore follow the association retained
  in the database. Repositories are identified by stored `owner/name` strings,
  not immutable repository IDs; renames/transfers have no alias reconciliation.
- Count stored commits with a non-empty `date_month`. Sync skips entries without
  a SHA or author timestamp. Merge commits are included in these counts.

**Month and visibility**

`date_month` is the first seven characters of `commit.author.date`. There is no
local timezone conversion; a timestamp ending in `Z` uses its UTC calendar month.
The committer timestamp, push date, and sync date do not determine the month.

`is_private` is the repository's latest successfully observed visibility,
applied to **all stored commits for that repository**, including old months.
It does not record visibility at the time each commit was authored. If a repo
becomes public, its stored historical activity moves to the public group on the
next successful sync and reanalysis; the reverse applies when it becomes private.

`is_discoverable` is separate from visibility. When a stored repo is absent from
discovery, its details are hidden, but its last known visibility and stored
activity remain in the counts. Losing token access does not erase private history
or automatically reclassify previously public history as private.

**Monthly formulas**

For each `date_month`, [`github/analytics.py`](github/analytics.py) computes:

| Field | Calculation over that month's stored rows |
|-------|--------------------------------------------|
| `commits` | `COUNT(*)` across both visibility groups |
| `repos_touched` | `COUNT(DISTINCT repo)` across both groups |
| `public_commits` | Number of rows with `is_private = 0` |
| `private_commits` | Number of rows with `is_private = 1` |
| `public_repos_touched` | Distinct `repo` values among rows with `is_private = 0` |
| `private_repos_touched` | Distinct `repo` values among rows with `is_private = 1` |

Each private repo counts independently. Six private commits across three repos
produce `private_commits = 6` and `private_repos_touched = 3`. For normal synced
data, the public and private commit counts sum to `commits`, and the repo counts
sum to `repos_touched`, because sync gives every row for a repo the same visibility.

A month containing commits from only one visibility group has zero counts for
the other group. A month with no stored commits has no generated analysis row;
missing months are not filled with zeros.

**Comparisons**

[`comparison.py`](comparison.py) compares each of the four visibility metrics
with the **same metric** in the previous calendar month (MoM) and the same month
of the previous year (YoY):

```text
percentage change = round((current - previous) / previous * 100, 1)
```

The report displays the result as a whole percentage. A missing or zero previous
value yields `N/A`; a current value of zero with a positive baseline yields
`-100%`. Public and private groups never use each other's baseline. Missing
private history is not evidence that no private work occurred: granting broader
token access can change historical baselines and percentages.

**Refresh and historical changes**

`github-sync` refreshes repository visibility and fetches commits inclusively
from each repo's latest stored author timestamp. Existing SHAs are skipped, so
same-second siblings can be added without counting existing commits twice. A
newly discovered repo has no cursor and fetches its accessible default-branch
history. This can add private commits to months before the feature was enabled.

`github-analyze` syncs first, then recomputes and upserts **every month present
in raw commits**, not just the newest month. Stored history and derived totals
are therefore mutable. Sync does not reconcile deleted/unreachable commits or
rescan below the cursor for late-arriving commits with older timestamps.
Analysis also does not delete derived months that have lost all raw rows through
manual database edits. Those cases require explicit reconciliation.

Existing public-only raw databases gain `is_private = 0` and
`is_discoverable = 1`; sync then refreshes those values. The four new analysis
columns remain null until recomputation. Before a complete split is available,
the renderer and activity generator retain combined totals instead of guessing
public/private values.

**Outputs and compatibility**

The raw database retains private repo names and messages. Report details and
new-repo lists use only discoverable public repos. Commit detail tables also
exclude messages matching `Merge pull request #%`; aggregate counts include
those commits. Consequently, visible detail rows need not sum to headline counts.

All errors escaping `GitHubSyncManager.sync()` are converted to `GitHubSyncError`
with fixed diagnostic text and, for HTTP failures, a validated numeric status.
Original exception text, URLs, request/response objects, headers, and bodies are
not copied to the displayed error, and the original exception chain is suppressed.
The boundary covers discovery, all commit pages, response parsing, and local
database errors, regardless of the repo's discovered visibility. This protects
both uncaught CLI tracebacks and the bulk `analyze` command's caught-error output.
Successful private-repo progress messages use `Private repository` instead of a
repo name. Activity failures still raise rather than becoming empty successful
results; `publish` and `backfill` stop, while bulk `analyze` reports the sanitized
failure and continues its other source sections. Low-level API exceptions are
internal to this boundary and must not be logged separately. These rules apply
to the normal CLI/logging paths, not custom debugging that dumps frame locals or
raw transport objects.

`code.yaml` exports all six counts after recomputation. Existing `commits` and
`repos_touched` keys remain **combined totals**, but their population now includes
stored private activity. This preserves the keys, not their former public-only
meaning. Existing blog charts using those keys will still display combined
counts; they must consume the new fields to show a split.

`backfill` exports full history to the data repo and a month-filtered copy to the
blog, starting inclusively at the same calendar month one year before the run.
The cutoff filters already calculated records; it does not change their formulas.
Previously committed report posts do not update automatically when analysis
changes; they must be regenerated and published separately.

Implementation pointers: [API discovery](github/api_client.py),
[sync and author-month extraction](github/sync.py),
[identity and visibility updates](github/database.py),
[monthly aggregation](github/analytics.py),
[report assembly](publish/publisher.py), and
[activity exports](publish/data_generator.py).
Regression coverage: [private activity, comparisons, visibility, and migration](../tests/test_github_private_activity.py),
[discovery and permissions](../tests/test_github_client.py), and
[incremental sync](../tests/test_github_sync.py).
[Log and traceback regression tests](../tests/test_github_log_security.py) also
cover HTTP/transport failures, malformed responses, pagination, CLI subprocess
stderr, standard exception logging, and caught-error output.

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
- `total_minutes`
- `unique_exercises`
- `total_sets`

#### Apple Health (`apple_health.db`)

Data tables:

- `workouts`
- `json_batches`: immutable batch ID, byte SHA-256, receipt timestamp, archive
  reference, full envelope JSON, observation count, and imported/pending/excluded status.
- `json_observations`: unique `(batch_id, identifier)` snapshots used to rebuild
  each UUID's accepted view, indexed by identifier.
- `json_workout_aliases`: UUID primary key, unique canonical workout ID foreign
  key, and `xml`/`json` origin. XML IDs are preserved verbatim.
- `json_import_state`: per-UUID status/reason plus the last accepted receipt,
  merged snapshot, and per-field batch provenance. A held later observation does
  not erase the previously accepted snapshot or published row.

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

The `commits.is_private` integer flag defaults to `0` for legacy public-only
rows. Sync migrates existing databases automatically and refreshes this flag
from repository discovery before fetching new commits. Private names and messages
are stored locally but filtered from report details. `is_discoverable` defaults to
`1` and becomes `0` when a repository is absent from discovery; its `is_private`
flag then keeps the last known visibility for historical counts.

Analysis fields:

- `commits`
- `repos_touched`
- `public_commits`
- `private_commits`
- `public_repos_touched`
- `private_repos_touched`

`commits` and `repos_touched` remain combined totals for existing activity-data
consumers. New visibility fields are nullable during analysis schema migration
and are populated from raw commits by `github-analyze`.

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
| Strong | maximum set weight for each exercise in the latest workout |
| Apple Health | workouts, total duration, total calories |
| Blog | posts, total words, unique tags |
| Hardcover | books finished, average rating |
| GitHub | public/private commits and repos touched, each compared independently |
| Oura Ring | median/avg sleep score, median/avg readiness score |

## Database Access Pattern

All DB managers inherit from `BaseDatabase` in [`src/database.py`](/Users/yulong/Documents%20(local)/coding/digital-data-dump/src/database.py).

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
| GitHub activity | `CODEBASE_USERNAME`, `CODEBASE_GITHUB_TOKEN` (legacy fallback: `BLOG_GITHUB_TOKEN`) |
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
- `CODEBASE_GITHUB_TOKEN`
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

#### OAuth Token Persistence (Schwab & Oura)

Both the Charles Schwab and Oura Ring APIs use rotating OAuth refresh tokens (Oura refresh tokens are single-use with rotation upon every refresh; Schwab refresh tokens expire after 7 days). To automate renewals without giving CI write access to GitHub Secrets (which would require a highly privileged PAT and expand the security blast radius), we use the **private data repository** to persist updated tokens:

1. **Bootstrap/Fallback**: Checks for `data/.oura_tokens.json` (in `monthly-pipeline.yml`) or `data/.schwab_tokens.json` (in `schwab-sync.yml`) in the checked-out data repository. If the file does not exist, it falls back to the static environment secrets.
2. **Execution**: The sync managers proactively refresh tokens upfront when a refresh token is present.
3. **Token Refresh**: If the API client refreshes the access token, the new access and refresh tokens are written to `.env` via the shared `save_tokens_to_env` helper (`src/token_store.py`).
4. **Persistence**: The workflow extracts these tokens from `.env` and writes them to `data/.oura_tokens.json` or `data/.schwab_tokens.json`.
5. **Commit**: Commits and pushes the updated token JSON file back to the private data repository along with the updated databases.

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
