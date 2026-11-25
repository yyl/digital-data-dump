# AGENTS.md

## Project Notes

1. Use `uv run main.py publish --dry-run` to test changes made to the markdown generator and verify the generated report output locally.
2. Follow these rules for documentation separation of concerns:
   - `docs/SOURCES.md`: Supported sources, per-source setup, required/optional env vars, and source-specific user-facing usage notes.
   - `docs/SUMMARY.md`: Report details, output formats, and generated layout rules.
   - `README.md`: User guide, high-level project setup, and CLI command usage.
   - `src/README.md`: Technical details, implementation architecture, backfill/publish internals, and database schemas.
3. Use `make test-ci` when you need a local run that matches the pinned CI Python version and test entrypoint as closely as possible.
4. Always run `make test-ci` after code changes made to confirm all tests pass before committing. Never commit code with failing tests.

## Source and Pipeline Conventions

Use the [source integration guide](src/README.md#adding-or-changing-a-source)
for registration, schema ownership, and the locations of the reporting hooks.

- Keep provider logic in `src/<source>/` and reuse the shared source catalog and
  batch runner. Keep sync, network-free local analysis, and refresh distinct.
- Make imports safe to retry. Advance checkpoints only after the covered data
  is fetched and saved. Distinguish a successful empty fetch, a skip, and a failure.
- Use the shared read-only database helpers for status and reporting. Surface
  broken schemas and distinguish unavailable sources from available empty results.
- Select scheduled refresh and outputs explicitly. Refresh once and render all
  monthly outputs before delivery. Preserve [output contracts](docs/SUMMARY.md),
  including field names, month rules, and privacy filters.
- Follow the [metric change guidelines](src/README.md#metric-definitions-and-changes)
  when a metric’s meaning changes. Verify changes through the affected CLI
  commands using the [testing guide](src/README.md#testing).
