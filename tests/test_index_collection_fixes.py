"""
test_index_collection_fixes.py — Regressões dos bugs de coleta/reconhecimento
de índice encontrados no caso real SQL_ID a3yqht3qtyyhy.

Cobre três correções:
  1) BUG DO CURSOR: OracleMetadataCollector._indexes iterava o MESMO cursor de
     forma preguiçosa enquanto _index_cols/_index_usage reexecutavam nele,
     descartando o result set externo. Sintoma real: tabela com 5 índices
     voltava com 0 (e o --diag dizia "nenhum índice"). Fix: fetchall() antes do
     loop. O teste usa um cursor falso que reproduz exatamente essa semântica.
  2) RECONHECIMENTO POR CONJUNTO: existing_index_covering deve reconhecer um
     índice cujas colunas de igualdade líderes estão em OUTRA ORDEM (para
     igualdade a ordem é irrelevante). Sintoma real: sugeria um índice idêntico,
     em outra ordem, ao IX_ENR4G_MSITE_CELL_START já existente.
  3) R008 ignora índices GERADOS PELO SISTEMA (IDX$$_/SYS_NC) — não são decisões
     de design do usuário.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from advisor.metadata_collector import OracleMetadataCollector
from advisor.models import IndexMeta, SchemaMetadata, TableMeta
from advisor.rules import existing_index_covering


# ---------------------------------------------------------------------------
# 1) BUG DO CURSOR — cursor falso que reproduz a corrupção de iteração
# ---------------------------------------------------------------------------
class _FakeCursor:
    """
    Imita o python-oracledb: o cursor É o próprio iterador (estado único). Uma
    nova execute() troca o result set corrente. Logo, iterar preguiçosamente o
    cursor e chamar execute() no meio (como _index_cols faz) corromperia a
    iteração externa — exatamente o bug. fetchall() materializa e isola.
    """
    def __init__(self, dispatch):
        self._dispatch = dispatch
        self._pending = iter(())

    def execute(self, sql, binds=None):
        self._pending = iter(self._dispatch(sql, binds or {}))
        return self

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._pending)

    def fetchall(self):
        return list(self._pending)

    def fetchone(self):
        return next(self._pending, None)

    def close(self):
        pass


def _dispatch(sql, binds):
    s = sql.lower()
    if "dba_ind_columns" in s:
        return [("CELL_NAME",), ("MOBILE_SITE_NAME",)]
    if "dba_index_usage" in s:
        return []  # sem linha de uso
    if "dba_indexes" in s:
        # 5 índices: owner, table_name, index_name, uniqueness, partitioned, locality
        return [
            ("O", "T", "IX1", "NONUNIQUE", "NO", "NONE"),
            ("O", "T", "IX2", "NONUNIQUE", "YES", "LOCAL"),
            ("O", "T", "IX3", "UNIQUE", "NO", "NONE"),
            ("O", "T", "IX4", "NONUNIQUE", "YES", "LOCAL"),
            ("O", "T", "IX5", "NONUNIQUE", "NO", "NONE"),
        ]
    return []


def test_indexes_collects_all_despite_inner_subqueries():
    """Com o bug, voltava 1; com o fix (fetchall antes do loop), volta os 5."""
    collector = OracleMetadataCollector(connection=None)
    cur = _FakeCursor(_dispatch)
    out = collector._indexes(cur, owners=["O"], names=["T"])
    names = sorted(ix.index_name for ix in out)
    assert names == ["IX1", "IX2", "IX3", "IX4", "IX5"], names


# ---------------------------------------------------------------------------
# 2) RECONHECIMENTO POR CONJUNTO (ordem das colunas de igualdade irrelevante)
# ---------------------------------------------------------------------------
def _md_with_index(cols):
    return SchemaMetadata(
        tables=(TableMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", 800_000, True,
                          ("STARTTIME",)),),
        columns=(),
        indexes=(IndexMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS",
                           "IX_ENR4G_MSITE_CELL_START", tuple(cols),
                           False, True, True),),
    )


def test_existing_index_recognized_regardless_of_equality_order():
    md = _md_with_index(["MOBILE_SITE_NAME", "CELL_NAME", "STARTTIME"])
    # join por (CELL_NAME, MOBILE_SITE_NAME) — ordem trocada vs índice
    hit = existing_index_covering(md, "ENR_RADIO_4G_CELLS",
                                  ["CELL_NAME", "MOBILE_SITE_NAME"])
    assert hit is not None
    assert hit.index_name == "IX_ENR4G_MSITE_CELL_START"


def test_existing_index_not_recognized_when_set_differs():
    md = _md_with_index(["MOBILE_SITE_NAME", "CELL_NAME", "STARTTIME"])
    # FOO não é coluna líder do índice → conjunto difere → não reconhece
    assert existing_index_covering(md, "ENR_RADIO_4G_CELLS",
                                   ["CELL_NAME", "FOO"]) is None


# ---------------------------------------------------------------------------
# 3) R008 ignora índices gerados pelo sistema
# ---------------------------------------------------------------------------
def test_r008_skips_system_generated_indexes():
    from advisor.rules.rule_global_index_on_partitioned import (
        GlobalIndexOnPartitionedRule)
    from advisor.env_profile import load_env_profile
    from advisor.models import ParsedPlan, ParsedQuery, TableRef
    from advisor.rule_base import RuleContext

    md = SchemaMetadata(
        tables=(TableMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", 800_000, True,
                          ("STARTTIME",)),),
        columns=(),
        indexes=(
            # global gerado pelo sistema (funcional) — deve ser IGNORADO
            IndexMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", "IDX$$_03790001",
                      ("SYS_NC00037$", "SYS_NC00038$"), False, False, False),
            # global PK de usuário — deve ser SINALIZADO
            IndexMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", "PK_ENR_RADIO_4G_CELLS",
                      ("STARTTIME", "CELL_NAME"), True, False, False),
        ),
    )
    q = ParsedQuery("", (TableRef("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", "K"),),
                    (), (), (), ())
    ctx = RuleContext(q, ParsedPlan(None, None, ()), md,
                      load_env_profile(os.path.join(_ROOT, "config",
                                                    "env_profile_rawdb.yaml")))
    recs = GlobalIndexOnPartitionedRule().evaluate(ctx)
    flagged = {r.title.split()[2] for r in recs}  # nome do índice no título
    assert any("PK_ENR_RADIO_4G_CELLS" in r.title for r in recs)
    assert not any("IDX$$" in r.title for r in recs), flagged


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
