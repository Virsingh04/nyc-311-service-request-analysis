from __future__ import annotations
import logging
import json
import mysql.connector
from mysql.connector import Error

LOG = logging.getLogger(__name__)

def connect(settings):
    try:
        return mysql.connector.connect(host=settings.mysql_host, port=settings.mysql_port,
            user=settings.mysql_user, password=settings.mysql_password, database=settings.mysql_database,
            connection_timeout=8)
    except Error as exc: raise RuntimeError(f"MySQL connection failed for {settings.mysql_user}@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}: {exc}") from exc

def start_run(conn, run_id: str, start: str, end: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO etl_run_log (run_id,started_at,status,source_start,source_end_exclusive) VALUES (%s,UTC_TIMESTAMP(),'running',%s,%s)", (run_id,start,end))
        conn.commit()
    finally: cur.close()

def finish_run(conn, run_id: str, status: str, fetched: int, inserted: int, updated: int, rejected: int, error: str | None = None) -> None:
    cur = conn.cursor()
    try:
        cur.execute("UPDATE etl_run_log SET ended_at=UTC_TIMESTAMP(),status=%s,records_fetched=%s,records_inserted=%s,records_updated=%s,records_rejected=%s,error_summary=%s WHERE run_id=%s",
                    (status,fetched,inserted,updated,rejected,error[:1000] if error else None,run_id))
        conn.commit()
    finally: cur.close()

def load_records(conn, records: list[dict], raw_records: list[dict] | None = None, batch_size=500) -> tuple[int, int]:
    if not records: return 0, 0
    sql = """INSERT INTO fact_service_request
      (unique_key, created_date, closed_date, agency, agency_name, complaint_type, descriptor, status, borough, community_board, resolution_hours, is_open)
      VALUES (%(unique_key)s,%(created_date)s,%(closed_date)s,%(agency)s,%(agency_name)s,%(complaint_type)s,%(descriptor)s,%(status)s,%(borough)s,%(community_board)s,%(resolution_hours)s,%(is_open)s)
      ON DUPLICATE KEY UPDATE created_date=VALUES(created_date),closed_date=VALUES(closed_date),agency=VALUES(agency),agency_name=VALUES(agency_name),complaint_type=VALUES(complaint_type),descriptor=VALUES(descriptor),status=VALUES(status),borough=VALUES(borough),community_board=VALUES(community_board),resolution_hours=VALUES(resolution_hours),is_open=VALUES(is_open)"""
    cur = conn.cursor(); inserted = updated = 0
    try:
        keys = [str(r["unique_key"]) for r in records]
        existing = set()
        for i in range(0, len(keys), batch_size):
            part = keys[i:i+batch_size]
            marks = ",".join(["%s"] * len(part))
            cur.execute(f"SELECT unique_key FROM fact_service_request WHERE unique_key IN ({marks})", tuple(part))
            existing.update(str(row[0]) for row in cur.fetchall())
        inserted, updated = len(keys) - len(existing), len(existing)
        if raw_records:
            stage_sql = "INSERT INTO stg_service_request (unique_key,payload) VALUES (%s,%s) ON DUPLICATE KEY UPDATE payload=VALUES(payload),staged_at=CURRENT_TIMESTAMP"
            stage_rows = [(str(r["unique_key"]), json.dumps(r, ensure_ascii=False)) for r in raw_records if r.get("unique_key")]
            for i in range(0, len(stage_rows), batch_size): cur.executemany(stage_sql, stage_rows[i:i+batch_size])
        for i in range(0, len(records), batch_size): cur.executemany(sql, records[i:i+batch_size])
        conn.commit()
        return inserted, updated
    except Error:
        conn.rollback(); raise
    finally: cur.close()
