import pytest
from datetime import datetime
from nyc311_etl.validate import validate_records

def test_duplicate_is_rejected():
    row={"unique_key":"x","created_date":datetime(2025,1,1),"closed_date":None}
    with pytest.raises(ValueError): validate_records([row,row])
