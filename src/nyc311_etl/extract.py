from __future__ import annotations
import json, logging, time, hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger(__name__)

def make_session(token: str | None = None) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, connect=5, read=5, status=5, backoff_factor=0.7,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET"]))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"Accept": "application/json", "User-Agent": "nyc311-analytics-student-project/1.0"})
    if token: s.headers["X-App-Token"] = token
    return s

def build_where(cfg: dict, start: str | None = None, end: str | None = None, open_only: bool = False) -> str:
    start, end = start or cfg["start_date"], end or cfg["end_date"]
    clauses = [f"created_date >= '{start}T00:00:00'", f"created_date < '{end}T00:00:00'"]
    types = cfg.get("request_types", [])
    if types:
        escaped = ["'" + t.replace("'", "''") + "'" for t in types]
        clauses.append("complaint_type in (" + ",".join(escaped) + ")")
    if open_only: clauses.append("closed_date IS NULL")
    return " AND ".join(clauses)

def iter_records(cfg: dict, session: requests.Session, *, start=None, end=None, max_rows=None, max_runtime=None,
                 raw_dir: Path | None = None, dry_run=False, open_only=False) -> Iterator[dict]:
    """Keyset pagination with atomic per-page checkpoints, so interrupted runs resume."""
    started, total, page_no = time.monotonic(), 0, 0
    page_size = min(int(cfg.get("page_size", 1000)), 50000)
    fields = cfg["fields"]
    base_where = build_where(cfg, start, end, open_only=open_only)
    query_config = {"dataset_id": cfg["dataset_id"], "select": fields, "where": base_where,
                    "order": "created_date ASC, unique_key ASC", "page_size": page_size}
    digest = hashlib.sha256(json.dumps(query_config, sort_keys=True).encode()).hexdigest()[:16]
    workdir = None
    if raw_dir is not None and not dry_run:
        raw_dir.mkdir(parents=True, exist_ok=True)
        workdir = raw_dir / f"partial_{digest}"
        workdir.mkdir(exist_ok=True)
    cached_pages = sorted(workdir.glob("page_*.json")) if workdir else []
    cursor = None
    for path in cached_pages:
        with path.open(encoding="utf-8") as f: page = json.load(f)
        if not page: continue
        page_no += 1; total += len(page)
        cursor = (page[-1].get("created_date"), page[-1].get("unique_key"))
        LOG.info("Resumed checkpoint page %s (%s records)", page_no, total)
        yield from page
    if cached_pages and len(json.loads(cached_pages[-1].read_text(encoding="utf-8"))) < page_size:
        if workdir is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            manifest = {"status":"complete", "source":"NYC Open Data Socrata API", "dataset_id":cfg["dataset_id"],
                        "filters":query_config, "extracted_at_utc":stamp, "page_count":page_no, "record_count":total,
                        "date_coverage":{"start":start or cfg["start_date"],"end_exclusive":end or cfg["end_date"]}}
            mt=workdir/"manifest.json.tmp"; mt.write_text(json.dumps(manifest,indent=2),encoding="utf-8"); mt.replace(workdir/"manifest.json")
            workdir.rename(raw_dir/f"extract_{stamp}_{digest[:8]}")
        return
    while True:
        if max_runtime and time.monotonic() - started > max_runtime: raise TimeoutError("Extraction exceeded MAX_RUNTIME_SECONDS")
        if max_rows and total >= max_rows: raise RuntimeError(f"Extraction reached MAX_ROWS={max_rows}; narrow the date/type scope")
        where = base_where
        if cursor:
            created, key = cursor
            key = str(key).replace("'", "''")
            where += f" AND (created_date > '{created}' OR (created_date = '{created}' AND unique_key > '{key}'))"
        params = {"$select": ",".join(fields), "$where": where,
                  "$order": "created_date ASC, unique_key ASC", "$limit": page_size}
        if max_rows: params["$limit"] = min(page_size, max_rows - total + 1)
        response = session.get(cfg["api_base_url"], params=params, timeout=(10, 90))
        if response.status_code >= 400: raise RuntimeError(f"Socrata returned HTTP {response.status_code}: {response.text[:300]}")
        page = response.json()
        if not isinstance(page, list): raise RuntimeError("Socrata response was not a JSON array")
        if not page: break
        if max_rows and total + len(page) > max_rows: raise RuntimeError(f"Extraction would exceed MAX_ROWS={max_rows}; narrow the date/type scope")
        if dry_run: yield from page; return
        if workdir is not None:
            tmp=workdir/f"page_{page_no+1:06d}.json.tmp"; tmp.write_text(json.dumps(page),encoding="utf-8"); tmp.replace(workdir/f"page_{page_no+1:06d}.json")
            running={"status":"running","query":query_config,"page_count":page_no+1,"record_count":total+len(page),"updated_at_utc":datetime.now(timezone.utc).isoformat()}
            mt=workdir/"manifest.json.tmp"; mt.write_text(json.dumps(running,indent=2),encoding="utf-8"); mt.replace(workdir/"manifest.json")
        yield from page
        total += len(page); page_no += 1
        cursor = (page[-1].get("created_date"), page[-1].get("unique_key"))
        LOG.info("Fetched %s records", total)
        if len(page) < page_size: break
    if workdir is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        manifest = {"status":"complete", "source":"NYC Open Data Socrata API", "dataset_id":cfg["dataset_id"],
                    "filters":query_config, "extracted_at_utc":stamp, "page_count":page_no, "record_count":total,
                    "date_coverage":{"start":start or cfg["start_date"],"end_exclusive":end or cfg["end_date"]}}
        mt=workdir/"manifest.json.tmp"; mt.write_text(json.dumps(manifest,indent=2),encoding="utf-8"); mt.replace(workdir/"manifest.json")
        workdir.rename(raw_dir/f"extract_{stamp}_{digest[:8]}")

def fetch_metadata(url: str, session: requests.Session) -> dict:
    r = session.get(url, timeout=(10, 60)); r.raise_for_status(); return r.json()

def preview(cfg: dict, session: requests.Session, limit=5) -> list[dict]:
    params = {"$select": ",".join(cfg["fields"]), "$where": build_where(cfg),
              "$order": "created_date DESC, unique_key ASC", "$limit": limit}
    r = session.get(cfg["api_base_url"], params=params, timeout=(10, 60)); r.raise_for_status(); return r.json()

def profile_types(cfg: dict, session: requests.Session) -> list[dict]:
    profile_cfg = dict(cfg, request_types=[])
    params = {"$select": "complaint_type,count(*) as request_count", "$where": build_where(profile_cfg),
              "$group": "complaint_type", "$order": "request_count DESC", "$limit": 25}
    r = session.get(cfg["api_base_url"], params=params, timeout=(10, 90)); r.raise_for_status(); return r.json()
