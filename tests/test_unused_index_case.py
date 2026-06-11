"""
test_unused_index_case.py — Terceiro caso real (SQL_ID 3fjgnfugy2kd6).

Valida: (a) não recomendar índice que já existe; (b) R007 detectar índice
existente não usado; (c) consolidação de índices redundantes entre regras.
"""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)                      # acha o pacote tests/
sys.path.insert(0, os.path.join(_ROOT, "src"))  # acha o pacote advisor/

from advisor.sql_parser import SqlParser
from advisor.plan_parser import parse_plan
from advisor.env_profile import load_env_profile
from advisor.engine import RuleEngine
from advisor.rule_base import RuleContext
from advisor.reporter import consolidate_indexes
from tests.fixtures_unused_idx import get_metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL = os.path.join(ROOT, "examples", "query_unused_idx.sql")
PLAN = os.path.join(ROOT, "examples", "plan_unused_idx.xml")
ENV = os.path.join(ROOT, "config", "env_profile_rawdb.yaml")

def _recs(consolidate=True):
    q = SqlParser().parse(open(SQL).read())
    p = parse_plan(open(PLAN).read())
    ctx = RuleContext(q, p, get_metadata(), load_env_profile(ENV))
    recs = RuleEngine().run(ctx)
    return consolidate_indexes(recs) if consolidate else recs

def test_does_not_recommend_existing_index():
    # IX_4G_ENODEB_NE_START (NE_NAME, STARTTIME) já existe → R001/R002 não devem
    # recomendar índice em ENR_RADIO_4G_ENODEB liderado por NE_NAME
    recs = _recs()
    for r in recs:
        if r.ddl and "ENR_RADIO_4G_ENODEB" in r.ddl:
            assert False, f"recomendou índice duplicado: {r.ddl}"

def test_r007_detects_unused_index():
    recs = _recs()
    r007 = [r for r in recs if r.rule_id == "R007_unused_existing_index"]
    assert r007
    assert "IX_4G_ENODEB_NE_START" in r007[0].title
    assert any("CARTESIAN" in w or "estatísticas" in w for w in r007[0].warnings)

def test_consolidation_removes_redundant_index():
    # sem consolidar: R002 e R006 produzem 2 índices p/ IPPATH; consolidado: 1
    raw = _recs(consolidate=False)
    ippath_raw = [r for r in raw if r.ddl and "HUA_IPPATH" in r.ddl]
    cons = _recs(consolidate=True)
    ippath_cons = [r for r in cons if r.ddl and "HUA_IPPATH" in r.ddl]
    assert len(ippath_raw) >= 2
    assert len(ippath_cons) == 1   # consolidado no superset

if __name__ == "__main__":
    import traceback
    fns = [v for k,v in sorted(globals().items()) if k.startswith("test_")]
    p=0
    for fn in fns:
        try: fn(); print("PASS",fn.__name__); p+=1
        except Exception: print("FAIL",fn.__name__); traceback.print_exc()
    print(f"\n{p}/{len(fns)} testes passaram")
