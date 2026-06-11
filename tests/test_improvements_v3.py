"""
test_improvements_v3.py — Valida correções pedidas no 4º feedback:
nome de índice com owner e sem '__', GATHER_INDEX_STATS no DDL, e diagnóstico
de estatística obsoleta (R004) identificando a tabela culpada.
"""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)                      # acha o pacote tests/
sys.path.insert(0, os.path.join(_ROOT, "src"))  # acha o pacote advisor/
from advisor.rules import build_index_name, build_index_ddl
from advisor.sql_parser import SqlParser
from advisor.plan_parser import parse_plan
from advisor.env_profile import load_env_profile
from advisor.engine import RuleEngine
from advisor.rule_base import RuleContext
from tests.fixtures_stale_stats import get_metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_index_name_has_owner_no_double_underscore():
    n = build_index_name("ENR_RADIO_5G_GNODEB", ["NE_NAME","STARTTIME"], owner="DBN0_EXT_ENRICH")
    assert n.startswith("IX_DBN0")     # inclui prefixo do owner
    assert "__" not in n               # sem underscore duplo
    assert not n.endswith("_")         # sem underscore no fim
    assert len(n) <= 30                # limite Oracle

def test_ddl_includes_gather_index_stats():
    ddl = build_index_ddl("DBN0_EXT_ENRICH","ENR_RADIO_5G_GNODEB",
                          "IX_TESTE",["NE_NAME","STARTTIME"],True)
    assert "CREATE INDEX" in ddl
    assert "GATHER_INDEX_STATS" in ddl
    assert "DEGREE=>16" in ddl and "FORCE=>TRUE" in ddl
    assert "GRANULARITY=>'ALL'" in ddl

def test_r004_identifies_stale_table():
    q = SqlParser().parse(open(os.path.join(ROOT,"examples","query_stale_stats.sql")).read())
    p = parse_plan(open(os.path.join(ROOT,"examples","plan_stale_stats.xml")).read())
    ctx = RuleContext(q, p, get_metadata(),
                      load_env_profile(os.path.join(ROOT,"config","env_profile_rawdb.yaml")))
    recs = RuleEngine().run(ctx)
    r004 = [r for r in recs if r.rule_id == "R004_cartesian_or_bad_estimates"]
    assert r004
    # deve nomear a tabela obsoleta e gerar o GATHER_TABLE_STATS
    txt = " ".join(r.rationale + " ".join(r.warnings) for r in r004)
    assert "T1526726713" in txt
    assert "STALE=YES" in txt
    assert "GATHER_TABLE_STATS" in txt


def test_local_inferred_from_plan_when_table_not_collected():
    # T1526726713 NÃO está nos metadados, mas é particionada no plano (PARTITION
    # RANGE ITERATOR). O índice deve sair com LOCAL via inferência do plano.
    from tests.fixtures_partial import get_metadata as gm_partial
    q = SqlParser().parse(open(os.path.join(ROOT,"examples","query_stale_stats.sql")).read())
    p = parse_plan(open(os.path.join(ROOT,"examples","plan_stale_stats.xml")).read())
    ctx = RuleContext(q, p, gm_partial(),
                      load_env_profile(os.path.join(ROOT,"config","env_profile_rawdb.yaml")))
    recs = RuleEngine().run(ctx)
    t_idx = [r for r in recs if r.ddl and "T1526726713" in r.ddl]
    assert t_idx
    assert all("LOCAL" in r.ddl for r in t_idx), "índice em tabela particionada deve ser LOCAL"


if __name__ == "__main__":
    import traceback
    fns = [v for k,v in sorted(globals().items()) if k.startswith("test_")]
    pa=0
    for fn in fns:
        try: fn(); print("PASS",fn.__name__); pa+=1
        except Exception: print("FAIL",fn.__name__); traceback.print_exc()
    print(f"\n{pa}/{len(fns)} testes passaram")
