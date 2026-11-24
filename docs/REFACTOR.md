# D3 refactor review

Reviewed against `e03b1a7`. The review covered all 14 source packages, the CLI,
scheduled workflows, SQLite ingestion and analysis, and Markdown and activity
exports. The baseline was 512 passing tests on Python 3.12.9 and a successful
local report dry run. The reproductions used temporary databases and repositories
and mocked provider calls.

D3's source packages have zero direct cross-source imports. The main opportunity
is the application code that runs them and publishes their data. `main.py` and
the three main reporting modules total 4,000 lines. Adding Kaya required changes
in all four as well as its own package.

## Findings and actions

1. **High. Workflow database changes can go unstaged.** The monthly and Schwab
   jobs stage databases together with an optional token file and suppress Git
   errors. A missing token file rejects the entire staging command. Stage
   database files independently and stage token files when present. Propagate
   unexpected staging errors.
   [Monthly workflow](../.github/workflows/monthly-pipeline.yml) ·
   [Schwab workflow](../.github/workflows/schwab-sync.yml)
2. **High. Incremental sync can reread history or skip failed data.** Foursquare
   zeros its saved cursor before reading it and can return a partial result after
   a failed page. Oura can advance past a failed write. Checkpoint only completed
   work, make partial retrieval visible, and keep failed inputs eligible for
   retry. Preserve the source-specific cursor and identity rules.
   [Foursquare sync](../src/foursquare/sync.py) ·
   [Foursquare client](../src/foursquare/api_client.py) ·
   [Oura sync](../src/oura/sync.py)
3. **High. The CLI conflates absence, failure, and success.** Foursquare can
   return the same counts on failed authentication as on a clean empty fetch.
   The shared analyzer ignores the sync result. Aggregate `analyze` can report
   completion after exceptions or abort early on a nested `SystemExit`. Give
   operations explicit outcomes and have the CLI determine the exit code after
   attempting independent sources.
   [CLI](../main.py)
4. **Medium. Removed inputs can leave stale totals and activity files.** Moving
   the last Readwise article out of its archive month clears the source breakdown
   while leaving the monthly total. An empty activity export is omitted and the
   GitHub writer preserves the old file. Replace derived records for the scope
   recomputed and distinguish an available, empty export from an unavailable
   source. Preserve the difference between zero, unknown, and unobserved periods.
   [Readwise analysis](../src/readwise/analytics.py) ·
   [Activity export](../src/publish/data_generator.py) ·
   [GitHub writer](../src/publish/github_client.py)
5. **Medium. Scheduled publication repeats refresh and reads.** The configured
   schedule invokes 24 refreshes across 12 sources. Backfill also reads the same
   activity history twice and delivers private files before rendering the blog
   window. Refresh once, render the draft and both activity windows from the
   resulting data, then deliver them. Delivery retries should be able to reuse
   existing analysis.
   [Monthly workflow](../.github/workflows/monthly-pipeline.yml) ·
   [Publisher](../src/publish/publisher.py)
6. **Medium. Report month selection and status use inconsistent readiness.**
   A raw Strong workout can render an explicit month while automatic selection
   finds no analysis month. Some status paths create or migrate databases, as
   reproduced with Blog. Let report readers identify eligible months and reuse
   the existing read-only SQLite policy for status.
   [Publisher](../src/publish/publisher.py) · [SQLite reader](../src/database.py) ·
   [Blog sync](../src/blog/sync.py) · [Surfilog sync](../src/surfilog/sync.py)

## Implementation order

1. Fix workflow staging, Foursquare and Oura checkpoint handling, and the
   reproduced stale Readwise total. Verify interrupted work can be retried and
   that removing the final eligible record also removes the derived month.
2. Expose callable sync, local analysis, and refresh operations. Use a small
   explicit source catalog for CLI registration and batch execution. Keep
   existing commands and source-specific options, record intentional skips, and
   give batch failures a consistent exit status. Run the scheduled refresh once
   before rendering and delivering its outputs.
3. Consolidate reporting around contributions that can supply eligible months,
   a Markdown section, and an activity export as applicable. Start with Oura's
   duplicated sleep/readiness pivot, Strong's month eligibility and unused
   helpers, and the repeated YAML export loop. Render both activity windows
   before delivery. Cover empty window replacement and a fixture source that can
   be registered without changing the generic loops.
4. Apply the existing read-only database policy to status. Use explicit column
   checks on write-side schema migrations. Reuse processed-archive tracking for
   Kaya if repeated archive parsing becomes a material cost.

Preserve validated snapshot replacement in Strong and Surfilog, Apple Health
provenance and aliases, Workflowy event history, and GitHub visibility filtering.
Preserve the current report and export contracts. Strong contributes a Markdown
section, Apple Health owns `workouts.yaml`, and Schwab and Workflowy are outside
the scheduled reporting profile.

For each change, run `make test-ci`. For Markdown changes, also run
`uv run main.py publish --dry-run` and compare the report and assets against the
existing output contract.

## Implementation and verification

- Monthly and Schwab staging handle optional token files independently.
  Temporary Git repositories verified all four combinations of database and
  token file presence in both workflows.
- Foursquare keeps its cursor across empty, failed, and concurrent runs and
  revisits the cursor second to pick up unseen checkin IDs. Oura advances an
  endpoint checkpoint only after processing its full fetch. Readwise rebuilds
  the monthly totals and source breakdown together.
- The source catalog drives CLI registration, initialization, batch refresh, and
  read-only status. `--local` runs analysis without source requests. A batch
  attempts independent sources and exits with failure if a selected operation
  fails. The scheduled pipeline refreshes once and renders all outputs before
  delivery.
- Report contributions supply month eligibility, section data, and tags. Activity
  contributions share one export loop and both delivery windows use the same
  loaded records. Strong's eligible months come from its raw workouts, and Oura
  shares a score reader across Markdown and activity YAML. Available empty
  activity windows publish `[]` to replace old data.
- `make test-ci` passed 514 tests. The local report preview matched the baseline
  apart from its generation timestamp, and its asset matched by checksum. All
  11 activity exports matched the baseline in both delivery windows.

The configured local vault had no archived Kaya CSVs during verification.
Processed-archive tracking stays deferred until repeated parsing has a measured
cost. Remaining source-specific report SQL can move into source-owned readers
as those queries change.

### Local end-to-end run

- The aggregate sync completed for 11 sources against a copy of the local vault.
  Hardcover lacked an API token. Oura and Schwab rejected their existing access
  tokens with refresh disabled for the test. Sync returned exit status 1 and
  continued through the remaining sources.
- `analyze --local` rebuilt the analysis for all 14 sources. Every copied SQLite
  database passed `PRAGMA quick_check`. The run exposed a status regression for
  Schwab's two monthly tables. Status now uses each database's declared analysis
  tables, and a CLI regression test covers Schwab.
- The October 2026 dry run and local Git publish produced a matching draft and
  two assets. Both temporary destinations received 11 activity YAML files. The
  blog files matched the full history filtered to the rolling cutoff.
