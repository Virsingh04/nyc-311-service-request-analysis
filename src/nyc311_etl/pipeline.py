from __future__ import annotations
import argparse, json, logging, sys, uuid, hashlib
from datetime import datetime, timedelta
from pathlib import Path
from .config import ROOT, load_settings
from .extract import make_session, iter_records, preview, profile_types, build_where
from .transform import clean_records
from .validate import validate_records
from .load import connect, load_records, start_run, finish_run

LOG = logging.getLogger(__name__)

def main():
    p = argparse.ArgumentParser(description="NYC 311 data preview and ETL")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("preview", help="Fetch a five-row scoped sample")
    sub.add_parser("profile", help="Count request types in configured date window")
    sub.add_parser("check-db", help="Check MySQL connectivity")
    backfill = sub.add_parser("backfill", help="Load configured date window")
    backfill.add_argument("--reuse-snapshot", action="store_true", help="Load the matching complete raw snapshot instead of fetching it again")
    sub.add_parser("refresh", help="Refresh overlap and recently open requests")
    d = sub.add_parser("dry-run", help="Extract and transform without writing to MySQL")
    args = p.parse_args(); settings = load_settings(); cfg = settings.project
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = make_session(settings.socrata_token)
    conn = None
    run_id = str(uuid.uuid4())
    run_started = False
    rows = []
    cleaned = []
    rejected = []
    try:
        if args.command == "check-db":
            c = connect(settings); c.close(); print("MySQL connection successful"); return
        if args.command == "preview":
            if not settings.socrata_token: print("SOCRATA_APP_TOKEN absent; trying public endpoint without a token.", file=sys.stderr)
            print(json.dumps(preview(cfg, session), indent=2)); return
        if args.command == "profile": print(json.dumps(profile_types(cfg, session), indent=2)); return
        start, end = cfg["start_date"], cfg["end_date"]
        if args.command == "refresh":
            start = (datetime.fromisoformat(end) - timedelta(days=int(cfg.get("overlap_days", 14)))).date().isoformat()
        if args.command != "dry-run":
            conn = connect(settings)
            start_run(conn, run_id, start, end)
            run_started = True
        rows = []
        if args.command == "backfill" and args.reuse_snapshot:
            query = {"dataset_id":cfg["dataset_id"],"select":cfg["fields"],"where":build_where(cfg,start,end),
                     "order":"created_date ASC, unique_key ASC","page_size":int(cfg.get("page_size",1000))}
            digest = hashlib.sha256(json.dumps(query,sort_keys=True).encode()).hexdigest()[:8]
            matches = sorted((ROOT / cfg["raw_dir"]).glob(f"extract_*_{digest}"), reverse=True)
            for candidate in matches:
                manifest_path = candidate / "manifest.json"
                if not manifest_path.exists(): continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("status") == "complete" and manifest.get("filters") == query:
                    for page_path in sorted(candidate.glob("page_*.json")):
                        rows.extend(json.loads(page_path.read_text(encoding="utf-8")))
                    LOG.info("Reusing complete snapshot %s (%s records)", candidate.name, len(rows))
                    break
            if not rows: raise RuntimeError("No complete raw snapshot matches this configured backfill; run backfill without --reuse-snapshot")
        else:
            rows = list(iter_records(cfg, session, start=start, end=end, max_rows=cfg["max_rows"], max_runtime=cfg["max_runtime_seconds"], raw_dir=ROOT / cfg["raw_dir"]))
        if args.command == "refresh":
            # Also fetch recent currently open records so closure updates are captured.
            open_cfg = dict(cfg, request_types=cfg.get("request_types", []))
            rows += list(iter_records(open_cfg, session, start=(datetime.utcnow()-timedelta(days=int(cfg.get("open_refresh_days", 180)))).date().isoformat(), end=(datetime.utcnow()+timedelta(days=1)).date().isoformat(), max_rows=cfg["max_rows"], max_runtime=cfg["max_runtime_seconds"], raw_dir=ROOT / cfg["raw_dir"], open_only=True))
        cleaned, rejected, counts = clean_records(rows); validate_records(cleaned)
        print(json.dumps({"run_id": run_id, "counts": counts, "valid": len(cleaned), "rejected_reasons": [x["reason"] for x in rejected], "dry_run": args.command == "dry-run"}, indent=2))
        if args.command != "dry-run":
            ins, upd = load_records(conn, cleaned, raw_records=rows)
            finish_run(conn, run_id, "success", len(rows), ins, upd, len(rejected))
            print(f"Committed {len(rows)} staged rows and {len(cleaned)} cleaned upserts (inserted={ins}, updated={upd}).")
    except Exception as exc:
        if conn is not None and run_started:
            try: finish_run(conn, run_id, "failed", len(rows), 0, 0, len(rejected), str(exc))
            except Exception: logging.exception("Could not persist ETL failure status")
        logging.exception("Pipeline failed: %s", exc); sys.exit(1)
    finally:
        if conn is not None: conn.close()

if __name__ == "__main__": main()
