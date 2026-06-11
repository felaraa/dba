"""
test_global_index_rule.py — Testes da regra R008 (índice global em particionada).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from advisor.models import (SchemaMetadata, TableMeta, ColumnStats, IndexMeta)
from advisor.sql_parser import SqlParser
from advisor.plan_parser import parse_plan
from advisor.env_profile import load_env_profile
from advisor.engine import RuleEngine
from advisor.rule_base import RuleContext

ROOT = _ROOT
ENV = os.path.join(ROOT, "config", "env_profile_rawdb.yaml")
SQL = os.path.join(ROOT, "examples", "query.sql")
PLAN = os.path.join(ROOT, "examples", "plan.txt")


def _meta(global_idx: bool):
    # ENR_RADIO_5G_GNODEB particionada, com um índice GLOBAL (ou LOCAL)
    return SchemaMetadata(
        tables=(
            TableMeta("DBN0_HUA_RAN", "T1542455817", 100_000_000, True, ("RESULTTIME",), is_hot=True),
            TableMeta("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", 500_000, True, ("STARTTIME",)),
            TableMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", 33_000, False, ()),
        ),
        columns=(
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "NE_NAME", 20632, 0, 22),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "STARTTIME", 17, 0, 8),
        ),
        indexes=(
            IndexMeta("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "IX_GLOBAL_TESTE",
                      ("NE_NAME",), False, partitioned=(not global_idx), local=(not global_idx)),
        ),
    )


def _run(meta):
    q = SqlParser().parse(open(SQL).read())
    p = parse_plan(open(PLAN).read())
    ctx = RuleContext(q, p, meta, load_env_profile(ENV))
    return RuleEngine().run(ctx)


def test_r008_dispara_para_indice_global_em_particionada():
    recs = _run(_meta(global_idx=True))
    r008 = [r for r in recs if r.rule_id == "R008_global_index_on_partitioned"]
    assert r008, "deveria sinalizar índice global em tabela particionada"
    assert "IX_GLOBAL_TESTE" in r008[0].title
    assert r008[0].ddl is None  # auditoria, não gera índice


def test_r008_nao_dispara_para_indice_local():
    recs = _run(_meta(global_idx=False))
    r008 = [r for r in recs if r.rule_id == "R008_global_index_on_partitioned"]
    assert not r008, "índice LOCAL não deve ser sinalizado"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__); passed += 1
        except Exception:
            print("FAIL", fn.__name__); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} testes passaram")
