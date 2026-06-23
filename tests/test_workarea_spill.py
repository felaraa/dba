"""
test_workarea_spill.py — Testes da regra R010 (spill de workarea para TEMP).

Caso real vivo: MERGE 86kwg7rukwx07 (agregação diária → AGG_DD_F_R4G_ADJL). O
SORT GROUP BY (id 5) derramou ~198 GB para o TEMP, ainda em 50% após 73 min.
Valida que a regra dispara como CRITICAL e NÃO dispara em planos sem spill
relevante.
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


def test_r010_dispara_no_spill_massivo():
    ctx = _ctx("query_agg_merge_spill.sql", "plan_agg_merge_spill.xml")
    recs = RuleEngine().run(ctx)
    alvo = [r for r in recs if r.rule_id == "R010_workarea_spill_to_temp"]
    assert alvo, "R010 deveria disparar com SORT GROUP BY derramando ~198 GB"
    r = alvo[0]
    assert r.severity.value == "critical"          # > 100 GiB de TEMP
    assert "SORT GROUP BY" in r.title
    assert r.ddl is None                            # diagnóstico, não índice
    # deve apontar a remediação certa: estatística + paralelismo
    txt = r.rationale + " " + " ".join(r.warnings)
    assert "PARALLEL DML" in txt
    assert "R004" in txt or "estimativa" in txt
    # deve sinalizar o plano serial apesar do hint PARALLEL
    assert any("SERIAL" in w for w in r.warnings)


def test_r010_nao_dispara_sem_spill_relevante():
    # plano sem TEMP (e o plan_cartesian tem BUFFER SORT de ~204 MB, < 1 GiB):
    for plan in ("plan_stale_stats.xml", "plan_unused_idx.xml", "plan_cartesian.xml"):
        ctx = _ctx("query_agg_merge_spill.sql", plan)
        recs = RuleEngine().run(ctx)
        alvo = [r for r in recs if r.rule_id == "R010_workarea_spill_to_temp"]
        assert not alvo, f"R010 não deveria disparar em {plan} (spill abaixo do piso)"


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
