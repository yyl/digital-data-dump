# Source Modules

This document is the developer-oriented guide to how the codebase works.

It covers architecture, storage layout, per-source implementation patterns, analysis tables, publishing, backfill behavior, and deployment details that are useful when modifying the repo.

For the proposed D3/DDV/DDU consolidation, refactor sequence, and hosting tradeoffs,
see [the system consolidation analysis](../docs/design/SYSTEM_CONSOLIDATION.md).

## Project Structure

Note: the tree below is shown from the repository root.

```text
├── main.py                 # CLI entry point
├── scripts/                # Standalone helper scripts (e.g. surfilog_login.py)
├── src/
│   ├── config.py           # Environment configuration and storage resolution
│   ├── database.py         # Base SQLite connection manager
│   ├── source_operations.py # Shared source lifecycle and batch execution
│   ├── comparison.py       # Shared MoM/YoY comparison helpers
│   ├── time_utils.py       # UTC timestamp helpers
│   ├── token_store.py      # Shared .env OAuth token persistence helper
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
│   ├── schwab/
│   ├── workflowy/
│   ├── surfilog/
│   ├── kaya/
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
| `analytics.py` | Source-owned monthly rollups and derived tables |

### Adding or Changing a Source

Keep provider-specific code in `src/<source>/` and reuse shared helpers for
behavior common to multiple sources. Ingestion initializes and migrates raw
tables. Analytics owns the derived tables. Each database declares `source_name`,
`raw_table_names`, and `analysis_table_names` when its derived tables differ
from the default `analysis` table. Status and reporting use the shared
[read-only database helpers](#report-and-activity-reads).

Keep sync, local analysis, and refresh as separate operations. Sync acquires and
stores input data, local analysis computes results from SQLite without provider
requests, and refresh runs sync before analysis. Advance checkpoints only after
the covered data is fully fetched and saved. A successful empty fetch, an
intentional skip, and a failed or incomplete fetch have different outcomes.
The shared batch runner attempts independent sources and returns failure when
a selected operation fails.

Register only the features a source participates in.

| Feature | Registration |
|---------|--------------|
| CLI, initialization, and status | `source_catalog()` in `main.py` binds the database, sync, analysis, validation, and any source-specific arguments. `src/source_operations.py` runs the lifecycle. |
| Monthly refresh | `REPORT_SOURCES` in `main.py` selects the sources refreshed before publishing and backfill. `optional_for_reporting` controls whether failed configuration validation skips a source. |
| Monthly Markdown | `MarkdownGenerator.report_sections()` registers the section and tag. `Publisher.report_sources()` supplies eligible months and section data. |
| Monthly activity YAML | `DataGenerator.activity_sources()` registers the output file and its record reader. |

Document source setup in [SOURCES.md](../docs/SOURCES.md), CLI usage in the
[main README](../README.md#basic-usage), and published formats and privacy rules
in [SUMMARY.md](../docs/SUMMARY.md). Keep source schema and calculation details
in this guide.

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
| API-backed | Readwise, Foursquare, Blog, Hardcover, GitHub, Oura, Schwab, Workflowy, Surfilog, Strong | `api_client.py` + `sync.py` |
| File-backed | Letterboxd, Overcast, Apple Health, Kaya | `importer.py` |

Letterboxd is hybrid in practice: it uses RSS for incremental sync, plus CSV export seeding when the DB is empty.

## Publish Module

The `src/publish/` package contains the publishing layer.

| File | Purpose |
|------|---------|
| `publisher.py` | Orchestrates data fetch, comparisons, report assembly, and publish flow |
| `markdown_generator.py` | Renders the monthly markdown report |
| `data_generator.py` | Generates `data/activity/*.yaml` files from analysis tables |
| `activity_chart.py` | Renders the SVG hourly GitHub commit activity chart |
| `travel_map.py` | Renders the static OpenStreetMap PNG travel map |
| `github_client.py` | Writes report/data files to GitHub using PyGithub |

## Publish and Backfill Flows

### Publish

Supported paths:

- `publish`: refresh the reporting sources, generate the report, and commit the draft to the data repo under `posts/`
- `publish --skip-sync-analysis`: generate the report from existing analysis data
- `publish --dry-run`: render the report locally only
- `publish --last-month`: publish the previous calendar month based on the process's local date when report data is available for it

Report sources declare which months they can render. Most use monthly analysis.
Strong uses months whose latest workout has exercise data. With `--last-month`,
the publisher selects the previous calendar month. The scheduled workflow sets
`TZ=America/Los_Angeles` so this selection follows Pacific time. Drafts are
written to `DATA_REPO_POSTS_DIR`, which defaults to `posts`.

### Backfill

`backfill` reads the activity records once and renders two windows. The
full-history set goes to the data repo and the rolling one-year set goes to the
blog repo under `data/activity/`. Both windows are rendered before delivery.

The scheduled `pipeline --last-month` refreshes the reporting sources once, then
renders the draft and both activity windows before delivering any files.
`--skip-sync-analysis` reuses the current local analysis on a delivery retry.

See [activity data files](../docs/SUMMARY.md#activity-data-files) for the export
names, source ownership, fields, and empty-file behavior.

## Source-Specific Technical Notes

### Workflowy

- Syncs the complete `GET /api/v1/nodes-export` response into `workflowy.db`; Workflowy does not document a delta endpoint, cursor, or modified-since filter.
- `nodes` preserves source fields, the complete raw JSON object, and local audit fields (`first_seen_at`, `last_seen_at`, `is_deleted`). Missing IDs from a validated export are retained as tombstones rather than deleted.
- `sync_state` records the last successful snapshot and counts. A file lock prevents overlapping Workflowy syncs from applying stale snapshots.
- `node_modifications(node_id, modified_at)` preserves each observed source edit timestamp; `node_removals(node_id, removed_at)` preserves active-to-missing transitions in UTC ISO format. Both use the pair as their primary key and are written in the snapshot transaction, so failed snapshots cannot leave activity behind.
- Analysis owns `analysis(year_month, year, month, nodes_added, nodes_modified, nodes_removed, updated_at)`. Workflowy has standalone and aggregate analysis commands, but no report or activity YAML integration yet.

#### Workflowy metric definitions

All counts use distinct node IDs per UTC calendar month, independently for each
metric. A node can contribute to multiple metrics in the same month.

- **`nodes_added`** counts stored nodes by `created_at` (Workflowy's Unix seconds),
  including tombstones. The initial snapshot contributes historical creations;
  restoration of an ID does not count as another creation.
- **`nodes_modified`** counts recorded `modified_at` timestamps strictly later
  than the node's creation. Equal creation/modification times and null modification
  times contribute no edits. Initial and legacy snapshots seed the latest known
  edit; subsequent snapshots retain each newly observed edit timestamp. Multiple
  edits in a month count once per node. A later month's edit does not erase the
  earlier month's count, and restoration alone does not count as an edit.
- **`nodes_removed`** counts nodes transitioning from active to missing in a
  validated successful export, using the detection time, not an inferred source
  deletion date. Repeated missing snapshots contribute nothing. Restoration
  retains previous removals; a later removal can count again in another month.

Raw initialization adds the two history tables without rewriting existing nodes.
It seeds known modification timestamps idempotently, including those on legacy
tombstones. Existing tombstones have unknown deletion dates and are not assigned
invented removals. Newly observed deletions are tracked after this upgrade.

Analysis rebuilds all monthly rows from stored nodes and history. Quiet months
between the earliest known activity and the latest activity/successful sync get
zero counts; a successful empty initial snapshot yields a zero row for its month.
An unpopulated mirror with no successful sync yields no rows. `updated_at` is the
UTC recomputation time. Zero means no recorded activity, not guaranteed historical
coverage. There is no complete edit history in an export: edits overwritten
between snapshots, nodes created and deleted entirely between syncs, and removals
before tracking began cannot be reconstructed. More frequent syncs improve
coverage. Later discovery of older nodes can increase historical creation/edit
counts; observed edit dates are retained even if later source metadata changes.

### Surfilog

- Uses `POST /api/auth/login`, verifies its cookie with `GET /api/auth/me`, then
  fetches `GET /api/sessions` and `GET /api/sessions/{id}` for every listed session.
- `surfilog-import-strava` (`src/surfilog/strava_import.py`) reuses the same
  cookie-authenticated client to check `GET /api/strava/status`, paginate
  `GET /api/strava/activities` (`stravaPageFrom`, `per_page`, optional `after`),
  filter unimported matching `sport_type` activities (defaulting to `Surfing`),
  and trigger `POST /api/strava/import/{activityId}` oldest-first. HTTP 409 is
  treated as idempotent already-imported; `STRAVA_DISCONNECTED`, HTTP 401/403/429,
  and Cloudflare blocks abort immediately without leaking response bodies. It is
  intentionally decoupled from read-only `surfilog-sync` and runs on its own
  daily workflow (`.github/workflows/surfilog-strava-import.yml`).
- The standard-library client is shared with `scripts/surfilog_login.py` and
  identifies itself as `digital-data-dump-surfilog-login/1.0`, following
  [Cloudflare's descriptive User-Agent guidance](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/#requests-to-pages-projects-or-workersdev).
  HTTP redirects are rejected, requests have finite timeouts, and response bodies
  and cookies are omitted from error messages. There are no automatic retries of
  login failures, rate limits, or browser challenges.
- Tokens are held only in an in-memory cookie jar. Each sync starts with a fresh
  login. The raw DB never receives the password, login cookie, or session share token.
- Fully fetches and validates all session details before a single SQLite
  transaction replaces the raw snapshot and advances `sync_state`. Failure at
  any download, normalization, or write preserves the previous snapshot and
  successful-sync timestamp. Reprocessing, exclusions, and remote removals are
  reflected on the next successful sync. The stored account ID prevents a
  different configured account from replacing this database.
- Raw session JSON, full-session `trackPoints`, and per-wave `coords_json` retain
  the available source measurements. Wave coordinates include timestamps and
  sample speeds, not only the display map's polyline points. Source numeric
  strings become SQLite numbers for queried measurements.

#### Surfilog metric definitions

Session `started_at` is normalized to UTC and shifted using its recorded
`utc_offset_min` to derive `local_started_at` and `date_month`. A missing offset
uses UTC, independent of the machine's timezone. Upload time (`created_at`) never
determines the surfing month. All waves belong to their session's start month,
including sessions that span midnight. A session without waves still counts as
one session and contributes its full water time.

Analysis groups the current complete snapshot by `date_month`:

- `sessions`: session count; `waves`: count of wave rows with `is_excluded = 0`.
  `sessions.reported_wave_count` preserves the API's count for auditing; rollups
  derive counts from individual waves so manual exclusions take effect even if
  the API's session summary lags behind them.
- `total_duration_seconds`: sum of each session's `duration_sec`, counted once.
- `surf_time_seconds` and `surf_distance_m`: sums of non-excluded wave durations
  and distances, retaining API precision rather than HTML-rounded measurements.
- `max_speed_kmh`, `longest_wave_m`, and `max_wave_seconds`: maxima across
  non-excluded waves. Stored as zero when no counted waves exist, displayed as
  unavailable in the report.
- `median_wave_seconds` and `median_speed_kmh`: medians of non-excluded wave
  durations and per-wave top speeds across the month. Both are null when no
  counted waves exist.
- `paddling_distance_m`: sum of available `session_metrics.paddlingDistanceM`;
  missing measurements contribute nothing to the sum.

Reanalysis replaces all monthly rows, so corrected dates, exclusions, and removed
sessions update history and remove stale months. `surfing.yaml` and the Surfing
report section publish aggregates, keeping individual tracks and raw metadata
in the data database. Surfilog is included in the standard optional-source
readiness and read-only publishing policy.

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
- After CSV/RSS import, `letterboxd-sync` runs a TMDB enrichment pass for any rows missing `runtime_minutes`
- `TMDBClient` prefers `TMDB_ACCESS_TOKEN` (Bearer) over `TMDB_API_KEY`, raises `TMDBAPIError` (with sanitized messages that omit credentials) on auth/HTTP/transport/JSON errors or missing credentials when movies still lack runtimes, and treats HTTP 404 on `/movie/{id}` as a non-fatal miss
- The TMDB enrichment path prefers exact title plus exact year, then falls back to exact title with a `+/- 1` year window; each matched movie is saved immediately so interrupted runs resume safely
- If runtime enrichment still finds no safe match, sync prints the unmatched movie titles without failing; `status` reports `has_tmdb_token` and `missing_runtime`

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
- The daily Activity workflow runs the same importer against a temporary database with RSS enrichment disabled. It compares the imported episode with vault history and only publishes a changed `data/activity/latest_podcast.json` snapshot. The vault database is read-only for this workflow.

### Strong

- Syncs Strong's unofficial API into `strong.db`; retains CSV import/recovery
- Computes monthly workout/exercise/set metrics and supplies the published
  `Weightlifting` section through `StrongAnalytics.get_weightlifting_summary()`

`api_client.py` logs in at `https://back.strong.app/auth/login`, reads standard
and user exercise definitions, and downloads `include=log` from the authenticated
user endpoint. Exercise pages follow `next` page numbers; workout pages follow
continuation tokens. Exercise pages overlap in the live backend, so definitions
are deduplicated by ID. Cursors never change the request host. Redirects, malformed
responses, non-advancing cursors, duplicate logs, and unresolved exercise definitions fail the sync
without printing credentials, tokens, or response bodies. No token file is used.

`sync.py` validates all pages before replacing `workouts` and `exercises` in one
transaction. It uses API UUIDs, removes deleted workouts, and clears stale
`analysis` rows. `strong-analyze` regenerates those rows. Empty API histories
cannot erase an existing history; changing accounts requires a separate database.
`sync_state` records source, account ID, output units, fallback timezone, and
last successful sync. A prior API snapshot prevents automatic CSV fallback when
credentials disappear; `strong-sync --csv` explicitly replaces it from a full
export and records CSV provenance. Legacy CSV-only databases remain readable.

### Strong metric definitions

The Weightlifting section reads raw `workouts` and `exercises`. A month is
eligible for the report when its latest Strong workout includes exercises.
The monthly `analysis` table supplies counts for `weightlifting.yaml`. Apple
Health supplies the separate Workout section and `workouts.yaml`.

- **Session selection:** the latest `started_at` inside the report's calendar
  month, interpreted as the local timestamp recorded in the CSV or derived from
  the API's UTC timestamp and workout timezone (`STRONG_TIMEZONE` fallback).
  `started_at` omits offsets so SQLite preserves local calendar months. API
  `started_at_utc` preserves absolute chronology for latest-session ordering,
  including repeated DST hours and travel between timezones. Legacy CSV rows
  have no absolute timestamp and retain local ordering. Ties use the greatest
  workout ID. No fallback to an earlier month or workout with sets.
- **Exercise identity and population:** exact, case-sensitive `exercise_name`;
  only exercises in the selected session, displayed in their first imported set
  order. The CSV importer groups sessions by `Date` and skips Rest Timer and
  other nonnumeric set-order rows. API sync excludes hidden workouts/groups/sets/
  cells, explicitly incomplete sets, rest timers, and note-only sets. Legacy
  sets without a completion flag remain eligible. Visible exercise notes are
  attached to the first imported set. Every imported numeric set participates,
  without adjusting for reps, equipment, assisted weight, or bodyweight.
- **Best weight:** `MAX(weight)` across the exercise's sets in that session.
  It is a session maximum, not a monthly best, all-time record, estimated 1RM,
  or volume measure. Zero remains zero; SQL NULL weights display as `N/A` when
  no set has a recorded weight. The importer represents blank CSV weights as
  zero. API kg weights are converted to `STRONG_WEIGHT_UNIT` (`lb` by default)
  before storage; workout durations are elapsed whole minutes and set durations
  are seconds. CSV weights retain their unspecified export units. Comparable
  history requires consistent units; API snapshot replacement rebuilds the
  entire history in the configured unit.
- **Total volume and time:** `SUM(weight * reps)` across the selected workout's
  sets for each exercise, using stored weights and repetitions. A missing weight
  or repetition count yields null volume for the whole exercise. Recorded zero
  weights yield zero volume. The session's `duration_minutes` supplies total
  elapsed workout time. Strong does not supply a complete exercise-by-exercise
  elapsed-time breakdown.
- **Historical baseline:** the same exercise's maximum set weight in its latest
  session within the previous calendar month (MoM) or the same calendar month
  one year earlier (YoY). That session may precede the comparison month's final
  workout if the exercise was absent from the final workout. Never substitute
  an older month or a different exercise.
- **Change:** `(current - baseline) / baseline * 100`, rounded to one decimal
  by the shared comparison helper and displayed as a whole percentage like
  other report metrics. Missing exercises/months/weights and zero baselines
  yield `N/A`. A current zero against a positive baseline yields `-100%`.

The query path is read-only, so syncing corrected history changes a
subsequently regenerated report without a schema migration. Previously published
posts are unchanged until regenerated. An absent database, a month without
workouts, or a latest workout without sets yields no Weightlifting section.
Coverage is limited to synced history; regression tests cover session versus
monthly maxima, calendar boundaries, sparse history, zero/missing weights,
timer exclusion, repeat imports, and end-to-end markdown generation in
[`test_strong_weightlifting.py`](../tests/test_strong_weightlifting.py).
API pagination, normalization, migration, recovery, and transactional failure
coverage is in [`test_strong_sync.py`](../tests/test_strong_sync.py).

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
- `apple-health-publish-latest` (`src/apple_health/activity_snapshot.py`) reads the latest non-walk workout from `workouts` and updates `data/activity/latest_workout.json` on the blog repo when changed. The daily workflow (`.github/workflows/apple-health-activity.yml`) runs `apple-health-sync` before publishing the card.
- `apple-health-import-heart-breathing` streams top-level heart and breathing `<Record>` elements from an explicit Apple Health `export.xml` into `heart_breathing_samples` in a single transaction, deduplicating identical samples by field hash.

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

### Kaya

- File-backed CSV source with no external API or credentials. `kaya-sync` and `kaya-analyze` accept an explicit CSV path or auto-discover both the latest manual `files/KAYA-Export-*.csv` file and every immutable DDU archive under `files/kaya/exports/*.csv`.
- Timestamps are parsed from Kaya's export format and converted into `local_date` using `KAYA_TIMEZONE` (default `America/Los_Angeles`). Each row receives a deterministic `climb_id` hashing UTC timestamp, export fields, and within-file occurrence index so full and partial exports merge idempotently without losing prior history.
- The importer validates headers, field counts, dates, and non-empty `ascent_type` across the entire file before inserting new rows in one transaction.
- `KayaAnalytics.analyze_climbs()` rebuilds all monthly rows in `analysis` (distinct climbing days, sends counting `redpoint`/`flash`/`onsight`, recorded attempts and missing-attempt counts, flashes, onsights, numeric `hardest_v_grade`, and sorted JSON `grade_counts`), powering the **Bouldering** report section and `bouldering.yaml`.

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
- Caches additions and deletions by SHA from the REST commit detail endpoint and fills gaps for discovered repos on sync
- Migrates `commits.is_private` and `commits.is_discoverable` on sync and refreshes stored visibility even when no new commits exist; undiscoverable repos retain their last known visibility for counts but have their details hidden
- Monthly analysis and activity YAML include separate public/private counts alongside combined totals; Markdown renders nested Public/Private counts with independent MoM/YoY comparisons
- Analysis migrates existing monthly tables and recalculates all stored months; until recalculation, legacy combined totals remain available without guessing a split
- Report detail queries exclude private and undiscoverable rows and also support legacy public-only databases
- Publishing uses PyGithub and retries branch update races when necessary

#### GitHub metric definitions

Definition updated **2026-11-25** (including line counts, hourly activity, and renamed-repository reconciliation). See the
[dated change entry](../docs/JOURNAL.md#2026-10-25--github-private-activity-and-metric-definitions)
for the original change from public-only metrics to public/private metrics, and
[2026-11-25](../docs/JOURNAL.md#2026-11-25--reconcile-renamed-github-repositories)
for renamed-repository reconciliation.

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
  in the database. Repositories are identified by stored `owner/name` strings.
  When GitHub resolves a former name to a currently discovered repository, sync
  moves the stored commits to that name before refreshing visibility and fetching
  commits. Names with no resolvable redirect or with a destination outside
  discovery retain their existing history.
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
| `public_additions`, `public_deletions` | Sum of the respective line counts for rows with `is_private = 0` |
| `private_additions`, `private_deletions` | Sum of the respective line counts for rows with `is_private = 1` |

Line counts use GitHub's commit-level totals across all files, including non-code
text. A line total is null if any stored commit in that month and visibility
group lacks the count. A group with no commits in an otherwise active month has
zero lines added and deleted.

Each private repo counts independently. Six private commits across three repos
produce `private_commits = 6` and `private_repos_touched = 3`. For normal synced
data, the public and private commit counts sum to `commits`, and the repo counts
sum to `repos_touched`, because sync gives every row for a repo the same visibility.

A month containing commits from only one visibility group has zero counts for
the other group. A month with no stored commits has no generated analysis row;
missing months are not filled with zeros.

**Comparisons**

[`comparison.py`](comparison.py) compares each visibility metric
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

`github-sync` resolves former repository names, refreshes repository visibility,
and fetches commits inclusively
from each repo's latest stored author timestamp. Existing SHAs are skipped, so
same-second siblings can be added without counting existing commits twice. A
newly discovered repo has no cursor and fetches its accessible default-branch
history. This can add private commits to months before the feature was enabled.

After syncing commit history, sync requests line counts for new and historical
commits that lack them in repos still returned by discovery. Each successful
result is saved immediately. A missing commit (HTTP 404) or missing stats
stays eligible for retry on later runs.

`github-analyze` syncs first, then recomputes and upserts **every month present
in raw commits**, not just the newest month. Stored history and derived totals
are therefore mutable. Sync does not reconcile deleted/unreachable commits or
rescan below the cursor for late-arriving commits with older timestamps.
Analysis also does not delete derived months that have lost all raw rows through
manual database edits. Those cases require explicit reconciliation.

Existing public-only raw databases gain `is_private = 0` and
`is_discoverable = 1`; sync then refreshes those values. The commit and repo split
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

`code.yaml` exports all six commit and repo counts after recomputation, plus any
available public/private line totals. Existing `commits` and
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

- Syncs daily health summaries and detailed sleep documents from the Oura v2 REST API into `oura.db`
- Uses OAuth2 authorization code flow. Sync refreshes upfront when a refresh token is available and saves renewed tokens to `.env`.
- Fetches seven daily summary types: activity, sleep, readiness, stress, resilience, SpO2, cardiovascular age
- Fetches sleep periods from `/v2/usercollection/sleep` and bedtime recommendations from `/v2/usercollection/sleep_time`
- Nested `contributors` objects in the API response are flattened into columns (e.g., `contributors.deep_sleep` → `contributor_deep_sleep`)
- Incremental sync uses a `sync_state` table tracking the last synced date per data type
- Skips resilience, SpO2, and cardiovascular age if Oura denies endpoint access, including explicit missing-scope responses
- Cursor-based pagination via `next_token` query parameter handles large historical fetches
- Analysis aggregates 20 numeric columns from `daily_sleep` and `daily_readiness` (scores, contributors, and temperature deviations) into monthly min, median, mean, max, and sample count rows in the normalized `analysis` table; `src/oura/reporting.py` pivots the four sleep/readiness score averages and medians for reports and `sleep.yaml`
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
- `schwab-analyze` syncs first, then writes per-account trade cash-flow summaries to `monthly_pnl` and the last available balance snapshot per month to `monthly_account_snapshots`. Cash flows are not cost-basis investment P&L. Aggregate `analyze` includes Schwab; report and activity publishing do not.

## Database Schemas

Each source has a separate SQLite database under `<storage-root>/data/`.

### Common Analysis Table Shape

Most sources' primary `analysis` table has:

- `year_month` as a `YYYY-MM` primary key
- `year`
- `month`
- source-specific metrics
- `updated_at`

Exceptions: Oura uses a normalized `analysis` table keyed by `(year_month, source_table, metric)` without `year`/`month`; Charles Schwab uses `monthly_pnl` and `monthly_account_snapshots` keyed by `(year_month, account_hash)`; and secondary breakdown tables (`analysis_by_source`, `analysis_by_activity`, `analysis_by_hour`) also omit `year`/`month`.

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

Readwise's `analysis_by_source` groups archived documents by month and resolved
publication name. Each row stores the document count, count with reading time,
and estimated reading seconds.

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

Overcast's `analysis_by_source` groups played episodes by month and show title.
Each row stores the episode count, count with a duration, and total known seconds.
Both sources rebuild these rows with their monthly totals in one transaction.
The report applies its display grouping, including **Other**, to these rows.

#### Strong (`strong.db`)

Data tables:

- `workouts`: local `started_at` for calendar grouping and nullable
  `started_at_utc` for API chronology. Raw initialization adds the UTC column
  to older databases; read-only reporting also supports the old schema.
- `exercises`
- `sync_state`: singleton source/account, weight unit, timezone, and successful
  sync timestamp. This optional metadata is added when raw tables are initialized.

Analysis fields:

- `workouts`
- `total_minutes`
- `unique_exercises`
- `total_sets`

#### Apple Health (`apple_health.db`)

Data tables:

- `workouts`
- `heart_breathing_samples` is an optional raw table populated by the explicit XML
  heart and breathing import. Each row keeps the Apple quantity type (without
  the `HKQuantityTypeIdentifier` prefix), value, original unit, UTC timestamps,
  source, device, and metadata JSON. A hash of these fields deduplicates
  identical samples. The import streams top-level records in one transaction.
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

`analysis_by_activity` stores one row per `(year_month, activity_type)` with
these same totals, `avg_heart_rate`, and `max_heart_rate`. Analysis rebuilds
both tables in one transaction. A preview of an older database can compute the
breakdown from its workouts until the first analysis run creates the table.

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
The nullable `commits.additions` and `commits.deletions` columns cache GitHub's
per-commit line counts.

Analysis fields:

- `commits`
- `repos_touched`
- `public_commits`
- `private_commits`
- `public_repos_touched`
- `private_repos_touched`
- `public_additions`
- `private_additions`
- `public_deletions`
- `private_deletions`

`analysis_by_hour` stores authored commit counts by `(year_month, hour)`,
with separate public and private counts. `github-analyze` rebuilds this table
alongside the existing monthly totals. Hours are converted to
`America/Los_Angeles`; the month retains the existing `date_month` convention.
Report generation supports an older database by aggregating its commit timestamps.

Report images are prepared in `Publisher.report_assets` and committed beside the
Markdown in the same Git tree. SVG charts are text blobs. PNG maps use base64 Git
blobs. `publish --dry-run` writes both to `.cache/report-preview/` for local
inspection. Map viewport fitting handles longitude wrap and excludes invalid
coordinates. Only visible OpenStreetMap tiles are fetched, using an identifying
User-Agent and a seven-day local cache.

`commits` and `repos_touched` remain combined totals for existing activity-data
consumers. New visibility fields are nullable during analysis schema migration
and are populated from raw commits by `github-analyze`.

#### Workflowy (`workflowy.db`)

Data tables:

- `nodes` (mirrored nodes with source fields, raw JSON, `first_seen_at`, `last_seen_at`, and `is_deleted` tombstones)
- `node_modifications` (observed `(node_id, modified_at)` edit history)
- `node_removals` (observed `(node_id, removed_at)` active-to-missing transitions)
- `sync_state` (latest successful snapshot metadata and counts)

Analysis fields:

- `nodes_added`
- `nodes_modified`
- `nodes_removed`

#### Surfilog (`surfilog.db`)

- `sessions`: primary key `id`; UTC and local session start, recorded UTC offset,
  `date_month`, session duration, source-reported wave count, available paddling
  distance, board/spot metadata, sanitized source JSON, full track JSON, sync time.
- `waves`: primary key `id`; cascading `session_id` foreign key; unique
  `(session_id, wave_num)`; UTC start, duration, distance, max speed, start
  coordinates, exclusion flag, timestamped coordinates JSON, and raw wave JSON.
- `sync_state`: singleton row with authenticated `user_id` and
  `last_successful_sync_at`.
- `analysis`: common `year_month`, `year`, `month`, and `updated_at`, plus
  `sessions`, `waves`, `total_duration_seconds`, `surf_time_seconds`,
  `surf_distance_m`, `paddling_distance_m`, `max_speed_kmh`, `longest_wave_m`,
  `max_wave_seconds`, `median_wave_seconds`, and `median_speed_kmh`.

Sync initializes only raw tables. `surfilog-analyze` creates and refreshes the
derived `analysis` table and adds the median columns to older databases.

#### Kaya (`kaya.db`)

- `climbs` stores imported CSV records with all export fields and an ISO 8601
  timestamp. `climb_id` is unique, and `local_date` is derived in
  `KAYA_TIMEZONE` during import.
- `analysis` stores one row per `year_month` with `climbing_days`, `sends`,
  `attempts`, `climbs_missing_attempts`, `flashes`, `onsights`, nullable
  integer `hardest_v_grade`, and a JSON `grade_counts` object keyed by uppercase
  grade label. The empty grade key counts ungraded sends.

The local ID hashes the UTC timestamp and the remaining CSV fields, with an
occurrence number for identical rows in one export. Existing databases receive
IDs in place when initialized. The importer validates the entire file before
inserting new IDs in one transaction. Analysis rebuilds all months in a
transaction using distinct local dates and successful ascent types. Numeric V
grades are ranked by their integer value. Attempt totals sum nonnegative
integers supplied by Kaya. A month with no usable counts stores a null total.
`kaya-analyze` adds and backfills the attempt columns in older databases.

#### Oura Ring (`oura.db`)

Data tables:

- `daily_activity`
- `daily_sleep`
- `daily_readiness`
- `daily_stress`
- `daily_resilience`
- `daily_spo2`
- `daily_cardiovascular_age`
- `sleep_periods`
- `sleep_time`
- `sync_state`

`daily_activity`, `daily_sleep`, `daily_readiness`, and `daily_resilience` flatten nested `contributors` objects into `contributor_*` columns.

`daily_resilience`, `daily_spo2`, and `daily_cardiovascular_age` may remain empty depending on hardware, membership, or OAuth permissions.

The two detailed sleep tables store the API document ID, an indexed `day`, and
the complete response document in `payload_json`. Each table tracks its own
sync cursor. Upserts use the document ID so multiple sleep periods on the same
day are preserved. The sync command creates both tables in existing databases.

Analysis table (`analysis`, composite primary key `(year_month, source_table, metric)`):

- Stores `min_value`, `median_value`, `avg_value`, `max_value`, `sample_count`, and `updated_at` for 20 numeric metrics across `daily_sleep` (score + 7 contributors) and `daily_readiness` (score, 2 temperature deviations, + 9 contributors).
- During publish and backfill, `src/oura/reporting.py` pivots the `score` rows into `median_sleep_score`, `avg_sleep_score`, `median_readiness_score`, and `avg_readiness_score`.

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

Analysis table 2 (`monthly_account_snapshots`, keyed by `(year_month, account_hash)`):

- Stores the latest `account_snapshots` row per account in each calendar month (`account_number`, `account_type`, `snapshot_at`), core balances (`liquidation_value`, `equity`, `cash_balance`, `buying_power`), and extended fields extracted from `current_balances_json` (`long_market_value`, `short_market_value`, `margin_balance`, `short_balance`, `long_margin_value`, `short_margin_value`, `maintenance_requirement`, `money_market_fund`, `total_cash`, `cash_available_for_trading`, `cash_available_for_withdrawal`), plus `updated_at`.

Run `uv run main.py schwab-analyze` to populate both tables. `net_cash_flow` is a cash-flow approximation of realized P&L; true P&L would require a separate cost-basis ledger.

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
| Surfilog | sessions, waves, water time, riding time, median/max wave duration, median/max wave speed, riding/paddling distance, longest wave |
| Kaya | climbing days, sends |
| Blog | posts, total words, unique tags |
| Hardcover | books finished, average rating |
| GitHub | public/private commits, repos touched, additions, and deletions, each compared independently |
| Oura Ring | median/avg sleep score, median/avg readiness score |

## Database Access Pattern

All DB managers inherit from `BaseDatabase` in [`src/database.py`](database.py).

Sync, imports, migrations, and analysis writes use `get_connection()`:

```python
with self.db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT ...")
    rows = cursor.fetchall()
```

Connections use `sqlite3.Row`, so rows are accessed by column name.

### Report and Activity Reads

Status, report generation, latest-month selection, Strong session summaries,
and activity YAML exports use `BaseDatabase.read_connection()` or `fetch_rows()`.
Status can show raw counts before monthly analysis exists. The shared reader
applies one readiness policy:

| State | Behavior |
| --- | --- |
| File absent | Skip and ask the user to sync the source |
| Schema has no user tables | Skip as uninitialized |
| Raw schema complete, requested analysis table absent | Skip and ask the user to run analysis |
| Declared raw table or required detail table missing | Raise `DatabaseReadError` naming the source and missing tables |
| SQL query or SQLite read fails | Raise `DatabaseReadError` naming the source and diagnostic category |
| Query returns no rows | Return an empty result normally |

`read_connection(required_tables=(...))` yields a connection or `None` for an
unavailable source. It opens an escaped SQLite file URI with `mode=ro`, closes
the connection on every exit, and never initializes or commits source data.
`fetch_rows(query, params, required_tables=("analysis",))` wraps this policy and
returns dictionaries. Raw detail queries declare the tables they require;
Strong uses one read connection for the current workout and its comparisons.
Unavailability is rechecked on each read, with duplicate diagnostics suppressed
per reason on each database instance.

The reader validates table presence. SQLite identifies incompatible columns and
damaged pages when the relevant queries execute; no full-file integrity scan is
performed. An empty schema, missing analysis, partial schema, invalid non-SQLite
file, and damaged SQLite pages have distinct regression coverage. SQLite and
filesystem failures are surfaced with fixed diagnostic text and suppressed
exception chaining; SQL text, file contents, and raw exception messages are not
copied into the public error. Unexpected programming errors propagate.

Publisher and DataGenerator share this policy; there are no per-source
`suppress_errors` switches. A failed read stops generation before report/activity
files are sent to either repository. Existing sync and analysis write paths
retain their transaction behavior and schema ownership. Regression coverage is in
[`test_database_reader.py`](../tests/test_database_reader.py) and
[`test_source_readiness.py`](../tests/test_source_readiness.py).

## Time and Timestamps

`src/time_utils.py` provides UTC timestamp helpers, including `utc_now_iso()`, which is used for `updated_at` values in analysis tables.

## Configuration

`src/config.py` loads `.env`, resolves the storage root, and exposes validation methods.

Key config areas:

| Area | Variables |
|------|-----------|
| Readwise | `READWISE_ACCESS_TOKEN` |
| Workflowy | `WORKFLOWY_API_KEY` |
| Foursquare | `FOURSQUARE_ACCESS_TOKEN`, `FOURSQUARE_CLIENT_ID`, `FOURSQUARE_CLIENT_SECRET`, `FOURSQUARE_API_KEY`, `FOURSQUARE_REDIRECT_URI` |
| Letterboxd | `LETTERBOXD_RSS_URL`, `TMDB_ACCESS_TOKEN`, `TMDB_API_KEY` |
| Overcast | `OVERCAST_COOKIE`, `OVERCAST_EMAIL`, `OVERCAST_PASSWORD` |
| Strong | `STRONG_USER`, `STRONG_PASS`, `STRONG_WEIGHT_UNIT`, `STRONG_TIMEZONE` |
| Surfilog | `SURFILOG_EMAIL`, `SURFILOG_PASSWORD` |
| Kaya | `KAYA_TIMEZONE` |
| Blog tracking | `BLOG_POSTS_INDEX_URL` |
| Hardcover | `HARDCOVER_ACCESS_TOKEN` |
| GitHub activity | `CODEBASE_USERNAME`, `CODEBASE_GITHUB_TOKEN` (legacy fallback: `BLOG_GITHUB_TOKEN`) |
| Oura Ring | `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, `OURA_REDIRECT_URI`, `OURA_ACCESS_TOKEN`, `OURA_REFRESH_TOKEN` |
| Charles Schwab | `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SCHWAB_CALLBACK_URL`, `SCHWAB_ACCESS_TOKEN`, `SCHWAB_REFRESH_TOKEN` |
| GitHub publishing | `DATA_REPO_GITHUB_TOKEN` (fallbacks: `DATA_REPO_PAT`, `BLOG_GITHUB_TOKEN`), `DATA_REPO_OWNER`, `DATA_REPO_NAME`, `DATA_GITHUB_TARGET_BRANCH`, `DATA_REPO_POSTS_DIR`, `BLOG_GITHUB_TOKEN`, `BLOG_REPO_OWNER`, `BLOG_REPO_NAME`, `BLOG_GITHUB_TARGET_BRANCH` |
| Storage override | `DATA_REPO_LOCAL_PATH` |

Optional publishing variables that have defaults treat blank strings as unset. This matters in GitHub Actions, where an absent secret can be passed through as an empty environment variable; blank `DATA_GITHUB_TARGET_BRANCH` and `BLOG_GITHUB_TARGET_BRANCH` values fall back to `main`.

## Testing

Useful commands:

```bash
uv run pytest
make test-ci
uv run main.py publish --dry-run
```

Run `make test-ci` after code changes and before committing. Use
`publish --dry-run` to verify Markdown and report assets. For changes spanning
sync, analysis, and delivery, exercise the affected commands with a temporary
vault copy and local publishing destinations. The
[refactor verification](../docs/REFACTOR.md#local-end-to-end-run) shows an example.

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
- `SURFILOG_EMAIL`
- `SURFILOG_PASSWORD`
- `STRONG_USER`
- `STRONG_PASS`
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
- `TMDB_ACCESS_TOKEN` (preferred) or `TMDB_API_KEY` for Letterboxd runtime enrichment in Actions

Optional repository variables (`vars`) used by `monthly-pipeline.yml`:

- `KAYA_TIMEZONE` (defaults to `America/Los_Angeles`)
- `STRONG_WEIGHT_UNIT` (defaults to `lb`)
- `STRONG_TIMEZONE` (defaults to `America/Los_Angeles`)

### Per-Source Job Isolation and Workflows

Sources with sensitive credentials or independent cadences run in separate workflows so each job receives only the secrets it needs and runs on its own schedule.

Standalone workflows alongside `monthly-pipeline.yml` and `tests.yml`:

| Workflow | Secrets | Schedule / Strategy |
|---|---|---|
| `schwab-sync.yml` | Vault access + `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SCHWAB_ACCESS_TOKEN`, `SCHWAB_REFRESH_TOKEN`, `SCHWAB_CALLBACK_URL` | Manual (`workflow_dispatch`, runs `schwab-analyze`; scheduled runs currently paused due to OAuth/token-refresh failures) |
| `overcast-activity.yml` | Vault read access + `OVERCAST_COOKIE`, `OVERCAST_EMAIL`, `OVERCAST_PASSWORD` + Blog repo publishing | Daily at `08:25 UTC` (`overcast-publish-latest`) |
| `apple-health-activity.yml` | Vault read access + Blog repo publishing | Daily at `08:45 UTC` (`apple-health-sync` then `apple-health-publish-latest`) |
| `surfilog-strava-import.yml` | `SURFILOG_EMAIL`, `SURFILOG_PASSWORD` | Daily at `09:15 UTC` (`surfilog-import-strava`, optional `dry_run`/`since` manual inputs) |

#### OAuth Token Persistence (Schwab & Oura)

Both the Charles Schwab and Oura Ring APIs use rotating OAuth refresh tokens (Oura refresh tokens are single-use with rotation upon every refresh; Schwab refresh tokens expire after 7 days). To automate renewals without giving CI write access to GitHub Secrets (which would require a highly privileged PAT and expand the security blast radius), we use the **private data repository** to persist updated tokens:

1. **Bootstrap**: Load access and refresh tokens from `data/.oura_tokens.json` (in `monthly-pipeline.yml`) or `data/.schwab_tokens.json` (in `schwab-sync.yml`) in the checked-out data repository. Each missing token falls back to its corresponding Actions secret.
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
