# NYC 311 Service Request Delays and Backlog Analysis

A portfolio-scale analytics pipeline for a configurable window of NYC 311 service requests. Python extracts a bounded slice from the NYC Open Data Socrata API, preserves a raw JSON snapshot and manifest, cleans and validates request records, then upserts a MySQL fact table. SQL views provide Tableau-facing monthly, closure, and open-backlog reporting.

## Current implementation and verification

- Dataset metadata was checked against the official API on October 3, 2026. Dataset ID: `erm2-nwe9`; title: **311 Service Requests from 2020 to Present**. The API names are `complaint_type` and `descriptor` (the current display labels are “Problem (formerly Complaint Type)” and “Problem Detail (formerly Descriptor)”). The configured fields below exist in the metadata.
- A live five-row preview returned the configured fields without a token. A grouped 12-month profile returned 432,431 Noise - Residential, 359,087 HEAT/HOT WATER, and 194,672 Blocked Driveway requests. The default is now the single Blocked Driveway category: it offers ample records for analysis and its observed count fits the 250,000-row extraction cap. `profile` shows top categories across the configured date window without downloading request rows.
- The five-row sample and grouped profile were followed by a full configured dry-run on October 4, 2026. It fetched 194,672 records into ignored raw snapshots and validated all of them: zero duplicate keys and zero rejected rows. The snapshot was then staged and loaded into MySQL: 194,672 fact rows inserted, 0 updated, 0 rejected. The latest ETL run is successful. All four reporting views were queried successfully. Tableau workbook/driver availability has not been checked.
- Automated tests cover pagination stopping, safe request-type filter quoting, retry setup, date parsing, duplicate removal, open requests, invalid durations, validation, and parameterized idempotent upsert construction. Run them with `pytest`.

## Scope and data volume

By default, `config/project.json` covers `[2025-10-01, 2026-10-01)` (12 months), selecting `Blocked Driveway`. The window and request types are editable in JSON, with no Python edits needed. The API query selects only ten fields:

`unique_key`, `created_date`, `closed_date`, `agency`, `agency_name`, `complaint_type`, `descriptor`, `status`, `borough`, `community_board`.

The project has a configurable hard cap of 250,000 rows per extraction and a 3,600 second runtime safeguard. A live count query found 194,672 requests in the default 12-month type window; this was an aggregate count, not a record download. Use `profile` to see top request-type counts and `preview` to inspect five records before changing scope. Backfill and refresh write fetched raw rows under ignored `data/raw/` with a manifest. No full-history extraction is the default.

## Architecture and pipeline

```text
NYC Open Data / Socrata SODA API
  -> requests client (timeouts, retry/backoff, X-App-Token when present)
  -> bounded, ordered API pages -> atomic raw JSON snapshot + manifest
  -> deterministic timestamp normalization, deduplication, validity checks
  -> invalid-row reason counts + validated fact records
  -> MySQL fact_service_request (unique_key upsert; reruns do not duplicate)
  -> SQL reporting views -> Tableau Desktop
```

The repository layers are `config/project.json`, `src/nyc311_etl/{config,extract,transform,validate,load,pipeline}.py`, `sql/`, and `tests/`. Raw JSON is kept immutable after it is written, and `.env`, raw downloads, logs, and virtual environments are ignored by Git. Extraction is bounded and uses deterministic keyset pagination. Each page is saved atomically under an incomplete-run folder with a manifest; rerunning the same incomplete query resumes after its last saved key, then marks the snapshot complete. As the source is mutable, a retroactive source edit during a long run may still affect coverage. Rerunning a completed extraction starts a new snapshot, and MySQL upserts by `unique_key` avoid duplicate fact rows.

Refresh pulls the configured recent overlap and the configured recent window for records with a null close date. The upsert updates existing records when their closure status changes. Limitation: it cannot capture a close-date correction to an older record outside the overlap/open window; increase those windows if your use case requires it.

## Data preparation and analysis

Before loading, Python trims whitespace in string fields, parses timestamps as UTC-naive MySQL `DATETIME`, keeps one row per `unique_key`, and calculates `resolution_hours` only when a valid close timestamp exists. Open requests retain `closed_date = NULL`, `resolution_hours = NULL`, and `is_open = true`; they are not counted as zero-hour closures. Rows missing a key or creation date, with invalid timestamps, or with close time before create time are rejected with a reason (and counted in the run output). Duplicate keys are counted and skipped. Raw source values remain in the saved snapshot.

Analysis implemented/planned in SQL reporting views:

- Reported request count, open count, and open share (not prevalence of underlying conditions).
- Median and 90th-percentile resolution hours for valid closed requests. The closure view computes the midpoint median and nearest-rank p90 from MySQL 8.0 window ranks.
- Open backlog records with age bands: 0–6, 7–29, 30–89, and 90+ days.
- Monthly reporting with request type, agency, borough, and community-board fields for slicing/comparison.

The fact table is one row per request and retains borough/community board for aggregate geographic comparisons. It intentionally omits coordinates and street address fields from the extract and reporting model. Requests are service cases that can be routed to agencies, not all 311 contacts. A recorded close date does not show that a resident considers an issue resolved. Differences by place, request type, or agency do not establish causation or poor performance. No SLA/“late” claim is made because no verified SLA target data is included. Compare similar request types.

## macOS setup

Requires Python 3.10+ and MySQL 8.0. From this project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

Edit `.env` with your local MySQL host, port, database, username, and password. Do not commit `.env`. In `sql/01_create_database.sql`, replace the `change_me` placeholder with a strong local password, run it as a MySQL administrator, and restore the placeholder before committing the SQL file:

```bash
mysql -u root -p < sql/01_create_database.sql
mysql -h 127.0.0.1 -u nyc311_user -p nyc311_analytics < sql/02_create_tables.sql
mysql -h 127.0.0.1 -u nyc311_user -p nyc311_analytics < sql/03_create_views.sql
```

If you already have a local MySQL instance/user, create the database and grant appropriate privileges yourself, then update `.env`. The example user grant is restricted to TCP connections from `127.0.0.1` and scoped to this database. Never paste a production password into shell history or source files.

## NYC Open Data token

The API may allow small public requests without a token. For larger/repeated requests, create a free NYC Open Data account, sign in, open **Developer Settings** from your profile, and create an app token. Store only the token value as `SOCRATA_APP_TOKEN` in local `.env`. The client sends it in the `X-App-Token` header. The sample command warns and continues without a token when the public endpoint permits it.

Official references: [311 dataset](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9), [Socrata API guide](https://www.nyc.gov/opendata/get-started/user-guides/open-data-apis), [dataset metadata](https://data.cityofnewyork.us/api/views/erm2-nwe9.json).

## Commands

Run the commands from the project root with `.venv` activated:

```bash
python -m nyc311_etl.pipeline preview     # five rows in configured scope; API smoke test
python -m nyc311_etl.pipeline profile     # top request type counts in configured 12-month scope
python -m nyc311_etl.pipeline check-db    # MySQL connectivity only
pytest                                    # offline automated tests
python -m nyc311_etl.pipeline dry-run     # extract/clean/validate, no MySQL writes
python -m nyc311_etl.pipeline backfill    # bounded configured historical window; requires MySQL
python -m nyc311_etl.pipeline backfill --reuse-snapshot  # reuse a complete matching raw snapshot
python -m nyc311_etl.pipeline refresh     # recent overlap plus currently open recent requests
```

`preview` and `profile` are safe live API checks. Neither makes a database change. Before running backfill, inspect `profile`, review dates and types in `config/project.json`, confirm the configured row/runtime safeguards, and ensure the MySQL schema scripts have succeeded. `backfill --reuse-snapshot` loads only when a completed snapshot matches the configured filters and dates; otherwise use `backfill` to fetch the configured window. Backfill never means the dataset’s complete 2020-to-present history unless you deliberately configure such a date range (and the safeguards still apply).

## MySQL model and Tableau

`fact_service_request` is the analytical fact table with `unique_key` primary key and indexes for created date, request type, agency, geography, and open status. `stg_service_request` stores source row payloads; valid cleaned rows are then upserted into the fact table. `etl_run_log` records run window, status, fetched/inserted/updated/rejected counts, and failure summary. These require the schema scripts to be applied before a database-writing command.

Reporting views:

- `vw_monthly_overview`: monthly volume/open counts and share.
- `vw_closure_by_type`: valid closed case counts, midpoint median, and nearest-rank p90 resolution hours by request type, agency, and geography.
- `vw_open_backlog_age`: open requests with age in days and age band.
- `vw_backlog_by_month`: open backlog aggregates by request type, agency, and geography.

In Tableau Desktop for Mac, choose **Connect → To a Server → MySQL**, enter the host/port/database/user from `.env`, and use the local MySQL driver Tableau requests if it is not installed. Select reporting views rather than staging/raw data. Suggested sheets: **Overview** (request count, open backlog, median/p90); **Comparison** (closure/backlog by matching request type, agency, borough/community board); **Monthly trend** (month with date, geography, type, and agency filters). Tableau driver presence and workbook creation have not been verified; no workbook is included.

## Tests and troubleshooting

`pytest` does not call the live API or require MySQL. HTTP behavior is tested with local mock response/session objects. For `ModuleNotFoundError`, activate `.venv` and run `pip install -e .`; for API errors, check connectivity and retry later, verify token/configuration, and keep the date/type scope bounded. For MySQL connection errors, confirm the service is running, `MYSQL_HOST`/`MYSQL_PORT` are correct, the database and user exist, and privileges apply from the connecting host. The `check-db` command never creates or modifies a database.

[Watch my Tableau dashboard demo](https://youtu.be/FPcn39zsQuA)
