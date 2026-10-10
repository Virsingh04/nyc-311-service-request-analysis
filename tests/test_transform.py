from datetime import datetime
from nyc311_etl.transform import clean_records, parse_dt

def test_parse_iso_z():
    assert parse_dt("2025-01-01T00:00:00Z") == datetime(2025, 1, 1)

def test_dedup_open_invalid_and_duration():
    rows = [
        {"unique_key":"1","created_date":"2025-01-01T00:00:00","closed_date":"2025-01-02T00:00:00","complaint_type":" Noise "},
        {"unique_key":"1","created_date":"2025-01-01T00:00:00","closed_date":None},
        {"unique_key":"2","created_date":"2025-01-01T00:00:00","closed_date":None},
        {"unique_key":"3","created_date":"2025-02-01T00:00:00","closed_date":"2025-01-01T00:00:00"},
        {"unique_key":"4","created_date":None,"closed_date":None},
    ]
    clean, rejected, counts = clean_records(rows)
    assert len(clean) == 2 and clean[0]["resolution_hours"] == 24
    assert clean[1]["is_open"] and clean[1]["resolution_hours"] is None
    assert counts["duplicates"] == 1 and len(rejected) == 2
