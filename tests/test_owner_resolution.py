"""
test_owner_resolution.py — Regressão do bug "CREATE INDEX None.IX_... ON None.TAB".

Queries geradas por ferramentas (BI/ETL) não qualificam o owner (`FROM F_R4G_ADJN`,
não `DBN1.F_R4G_ADJN`), então `ctx.query.tables[*].owner` vem None. O owner real
está no plano (<object><owner> da seção runtime do SQL Monitor). `ctx.resolve_owner`
deve recuperá-lo, de modo que as regras que geram DDL nunca emitam `None.`.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

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


def test_resolve_owner_from_plan_runtime():
    ctx = _ctx("query_agg_merge_adjn.sql", "plan_agg_merge_adjn.xml")
    # a query não qualifica o owner; o plano traz DBN1 em <object><owner>
    assert ctx.query.alias_to_table()["FACTS"].owner is None
    assert ctx.resolve_owner("F_R4G_ADJN") == "DBN1"


def test_generated_ddl_is_owner_qualified_not_none():
    ctx = _ctx("query_agg_merge_adjn.sql", "plan_agg_merge_adjn.xml")
    recs = RuleEngine().run(ctx)
    ddls = [r.ddl for r in recs if r.ddl]
    assert ddls, "esperava ao menos uma recomendação com DDL (R003)"
    for ddl in ddls:
        assert "None." not in ddl, f"DDL com owner None: {ddl[:80]}"
        assert "CREATE INDEX DBN1." in ddl
        assert "ON DBN1.F_R4G_ADJN" in ddl


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
