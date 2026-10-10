def validate_records(records: list[dict]) -> None:
    keys = set()
    for i, r in enumerate(records):
        if not r.get("unique_key") or not r.get("created_date"):
            raise ValueError(f"Record {i} lacks required unique_key or created_date")
        if r["unique_key"] in keys: raise ValueError(f"Duplicate key after transform: {r['unique_key']}")
        keys.add(r["unique_key"])
        if r.get("closed_date") and r["closed_date"] < r["created_date"]: raise ValueError(f"Invalid duration for {r['unique_key']}")
