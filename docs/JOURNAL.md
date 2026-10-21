# Change journal

Record meaningful project changes here, newest first. Each entry explains what
changed, why, and where to find the design, usage, and implementation details.

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
