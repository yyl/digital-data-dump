# Change journal

Record meaningful project changes here, newest first. Each entry explains what
changed, why, and where to find the design, usage, and implementation details.

## 2026-10-29 — Share source readiness and database read handling

All published sources now use the same read-only database layer for report
queries, month selection, Strong exercise comparisons, and activity exports.
Missing files, empty schemas, and missing analysis are omitted with diagnostics.
Partial schemas and SQLite/filesystem failures stop generation with the source
name. This replaces the previous mix of unguarded reads and blanket exception
suppression, which could either abort on optional empty sources or silently hide
an unreadable source. Read-only file URIs prevent missing files from being created
by report queries.

Source classes declare their raw table names. Sync/import/analysis writes and
metric definitions remain unchanged; no migration is required. Normal report
and YAML contents are preserved, while broken sources now need repair before
generation succeeds. See the [read policy](../src/README.md#report-and-activity-reads)
and [source integration regressions](../tests/test_source_readiness.py).

## 2026-10-29 — Publish Strong weightlifting progress

Strong's existing CSV source now supplies a separate `Weightlifting` section in
monthly reports. Each exercise in the month's latest workout shows its maximum
recorded set weight, with MoM/YoY comparisons against that exercise's latest
session in the corresponding calendar month. Missing or zero comparison
baselines display `N/A`; export units are preserved without assuming kg or lb.
Strong analysis now participates in selecting the report's latest month.

This adds report output without changing existing monthly Strong fields,
Apple Health workout metrics, or activity YAML schemas. Historical reports
require regeneration to gain the new section, and corrected CSV imports affect
future regeneration. No database migration is needed. See
[source setup](SOURCES.md#strong), [report layout](SUMMARY.md#weightlifting),
[metric definitions](../src/README.md#strong-metric-definitions), and
[regression coverage](../tests/test_strong_weightlifting.py).

## 2026-10-25 — Sanitize GitHub activity failures

Implementation commit: `a746a7c` — `feat: track private GitHub activity with
separate visibility metrics`. This commit includes the private activity and
metric-definition changes described below, plus the reviewed log-sanitization fix.

### Why

Code review reproduced a private repo name leaking through a failed commit API
request: `requests.HTTPError` included the full private URL, which reached the
public monthly workflow's traceback. Normal progress messages and report detail
filtering were already anonymized, but error output needed its own boundary.

### Change

`GitHubSyncManager.sync()` now replaces escaping failures with `GitHubSyncError`.
It exposes only fixed diagnostic categories/advice and a validated numeric HTTP
status, with no original exception text, response body, headers, or request URL.
The original exception chain is suppressed so standard traceback and
`logging.exception` output cannot reveal it. Protection includes discovery,
pagination, stale public metadata leading to a private error URL, transport
failures, malformed responses, and database errors. The empty-repo 409 check also
guards invalid JSON and non-object bodies while preserving failure status.

Errors remain failures: publishing and backfill stop; bulk analysis prints the
sanitized GitHub failure and continues its other sources. No metric formula or
historical-counting rule changes. This does not redact custom debugging that
explicitly dumps raw objects/frame locals, or publishing-target information from
the separate publishing client.

### Validation and pointers

- `make test-ci`: all 341 tests passed on Python 3.12.9, including 40 new
  log/error-path cases. An independent follow-up review found no remaining
  practical bypass in the normal activity CLI/logging paths; extra probes for
  nested exception causes and unsafe error/status formatting also stayed redacted.
- [Logging contract](../src/README.md#github-metric-definitions),
  [sanitization boundary](../src/github/sync.py), and
  [error-path regressions](../tests/test_github_log_security.py).
- Regression coverage checks stdout, stderr, standard exception logging, a real
  uncaught CLI subprocess, and caught bulk-analysis output for private repo names,
  commit messages/SHAs, token text, and URLs. It also confirms failures prevent
  publishing and do not masquerade as empty activity.

## 2026-10-25 — GitHub private activity and metric definitions

### Overview

GitHub activity sync now prefers a separate read-only `CODEBASE_GITHUB_TOKEN`,
with `BLOG_GITHUB_TOKEN` retained as a legacy fallback. Discovery combines owned
public repos with token-accessible owned private repos and continues to exclude
forks, organization-owned repos, and collaborator repos. Raw commits retain
their repo identity, visibility, and discovery state.

Monthly analysis now calculates `public_commits`, `private_commits`,
`public_repos_touched`, and `private_repos_touched`. Markdown shows nested
Public/Private counts with independent MoM/YoY comparisons. Private repo names,
links, and commit messages stay out of reports. Activity YAML adds the four split
fields and keeps `commits` and `repos_touched` as combined totals.

### Why and effect on existing metrics

The previous public-only counts omitted private work. Simply including that work
in the old totals would hide the change in what those numbers measure. The split
makes the two populations visible while preserving existing export keys.

This changes metric meaning and historical data, beyond report formatting:

- Combined totals now include stored private activity. Existing blog charts that
  read the old keys will show combined counts until their templates use the new
  fields; adding YAML fields does not update those chart templates.
- Newly accessible private repo history can increase old monthly totals and
  alter comparison baselines. Counts are limited by the token's selected repos.
- Visibility is the latest observed repo visibility, not visibility at commit
  time. A visibility change moves that repo's stored history between groups on
  reanalysis. Missing repos retain their last known group and counts but have
  their details hidden.
- Months follow the author timestamp's calendar month, with no local timezone
  conversion. Counts use globally deduplicated SHAs and default-branch history;
  they are not GitHub contribution-graph counts or complete all-branch activity.
- Sync migrates raw tables. Analysis migrates the four monthly fields and
  recomputes all months present in raw data. Unknown legacy splits stay null
  until recomputation; reports keep combined totals in the meantime.

The technical guide now contains the current definitions and a maintenance
checklist: update definitions, record a dated journal entry, explain historical
and compatibility effects, and add regression coverage with each metric change.
There is no stored metric-definition version or repository-scope snapshot;
reproducing older results requires the matching code and data snapshots.

### Validation and pointers

- Implementation validation: `make test-ci` passed all 301 tests on Python 3.12.9.
  Fixtures cover distinct repo counts, separate comparison baselines, zero/missing
  data, privacy filtering, visibility changes, repeat syncs, and legacy migration.
- `publish --dry-run` completed locally. A separate fixture preview exercised the
  new split layout; the existing local analysis still rendered its legacy
  combined counts until recalculation. These checks are not a live private-repo
  coverage audit, and no report was published.
- [Calculation rules and limits](../src/README.md#github-metric-definitions),
  [source/token setup](SOURCES.md#github),
  [report layout](SUMMARY.md#code), and
  [regression fixtures](../tests/test_github_private_activity.py).
- Run `uv run main.py github-analyze`, then `uv run main.py publish --dry-run` to
  populate the split and inspect the report. Publishing/backfill remain separate
  actions; recomputing local analysis does not update committed posts or charts.

## 2026-10-21 — Publish completed months on the 1st

### Overview

The monthly pipeline now runs on the 1st of each month at 6:00 AM Pacific,
using `America/Los_Angeles` to adjust automatically between PDT and PST. It
runs `publish --last-month`, then `backfill`. The 28th–31st schedule and
last-day-of-month check have been removed.

`--last-month` now selects the previous calendar month rather than the
second-newest month present in analysis data. It works when no current-month
data exists and fails instead of publishing another month when the intended
month has no analysis data. The workflow's process timezone is also Pacific.

### Why

Running after month-end includes the completed month and allows a single cron
trigger without special handling for different month lengths or leap years.

### Validation and pointers

- `make test-ci`: all 285 tests passed on Python 3.12.9, including missing
  current-month data, missing target data, leap years, and January rollover.
- Both the default report dry-run and `publish --dry-run --last-month`
  completed locally; the latter selected September 2026 on October 21, 2026.
- [Workflow](../.github/workflows/monthly-pipeline.yml),
  [CLI usage](../README.md#github-actions), and
  [month selection implementation](../src/publish/publisher.py).

## 2026-10-21 — Defer workout-level deduplication in DDU

### Decision

Keep DDU's existing whole-batch deduplication and D3's workout-level deduplication.
Do not add a per-workout UUID/content-fingerprint index to D1 for now. The phone
can continue uploading a fixed number of recent workouts, including overlaps.

### Why

The concern was D1 storage usage: a changed rolling window creates a new batch,
even when most workouts already appeared in earlier batches. DDU could filter
unchanged observations before queuing another payload, but reliable filtering
would require persistent metadata, normally in D1 itself.

The audited 100-workout archive is 124,557 bytes (about 125 KB). DDU already
clears payloads seven days after successful archival to DDV, retaining receipt
metadata. Pending and failed deliveries retain their payloads. Assuming timely
delivery and cleanup, retained payloads would be roughly 125 KB with weekly
uploads or 875 KB with daily uploads, excluding receipts and SQLite overhead.

DDU caps retained payload bytes at 32 MiB. At review time, the D1 Free-plan limit
is 500 MB per database. A compact fingerprint index would be smaller per
observation than full JSON, but an indefinitely retained index accumulates
workouts and revisions while successful payload retention is temporary. It
therefore does not guarantee a net storage saving for this upload pattern.

### Revisit when

- Actual database usage grows materially or cleanup is not running reliably.
- Upload frequency or payload size increases significantly.
- Reducing duplicate GitHub archives or downstream processing becomes a goal,
  beyond saving D1 space alone.

If implemented later, deduplicate by UUID plus content fingerprint so corrections
still pass through, and persist the marker atomically with durable acceptance.
Keep D3's reconciliation for historical XML entries. Monitor actual D1 usage and
verify cleanup before adding another persistent index.

### Quick pointers

- DDU: `src/store.ts` (`cleanup`, batch acceptance, receipt metadata),
  `src/deliver.ts` (cleanup invocation), and `src/types.ts` (buffer limits).
- [D3 deduplication and reconciliation](design/AH_JSON.md#identity-and-deduplication)
- [Cloudflare D1 limits](https://developers.cloudflare.com/d1/platform/limits/)

## 2026-10-21 — Apple Health JSON imports

### Overview

Apple Health sync now reads all immutable JSON batches produced by
digital-data-uploader (DDU) in digital-data-vault (DDV), instead of discovering
the latest XML export. Existing XML-derived workout rows and richer measurements
are preserved; explicit XML import remains available for historical recovery.

The importer deduplicates overlapping uploads by case-insensitive workout UUID,
persists aliases to existing rows, and records batch fingerprints, snapshots,
field provenance, and review outcomes. Older uploads cannot replace newer
observations, and missing optional fields do not erase existing measurements.
Unchanged archives and completed UUIDs bypass repeated processing.

Cross-format matching is limited to workouts starting August 1, 2026 onward
(midnight in America/Los_Angeles). Earlier workouts without an alias are flagged
as deliberate skips without blocking sync. Ambiguous identities, invalid files,
and unresolved dates still require attention. The known synthetic test batch is
explicitly excluded, and an existing database is backed up before migration.

New JSON rows use `duration` for workout duration and `energy_burned` for total
calories. Real overlap revealed six workouts whose XML duration instead agrees
with JSON `elapsed_time`; either agreement can support identity matching, while
matched rows retain their original XML durations. These differences remain
visible in coverage reporting. Monthly analysis also removes stale derived
months when a corrected workout date moves between months.

### Why

DDU automates phone uploads and archives JSON summaries, while the previous D3
importer required manual XML exports. Supporting these rolling uploads keeps
workout reporting current without duplicating sessions or discarding the richer
historical data. The cutoff bounds legacy reconciliation work, and persistent
aliases make later syncs direct lookups.

### Validation and first live sync

- `make test-ci`: all 283 tests passed on the pinned Python 3.12.9 runtime.
- The live archives contained 110 real observations representing 100 unique
  workouts. Ten repeated observations were deduplicated; one synthetic workout
  was excluded separately.
- Imported 11 new workouts, matched 64 existing XML rows, and deliberately
  skipped 25 pre-cutoff workouts. No invalid batches or unresolved matches remain.
- All 960 historical rows and 53 historical monthly totals remained unchanged;
  DDV now contains 971 workouts. SQLite integrity and foreign-key checks passed.
- A repeat sync made no workout changes. Monthly analysis and the report dry-run
  completed; no report was published.

### Quick pointers

- [Design and reconciliation decisions](design/AH_JSON.md)
- [Source setup, archive location, and backup behavior](SOURCES.md#apple-health)
- [Implementation and database state](../src/README.md#apple-health)
- [JSON reader, deduplication, and matching](../src/apple_health/json_importer.py)
- [Import and replay regression tests](../tests/test_apple_health_json_importer.py)
- Run `uv run main.py apple-health-analyze` after updating the vault checkout to
  sync local archives and refresh monthly analysis.
- Run `uv run main.py publish --dry-run` to inspect the current report locally.
