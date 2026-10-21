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
3. `Travel`
4. `Movies`
5. `Podcasts`
6. `Workout`
7. `Writing`
8. `Books`
9. `Code`
10. `Sleep & Readiness`

Only sections with available data are included.

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

- a ranked source summary table
- grouped article tables
- grouped highlights

First-time reading sources are marked with `🆕`.

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

- a ranked podcast summary table
- grouped episode tables

New podcast feeds are marked with `🆕`.

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

- commits
- repos touched

It also includes:

- a ranked repo summary table
- grouped commit tables

Merge commits of the form `Merge pull request #...` are excluded.

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
