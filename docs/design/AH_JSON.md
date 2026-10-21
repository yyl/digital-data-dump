# Apple Health JSON import design

Status: implemented; production JSON sync first run on 2026-10-21.

Design date: 2026-10-20.

## Goal and scope

Make digital-data-uploader (DDU) JSON archives the ongoing Apple Health input
for digital-data-dump (D3). Archives live in digital-data-vault (DDV).
Preserve existing XML-derived workout rows and richer measurements. Deduplicate
JSON observations by workout UUID before importing them, and reconcile eligible
JSON workouts against existing rows without counting a workout twice.

This document records the agreed design. Routine sync now reads JSON; explicit
XML import remains available for restoring a historical baseline. User setup belongs in `docs/SOURCES.md`, CLI usage in
`README.md`, implementation and schema details in `src/README.md`, and changes
to published output rules in `docs/SUMMARY.md`.

## Current behavior and audited inputs

D3 previously found the latest `export.xml`, parsed workouts, filled missing heart
rate and calorie measurements from overlapping Health records, and upserted rows
into `apple_health.db`. Published analysis excludes workouts normalized as `walk`.

The audit on 2026-10-20 found:

- The local XML and database contain 960 workouts, from June 2019 through
  September 29, 2026.
- Of those XML workouts, 130 contain `HKExternalUUID`: 129 from Oura and one from
  HeavySet. The other 830 use D3-generated identifiers.
- The newer remote vault archives contain ten real workouts, from October 2
  through October 19, 2026, and one synthetic test workout in a separate batch.
- All eleven JSON workout UUIDs are distinct. Future rolling uploads can repeat
  UUIDs across batches, so this sample does not remove the need for deduplication.
- Six real JSON workouts are walks. Under the existing exclusion rule, the ten
  real workouts contribute four workouts to published counts.
- These JSON workouts do not overlap the audited XML history. Matched XML/JSON
  measurement parity has therefore not been established.

The JSON audit used remote vault revision
`0bdb31546a6ce4e15177b613e4133eb4df68d66c`; the user's local vault checkout was
older. These counts describe that snapshot, not a guarantee of current coverage.

## Input contract

Discover all files matching:

```text
<storage-root>/files/apple_health/actions/batches/*.json
```

Read DDU's archived envelope, rather than the phone's upload request format:

```text
batch_id
received_at
schema_version
normalization_version
timezone_assumed
warnings
workouts: [{raw, normalized}]
```

The currently supported schema and normalization versions are both 1. Validate
the envelope, versions, filename/batch ID consistency, workout UUIDs, required
fields, finite measurements, and timestamp resolution before persistence.
Unsupported versions or malformed files must produce visible failures, with no
partial writes from the affected batch.

Use the normalized measurements and timestamp resolutions supplied by DDU;
retain raw values, assumptions, warnings, and archive references as provenance.
Do not reinterpret old archives using a new machine timezone or file modification
time. DDU's batch identity depends on raw values, so batch IDs and normalized
workout UUIDs serve different purposes.

An empty archive or a workout absent from a later rolling upload never implies
deletion.

## Data coverage and measurement rules

| Current D3 field or input | JSON coverage | Planned handling |
| --- | --- | --- |
| Workout identity | Required UUID | Normalize case and maintain aliases to existing rows. |
| Activity type | Required display label | Map to D3's existing activity categories. |
| Start/end timestamps | Minute precision; timezone assumed | Preserve assumptions and precision; use resolved instants. |
| Duration | Required decimal seconds | Use `duration`, as confirmed by the user. |
| Elapsed time | Optional, separate from duration | Preserve separately; do not substitute for duration automatically. |
| Active calories | Optional; normalized kcal with an assumed unit | Use the normalized value and retain its unit assumption. |
| Total calories | `energy_burned`; uploader warning remains unverified | Map to D3's `total_calories`, as confirmed by the user. |
| Average heart rate | Optional; normalized bpm with an assumed unit | Use the normalized value and retain its unit assumption; absent values stay null. |
| Maximum heart rate | Missing | Preserve existing XML values; null for new JSON-only rows. |
| Source name | Optional raw field | Preserve when available. |
| Source version | Missing | Preserve existing XML values; null for new JSON-only rows. |
| Device | Optional name/model; not full XML metadata | Preserve structured provenance without replacing richer XML metadata. |
| Creation date | Missing | Preserve existing XML values; do not invent a timestamp. |
| Associated heart-rate, active-energy, and basal-energy samples | Missing | XML fallback calculations cannot be reproduced from these JSON archives. |

JSON also supports distance, speed, flights climbed, recording method, and
watch/third-party flags. Preserve these in provenance even where D3 has no
current workout column or report metric for them. The audited real batch has no
distance, speed, or flights-climbed measurements, and its six walks have no
average heart rate.

Missing measurements remain missing. Do not turn them into zero or derive maximum
heart rate from an average. D3 currently aggregates null total calories as zero;
coverage reporting must make incomplete calorie totals visible before cutover.
If report behavior needs to change, define that explicitly in `docs/SUMMARY.md`.

## Identity and deduplication

### Identifier origins

The existing XML importer uses `HKExternalUUID` when present. Otherwise it
generates a SHA-1 hash from activity type, start date, end date, source name, and
creation date. The audited XML workout elements do not expose HealthKit's
internal object UUID, and the vault extraction script preserves whole workout
elements rather than stripping their attributes.

Apple documents external UUID metadata as independent of the HealthKit object
UUID. DDU accepts `identifier` from the Actions/Shortcut payload and lowercases
its normalized representation, while retaining the original spelling in `raw`.
It does not generate a workout UUID. The user confirmed that we should use the
payload's unique identifier regardless of whether it is HealthKit's internal UUID.
It must consistently identify the same workout across exports for deduplication
to work; its precise UUID namespace is not a prerequisite for import.

During implementation, the user also confirmed `duration` as workout duration and
`energy_burned` as total calories. These are the active mapping policies. Retain
the original uploader warnings as provenance; do not rewrite archived envelopes
to suggest that the uploader itself verified these meanings. Matched XML/JSON
parity remains useful validation when overlapping real archives become available.

References:

- [HealthKit object UUID](https://developer.apple.com/documentation/healthkit/hkobject/uuid)
- [External UUID metadata](https://developer.apple.com/documentation/healthkit/hkmetadatakeyexternaluuid)
- [UUID textual representation](https://www.rfc-editor.org/rfc/rfc9562.html#section-4)

### Deduplicate JSON before writes

1. Validate observations and group them by lowercase workout UUID across all
   discovered batches, including within each file. DDU rejects duplicate UUIDs
   within uploads, but D3 must still validate its own inputs.
2. Collapse equivalent observations. A batch ID identifies an upload snapshot,
   not an individual workout.
3. For changed snapshots of the same UUID, use the newest envelope `received_at`
   as precedence. This is upload receipt time, not workout modification time.
4. If equal receipt times contain conflicting measurements or identity fields,
   flag the conflict and retain the last accepted state until resolved. Do not
   let filesystem order choose a winner.
5. Preserve previously accepted nonmissing values when a later snapshot omits
   them. Record field provenance so a preserved value is not represented as a
   new measurement from the latest batch.
6. Compare incoming precedence with persisted state so replaying an older batch
   cannot overwrite newer accepted values.

UUID deduplication applies to all JSON observations regardless of workout date.
Do not lowercase arbitrary XML external identifiers as if they were UUIDs.

### Match existing XML-derived rows only from August 2026 onward

Preserve all existing workout rows. Restrict cross-format matching to workouts
starting on or after **August 1, 2026**. The cutoff uses workout start time,
because JSON does not contain creation time.

Use midnight in `America/Los_Angeles` for the boundary
(`2026-08-01T00:00:00-07:00`), comparing resolved instants. Preserve each archive's
own timestamp assumptions; unresolved or inconsistent dates require review.

For each deduplicated JSON workout:

1. If a UUID alias already exists, use the mapped row directly. No fuzzy matching
   is needed, including on subsequent imports of older workouts.
2. If it predates the cutoff and has no alias, skip importing it and flag it.
   This deliberate policy skip does not fail sync and is not retried unless a
   new snapshot or explicit alias arrives. Historical backfill requires a
   separate deliberate reconciliation process.
3. For an eligible workout, search only existing rows at or after the cutoff.
   Compare normalized activity, compatible source, start/end minute windows,
   and agreement of XML duration with either JSON `duration` or `elapsed_time`.
   Real overlapping data showed that paused sessions can have XML duration
   matching JSON elapsed time while JSON duration represents the wall-clock span.
   This agreement is identity evidence only: retain XML duration on matched rows
   and continue using JSON `duration` on new rows. Coverage reports this difference
   for matched non-walk workouts. Missing measurements such
   as maximum heart rate are not prerequisites for identity matching.
4. Accept only a unique match supported by the available identifying evidence.
   A matching timestamp alone is insufficient. Missing source information or
   incompatible timezone assumptions must not silently weaken the match.
5. For a confirmed match, retain the existing row ID and save an Actions UUID
   alias to it. Preserve richer XML fields and original identity information.
6. If no plausible existing candidate exists, insert one JSON-only row keyed by
   its normalized UUID. If plausible candidates exist but evidence is ambiguous,
   hold the observation out of published totals and report it for review.

The absence of overlap in the audited sample makes its real workouts new
candidates, but does not prove the correctness of cross-format matching. The
synthetic workout must be excluded before inserting any rows.

## Persistence and migration

Back up the existing SQLite database before applying a schema migration. Add
persistent state for:

- UUID aliases pointing to canonical workout rows.
- Imported batch IDs, content fingerprints, supported versions, and outcomes.
- Accepted snapshot precedence, source references, and field provenance.
- Excluded or unresolved observations and the reason they were held.

Table definitions are documented in `src/README.md`. Keep this state alongside the workouts so incremental imports
and rebuilds use the same reconciliation decisions. Commit batch completion
state atomically with the associated workout and alias changes. Failed and
unresolved observations must remain retryable; they are not successful imports.

Preserve existing measurements unless an explicitly verified field policy permits
replacement. The current unconditional upsert must not replace XML values with
JSON nulls or lower-precision timestamps. Walk normalization and the existing
report month grouping must remain consistent during this migration.

The known synthetic batch is:

```text
a7dc2872eb888d24b61a27360ae6cac29e6c4dc10c4f9ab5b7fac01693b5ff73
```

Record an explicit exclusion for this batch. Do not infer that arbitrary UUID
prefixes or source names identify test data. Keep personal payloads in DDV and
use synthetic fixtures in D3 tests.

## Sync behavior and reporting

Keep `apple-health-sync` as the entrypoint, but change discovery and status from
the latest XML file to the JSON archive set. Track completed batches to avoid
reprocessing unchanged files; reject unexpected content changes for a previously
imported immutable batch. Existing UUID mappings avoid repeated cross-format
searches. These optimizations must preserve the same result as a full replay.

Report files scanned, unchanged batches, observations read, unique UUIDs,
duplicates collapsed, inserted/updated/unchanged rows, excluded test data,
pre-cutoff skips, ambiguous matches, invalid batches, and measurement coverage.
Do not report an import as entirely successful when it contains validation
failures or unresolved observations. Deliberate pre-cutoff skips are informational
and remain visible separately from pending observations.

Ongoing sync must not require XML. Retain the historical database and XML archive
as a baseline: today's JSON does not contain the historical workouts or all of
their measurements. A fresh rebuild needs that baseline plus migration/alias
state and JSON archives, or a separately designed complete backfill. JSON alone
cannot currently reproduce the full database.

## Implementation sequence and acceptance checks

1. Use the user's confirmed UUID, duration, and total-calorie policies. Obtain
   overlapping real XML/JSON workouts when available to further validate source
   labels and timestamp assumptions; the current real sample has no overlap.
2. Implement the envelope reader, version validation, activity normalization,
   provenance handling, and explicit synthetic exclusion using synthetic tests.
3. Add the backed-up database migration, UUID aliases, batch tracking, and
   deterministic deduplication before workout writes.
4. Implement the August 1 cutoff and conservative cross-format reconciliation.
5. Connect sync/status to JSON and compare analysis and generated outputs using
   a copied database before changing the production database.
6. Update the user and technical documentation in their designated files.

Required tests cover:

- Identical UUIDs across files and UUID case differences; distinct UUIDs must
  not be merged solely because their measurements look similar.
- Changed snapshots, equal-time conflicts, missing optional fields, and older
  replays; file order must not change accepted results.
- Preservation of all historical rows and richer XML fields.
- A confirmed legacy match creating one alias without increasing workout count;
  ambiguous candidates must not create duplicate rows.
- Pre-cutoff skips, the exact cutoff boundary, and subsequent direct alias lookup.
- Unsupported versions, malformed JSON, invalid identifiers, unresolved DST
  timestamps, timezone assumptions, and minute precision.
- Walk exclusion and multiword labels such as `Traditional Strength Training`.
- Synthetic batch exclusion, restart/retry behavior, and transactional persistence.
- Monthly count, duration, calorie coverage, and month-boundary behavior compared
  with the preserved baseline.

Run `make test-ci` after implementation changes and before any code commit.
Verify generated output with `uv run main.py publish --dry-run` against a copied
storage root; this is also required if the markdown generator changes. No
production import is part of this implementation's validation; use a copied
database instead.

## Initial implementation validation (2026-10-20)

- `make test-ci`: 280 tests passed on the pinned Python 3.12.9 runtime.
- Imported the audited JSON archives into an isolated copy of the vault data:
  all 960 historical workout rows remained identical, ten real workouts were
  added, and the synthetic test workout was excluded.
- All 53 historical monthly count, duration, and calorie totals remained
  unchanged. October's new non-walk totals were four workouts, 22,549 seconds,
  and 2,939.74 kcal.
- Replaying unchanged archives inserted and updated no workouts; completed UUIDs
  bypassed JSON parsing, snapshot replay, and legacy matching.
- `uv run main.py publish --dry-run` completed against the copied storage root.
  The preview showed four workouts, 6h 16m, and 2,940 kcal with the expected
  activity breakdown. The production database and uploader were not changed.

## First production sync (2026-10-21)

The user requested a live sync against the latest 100-workout upload. The vault
checkout was fast-forwarded to `213a8cd`; this added only JSON archives.

- Three archives contain 110 real observations representing 100 unique UUIDs,
  plus the separately excluded synthetic test workout. Ten observations repeat
  across the earlier and newer real batches.
- Eleven new October workouts were inserted and 64 UUIDs were linked to existing
  XML-derived rows. The 25 workouts before August 1 were recorded as deliberate
  skips. No observations remain pending, and no archive failed validation.
- Six otherwise unique legacy matches initially failed the duration check.
  Their XML durations agree with JSON `elapsed_time`, while JSON `duration`
  differs. Matching now accepts either measurement as identity evidence while
  preserving XML duration and continuing to use `duration` for JSON-only rows.
  Coverage flags these six differences for review.
- Deliberate pre-cutoff skips now have a separate status and do not fail sync or
  block analysis. They are not reprocessed without new observations or aliases.
- All 960 original workout rows remained identical, all 53 historical monthly
  totals were unchanged, and the database contains 971 workouts after sync.
  SQLite integrity and foreign-key checks passed. The pre-migration database is
  retained in `data/.backups/apple_health.db.pre-json-v1.sqlite3`.
- Monthly analysis was refreshed. October contains five non-walk workouts,
  25,984 seconds, and 3,276.62 kcal. Report dry-run showed five workouts,
  7h 13m, and 3,277 kcal. No report was published.
- A subsequent sync inserted, updated, and matched no additional workouts.
  `make test-ci` passed all 283 tests, including the duration evidence and
  non-blocking cutoff-skip regressions.
