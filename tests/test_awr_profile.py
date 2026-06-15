"""
test_awr_profile.py — Cobre o processo AWR -> env_profile.

Verifica: (1) o parser extrai os números certos do AWR HTML sintético;
(2) o builder aplica os limiares (cpu_bound, cache_hit_very_high);
(3) o YAML emitido é válido e re-carregável pelo load_env_profile do projeto;
(4) o modo UPDATE preserva campos humanos (scoring/index_ddl/exadata) e
refresca os derivados do AWR; (5) a agregação de múltiplos AWRs (RAC).

Rodar com: pytest -q
"""
import io
import os
import sys

import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from advisor.awr_parser import (AwrMetrics, HotSegment, aggregate_metrics,
                                parse_awr)
from advisor.profile_builder import build_profile, emit_yaml
from advisor.env_profile import load_env_profile
from advisor import awr_cli

HERE = os.path.dirname(os.path.abspath(__file__))
AWR = os.path.join(HERE, "fixtures", "awr_sample.html")


def _metrics():
    return parse_awr(open(AWR, encoding="utf-8").read(), source_name="awr_sample.html")


# ---- parser ---------------------------------------------------------------
def test_parse_identity():
    m = _metrics()
    assert m.db_name == "TESTDB"
    assert m.oracle_version == "19.0.0.0.0"
    assert m.rac is True
    assert m.db_block_size == 8192


def test_parse_workload_numbers():
    m = _metrics()
    # DB CPU 146000 / DB time 205900 ~= 0.71
    assert abs(m.db_cpu_pct_of_dbtime - 0.71) < 0.02
    assert m.buffer_hit_pct == 99.95
    # redo 95,420,160 B/s -> ~91 MB/s
    assert abs(m.redo_mb_per_s - 91.0) < 1.0
    assert m.block_changes_per_s == 206655.0
    assert m.logical_reads_per_s and m.physical_reads_per_s


def test_parse_io_single_block():
    m = _metrics()
    # db file sequential read 0.34 ms -> 340 µs
    assert m.single_block_read_us == 340
    assert m.multiblock_read_count == 128


def test_parse_optimizer_params():
    m = _metrics()
    assert m.optimizer_index_cost_adj == 100
    assert m.optimizer_index_caching == 0
    assert m.optimizer_adaptive_plans is True


def test_parse_rac_contention_flags():
    m = _metrics()
    assert m.index_contention_in_top_events is True
    assert m.gc_buffer_busy_in_top_events is True
    # há índice em "Segments by Buffer Busy Waits"
    assert m.index_in_buffer_busy_segments is True


def test_parse_hot_segments():
    m = _metrics()
    names = {(s.owner, s.name, s.type) for s in m.hot_segments}
    assert ("DBN0_HUA_RAN", "T1542455817", "TABLE") in names
    assert ("NA_MF", "NAMF_STATS_SEQ_IDX", "INDEX") in names
    # TABLE PARTITION normaliza para TABLE
    assert all(s.type in ("TABLE", "INDEX") for s in m.hot_segments)


def test_dictionary_segments_filtered():
    m = _metrics()
    owners = {s.owner for s in m.hot_segments}
    names = {s.name for s in m.hot_segments}
    assert "SYS" not in owners                  # schema mantido pela Oracle
    assert "SEG$" not in names                  # objeto de dicionário
    assert "WRI$_OPTSTAT_SYNOPSIS_HEAD$" not in names


def test_parser_never_crashes_on_garbage():
    m = parse_awr("isto não é html", source_name="x")
    assert isinstance(m, AwrMetrics)
    assert m.missing  # registra que não parecia HTML


# ---- builder + limiares ---------------------------------------------------
def test_build_profile_thresholds():
    prof = build_profile(_metrics(), name="TESTDB")
    assert prof["identity"]["name"] == "TESTDB"
    assert prof["identity"]["rac_nodes"] == 2          # rac=YES -> default 2
    assert prof["workload"]["cpu_bound"] is True       # 71% >= 50%
    assert prof["workload"]["cache_hit_very_high"] is True
    assert prof["io"]["single_block_read_us"] == 340
    # scoring recebe defaults no CREATE
    assert prof["scoring"]["maint_cost_hot_table"] == 0.6


def test_emitted_yaml_loads_back():
    prof = build_profile(_metrics(), name="TESTDB")
    text = emit_yaml(prof)
    data = yaml.safe_load(text)             # YAML válido
    assert data["identity"]["name"] == "TESTDB"
    # carregável pelo loader real do projeto, com os atalhos funcionando
    import tempfile
    fd = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    fd.write(text); fd.close()
    env = load_env_profile(fd.name)
    assert env.name == "TESTDB"
    assert env.is_cpu_bound is True
    assert env.is_hot_segment("DBN0_HUA_RAN", "T1542455817") is True
    os.unlink(fd.name)


# ---- modo UPDATE: preserva humano, refresca AWR ---------------------------
def test_update_preserves_human_fields():
    existing = {
        "identity": {"name": "OLD", "exadata": True, "rac_nodes": 4},
        "scoring": {"maint_cost_hot_table": 0.99, "nl_explosion_factor": 7},
        "index_ddl": {"parallel": 32, "tablespace": "DBN0_I_BIG"},
        "workload": {"benefit_metric": "buffer_gets_and_rows"},
    }
    prof = build_profile(_metrics(), existing=existing)   # sem --name
    # humano preservado
    assert prof["identity"]["exadata"] is True
    assert prof["scoring"]["maint_cost_hot_table"] == 0.99
    assert prof["scoring"]["nl_explosion_factor"] == 7
    assert prof["index_ddl"]["parallel"] == 32
    assert prof["index_ddl"]["tablespace"] == "DBN0_I_BIG"
    # derivado do AWR é refrescado (nome vem do DB Name do AWR)
    assert prof["identity"]["name"] == "TESTDB"
    assert prof["workload"]["cpu_bound"] is True
    assert prof["io"]["single_block_read_us"] == 340


def test_hot_segments_replaced_when_awr_has_them():
    existing = {"rac_contention": {"hot_segments": [
        {"owner": "X", "name": "OLD_SEG", "type": "TABLE"}]}}
    prof = build_profile(_metrics(), existing=existing)
    names = {s["name"] for s in prof["rac_contention"]["hot_segments"]}
    assert "OLD_SEG" not in names           # substituído pelos do AWR
    assert "T1542455817" in names


def test_hot_segments_preserved_when_awr_empty():
    empty = AwrMetrics()
    existing = {"rac_contention": {"hot_segments": [
        {"owner": "X", "name": "OLD_SEG", "type": "TABLE"}]}}
    prof = build_profile(empty, existing=existing)
    names = {s["name"] for s in prof["rac_contention"]["hot_segments"]}
    assert names == {"OLD_SEG"}             # AWR não trouxe nada -> preserva


# ---- agregação de múltiplos AWRs ------------------------------------------
def test_aggregate_two_nodes():
    a = AwrMetrics(db_name="P", redo_mb_per_s=80.0, db_cpu_pct_of_dbtime=0.60,
                   index_contention_in_top_events=False,
                   hot_segments=[HotSegment("O", "SEG_A", "TABLE")])
    b = AwrMetrics(db_name="P", redo_mb_per_s=100.0, db_cpu_pct_of_dbtime=0.80,
                   index_contention_in_top_events=True,
                   hot_segments=[HotSegment("O", "SEG_B", "INDEX")])
    agg = aggregate_metrics([a, b])
    assert agg.redo_mb_per_s == 90.0                  # média
    assert abs(agg.db_cpu_pct_of_dbtime - 0.70) < 1e-6
    assert agg.index_contention_in_top_events is True  # OR
    names = {(s.owner, s.name) for s in agg.hot_segments}
    assert names == {("O", "SEG_A"), ("O", "SEG_B")}   # união


# ---- CLI end-to-end (create -> arquivo, depois update) --------------------
def test_cli_create_and_update(tmp_path):
    out = tmp_path / "env_profile_testdb.yaml"
    rc = awr_cli.main(["--awr", AWR, "--out", str(out), "--name", "TESTDB"])
    assert rc == 0 and out.exists()
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["identity"]["name"] == "TESTDB"
    assert data["scoring"]["maint_cost_hot_table"] == 0.6

    # edita um campo humano e roda UPDATE: deve ser preservado
    raw = out.read_text(encoding="utf-8").replace(
        "maint_cost_hot_table: 0.6", "maint_cost_hot_table: 0.91")
    out.write_text(raw, encoding="utf-8")
    rc = awr_cli.main(["--awr", AWR, "--out", str(out), "--update"])
    assert rc == 0
    data2 = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data2["scoring"]["maint_cost_hot_table"] == 0.91   # preservado
    assert data2["identity"]["name"] == "TESTDB"              # refrescado


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            # injeta tmp_path simples p/ rodar sem pytest
            import inspect
            if "tmp_path" in inspect.signature(fn).parameters:
                import tempfile, pathlib
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print(f"PASS {fn.__name__}"); passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} testes passaram")
