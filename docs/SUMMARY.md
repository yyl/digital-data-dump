# Report Summary Format

This document describes what the generated monthly report looks like.

## Overview

The `publish` command generates a draft markdown wrap-up post for a single month.

The report is built from each source's monthly analysis data and includes the latest available month across the initialized sources. With `--last-month`, it includes the previous calendar month instead, requiring analysis data for that month.

## Output Format

- Title format: `Wrap up {month_name} {year}`
- Slug format: `wrap-up-{month}-{year}`
- Output path: `posts/wrap-up-{month}-{year}.md` in the data repository
- Draft status: `draft: true`

## High-Level Layout

The report contains:

1. Hugo front matter
2. `Reading`
3. `Books`
4. `Podcasts`
5. `Writing`
6. `Code`
7. `Workout`
8. `Surfing`
9. `Weightlifting`
10. `Travel`
11. `Movies`
12. `Sleep & Readiness`

Only sections with available data are included.

Missing or uninitialized databases and unavailable analysis are reported in CLI
diagnostics and omitted from the post. Incomplete schemas and SQLite read errors
stop generation with the source name; they do not produce a partial report.

## What's New

`What's new` blocks appear inside the section they belong to and highlight newly seen items for the month, such as:

- new reading sources
- new podcast feeds
- new GitHub repos
- new places visited

## Section Details

### Reading

Shows article totals and reading metrics such as:

- articles archived
- total words
- time spent reading
- average reading speed
- max, median, and min words per article

It also includes:

- a ranked source summary table with estimated reading time per source
- grouped article tables with estimated time per article
- grouped highlights

First-time reading sources are marked with `🆕`.
Reading time uses the estimates saved by Readwise. Source totals with missing
estimates are marked partial, or shown as `N/A` when every estimate is missing.

Newsletter-style `mailto:` links are rendered as plain text instead of broken links.

### Travel

Shows:

- checkins
- unique places visited

### Movies

Shows:

- movies watched
- average rating
- min rating
- max rating
- average years since release

It also includes a movie table with watch date and rating for the month.

### Podcasts

Shows:

- new feeds subscribed
- feeds removed
- episodes played
- minutes played

It also includes:

- a ranked podcast summary table with estimated listening time per show
- grouped episode tables with individual episode durations

New podcast feeds are marked with `🆕`.
Listening estimates sum the full durations of episodes marked played. Show
totals with missing durations are marked partial, or shown as `N/A` when every
duration is missing.

### Workout

Shows:

- workouts
- total time
- total calories

This section is sourced from Apple Health analysis.

Apple Health JSON uses the confirmed workout `duration` and `energy_burned`
(total kcal) mappings. Existing XML-derived measurements are preserved. Walks
remain excluded, and months follow the existing UTC grouping. Missing calorie
measurements contribute nothing to the existing sum; sync reports their coverage
so a partial total is not mistaken for complete measurement coverage. Observations
held for identity or timestamp review are not added to workout rows or totals.

### Surfing

Sourced from Surfilog. Shows:

- sessions and waves caught, with MoM and YoY comparisons
- time in the water and riding time
- riding distance and paddling distance
- maximum riding speed and longest wave

The report uses session-local calendar months. Excluded waves remain in raw
storage but do not contribute to wave counts, riding measurements, or records.
Individual GPS tracks, spot names, and session share links are not rendered.

### Weightlifting

Sourced from Strong. Shows the date and name of the report month's latest
workout, followed by a table with one row per exercise:

| Exercise | Best weight | MoM | YoY |
| --- | ---: | ---: | ---: |
| Squat (Barbell) | 145 | +4% | +26% |

Best weight is the highest recorded set weight for that exercise in that
workout, rather than an all-time or monthly record. Comparisons use the same
exercise's latest session in the previous calendar month and the same calendar
month last year. Missing comparisons and zero baselines show `N/A`. API-backed
reports label the configured weight unit (`lb` or `kg`). CSV-backed reports use
the export's unspecified units; bodyweight exercises retain their recorded zero
weight.

The section is omitted when the month has no Strong workout or its latest
workout has no exercise sets. See the
[calculation rules](../src/README.md#strong-metric-definitions).

### Writing

Shows:

- posts
- total words
- unique tags

It also includes a top-tags table when available.

### Books

Shows:

- books finished
- average rating

### Code

Shows:

- commits, split into Public and Private
- repos touched, split into Public and Private
- lines added and lines deleted, split into Public and Private

Each visibility group has its own MoM and YoY comparison:

```markdown
- **Commits**:
    - Public: 42 (-26% MoM, +91% YoY)
    - Private: 42 (-26% MoM, +91% YoY)
- **Repos Touched**:
    - Public: 5 (-29% MoM, +150% YoY)
    - Private: 5 (-29% MoM, +150% YoY)
```

Comparisons show `N/A` when the relevant previous period is missing or zero.
Existing combined analysis continues to render as combined totals until
`github-analyze` recalculates the visibility breakdown for all stored months.

Line counts include text changes across all files, including documentation and
generated files. For each month and visibility group, a missing commit's line
counts make that group's totals unavailable. The report shows `N/A` if the
other group has a total. `code.yaml` includes the available fields
`public_additions`, `private_additions`, `public_deletions`, and
`private_deletions`.

It also includes:

- a ranked repo summary table
- grouped commit tables

Aggregate counts include synced private activity. Repo summaries, grouped
commit tables, and new-repo lists show public repositories only; private repo
names, links, and commit messages are omitted. Merge commits of the form
`Merge pull request #...` are excluded from detail tables, while totals count all
synced commits.

For input coverage, month boundaries, exact formulas, visibility changes, and
historical recomputation, see the
[GitHub metric definitions](../src/README.md#github-metric-definitions).

### Sleep & Readiness

Shows Oura Ring monthly aggregates:

- median sleep score
- average sleep score
- median readiness score
- average readiness score

## Comparisons

Where enough historical data exists, the report includes:

- Month-over-Month (`MoM`) comparisons
- Year-over-Year (`YoY`) comparisons

These appear inline with top-line metrics.

## Activity Data Files

The related `backfill` workflow regenerates monthly YAML data files under `data/activity/` for the blog.

Those files are not the markdown report itself, but they are derived from the same monthly analysis layer.

`surfing.yaml` includes `month`, `sessions`, `waves`, `total_duration_seconds`,
`surf_time_seconds`, `surf_distance_m`, `paddling_distance_m`, `max_speed_kmh`,
`longest_wave_m`, and `max_wave_seconds`.
