"""
test_plan_instability.py — Testes da regra R009 (instabilidade de plano).

Caso real SQL_ID 2z54xtcs69rhf: a mesma query aparece com vários plan_hash_value.
A regra deve (a) disparar quando há >1 plano, identificando o MELHOR; (b) ficar
inerte quando o histórico tem 0 ou 1 plano.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)                       # acha o pacote tests/
sys.path.insert(0, os.path.join(_ROOT, "src"))  # acha o pacote advisor/

from advisor.sql_parser import SqlParser
from advisor.plan_parser import parse_plan
from advisor.env_profile import load_env_profile
from advisor.engine import RuleEngine
from advisor.rule_base import RuleContext
from advisor.models import PlanHistory, PlanStat
from tests.fixtures_plan_instability import get_metadata, get_plan_history

ROOT = _ROOT
SQL = os.path.join(ROOT, "examples", "query_plan_instability.sql")
PLAN = os.path.join(ROOT, "examples", "plan_instability.xml")
ENV = os.path.join(ROOT, "config", "env_profile_rawdb.yaml")


def _ctx(plan_history):
    q = SqlParser().parse(open(SQL).read())
    p = parse_plan(open(PLAN).read())
    return RuleContext(q, p, get_metadata(), load_env_profile(ENV),
                       plan_history=plan_history)


# ---- o plano do arquivo de fato é o 3126586065 -----------------------------
def test_plan_file_hash_is_the_bad_plan():
    p = parse_plan(open(PLAN).read())
    assert p.sql_id == "2z54xtcs69rhf"
    assert p.plan_hash == "3126586065"


# ---- PlanHistory: ranqueamento do melhor/pior plano ------------------------
def test_history_identifies_best_plan():
    hist = get_plan_history()
    assert hist.distinct_count() == 3
    assert hist.best().plan_hash == "814617906"     # HASH JOIN, mais barato
    assert hist.worst().plan_hash == "3126586065"   # NESTED LOOPS, explode


# ---- a regra dispara e identifica o melhor plano ---------------------------
def test_r009_fires_on_multiple_plans():
    recs = RuleEngine().run(_ctx(get_plan_history()))
    r009 = [r for r in recs if r.rule_id == "R009_plan_instability"]
    assert r009, "R009 deveria disparar com vários plan_hash_value"
    rec = r009[0]
    assert rec.severity.value == "high"          # 3 planos e razão > 3x
    assert "3 planos" in rec.title
    # o melhor plano (814617906) é nomeado e o plano do arquivo é marcado pior
    assert "814617906" in rec.rationale
    assert "MELHOR" in rec.rationale
    assert any("DBMS_SPM" in w for w in rec.warnings)
    assert any("814617906" in w for w in rec.warnings)  # SPM aponta o melhor
    assert rec.ddl is None                       # diagnóstico, não gera índice


def test_r009_runs_before_index_rules():
    ids = RuleEngine().loaded_rule_ids
    assert ids.index("R009_plan_instability") < ids.index("R001_filter_should_be_access")


# ---- a regra NÃO dispara com 0 ou 1 plano ----------------------------------
def test_r009_silent_on_single_plan():
    single = PlanHistory("2z54xtcs69rhf", plans=(
        PlanStat("3126586065", ("cursor",), 42, 690.0, 1.6e8, 685.0, 1359.0),
    ))
    recs = RuleEngine().run(_ctx(single))
    assert not [r for r in recs if r.rule_id == "R009_plan_instability"]


def test_r009_silent_without_history():
    recs = RuleEngine().run(_ctx(PlanHistory("2z54xtcs69rhf", plans=())))
    assert not [r for r in recs if r.rule_id == "R009_plan_instability"]


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
