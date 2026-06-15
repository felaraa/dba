"""
test_pipeline.py — Suite de testes do Oracle Index Advisor.

Cobre: parser de SQL, parser de plano (texto), e o pipeline completo (motor +
regras) reproduzindo o caso real 24h537gmxw93d. Rodar com: pytest -q
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
from advisor.reporter import merge_mitigation_warnings
from tests.fixtures_rawdb import get_metadata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SQL = os.path.join(ROOT, "examples", "query.sql")
PLAN = os.path.join(ROOT, "examples", "plan.txt")
# Ambiente PINADO da regressão (ver cabeçalho do YAML). Não usar o perfil de
# produção config/env_profile_rawdb.yaml: ele é DADO regenerado de AWRs e o
# padrão de contenção de índice — premissa da regressão R900 — pode sumir do
# top de eventos numa recalibração, quebrando o teste sem que a engine mude.
ENV = os.path.join(HERE, "fixtures", "env_profile_rawdb.yaml")


def _ctx():
    q = SqlParser().parse(open(SQL).read())
    p = parse_plan(open(PLAN).read())
    md = get_metadata()
    env = load_env_profile(ENV)
    return RuleContext(q, p, md, env)


# ---- parser de SQL --------------------------------------------------------
def test_sql_parser_tables():
    q = SqlParser().parse(open(SQL).read())
    names = {t.name for t in q.tables}
    assert names == {"T1542455817", "ENR_RADIO_5G_GNODEB", "ENR_RADIO_4G5G_HUA_SCTP"}


def test_sql_parser_joins():
    q = SqlParser().parse(open(SQL).read())
    pairs = {(str(j.left), str(j.right)) for j in q.join_predicates}
    # join A.OBJECT=K.NE_NAME deve estar presente (em alguma ordem)
    flat = {frozenset((a, b)) for a, b in pairs}
    assert frozenset(("A.OBJECT", "K.NE_NAME")) in flat
    assert frozenset(("A.LINKNO", "L.LINKNO")) in flat


def test_sql_parser_range_filters():
    q = SqlParser().parse(open(SQL).read())
    ranges = {str(f.column) for f in q.filter_predicates if f.kind.value == "range"}
    assert "A.RESULTTIME" in ranges and "K.STARTTIME" in ranges


# ---- parser de plano ------------------------------------------------------
def test_plan_parser_hierarchy():
    p = parse_plan(open(PLAN).read())
    by = p.by_id()
    assert by[11].parent_id == 3          # table access K filho do NL externo
    assert by[10].parent_id == 4          # PK scan filho do NL interno
    assert by[8].parent_id == 7           # index scan filho do table access A


def test_plan_parser_runtime_stats():
    p = parse_plan(open(PLAN).read())
    assert p.has_runtime_stats()
    assert p.by_id()[10].actual_rows == 609_000_000
    assert p.by_id()[11].executions == 609_000_000


def test_plan_parser_predicates():
    p = parse_plan(open(PLAN).read())
    assert any("OBJECT" in f and "NE_NAME" in f
               for f in p.by_id()[11].filter_predicates)


# ---- pipeline completo ----------------------------------------------------
def test_engine_recommends_probe_index_critical():
    recs = RuleEngine().run(_ctx())
    r001 = [r for r in recs if r.rule_id == "R001_filter_should_be_access"]
    assert r001, "R001 deveria disparar no caso real"
    rec = r001[0]
    assert rec.severity.value == "critical"
    assert "NE_NAME" in rec.ddl and "ENR_RADIO_5G_GNODEB" in rec.ddl
    assert rec.net_score > 0.5


def test_engine_covering_has_negative_score_on_hot_table():
    recs = RuleEngine().run(_ctx())
    r003 = [r for r in recs if r.rule_id == "R003_covering_for_aggregation"]
    assert r003
    # tabela quente => custo de manutenção supera benefício (alerta de trade-off)
    assert r003[0].estimated_maint_cost > r003[0].estimated_benefit


def test_mitigation_merged_into_index_rec():
    recs = merge_mitigation_warnings(RuleEngine().run(_ctx()))
    hot_idx = [r for r in recs if r.target_table == "T1542455817" and r.ddl]
    assert hot_idx
    assert any("INITRANS" in w or "HASH" in w for w in hot_idx[0].warnings)


def test_denylist_disables_rule():
    recs = RuleEngine(denylist={"R001_filter_should_be_access"}).run(_ctx())
    assert not any(r.rule_id == "R001_filter_should_be_access" for r in recs)


if __name__ == "__main__":
    # permite rodar sem pytest
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}"); passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} testes passaram")
