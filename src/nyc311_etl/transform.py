from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterable

def parse_dt(value):
    if not value: return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

def clean_records(records: Iterable[dict]) -> tuple[list[dict], list[dict], dict]:
    clean, rejected, seen = [], [], set()
    counts = {"input": 0, "duplicates": 0, "rejected": 0}
    for raw in records:
        counts["input"] += 1
        row = {k: (str(v).strip() if v is not None and isinstance(v, str) else v) for k, v in raw.items()}
        key = row.get("unique_key")
        if not key: rejected.append({"row": row, "reason": "missing_unique_key"}); continue
        if key in seen: counts["duplicates"] += 1; continue
        seen.add(key)
        try: created, closed = parse_dt(row.get("created_date")), parse_dt(row.get("closed_date"))
        except (ValueError, TypeError): rejected.append({"row": row, "reason": "invalid_timestamp"}); continue
        if created is None: rejected.append({"row": row, "reason": "missing_created_date"}); continue
        if closed is not None and closed < created: rejected.append({"row": row, "reason": "closed_before_created"}); continue
        row["created_date"], row["closed_date"] = created, closed
        row["resolution_hours"] = (closed - created).total_seconds() / 3600 if closed else None
        row["is_open"] = closed is None
        clean.append(row)
    counts["rejected"] = len(rejected)
    return clean, rejected, counts
