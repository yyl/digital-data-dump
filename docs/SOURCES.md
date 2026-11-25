# Supported Sources

This project supports the following sources for sync and monthly analysis.

All source data is stored in local SQLite databases under `<storage-root>/data/`. File-based imports are read from `<storage-root>/files/`.

For shared CLI behavior, including local analysis and monthly publication, see
the [CLI guide](../README.md#basic-usage).

## Readwise

Tracks books, highlights, and Reader documents.

**Commands**
- `readwise-sync`
- `readwise-analyze`

**Required in `.env`**
- `READWISE_ACCESS_TOKEN`

## Workflowy

Mirrors the current Workflowy outline as nodes, retaining locally observed deletions as tombstones and computing monthly activity counts.

**Commands**
- `workflowy-sync`
- `workflowy-analyze`

**Required in `.env`**
- `WORKFLOWY_API_KEY`

Create an API key in Workflowy account settings and add it to `.env`. Workflowy exposes a full `nodes-export` endpoint but no documented delta cursor or modified-since filter, so every sync downloads the complete node export and locally upserts only changed nodes. The export endpoint is limited to one request per minute; wait before retrying a rate-limited manual sync.

`workflowy-analyze` syncs first, then writes monthly counts of nodes added,
modified, and removed to the local `analysis` table. It also runs as part of
`analyze`. Creation and modification use Workflowy's dates; removals use the
date sync detects a missing node. Run sync regularly to capture changes: the
export only provides each node's latest modification, and past deletion dates
cannot be recovered. See the [metric definitions](../src/README.md#workflowy-metric-definitions)
for coverage limits. Workflowy report publishing is not included yet.

## Foursquare

Tracks Swarm/Foursquare checkins and place visits.

**Commands**
- `foursquare-sync`
- `foursquare-analyze`

**Required in `.env`**
- `FOURSQUARE_ACCESS_TOKEN`

**Optional in `.env`**
- `FOURSQUARE_CLIENT_ID`
- `FOURSQUARE_CLIENT_SECRET`
- `FOURSQUARE_API_KEY`

The sync reads checkins for the one Swarm account associated with its OAuth
token. For an unapproved pay-as-you-go Foursquare organization, use a Swarm
account that belongs to the developer organization that owns the OAuth project.
Use the client ID and secret when you need to run the OAuth flow again. If you
replace the token, update `FOURSQUARE_ACCESS_TOKEN` in GitHub Actions as well
if you use the monthly workflow. The optional API key enriches venue details.

Travel maps use the stored place coordinates and OpenStreetMap tiles, with no
additional API key. The first preview or publish downloads the visible map tiles
and caches them under `.cache/map-tiles/` for at least seven days. Tile download
failures are reported so the map can be retried. Venue coordinates are supplied
by the existing Foursquare sync.

## Letterboxd

Tracks watched movies and ratings.

**Commands**
- `letterboxd-sync`
- `letterboxd-analyze`

**Required in `.env`**
- None

**Optional in `.env`**
- `LETTERBOXD_RSS_URL`
- `TMDB_ACCESS_TOKEN`
- `TMDB_API_KEY`

`LETTERBOXD_RSS_URL` defaults to the configured user feed in `src/config.py`. Override it when running this project for a different Letterboxd account.

`letterboxd-sync` can seed history from a Letterboxd export folder in `<storage-root>/files/` when the database is empty, then continue with RSS updates. RSS entries are normalized from user-specific film URLs to canonical film URLs and deduplicated against CSV history by movie name and watched date.

If TMDB credentials are configured, `letterboxd-sync` also backfills movie runtimes. TMDB access-token auth is preferred when both token and API key are present. The runtime enrichment uses TMDB IDs from CSV/RSS when available, otherwise it falls back to conservative title/year matching. Monthly analysis uses available runtimes to populate `minutes_watched` for `movies.yaml`.

**Optional historical export setup**
1. Export your Letterboxd data from [letterboxd.com/settings/data](https://letterboxd.com/settings/data/)
2. Unzip the folder into `<storage-root>/files/`
3. Run `uv run main.py letterboxd-sync`

## Overcast

Tracks podcast subscriptions and played episodes.

**Commands**
- `overcast-sync`
- `overcast-analyze`
- `overcast-publish-latest`

**Optional in `.env` for direct export**
- `OVERCAST_COOKIE`
- `OVERCAST_EMAIL`
- `OVERCAST_PASSWORD`

`overcast-sync` prefers direct export when either `OVERCAST_COOKIE` or `OVERCAST_EMAIL` plus `OVERCAST_PASSWORD` is configured. You do not need all three values: either copy the `o` cookie from an authenticated Overcast browser session into `OVERCAST_COOKIE`, or use your Overcast account email and password. If neither direct auth option is available, place an Overcast OPML export matching `overcast*.opml` in `<storage-root>/files/`.

The monthly pipeline and the daily Overcast Activity workflow share the Overcast Actions secrets in the D3 repository. `OVERCAST_EMAIL` and `OVERCAST_PASSWORD` let D3 obtain a session on each run. With no live login configured, the daily workflow uses the saved OPML and Overcast database in the private vault, so the card advances when saved data is updated. It uses the same blog and vault access settings as the monthly pipeline.

To get `OVERCAST_COOKIE` from Chrome:

1. Open `https://overcast.fm` and log in.
2. Open DevTools with `Cmd+Option+I`.
3. Go to **Application**.
4. In the left sidebar, expand **Storage** and then **Cookies**.
5. Select `https://overcast.fm`.
6. Find the cookie named `o` and copy its **Value**.
7. Add that value as a repository Actions secret named `OVERCAST_COOKIE`.

If the cookie expires or Overcast sync stops, repeat those steps and update the secret.

After importing the OPML, `overcast-sync` fetches podcast RSS feeds and fills missing episode durations when RSS duration metadata is available. Monthly analysis uses those durations to populate `minutes_listened` for `podcasts.yaml`.

## Strong

Syncs workout history through Strong's unofficial backend API. CSV import is
available for accounts without API credentials and for explicit recovery.

**Commands**
- `strong-sync`
- `strong-analyze`

**Required in `.env` for API sync**
- `STRONG_USER`: Strong username or email
- `STRONG_PASS`: Strong account password

**Optional in `.env`**
- `STRONG_WEIGHT_UNIT`: `lb` (default) or `kg`; API weights are stored in kg
  and converted before saving. The default matches this project's CSV history.
- `STRONG_TIMEZONE`: IANA timezone, default `America/Los_Angeles`. Used when
  the API workout has no timezone so monthly dates match the local CSV dates.

`strong-sync` logs in afresh, downloads the complete history, validates it, then
replaces the local workout snapshot. Tokens remain in memory. API failures
preserve the previous snapshot and do not fall back to a stale CSV. This is an
undocumented API and may change. Endpoint research:
[strong-exporter](https://github.com/TheAlexLichter/strong-exporter).

For GitHub Actions, add `STRONG_USER` and `STRONG_PASS` repository secrets.
Optional repository variables `STRONG_WEIGHT_UNIT` and `STRONG_TIMEZONE` use the
same defaults as local runs.

For CSV recovery, place a **complete** Strong export at `<storage-root>/files/strong_workouts.csv`
(normally `digital-data-vault/files/strong_workouts.csv`). Exports named
`strong_workouts*.csv` are supported; sync imports the file with the newest
modification time. Run `uv run main.py strong-sync --csv` to replace the database
from that export without credentials. This can roll the history back to the
export's date. With no API credentials and no prior API snapshot, normal sync
keeps the existing automatic CSV import behavior. After an API sync, missing
credentials require an explicit `--csv` to avoid mixing timestamp and UUID IDs.

Run `uv run main.py strong-analyze` to sync and refresh monthly
analysis, then `uv run main.py publish --dry-run` to preview the report.
Normal `publish` refreshes Strong automatically; `--dry-run` and
`--skip-sync-analysis` use existing database contents.

Strong powers the published **Weightlifting** section, with the latest workout's
best set weight per exercise and MoM/YoY comparisons when available. Monthly
workout totals are exported in `weightlifting.yaml`. API reports
identify the configured weight unit. CSV exports do not identify weight units:
keep the same Strong unit settings between exports so the values remain
comparable. See the
[calculation rules](../src/README.md#strong-metric-definitions).

## Apple Health

Imports workout summaries archived by `digital-data-uploader` as JSON in
`digital-data-vault`. Existing XML-derived workout entries are preserved. A
separate XML import supports individual heart and breathing samples.

**Commands**
- `apple-health-sync`
- `apple-health-analyze`
- `apple-health-import-heart-breathing [xml_path]`

**Required in `.env`**
- None

Place or update the immutable DDU archives in
`<storage-root>/files/apple_health/actions/batches/*.json`, then run
`uv run main.py apple-health-analyze` to import and recompute monthly totals.
Workout sync reads JSON archives from the local vault checkout. Update that
checkout before syncing.

Workout UUIDs deduplicate overlapping uploads across all dates. Matching against
existing XML-derived rows is limited to workouts starting August 1, 2026 onward
(midnight in America/Los_Angeles). Older workouts without a saved UUID mapping
are skipped and flagged. Ambiguous matches and unresolved dates are held for
review instead of creating another workout. Ambiguous matches, unresolved dates,
or invalid files cause the source command to fail visibly; intentional pre-cutoff
skips are reported without failing sync. Valid observations already imported
remain saved for a later retry.

The confirmed mappings use `duration` for workout duration and `energy_burned`
for total calories. The importer reports missing measurements; maximum heart
rate, source version, creation date, and detailed Health samples are unavailable
from JSON. Richer existing XML values are retained. The known synthetic uploader
test batch is explicitly excluded.

Before its first JSON migration, an existing database is backed up to
`<storage-root>/data/.backups/apple_health.db.pre-json-v1.sqlite3`. Keep the
historical database/XML and import state: the current JSON archives alone cannot
rebuild the historical dataset. `uv run main.py status` shows archive and import
state counts. The technical review queries are documented in `src/README.md`.

Apple Health is the source used for published workout metrics and `workouts.yaml`.

Use **Export All Health Data** in the iPhone Health app and unpack the export to
import heart rate, resting heart rate, walking heart rate average, one-minute
heart-rate recovery, blood oxygen, VO₂ max, and respiratory rate. Place the
`export.xml` under `<storage-root>/files/` or supply its path to
`apple-health-import-heart-breathing`. New samples are added to the local
`heart_breathing_samples` table in `apple_health.db`. Reusing the same or an
overlapping export skips identical samples.

## Surfilog

Tracks surfing sessions and individual waves through the same JSON API used by
[Surfilog](https://surfilog.com). This is an internal website API and may change.

**Commands**
- `surfilog-sync`
- `surfilog-analyze`

**Required in `.env`**
- `SURFILOG_EMAIL`
- `SURFILOG_PASSWORD`

Use your Surfilog email/password sign-in credentials. Google-only accounts do
not support this login endpoint; a Google password is not a Surfilog password.
Each sync logs in for a fresh cookie, verifies the account, and downloads every
session's wave details. Cookies stay in memory, so the seven-day cookie lifetime
does not require manually updating a token.

`surfilog-sync` stores sessions, individual detected waves (including excluded
waves), per-wave timestamped GPS coordinates and speeds, and full session tracks.
`surfilog-analyze` syncs first, then recomputes all monthly totals. Months follow
the session's recorded local date, with UTC used when the API has no offset;
manually excluded waves do not count toward riding totals. Repeat syncs refresh
corrections and removals without duplicating rides. Raw records stay in SQLite;
the report and `surfing.yaml` contain monthly aggregates.

Surfilog participates in `sync`, `analyze`, normal `publish`, and `backfill` when
configured; missing credentials skip this optional source. Add the same two
variables as repository Actions secrets for monthly automation. Configured
authentication or download failures stop the pipeline rather than publish a
partially downloaded surfing snapshot. The standalone login probe remains
available as `uv run python scripts/surfilog_login.py`.

## Kaya

Place a Kaya CSV export in `<storage-root>/files/` with its original
`KAYA-Export-<timestamp>.csv` name, then run `uv run main.py kaya-analyze`.
When several exports are present, D3 uses the latest filename timestamp.
Both `kaya-sync` and `kaya-analyze` accept an explicit CSV path.
You can also [upload from the iPhone share sheet](SHORTCUTS.md#kaya-upload-from-the-share-sheet).
After updating your local vault checkout, these commands also read every DDU
archive under `files/kaya/exports/`.

Full and partial exports both merge into the stored history. D3 skips matching
records and keeps records missing from the new file. A malformed file fails
before any climbs are added. Kaya exports have no source ID, so an edited record
can be imported as a new entry.

Kaya requires no credentials. Set `KAYA_TIMEZONE` to an IANA timezone if your
climbing days should use a timezone other than the default
`America/Los_Angeles`. For scheduled runs, put the export in the data
repository's `files/` directory. The workflow also reads the optional
`KAYA_TIMEZONE` repository variable.

`sync`, `analyze`, normal `publish`, and `backfill` look for the export
automatically. If the file is absent, analysis uses any previously imported
climbs.

## Blog

Tracks published blog posts from a public Hugo JSON index.

**Commands**
- `blog-sync`
- `blog-analyze`

**Required in `.env`**
- None

**Optional in `.env`**
- `BLOG_POSTS_INDEX_URL`

Blog analysis powers the published `Writing` section and `writing.yaml`.

## Hardcover

Tracks finished books from Hardcover.

**Commands**
- `hardcover-sync`
- `hardcover-analyze`

**Required in `.env`**
- `HARDCOVER_ACCESS_TOKEN`

The [monthly GitHub Actions workflow](../.github/workflows/monthly-pipeline.yml)
also requires `HARDCOVER_ACCESS_TOKEN` as an Actions secret for scheduled refresh.

## GitHub

Tracks your authored commits on the default branch of owned, non-fork public
repositories and private repositories accessible to your activity token.

**Commands**
- `github-sync`
- `github-analyze`

**Required in `.env`**
- `CODEBASE_USERNAME`
- `CODEBASE_GITHUB_TOKEN` (preferred), or `BLOG_GITHUB_TOKEN` as a legacy fallback

Use a separate fine-grained personal access token for activity sync, belonging to
the account in `CODEBASE_USERNAME`. Grant **Contents: read-only** and
**Metadata: read-only** for the private repositories you want counted. Public
repositories remain readable without selecting them. Select **All repositories**
to include future repositories automatically, or select individual private repos
and update that selection as needed. Publishing tokens retain their separate
write permissions.

```dotenv
CODEBASE_USERNAME=your_github_username
CODEBASE_GITHUB_TOKEN=your_read_only_activity_token
```

Run `uv run main.py github-analyze` to sync accessible history and recalculate
monthly public/private counts and their historical comparisons. The first run
after upgrading fetches line counts for stored commits in repos you can still
access. Later runs fetch line counts for new commits and retry unavailable
counts. Private activity contributes to its own counts; its
repository names, links, and commit messages are excluded from
published reports. The local `github.db` still contains those details and belongs
in your private data repository.

For the monthly GitHub Actions pipeline, add `CODEBASE_GITHUB_TOKEN` as a
repository Actions secret alongside `CODEBASE_USERNAME`. Only repositories owned
by that user are included; organization and collaborator repositories and forks
remain excluded.

For what the counts include and how repository visibility or token access can
affect historical values, see the
[GitHub metric definitions](../src/README.md#github-metric-definitions).

## Oura Ring

Syncs daily health summaries, sleep periods, and bedtime recommendations from Oura Ring via the v2 API.

**Commands**
- `oura-sync`
- `oura-analyze`

**Required in `.env`**
- `OURA_CLIENT_ID`
- `OURA_CLIENT_SECRET`

**Optional in `.env`**
- `OURA_REDIRECT_URI` (defaults to `https://localhost:8888/callback`)
- `OURA_ACCESS_TOKEN` (auto-populated after first auth)
- `OURA_REFRESH_TOKEN` (auto-populated after first auth)

Register an application at [cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications), add your client ID and secret to `.env`, then run `oura-sync`. The CLI will open your browser for authorization and save the tokens automatically.

For GitHub Actions, set `OURA_CLIENT_ID` and `OURA_CLIENT_SECRET` as repository
secrets. The workflow prefers tokens saved in the private vault and uses
`OURA_ACCESS_TOKEN` and `OURA_REFRESH_TOKEN` secrets as fallbacks. See the
[token persistence flow](../src/README.md#oauth-token-persistence-schwab--oura).

Oura syncs activity, sleep, readiness, and daily stress, plus optional resilience,
SpO2, and cardiovascular age. The optional endpoints can require supported
hardware, an active membership, or additional OAuth scopes. D3 reports which
optional endpoints were skipped when Oura denies access, and continues the
rest of the sync.

The `daily` permission also provides individual sleep periods, including naps
when available, with bedtimes, durations by stage, breathing rate, and overnight
heart-rate and heart-rate variability series when Oura supplies them. D3 also
stores Oura's sleep timing documents, including recommended bedtime windows
when available.

Monthly analysis currently covers 20 numeric measures from sleep and readiness:
the two scores, their contributor measures, and readiness temperature deviations.
Each measure has minimum, median, mean, maximum, and non-null sample count.
Reports and activity exports currently use only mean and median sleep/readiness
scores.

## Charles Schwab

Syncs account balance snapshots and recent trade transactions from the Charles Schwab Trader API.

**Commands**
- `schwab-sync`

**Required in `.env`**
- Either `SCHWAB_ACCESS_TOKEN`, or both `SCHWAB_CLIENT_ID` and `SCHWAB_CLIENT_SECRET`

**Optional in `.env`**
- `SCHWAB_CALLBACK_URL` (defaults to `https://127.0.0.1`)
- `SCHWAB_REFRESH_TOKEN` (auto-populated after OAuth)

Register an application at [developer.schwab.com](https://developer.schwab.com), add your credentials to `.env`, then run `schwab-sync`. If no access token is present, the CLI will start the OAuth flow and save the returned access and refresh tokens.

Each sync stores a new row in `account_snapshots` per Schwab account, keyed with the Schwab account hash so multiple accounts under one client account remain distinguishable. Transactions are fetched per account hash and upserted into `transactions` by account hash plus `activityId`; the full Schwab transaction payload is preserved as JSON for future analysis. Initial transaction sync fetches the maximum supported one-year window, and later syncs start from the latest stored transaction with a one-day overlap.
