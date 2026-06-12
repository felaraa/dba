"""
test_index_ddl_options.py — DDL de CREATE INDEX: owner-qualificado + PARALLEL +
TABLESPACE controlados pelo env.

Cobre:
  - o índice é SEMPRE qualificado pelo owner da tabela (CREATE INDEX owner.idx
    ON owner.tab ...);
  - index_ddl.parallel no env => "PARALLEL n" no CREATE + "ALTER INDEX ...
    NOPARALLEL;" logo em seguida;
  - index_ddl.tablespace no env => "TABLESPACE y" no CREATE;
  - sem config => DDL limpo (sem PARALLEL/TABLESPACE/ALTER);
  - leitura dos parâmetros pelo EnvProfile.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from advisor.rules import build_index_ddl
from advisor.env_profile import EnvProfile


OWNER, TABLE, IDX = "DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", "IX_ENR4G_TEST"
COLS = ["CELL_NAME", "MOBILE_SITE_NAME", "STARTTIME"]


def test_index_is_owner_qualified_by_default():
    ddl = build_index_ddl(OWNER, TABLE, IDX, COLS, local=True)
    # nome do índice qualificado pelo MESMO owner da tabela
    assert f"CREATE INDEX {OWNER}.{IDX} ON {OWNER}.{TABLE}" in ddl
    assert "LOCAL" in ddl
    # sem opções: nada de PARALLEL/TABLESPACE/ALTER
    assert "PARALLEL" not in ddl
    assert "TABLESPACE" not in ddl
    assert "ALTER INDEX" not in ddl
    # gather de estatísticas presente
    assert "GATHER_INDEX_STATS" in ddl


def test_parallel_adds_clause_and_noparallel_followup():
    ddl = build_index_ddl(OWNER, TABLE, IDX, COLS, local=True, parallel=16)
    lines = ddl.splitlines()
    assert lines[0].endswith("PARALLEL 16;"), lines[0]
    assert f"ALTER INDEX {OWNER}.{IDX} NOPARALLEL;" in ddl
    # a ordem importa: NOPARALLEL vem logo após o CREATE
    assert lines[1] == f"ALTER INDEX {OWNER}.{IDX} NOPARALLEL;"
    assert "GATHER_INDEX_STATS" in lines[2]


def test_tablespace_adds_clause():
    ddl = build_index_ddl(OWNER, TABLE, IDX, COLS, local=True, tablespace="TBS_INDX")
    assert "TABLESPACE TBS_INDX" in ddl.splitlines()[0]
    assert "ALTER INDEX" not in ddl  # sem parallel, sem NOPARALLEL


def test_parallel_and_tablespace_together():
    ddl = build_index_ddl(OWNER, TABLE, IDX, COLS, local=True,
                          parallel=8, tablespace="TBS_INDX")
    create = ddl.splitlines()[0]
    assert "LOCAL" in create
    assert "TABLESPACE TBS_INDX" in create
    assert "PARALLEL 8" in create
    assert create.index("TABLESPACE") < create.index("PARALLEL")  # ordem estável
    assert f"ALTER INDEX {OWNER}.{IDX} NOPARALLEL;" in ddl


def test_non_partitioned_has_no_local():
    ddl = build_index_ddl(OWNER, TABLE, IDX, COLS, local=False)
    assert "LOCAL" not in ddl
    assert f"CREATE INDEX {OWNER}.{IDX} ON {OWNER}.{TABLE}" in ddl


# ---- leitura pelo EnvProfile ----------------------------------------------
def test_envprofile_reads_index_ddl_options():
    env = EnvProfile(raw={"index_ddl": {"parallel": 16, "tablespace": "TBS_INDX"}})
    assert env.index_parallel == 16
    assert env.index_tablespace == "TBS_INDX"


def test_envprofile_defaults_when_absent_or_blank():
    assert EnvProfile(raw={}).index_parallel is None
    assert EnvProfile(raw={}).index_tablespace is None
    blank = EnvProfile(raw={"index_ddl": {"parallel": None, "tablespace": ""}})
    assert blank.index_parallel is None
    assert blank.index_tablespace is None


def test_rawdb_profile_index_ddl_accessors_match_raw():
    from advisor.env_profile import load_env_profile
    env = load_env_profile(os.path.join(_ROOT, "config", "env_profile_rawdb.yaml"))
    # a seção existe e os acessores refletem FIELMENTE o configurado (seja qual
    # for o valor que o operador colocou no YAML), sem assumir set/unset.
    assert "index_ddl" in env.raw
    raw = env.raw["index_ddl"]
    if raw.get("parallel") in (None, "", 0, "0"):
        assert env.index_parallel is None
    else:
        assert env.index_parallel == int(raw["parallel"])
    if raw.get("tablespace") in (None, ""):
        assert env.index_tablespace is None
    else:
        assert env.index_tablespace == str(raw["tablespace"])


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
