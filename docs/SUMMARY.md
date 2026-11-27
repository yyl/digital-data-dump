# Report Summary Format

This document describes what the generated monthly report looks like.

## Overview

The `publish` command generates a draft markdown wrap-up post for a single month.

By default, the report uses the latest month with data eligible for a report
section. Most sections use monthly analysis. Weightlifting uses raw Strong
workouts, and its latest workout in the month must include exercises. With
`--last-month`, the previous calendar month must have eligible report data.

## Output Format

- Title format: `Wrap up {month_name} {year}`
- Slug format: `wrap-up-{month}-{year}`
- Output path: `posts/wrap-up-{month}-{year}.md` in the data repository
- Image assets accompany the draft under `posts/assets/wrap-up-{month}-{year}/`.
  For Hugo, move the Markdown into a leaf bundle such as
  `content/posts/wrap-up-09-2026/index.md` and place that month's asset directory
  under `content/posts/wrap-up-09-2026/assets/wrap-up-09-2026/`.
  This preserves the Markdown image paths.
- Draft status: `draft: true`

`publish --dry-run` writes a local preview and its images to
`.cache/report-preview/index.md`.

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
9. `Bouldering`
10. `Weightlifting`
11. `Travel`
12. `Movies`
13. `Sleep & Readiness`

Only sections with available data are included.

Missing or uninitialized databases and unavailable inputs are reported in CLI
diagnostics and omitted from the post. Incomplete schemas and SQLite read errors
stop generation and identify the source.

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
- the three places with the most checkins in that month, including location and visit count
- a static OpenStreetMap image automatically fitted to the visited places

Place rankings count distinct Foursquare venue IDs. Ties are ordered by place
name and then venue ID, and months follow the existing UTC checkin grouping.
Map markers use stored venue coordinates and grow with visit count. A coverage
caption identifies how many places have valid coordinates. The image includes
OpenStreetMap attribution.

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

The **Activity Types** table shows workout count, total duration, total calories,
average heart rate, and maximum heart rate for each type in the report month.
Average heart rate gives each workout with a recorded average equal weight.
Maximum heart rate is the highest recorded workout maximum. Calories sum the
available measurements. A field with no recorded measurements shows `N/A`.

Apple Health JSON uses the confirmed workout `duration` and `energy_burned`
(total kcal) mappings. Existing XML-derived measurements are preserved. Walks
remain excluded, and months follow the existing UTC grouping. Missing calorie
measurements contribute nothing to the existing sum; sync reports their coverage
so a partial total is not mistaken for complete measurement coverage. Observations
held for identity or timestamp review are not added to workout rows or totals.

### Surfing

Sourced from Surfilog. Shows:

- sessions and total waves caught
- time in the water and riding time
- median and maximum wave duration
- median wave top speed and maximum speed
- riding distance and paddling distance
- longest wave by distance

Each metric shows MoM and YoY changes. Missing or zero comparison baselines
show `N/A`. Wave duration, speed, and longest wave are unavailable for months
with sessions but no counted waves. Median speed uses each counted wave's top
speed.

The report uses session-local calendar months. Excluded waves remain in raw
storage but do not contribute to wave counts, riding measurements, or records.
Individual GPS tracks, spot names, and session share links are not rendered.

### Bouldering

Sourced from Kaya. The report shows days with a logged climb, total sends,
recorded attempts, flashes, onsights, and a send count by grade. Redpoints,
flashes, and onsights count as sends. Days climbed and sends include MoM and YoY
changes. Recorded attempts sum the counts in that month's logs, including logs
without a send. The report shows how many logs are missing a count when the
total is partial and displays `N/A` when every count is missing.
The hardest V grade appears when there is a send with a numeric V grade.

### Weightlifting

Sourced from Strong. Shows the date, name, and total duration of the report month's
latest workout, followed by a table with one row per exercise:

| Exercise | Best weight | MoM | YoY | Total volume (lb × reps) |
| --- | ---: | ---: | ---: | ---: |
| Squat (Barbell) | 145 | +4% | +26% | 2,175 |

Total volume sums each set's recorded weight multiplied by its repetitions in
that workout. A missing weight or repetition count makes that exercise's volume
unavailable. Bodyweight sets retain their recorded weight. Total time uses the
session's elapsed duration in Strong; exercise-level time is unavailable.

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

A static hourly chart shows authored commit counts split by public/private
visibility. Hours use `America/Los_Angeles`, including daylight saving time.
The report month follows the existing stored author month. Commit timestamps
provide an activity distribution. Measuring coding hours would require a separate
time-tracking source.

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

`backfill` and `pipeline` publish monthly YAML files under `data/activity/`.
The data repository receives full history. The blog receives a rolling window
starting with the same calendar month one year earlier, inclusive. A source
with available analysis and an empty window writes `[]`. An unavailable source
leaves its existing export in place.

Each record includes a `month` in `YYYY-MM` format.

| File | Source | Other fields |
|------|--------|--------------|
| `reading.yaml` | Readwise | `articles_archived`, `total_words`, `time_spent_minutes`, `avg_reading_speed`, `max_words_per_article`, `median_words_per_article`, `min_words_per_article` |
| `travel.yaml` | Foursquare | `checkins`, `unique_places` |
| `movies.yaml` | Letterboxd | `movies_watched`, `minutes_watched`, `avg_rating` |
| `podcasts.yaml` | Overcast | `feeds_added`, `feeds_removed`, `episodes_played`, `minutes_listened` |
| `workouts.yaml` | Apple Health | `workouts`, `total_minutes`, `total_calories` |
| `writing.yaml` | Blog | `posts`, `total_words`, `unique_tags` |
| `books.yaml` | Hardcover | `books_finished`, `avg_rating` |
| `code.yaml` | GitHub | `commits`, `repos_touched`, and available public/private commit, repository, and line-change counts |
| `sleep.yaml` | Oura Ring | Available `median_sleep_score`, `avg_sleep_score`, `median_readiness_score`, and `avg_readiness_score` values |
| `surfing.yaml` | Surfilog | `sessions`, `waves`, `total_duration_seconds`, `surf_time_seconds`, `surf_distance_m`, `paddling_distance_m`, `max_speed_kmh`, `longest_wave_m`, `max_wave_seconds` |
| `bouldering.yaml` | Kaya | `climbing_days`, `sends`, `flashes`, `onsights`, `grade_counts`, optional `hardest_v_grade` |
| `weightlifting.yaml` | Strong | `workouts`, the number of Strong workouts logged that month |

In `bouldering.yaml`, `grade_counts` maps grades to send counts. An empty grade
key counts ungraded sends. When available, `hardest_v_grade` holds the numeric
part of the highest V grade sent, such as `4` for V4.

## Latest Podcast Card

The blog homepage reads `data/activity/latest_podcast.json`, refreshed daily by
`overcast-publish-latest`. The snapshot contains:

- `title`: played episode title
- `url`: `https://overcast.fm/+...` episode link, or an empty string if the
  stored URL does not match that pattern
- `detail`: podcast show title
- `date`: played timestamp normalized to UTC ISO 8601

The snapshot is updated only when a newer or changed played episode is found;
it never overwrites a newer episode already committed to the blog.

## Latest Workout Card

The blog homepage reads `data/activity/latest_workout.json`. The snapshot
contains `title` (workout type), `detail` (duration in whole minutes or seconds
for workouts under a minute, empty when unavailable), and `date` (the UTC start
day in `YYYY-MM-DD`).
Walks are excluded, as in the monthly workout report. The snapshot includes
only these three fields.
