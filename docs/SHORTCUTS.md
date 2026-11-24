# iPhone upload Shortcuts

The phone sends activity exports to digital-data-uploader (DDU), which saves them
in the private digital-data-vault (DDV) repository. digital-data-dump (D3) later
imports those local files and computes monthly metrics.

The Shortcuts themselves are maintained on the phone; no `.shortcut` export is
checked into these repositories. This guide records their behavior and the
request formats supported by DDU, rather than exact screenshots or action labels
for a particular iOS/Actions version.

## Upload workflows

| Shortcut | Phone input | DDU endpoint | Vault output | Delivery |
| --- | --- | --- | --- | --- |
| Apple Health | Recent workouts queried through Actions | `POST /v1/workout-batches` | `files/apple_health/actions/batches/<batch-id>.json` | Durable D1 inbox, then background/manual delivery |
| Strong | Latest complete CSV export shared from Strong or Files | `POST /v1/strong-export` | `files/strong_workouts.csv` | Direct GitHub save before returning success |
| Kaya | Kaya CSV export shared as a file | `POST /v1/kaya-export` | `files/kaya/exports/<sha256>.csv` | Direct GitHub save before returning success |

Uploading does not run D3, update its databases, or publish a report. Acceptance,
vault archival, and D3 import are separate outcomes.

## Connection settings

All three Shortcuts use **Get Contents of URL**, with:

- **Method:** `POST`.
- **Authorization header:** `Bearer YOUR_UPLOAD_TOKEN`.
- **Request Body:** **File**, selecting the final JSON Text or CSV file as
  described below.
- **Show Result** after the request while testing, to inspect the response.

Use the upload token configured in DDU. The administrative token belongs on the
trusted Mac/server, not in these phone Shortcuts.

For a deployed Worker, use `https://<YOUR-WORKER>` as the base URL. For local
testing, use `http://<MAC_NETWORK_IP>:8787`, with the phone and Mac on the same
network and the local server running. `0.0.0.0` is a server listening address;
the phone needs the Mac's actual network IP.

DDU setup and deployment remain documented in its
[README](https://github.com/yyl/digital-data-uploader/blob/main/README.md) and
[implementation guide](https://github.com/yyl/digital-data-uploader/blob/main/docs/IMPL.md).
No live endpoint URL or token is stored in this guide.

## Apple Health: recent workouts to JSON

### Phone action sequence

1. Use the Actions app's workout query in Shortcuts to find workouts. The current
   workflow selects the **100 most recent workouts**, sorted newest first. It
   does not keep a last-sent cursor; overlap with previous uploads is expected.
2. Repeat over the selected workouts. For each one, read its workout details and
   construct a **Dictionary** using the exact keys below.
3. Add each dictionary to a workout list. Keep measurements as **Text** values;
   the upload contract requires strings even for numbers and Yes/No flags.
4. After the repeat, wrap that list in a final dictionary with the single key
   `workouts`. Preserve a list even when it contains only one workout. With no
   results, send `{"workouts":[]}`.
5. Use the existing dictionary-to-JSON text conversion step. The result must be
   JSON text representing the final object, not a quoted/escaped JSON string.
6. Send that final **Text** variable with **Get Contents of URL**:

   | Setting | Value |
   | --- | --- |
   | URL | `<BASE_URL>/v1/workout-batches` |
   | `Content-Type` header | `application/json` |
   | Request Body | **File** → final JSON **Text** variable |

Do not use a form field or wrap the serialized text in another JSON object.
The body bytes should start with an object containing `workouts`.

### Dictionary keys and formats

The server accepts only these keys. Required values must be nonempty; optional
values can be omitted or sent as an empty string. Use empty values for missing
measurements rather than inventing zeroes.

| Key | Required | Value sent by the phone |
| --- | --- | --- |
| `identifier` | Yes | The workout's stable UUID; reuse it on every export, never generate a new UUID per upload |
| `type` | Yes | Activity label, such as `Climbing`, `Walking`, or `Traditional Strength Training` |
| `start_date` | Yes | English date with 24-hour time, e.g. `Oct 15, 2026 at 08:31` |
| `end_date` | Yes | Same date/time format as `start_date` |
| `duration` | Yes | Seconds with the ` sec` suffix, e.g. `3488.907 sec` |
| `elapsed_time` | No | Separate seconds value with the ` sec` suffix |
| `energy_burned` | No | Number with ` kcal`, e.g. `407.883 kcal` |
| `active_calories` | No | Unitless numeric text; DDU assumes kcal |
| `average_heart_rate` | No | Unitless numeric text; DDU assumes bpm |
| `total_distance` | No | Number followed by `m`, `km`, `mi`, `ft`, or `yd` |
| `average_speed` | No | Number followed by `m/s`, `km/h`, `km/hr`, `mi/hr`, `mph`, or `kph` |
| `flights_climbed` | No | Unitless whole-number text |
| `source_name` | No | App/device source label supplied by the workout |
| `device_name` | No | Device name, when available |
| `device_model` | No | Device model, when available |
| `recording_method` | No | Recording method label |
| `is_from_watch` | No | `Yes` or `No` |
| `is_from_third_party` | No | `Yes` or `No` |

Keep duration and elapsed time separate, as exposed by the workout actions.
D3 uses `duration` for new JSON-only workout duration and `energy_burned` for
total calories, following the confirmed mapping policy. Some paused workouts
have XML duration agreeing with JSON `elapsed_time`; D3 uses this as matching
evidence while preserving the existing XML measurements.

The UUID need not come from a particular UUID namespace, but it must consistently
identify the same workout. DDU preserves its raw spelling and lowercases its
normalized representation for comparisons.

### Synthetic request example

This is a minimal valid body; the on-phone workflow can include all optional
fields from the table. It is the upload request, not DDU's later archive envelope.

```json
{
  "workouts": [
    {
      "identifier": "00000000-0000-0000-0000-000000000001",
      "type": "Climbing",
      "start_date": "Oct 15, 2026 at 08:31",
      "end_date": "Oct 15, 2026 at 09:30",
      "duration": "3488.907 sec",
      "energy_burned": "407.883 kcal"
    }
  ]
}
```

### What DDU does next

DDU authenticates the request and validates the entire batch. Limits are **100
workouts** and **256 KiB** per request. A duplicate UUID within one batch,
invalid field, or unsupported format rejects the batch before acceptance.

The server retains raw fields and adds normalized quantities, timestamp
provenance, and warnings. Phone dates omit seconds and timezone; DDU interprets
them using its configured `ASSUMED_TIMEZONE` (default `America/Los_Angeles`).
Dates that are ambiguous or nonexistent around a clock change remain unresolved.
Travel or changing the phone's date formatting can require configuration review;
the server cannot recover information the phone omitted.

The validated envelope gets a deterministic batch ID and is saved to the D1
inbox. An identical whole batch reuses its receipt even if dictionary or workout
order changes. A new workout, changed field, or shifted recent-workout selection
can create a new batch containing overlapping workouts. Workout-level filtering
at DDU is intentionally deferred; D3 deduplicates those overlaps by UUID.

| Response status | Meaning |
| --- | --- |
| `queued` | Durably accepted into D1; not yet confirmed in DDV |
| `retrying` | Previously accepted; delivery is waiting for another attempt |
| `archived` | Saved in DDV; receipt includes the Git commit SHA |
| `empty` | No workouts selected; no batch created |
| `failed` | Batch needs attention; inspect its error and retry from the server |

Read the response's `status` and `error`, not just the HTTP code. A repeated
request can return HTTP 202 with an existing retrying or failed receipt. Current
responses use `record_count` (older versions used `workout_count`).

Delivery is configured hourly on Cloudflare. During local testing, run the
administrative retry from the Mac/server instead of assuming a timer is active.
One delivery invocation processes at most three batches, including older pending
ones. An archived receipt and the corresponding DDV file confirm delivery; a
phone acceptance receipt alone does not.

DDU clears archived payloads after seven days during delivery cleanup, retaining
compact receipts. It keeps pending/failed payloads for recovery. Long-term raw
archives live in DDV.

### Scheduling, overlap, and backfill

After manual upload and vault delivery work, a personal automation can run the
Shortcut on a **Time of Day** schedule with **Run Immediately**. The documented
starting schedule is weekly. Test actual scheduled runs while the phone is
locked and unlocked; server-side delivery cannot recover workouts the phone
never uploaded.

A fixed count is not a fixed lookback period. If more than 100 workouts occur
between successful runs, older unseen workouts can fall outside the selection.
Backfill those gaps using a historical date filter and multiple requests of at
most 100 workouts each, staying within the byte limit. Preserve original UUIDs.
DDU also supports date-window selections, but that is an alternative to the
current fixed-count query, not an additional default filter.

The upload health check currently flags no successful upload for over 14 days.
An empty or duplicate Apple Health upload also refreshes that timestamp; it is
not proof that new workouts were archived or imported. Monthly schedules can
cross this threshold. Strong uploads do not refresh this Apple Health timestamp.

## Strong: share a complete CSV export

This workflow is optional when [Strong API sync](SOURCES.md#strong) is configured.
Normal sync then reads the API; use `uv run main.py strong-sync --csv` to explicitly
replace the local history with an uploaded complete CSV export.

The **Upload Strong Export** Shortcut receives the CSV from Strong's export
share sheet and uploads it directly to DDU. Exporting the workout history and
tapping the Shortcut in the share sheet are manual steps; the Shortcut handles
the upload without a separate file picker. It does not generate the export or
run automatically when Strong finishes exporting.

### Shortcut setup

1. Enable **Show in Share Sheet** and accept **Files**. The shared CSV becomes
   **Shortcut Input**.
2. Add a **URL** action containing `<BASE_URL>/v1/strong-export`.
3. Add **Get Contents of URL**, using that URL and these settings:

   | Setting | Value |
   | --- | --- |
   | Method | `POST` |
   | Header `Authorization` | `Bearer YOUR_UPLOAD_TOKEN` |
   | Header `Content-Type` | Exactly `text/csv` |
   | Request Body | **File** |
   | File | **Shortcut Input** |

4. Add **Show Result** (or **Show**) with the **Contents of URL** response.

Set `Content-Type` explicitly. DDU compares its value directly with `text/csv`;
other values, including `text/csv; charset=utf-8`, return 415 `expected_csv`.
Send one original CSV file as the body. Do not convert it to JSON or a multipart
form. The limit is **512 KiB**; empty, header-only, or malformed exports are
rejected.

### Export and upload

1. In Strong, export the **complete workout history** as CSV.
2. In the export share sheet, tap **Upload Strong Export**. If the CSV was
   already saved in Files, share that file to the same Shortcut.
3. Check the response displayed by the Shortcut:

   | Response | Meaning |
   | --- | --- |
   | HTTP 200, `status: saved` | GitHub confirmed the save; `commit_sha` identifies the commit |
   | HTTP 200, `status: unchanged` | Identical bytes are already in DDV; no new commit was made |
   | HTTP error | The save was not confirmed; inspect the error and retain the export for retry |

Each changed export replaces `files/strong_workouts.csv`; Git history retains
previous versions. Always share the latest full export, since a successful
upload replaces the current file. A local DDU server also writes to DDV on
GitHub; it does not update the local DDV checkout.

This route uses D1 only for the shared upload rate limit. It has no durable
inbox, pending receipt, or automatic delivery retry. On failure, retain the file
and resend it; respect `Retry-After` when present. A 409 conflict requires
checking which export is now current before retrying.

### Check the CSV input

`invalid_strong_header` refers to the CSV's column header row, not the HTTP
headers configured in the Shortcut. DDU requires these column names, in any
order, and allows additional columns:

```text
Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds
```

Headers must be unique, data rows must have the same number of fields as the
header, and dates must be nonempty. The uploader validates structure without
normalizing workout values or changing the file bytes.

For diagnosis, temporarily add **Quick Look** for **Shortcut Input** before
the upload. Confirm it receives the exported CSV. Running the Shortcut with
the editor's Play button may provide no shared file. Inspect the CSV's first
line if `invalid_strong_header` persists; that line is enough to compare column
names without sharing workout records.

## Kaya upload from the share sheet

If you already have **Upload Strong Export**, duplicate it, rename it **Upload
Kaya Export**, and replace `/v1/strong-export` in the URL with
`/v1/kaya-export`. To build it from scratch, use these steps.

1. In **Shortcuts**, create a shortcut named **Upload Kaya Export**. Open
   **Details**, enable **Show in Share Sheet**, and set the accepted type to
   **Files**.
2. Add **URL** with `<BASE_URL>/v1/kaya-export`.
3. Add **Get Contents of URL**, expand its settings, and use these values.

   | Setting | Value |
   | --- | --- |
   | Method | `POST` |
   | Header `Authorization` | `Bearer YOUR_UPLOAD_TOKEN` |
   | Header `Content-Type` | `text/csv` |
   | Request Body | **File** |
   | File | **Shortcut Input** |

4. Add **Show Result** using the **Contents of URL** response.
5. Share the Kaya CSV to **Upload Kaya Export**. If you have the export in
   **Files**, touch and hold it, tap **Share**, and choose the shortcut.

Share one CSV at a time, up to 512 KiB. A `saved` response includes the path
in the vault and the GitHub commit SHA. `unchanged` means the same file is
already there. Changed exports get separate files, so multiple partial exports
can arrive before D3 runs. On an HTTP error, keep the file and inspect the
response before resending.

See Apple's [share sheet setup](https://support.apple.com/en-us/guide/shortcuts/apd163eb9f95/ios)
and [Get Contents of URL settings](https://support.apple.com/en-us/guide/shortcuts/apd58d46713f/ios).

## Refresh D3 after archival

Update the local DDV checkout before importing. From the D3 repository, run the
commands for whichever source was uploaded:

```sh
uv run main.py apple-health-analyze
uv run main.py strong-analyze
uv run main.py kaya-analyze
uv run main.py publish --dry-run
```

The analyze commands import local files and refresh monthly analysis. The dry
run previews the report using existing analysis. Apple Health supplies Workout,
Strong supplies Weightlifting, and Kaya supplies Bouldering. Walks remain in the
Apple Health database but are excluded from its published workout totals.

Existing XML-derived rows are preserved. Automatic XML/JSON matching is limited
to workouts starting August 1, 2026 onward; older observations without a saved
alias are deliberately skipped. JSON-only archives do not replace the richer
historical baseline. See [source setup](SOURCES.md#apple-health),
[Strong setup](SOURCES.md#strong), and the
[Apple Health JSON design](design/AH_JSON.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Phone cannot reach the local server | Mac network IP, same network, server listening on `0.0.0.0`, local network/firewall permission |
| 401 | Upload bearer token and Authorization header |
| 413 | Workouts/count/byte limit; split the export into smaller requests |
| 415 | Use a File body and set `Content-Type` to `application/json` for Apple Health or `text/csv` for Strong and Kaya |
| 422 | Required fields, string values, date/unit formats, duplicate UUIDs within a batch, or CSV structure |
| Strong `invalid_strong_header` | CSV column names or duplicate headers; inspect the first CSV row and confirm Shortcut Input contains the exported file |
| Apple Health remains queued | Local admin retry or deployed delivery execution; inspect receipt/status on the trusted server |
| New batch contains old workouts | Expected with a rolling selection; D3 deduplicates observations |
| DDV has new files but reports look old | Update the local vault checkout and run the corresponding D3 analyze command |

For server setup, administrative retry commands, and detailed error codes, use
the [DDU implementation guide](https://github.com/yyl/digital-data-uploader/blob/main/docs/IMPL.md).
