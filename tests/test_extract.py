from nyc311_etl.extract import build_where, iter_records, make_session

class Response:
    status_code=200
    def __init__(self, payload): self.payload=payload
    def json(self): return self.payload

class Session:
    def __init__(self): self.calls=[]
    def get(self, url, params, timeout):
        self.calls.append(params)
        return Response([{"unique_key":str(len(self.calls))}] if len(self.calls)==1 else [])

def test_filter_is_scoped_and_quoted():
    where=build_where({"start_date":"2025-01-01","end_date":"2025-02-01","request_types":["O'Brien"]})
    assert "created_date >= '2025-01-01T00:00:00'" in where
    assert "O''Brien" in where

def test_pagination_stops_on_empty_page():
    s=Session(); rows=list(iter_records({"api_base_url":"x","dataset_id":"x","start_date":"2025-01-01","end_date":"2025-02-01","request_types":[],"fields":["unique_key"],"page_size":1},s))
    assert len(rows)==1 and len(s.calls)==2

def test_session_configures_retry_for_rate_limits():
    s = make_session("sample-token")
    adapter = s.get_adapter("https://")
    assert adapter.max_retries.total == 5
    assert 429 in adapter.max_retries.status_forcelist
    assert s.headers["X-App-Token"] == "sample-token"

def test_interrupted_extract_resumes_from_saved_page(tmp_path):
    class Interrupted:
        def __init__(self): self.calls=0
        def get(self, url, params, timeout):
            self.calls += 1
            if self.calls == 1:
                return Response([{"unique_key":"1","created_date":"2025-01-02T00:00:00.000"}])
            raise RuntimeError("simulated interruption")
    cfg={"api_base_url":"x","dataset_id":"x","start_date":"2025-01-01","end_date":"2025-02-01",
         "request_types":[],"fields":["unique_key","created_date"],"page_size":1}
    try: list(iter_records(cfg,Interrupted(),raw_dir=tmp_path))
    except RuntimeError: pass
    class Resume:
        def __init__(self): self.params=None
        def get(self,url,params,timeout): self.params=params; return Response([])
    s=Resume(); rows=list(iter_records(cfg,s,raw_dir=tmp_path))
    assert [r["unique_key"] for r in rows] == ["1"]
    assert "created_date > '2025-01-02T00:00:00.000'" in s.params["$where"]
