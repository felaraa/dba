"""
test_cartesian_case.py — Testes do segundo caso real (SQL_ID 9brm2zn013zu1).

Cobre: parser XML do SQL Monitor (duas seções), detecção de MERGE JOIN
CARTESIAN (R004), SQL Profile ativo (R005), e materialização BUFFER SORT (R006).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)                      # acha o pacote tests/
sys.path.insert(0, os.path.join(_ROOT, "src"))  # acha o pacote advisor/

from advisor.sql_parser import SqlParser
from advisor.plan_parser import parse_plan
from advisor.env_profile import load_env_profile
from advisor.engine import RuleEngine
from advisor.rule_base import RuleContext
from tests.fixtures_cartesian import get_metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL = os.path.join(ROOT, "examples", "query_cartesian.sql")
PLAN = os.path.join(ROOT, "examples", "plan_cartesian.xml")
ENV = os.path.join(ROOT, "config", "env_profile_rawdb.yaml")


def _ctx():
    q = SqlParser().parse(open(SQL).read())
    p = parse_plan(open(PLAN).read())
    return RuleContext(q, p, get_metadata(), load_env_profile(ENV))


# ---- parser XML (duas seções) --------------------------------------------
def test_xml_parser_runtime_stats():
    p = parse_plan(open(PLAN).read())
    assert p.has_runtime_stats()
    by = p.by_id()
    # id 12: 2,16 bilhões de execuções (a explosão)
    assert by[12].executions == 2162311473
    # id 5 é o MERGE JOIN CARTESIAN
    assert "CARTESIAN" in by[5].operation


def test_xml_parser_hierarchy_and_objects():
    p = parse_plan(open(PLAN).read())
    by = p.by_id()
    assert by[12].parent_id == 3
    assert by[12].object_name == "T1526726696"
    assert by[7].object_name == "ENR_RADIO_4G_ENODEB"


def test_xml_parser_detects_sql_profile():
    p = parse_plan(open(PLAN).read())
    assert p.sql_profile is not None
    assert "coe_" in p.sql_profile
    assert any("Profile" in n for n in p.notes)


# ---- regras novas ---------------------------------------------------------
def test_r004_detects_cartesian():
    recs = RuleEngine().run(_ctx())
    r004 = [r for r in recs if r.rule_id == "R004_cartesian_or_bad_estimates"]
    assert r004
    assert any("CARTESIAN" in r.title.upper() for r in r004)
    assert any(r.severity.value == "critical" for r in r004)


def test_r005_detects_intervention():
    recs = RuleEngine().run(_ctx())
    r005 = [r for r in recs if r.rule_id == "R005_existing_intervention"]
    assert r005
    assert any("coe_" in w for w in r005[0].warnings)


def test_r001_still_detects_probe_explosion():
    recs = RuleEngine().run(_ctx())
    r001 = [r for r in recs if r.rule_id == "R001_filter_should_be_access"]
    assert r001
    assert "T1526726696" in r001[0].ddl


def test_cartesian_rule_runs_first():
    # R005 priority=1, R004 priority=5: contexto antes de índices
    eng = RuleEngine()
    ids = eng.loaded_rule_ids
    assert ids.index("R005_existing_intervention") < ids.index("R001_filter_should_be_access")
    assert ids.index("R004_cartesian_or_bad_estimates") < ids.index("R001_filter_should_be_access")


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}"); passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} testes passaram")
