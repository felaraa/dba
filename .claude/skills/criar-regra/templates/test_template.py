"""
test_<nome>.py — Testes da regra R0XX.

Valida que a regra dispara no cenário-alvo e NÃO dispara fora dele.
Rode com: pytest -q tests/test_<nome>.py
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
# from tests.fixtures_<nome> import get_metadata   # se precisar de cardinalidade

ROOT = _ROOT
ENV = os.path.join(ROOT, "config", "env_profile_rawdb.yaml")


def _ctx(sql_file, plan_file, metadata):
    q = SqlParser().parse(open(os.path.join(ROOT, "examples", sql_file)).read())
    p = parse_plan(open(os.path.join(ROOT, "examples", plan_file)).read())
    return RuleContext(q, p, metadata, load_env_profile(ENV))


def test_regra_dispara_no_cenario_alvo():
    # ctx = _ctx("<q>.sql", "<p>.xml", get_metadata())
    # recs = RuleEngine().run(ctx)
    # alvo = [r for r in recs if r.rule_id == "R0XX_nome_curto"]
    # assert alvo, "a regra deveria disparar neste cenário"
    # assert alvo[0].severity.value == "high"
    # # se gera índice: validar convenções
    # if alvo[0].ddl:
    #     assert "__" not in alvo[0].ddl              # sem underscore duplo
    #     assert alvo[0].ddl.startswith("CREATE INDEX IX_")
    #     assert "GATHER_INDEX_STATS" in alvo[0].ddl  # gather stats presente
    raise NotImplementedError("implemente o cenário-alvo")


def test_regra_nao_dispara_fora_do_cenario():
    # use um plano/query que NÃO tem o padrão; a regra deve retornar vazio
    raise NotImplementedError("implemente o cenário negativo")


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
