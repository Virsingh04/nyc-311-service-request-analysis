# NYC 311 Project: Beginner Guide

This guide explains the project in plain language: where its data comes from, what the Python pipeline does to the data, what each MySQL table and view is for, and how to build a Tableau dashboard from it.

For setup commands and the full pipeline reference, see the main [README](README.md).

## 1. What the project is about

The project looks at NYC 311 service requests for **Blocked Driveway** during the pilot period **October 1, 2025 through September 30, 2026**. The date filter is inclusive at the start and exclusive at the end: `[2025-10-01, 2026-10-01)`.

The live API profile counted 194,672 requests in that scope. The project fetched those rows, checked them, and loaded 194,672 rows into MySQL. The validation run found zero duplicate keys and zero rejected rows. The database stores one row per request.

These are *reported requests*, not a count of every 311 contact or a measure of how common blocked driveways are. A close date is an agency status in the data; it does not prove that the resident felt the issue was fixed. This project has no verified SLA targets, so it does not label requests “late.”

## 2. Where the information comes from

The source is NYC Open Data’s [311 Service Requests from 2020 to Present dataset](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9), dataset ID `erm2-nwe9`. Python reads the public Socrata SODA API at:

`https://data.cityofnewyork.us/resource/erm2-nwe9.json`

The API display labels may use “Problem” and “Problem Detail.” The field names sent by the API are `complaint_type` and `descriptor`.

The project requests these ten fields only:

| API field | What it tells us |
|---|---|
| `unique_key` | Stable identifier for one service request; used to deduplicate and upsert. |
| `created_date` | When the request was created; sets the pilot date window and trend month. |
| `closed_date` | When it was marked closed; blank/null means it is treated as open. |
| `agency` | Short agency code. |
| `agency_name` | Agency’s full name. |
| `complaint_type` | Request/problem category, here `Blocked Driveway`. |
| `descriptor` | More detailed category or description. |
| `status` | Source status text, retained for reference. |
| `borough` | Borough-level location. |
| `community_board` | NYC community-board location. |

Precise addresses and coordinates are not requested. This supports area comparisons without putting household-level locations in the analytics tables.

### How extraction works

The settings live in [`config/project.json`](config/project.json): dates, request type, fields, API page size, row cap, runtime cap, and refresh windows. Change the JSON settings to change the scope; no Python edit is needed.

The Python extractor:

1. Creates a reusable HTTP session. If `SOCRATA_APP_TOKEN` is present in local `.env`, it sends it in the `X-App-Token` header. A token is optional for the public sample request.
2. Uses HTTP timeouts and retries transient errors and rate limits with backoff.
3. Sends SoQL parameters to select the configured fields, filter dates and request type, and sort by `created_date` and `unique_key`.
4. Retrieves pages in key order. Each response page is written atomically, so a stopped extraction can resume from its last saved page.
5. Writes an extraction manifest with the query, time, page count, row count, and date coverage. Raw pages and manifests are under `data/raw/`, which is excluded from Git.

The project’s last dry-run snapshot can be loaded again without making the API download repeat:

```bash
python -m nyc311_etl.pipeline backfill --reuse-snapshot
```

The normal `backfill` command fetches the configured window again. `refresh` fetches the recent overlap and recent still-open requests, so it can update a request if its close status changes.

## 3. How Python cleans and validates the data

The main logic is in [`src/nyc311_etl/transform.py`](src/nyc311_etl/transform.py), [`src/nyc311_etl/validate.py`](src/nyc311_etl/validate.py), and the extraction/loading modules.

### Cleaning steps

1. **Trim text:** leading and trailing spaces are removed from text values. Missing values are kept missing; they are not turned into fake text such as `"None"`.
2. **Parse timestamps:** `parse_dt()` reads ISO date-time text, understands a trailing `Z` as UTC, converts timestamps to UTC, then removes the timezone marker because MySQL stores these columns as `DATETIME`.
3. **Remove duplicate requests:** `clean_records()` keeps the first occurrence of each `unique_key` and counts later copies as duplicates.
4. **Check required values:** rows without a `unique_key` or valid `created_date` are rejected with a reason.
5. **Check date order:** a request with `closed_date` earlier than `created_date` is rejected. A timestamp that cannot be parsed is rejected as `invalid_timestamp`.
6. **Calculate duration:** `resolution_hours` is calculated as `(closed_date - created_date)` in hours only when a valid close date exists.
7. **Keep open requests open:** if `closed_date` is null, `is_open` is true and `resolution_hours` stays null. An open case is never counted as a zero-hour closure.
8. **Validate the cleaned result:** `validate_records()` checks that keys and created dates exist, keys are unique, and closed dates are not before created dates.

Rejected rows are counted and their reasons are included in the run output and ETL log. The original API values remain available in the raw page snapshots. This pilot happened to have no rejected rows or duplicates.

### What gets loaded

The loader writes the original selected API row to the staging table and the cleaned analytical row to the fact table. It uses parameterized database statements and batches. `unique_key` is the primary key; an `ON DUPLICATE KEY UPDATE` upsert means running the same snapshot again updates existing rows instead of creating a second copy.

## 4. MySQL tables, columns, and relationships

The database is `nyc311_analytics`. Its tables are created by [`sql/02_create_tables.sql`](sql/02_create_tables.sql); the reporting views are created by [`sql/03_create_views.sql`](sql/03_create_views.sql).

### `stg_service_request`: source-shaped staging data

| Column | Purpose |
|---|---|
| `unique_key` | Primary key for the request. Matches the source ID and fact-table key. |
| `payload` | JSON object containing the selected raw API fields for that request. |
| `staged_at` | When the staging payload was inserted or refreshed. |

Use this table to inspect the selected source payload before or alongside its cleaned fact row. It is not the recommended Tableau source.

### `fact_service_request`: one cleaned row per request

| Column | Purpose |
|---|---|
| `unique_key` | Primary key; one fact row per request. |
| `created_date` | Request creation time, stored in UTC as `DATETIME`; used for time trends. |
| `closed_date` | Close time, or `NULL` if still open. |
| `agency` | Short agency code. |
| `agency_name` | Full agency name. |
| `complaint_type` | Request category. |
| `descriptor` | Request detail. |
| `status` | Source status text. |
| `borough` | Borough for geographic comparisons. |
| `community_board` | Community board for geographic comparisons. |
| `resolution_hours` | Elapsed hours for valid closed requests; `NULL` for open requests. |
| `is_open` | Boolean derived from whether `closed_date` is null. |
| `loaded_at` | Time the row was most recently inserted or updated. |

Indexes help MySQL filter by created date, request type, agency, borough/community board, and open status. This is a simple, denormalized fact table: the agency, request-type, and geography values are stored on each request row rather than in separate dimension tables. That keeps the student project and Tableau setup straightforward.

### `etl_run_log`: one row per pipeline attempt

| Column | Purpose |
|---|---|
| `run_id` | Unique ID for this ETL attempt; primary key. |
| `started_at` / `ended_at` | Run start and finish times in UTC. `ended_at` is null while running. |
| `status` | `running`, `success`, or `failed`. |
| `source_start` / `source_end_exclusive` | Date window requested from the source. |
| `records_fetched` | Number of source rows received. |
| `records_inserted` / `records_updated` | New fact rows and existing fact rows changed by the upsert. |
| `records_rejected` | Number of source rows rejected by validation. |
| `error_summary` | Short failure summary when a run fails. |

This is operational history. It does not join to an individual fact row because the fact table does not store a `run_id`.

### How the storage is related

```text
raw API page (JSON file)
          |
          v
stg_service_request -- unique_key --> fact_service_request
                                         |
                  +----------------------+---------------------+
                  v                      v                     v
       monthly/volume views       closure-time view       open-backlog views

etl_run_log records pipeline runs separately; it is not a request dimension.
```

The matching `unique_key` links a staged source payload to its cleaned fact row. The views are SQL queries over the fact table; they do not store another copy of the data.

## 5. Reporting views and their columns

| View | One row represents | Main fields and intended use |
|---|---|---|
| `vw_monthly_overview` | One created-date month | `month_start`, `request_count`, `open_count`, `open_share_pct`, `mean_resolution_hours`. Use for the simple overall monthly summary. It does not include request type, agency, or geography columns. |
| `vw_closure_by_type` | One request type + agency + borough + community board combination | Those four grouping fields, `closed_request_count`, `median_resolution_hours`, and `p90_resolution_hours`. Uses valid closed rows only. Median is the midpoint of the middle value(s); p90 uses nearest rank. This view has no month/date column, so a Tableau date filter cannot change these percentiles. |
| `vw_open_backlog_age` | One currently open request | Request key, creation date, agency, type, geography, calculated `age_days`, and `age_band`. Use for the current open-case count and age distribution. Ages are calculated against current UTC time when the view is queried. |
| `vw_backlog_by_month` | One created month + request type + agency + borough + community board combination among open requests | `month_start`, the grouping fields, `open_count`, and `open_90_plus`. Use for backlog comparisons and 90+ day counts. |

The current database check found 12 month rows in `vw_monthly_overview`, 70 grouped rows in `vw_closure_by_type`, 55 open-request rows in `vw_open_backlog_age`, and 19 groups in `vw_backlog_by_month`. The open views change as time passes and when later refreshes close requests.

## 6. Tableau Desktop: connect to MySQL

Tableau’s native MySQL connector requires a MySQL driver. Tableau will show a driver download link if it is missing; install the driver Tableau requests, then restart Tableau if prompted. See Tableau’s [official MySQL connection guide](https://help.tableau.com/current/pro/desktop/en-us/examples_mysql.htm).

1. Start Tableau Desktop on the Mac that has this local MySQL server.
2. In **Connect**, choose **MySQL** (or **More → MySQL** under server connectors).
3. Enter the local connection values:

   | Tableau field | Value |
   |---|---|
   | Server | `127.0.0.1` |
   | Port | `3306` |
   | Database | `nyc311_analytics` |
   | Username | `nyc311_user` |
   | Password | Open the local `.env` file and copy the value after `MYSQL_PASSWORD=`. Do not paste it into the README or share it. |

4. For this local connection, leave SSL off unless your MySQL installation was specifically configured to require it.
5. Select **Sign In**. On the Data Source page, select a table or view from the database list and drag it onto the canvas.
6. Choose **Live** to query the local database as you use the workbook. If the workbook feels slow, try **Extract** to create a Tableau copy of this 194k-row pilot dataset and use **Data → Refresh All Extracts** after reloading MySQL.
7. Save the workbook as a `.twb` or packaged `.twbx` file. No Tableau workbook is included in this project yet.

## 7. A dashboard you can build

Start with two data sources so the measures use the right calculations:

- **Request detail:** `fact_service_request` for counts, monthly trends, request type, agency, borough, community board, status, and age calculations.
- **Closure statistics:** `vw_closure_by_type` for MySQL-computed median and p90. Tableau’s `MEDIAN()` aggregate is not supported for a live MySQL connection, so use these SQL fields instead. Tableau documents this limitation in its [aggregate function reference](https://help.tableau.com/current/pro/desktop/en-gb/calculations_calculatedfields_aggregate_create.htm).

Create these worksheets first.

### Sheet A: KPI cards

Use `fact_service_request`.

1. Create a calculated field named **Requests**: `COUNTD([unique_key])`.
2. Create **Open requests**: `SUM(IIF([is_open], 1, 0))`.
3. Create **Open share**: `SUM(IIF([is_open], 1, 0)) / COUNTD([unique_key])`, then format it as a percentage.
4. For each measure, create a new worksheet, drag the calculated field to **Text** on the Marks card, enlarge the number, and give the sheet a clear title.

### Sheet B: Monthly request trend

Use `fact_service_request`.

1. Drag `created_date` to **Columns**, and choose the continuous **Month** date level so months stay in year order.
2. Drag `unique_key` to **Rows** and change its aggregation to **Count (Distinct)**.
3. Set Marks to **Line**.
4. Add `complaint_type` or `borough` to **Color** only when you want separate lines. This pilot currently has one request type; if you expand the configured types and reload, the type comparison becomes more useful.

### Sheet C: Open requests by age band

Use `vw_open_backlog_age`.

1. Drag `age_band` to **Rows** and `unique_key` to **Columns** as **Count (Distinct)**.
2. Choose **Bar** marks and sort descending or keep the natural band order: `0-6 days`, `7-29 days`, `30-89 days`, `90+ days`.
3. Optionally drag `borough` to **Color** or `community_board` to **Filters**.

### Sheet D: Median and p90 closure time

Use `vw_closure_by_type`.

1. Drag `community_board` or `agency` to **Rows**.
2. Drag `median_resolution_hours` and `p90_resolution_hours` to **Columns** or to **Measure Values** for a side-by-side comparison.
3. Use horizontal bars, sort by median, and show the request count in the tooltip so small groups are not mistaken for strong evidence.
4. Add `complaint_type`, `agency`, and `borough` as filters. This view summarizes the whole loaded pilot window; it has no date field, so those statistics do not respond to the monthly date filter.

### Sheet E: Open backlog by borough

Use either `vw_open_backlog_age` for the current case list or `vw_backlog_by_month` for grouped monthly counts.

1. Drag `borough` to **Rows** and `open_count` to **Columns** (from `vw_backlog_by_month`), or drag `unique_key` as **Count (Distinct)** from `vw_open_backlog_age`.
2. Use bar marks and sort from largest to smallest.
3. Add `community_board` to **Detail** or **Filters** for a more specific comparison. Avoid adding addresses or coordinates; they are not part of this analysis model.

### Assemble the dashboard

1. Choose **Dashboard → New Dashboard**.
2. Set a fixed desktop size or choose **Automatic**.
3. Drag the KPI sheets across the top; place the monthly trend below them; add the age-band and borough views alongside or below it.
4. Add a short text note: “Reported requests, not prevalence. No SLA target is included. Differences are descriptive, not causal.”
5. For fact-table sheets, show filters for `created_date`, `borough`, `community_board`, `agency`, and `complaint_type`. On a filter card’s menu, choose **Apply to Worksheets → All Using This Data Source** to make that control affect the other fact-table sheets.
6. Closure and backlog sheets use views as separate data sources. Add their own type/agency/geography filters. The closure view does not have `created_date`, so its median and p90 remain for the full loaded pilot window even when the monthly trend is narrowed. To make one dashboard selection control another view, use a dashboard filter action and map matching fields such as borough or request type; see Tableau’s [filter action guide](https://help.tableau.com/current/pro/desktop/en-us/actions_filter.htm).
7. Add tooltips that explain hours and counts. Give the dashboard a useful title such as **NYC 311 Blocked Driveway Requests: Volume, Backlog, and Observed Closure Time**.

Tableau’s official [dashboard guide](https://help.tableau.com/current/pro/desktop/en-us/dashboards_create.htm) covers adding sheets and objects. Keep the charts descriptive: request counts describe reports received; long closure times are observed durations, not proof that an agency missed an SLA or caused a neighborhood problem.

## 8. Metric definitions and cautions

- **Request count:** distinct `unique_key` values.
- **Open count:** rows whose `closed_date` is null (`is_open = true`).
- **Open share:** open count divided by request count.
- **Resolution time:** elapsed hours from create to close, for valid closed requests only.
- **Median:** middle closure duration (average the two central values for an even-sized group).
- **P90:** nearest-rank 90th percentile; 90% of the group’s valid closed requests are at or below this value.
- **Open age bands:** 0–6, 7–29, 30–89, and 90+ days, calculated from created date to current UTC time.

Compare similar request types and be careful with small groups. A difference by agency or borough does not demonstrate poor performance or causation. A close timestamp does not tell us whether the caller was satisfied. There is no SLA target in this project, so avoid “late” labels.

## 9. Troubleshooting

- **Tableau cannot find MySQL:** check the MySQL server is running, use server `127.0.0.1` and port `3306`, and install the driver linked by Tableau.
- **Access denied:** use username `nyc311_user` and the current project password from the ignored local `.env`. Confirm the same account is allowed to connect from `127.0.0.1`.
- **No tables or views appear:** check the selected database is `nyc311_analytics`; in Tableau refresh the data source metadata or reconnect.
- **MySQL `MEDIAN()` calculation error:** use `median_resolution_hours` and `p90_resolution_hours` from `vw_closure_by_type` instead.
- **Charts do not share filters:** use **Apply to Worksheets → All Using This Data Source** for worksheets built on the same source. For sheets from different views, create separate filters or a dashboard filter action with matching fields.
