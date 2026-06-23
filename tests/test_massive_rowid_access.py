"""
test_massive_rowid_access.py — Testes da regra R011.

Caso real vivo: MERGE 86kwg7rukwx07. O TABLE ACCESS BY LOCAL INDEX ROWID BATCHED
de F_R4G_ADJL (id 8) devolveu 389M linhas via PK por TIME_KEY — caminho errado
para esse volume; deveria ser full scan da partição. Valida que a regra dispara
(HIGH, apontando full scan + estatística) e NÃO dispara em planos sem acesso por
ROWID de volume massivo.
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
from advisor.models import SchemaMetadata

ROOT = _ROOT
ENV = os.path.join(ROOT, "config", "env_profile_datadb.yaml")


def _ctx(sql_file, plan_file):
    q = SqlParser().parse(open(os.path.join(ROOT, "examples", sql_file)).read())
    p = parse_plan(open(os.path.join(ROOT, "examples", plan_file)).read())
    md = SchemaMetadata(tables=(), columns=(), indexes=())
    return RuleContext(q, p, md, load_env_profile(ENV))


def test_r011_dispara_no_rowid_massivo():
    ctx = _ctx("query_agg_merge_spill.sql", "plan_agg_merge_spill.xml")
    recs = RuleEngine().run(ctx)
    alvo = [r for r in recs if r.rule_id == "R011_massive_rowid_access"]
    assert alvo, "R011 deveria disparar com 389M linhas via ROWID"
    r = alvo[0]
    assert r.severity.value == "high"              # >= 50M linhas
    assert r.target_table == "F_R4G_ADJL"
    assert r.ddl is None                            # diagnóstico, não índice
    assert "389,003,636" in r.title
    txt = r.rationale + " " + " ".join(r.warnings)
    # owner correto veio do <object><owner> da seção runtime
    assert "DBN1" in txt
    # remediação: full scan + estatística
    assert "FULL SCAN" in r.rationale.upper() or "FULL(" in txt
    assert "GATHER_TABLE_STATS" in txt
    # tabela particionada inferida do plano (PARTITION RANGE) → full scan da partição
    assert "parti" in r.rationale.lower()


def test_r011_nao_dispara_sem_rowid_massivo():
    for plan in ("plan_stale_stats.xml", "plan_unused_idx.xml", "plan_cartesian.xml"):
        ctx = _ctx("query_agg_merge_spill.sql", plan)
        recs = RuleEngine().run(ctx)
        alvo = [r for r in recs if r.rule_id == "R011_massive_rowid_access"]
        assert not alvo, f"R011 não deveria disparar em {plan}"


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
