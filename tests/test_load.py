from nyc311_etl.load import load_records

class Cursor:
    def __init__(self): self.executed=0; self.sql=[]
    def executemany(self, sql, rows): self.executed += len(rows); self.sql.append(sql)
    def execute(self, sql, params): self.sql.append(sql)
    def fetchall(self): return []
    def close(self): pass
class Conn:
    def __init__(self): self.cur=Cursor(); self.commits=0
    def cursor(self): return self.cur
    def commit(self): self.commits+=1
    def rollback(self): raise AssertionError("unexpected rollback")

def test_repeated_key_uses_upsert_and_commits_each_batch():
    c=Conn()
    row={"unique_key":"1","created_date":"2025-01-01 00:00:00","closed_date":None,
         "agency":None,"agency_name":None,"complaint_type":"Noise","descriptor":None,
         "status":"Open","borough":"QUEENS","community_board":"01 QUEENS",
         "resolution_hours":None,"is_open":True}
    assert load_records(c,[row]) == (1,0)
    assert load_records(c,[row]) == (1,0)
    assert c.commits == 2 and c.cur.executed == 2
    assert any("ON DUPLICATE KEY UPDATE" in q for q in c.cur.sql)

def test_empty_load_is_idempotent_noop():
    c=Conn(); assert load_records(c, []) == (0,0); assert c.commits==0
