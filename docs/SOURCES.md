# Supported Sources

This project supports the following sources for sync and monthly analysis.

All source data is stored in local SQLite databases under `<storage-root>/data/`. File-based imports are read from `<storage-root>/files/`.

## Readwise

Tracks books, highlights, and Reader documents.

**Commands**
- `readwise-sync`
- `readwise-analyze`

**Required in `.env`**
- `READWISE_ACCESS_TOKEN`

## Workflowy

Mirrors the current Workflowy outline as nodes, retaining locally observed deletions as tombstones for later analysis.

**Commands**
- `workflowy-sync`

**Required in `.env`**
- `WORKFLOWY_API_KEY`

Create an API key in Workflowy account settings and add it to `.env`. Workflowy exposes a full `nodes-export` endpoint but no documented delta cursor or modified-since filter, so every sync downloads the complete node export and locally upserts only changed nodes. The export endpoint is limited to one request per minute; wait before retrying a rate-limited manual sync.

Workflowy sync currently only stores raw node data. Monthly node-created/completed analysis and report publishing are intentionally not included yet.

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

Use the client ID and secret when you need to run the OAuth flow again. The API key is optional and is used to enrich venue details.

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

**Optional in `.env` for direct export**
- `OVERCAST_COOKIE`
- `OVERCAST_EMAIL`
- `OVERCAST_PASSWORD`

`overcast-sync` prefers direct export when either `OVERCAST_COOKIE` or `OVERCAST_EMAIL` plus `OVERCAST_PASSWORD` is configured. You do not need all three values: either copy the `o` cookie from an authenticated Overcast browser session into `OVERCAST_COOKIE`, or use your Overcast account email and password. If neither direct auth option is available, place an Overcast OPML export matching `overcast*.opml` in `<storage-root>/files/`.

The monthly GitHub Actions workflow can fetch the latest Overcast OPML export directly when you add either `OVERCAST_COOKIE` or `OVERCAST_EMAIL` plus `OVERCAST_PASSWORD` as repository Actions secrets.

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

Imports workouts from Strong CSV export.

**Commands**
- `strong-sync`
- `strong-analyze`

**Required in `.env`**
- None

Place the Strong CSV export in `<storage-root>/files/`.

Strong remains available as a standalone source, but published workout output now comes from Apple Health instead.

## Apple Health

Imports workouts from Apple Health `export.xml`.

**Commands**
- `apple-health-sync`
- `apple-health-analyze`

**Required in `.env`**
- None

Place `export.xml` in `<storage-root>/files/` or in an extracted Apple Health export folder under it.

Apple Health is the source used for published workout metrics and `workouts.yaml`.

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

## GitHub

Tracks commit activity from your public repositories.

**Commands**
- `github-sync`
- `github-analyze`

**Required in `.env`**
- `CODEBASE_USERNAME`
- `BLOG_GITHUB_TOKEN`

The GitHub token is reused for authenticated API access.

## Oura Ring

Syncs daily health summaries from Oura Ring via the v2 API.

**Commands**
- `oura-sync`

**Required in `.env`**
- `OURA_CLIENT_ID`
- `OURA_CLIENT_SECRET`

**Optional in `.env`**
- `OURA_REDIRECT_URI` (defaults to `https://localhost:8888/callback`)
- `OURA_ACCESS_TOKEN` (auto-populated after first auth)
- `OURA_REFRESH_TOKEN` (auto-populated after first auth)

Register an application at [cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications), add your client ID and secret to `.env`, then run `oura-sync`. The CLI will open your browser for authorization and save the tokens automatically.

Oura syncs seven daily summary types: activity, sleep, readiness, stress, resilience, SpO2, and cardiovascular age. Resilience, SpO2, and cardiovascular age require a Gen 3+ ring and may require an active Oura membership; they are skipped gracefully on older hardware.

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
