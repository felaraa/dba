"""
profile_builder.py — Transforma AwrMetrics (números crus do AWR) num
env_profile YAML, criando do zero ou atualizando um perfil existente.

Separação de responsabilidades (NÃO QUEBRAR):
- awr_parser.py LÊ o AWR (fatos crus).
- profile_builder.py DECIDE os limiares ("cpu_bound", "cache_hit_very_high")
  e MONTA o YAML. É aqui que mora a calibração.
- Os PESOS de scoring NÃO saem do AWR — são tuning humano. Em CREATE recebem
  defaults; em UPDATE são PRESERVADOS do arquivo existente.

Por que um emissor de YAML próprio (e não yaml.dump):
- O env_profile é fortemente COMENTADO (cada chave explica o que alimenta).
  yaml.dump descartaria todos os comentários. Este módulo re-emite o arquivo
  inteiro a partir de um template comentado, então tanto CREATE quanto UPDATE
  produzem um YAML legível e idêntico em estilo ao env_profile_rawdb.yaml —
  sem adicionar dependência (ruamel) ao projeto.

Campos por origem:
  AWR (atualizados a cada execução): identity.{name,rac_nodes,oracle_version,
    db_block_size}, workload.*, io.{single_block_read_us,multiblock_read_count},
    rac_contention.*, optimizer.*
  HUMANO (preservados no UPDATE; defaults no CREATE): scoring.*, index_ddl.*,
    identity.exadata, io.full_scan_block_discount
"""
from __future__ import annotations

import copy
from typing import Any, Optional

from .awr_parser import AwrMetrics, HotSegment

# ---------------------------------------------------------------------------
# Limiares de decisão (a "calibração"). Ajuste aqui, não no parser.
# ---------------------------------------------------------------------------
CPU_BOUND_THRESHOLD = 0.50          # DB CPU >= 50% do DB time => cpu_bound
CACHE_HIT_VERY_HIGH_PCT = 99.0      # Buffer Hit % a partir do qual é "muito alto"
CACHE_HIT_LIO_PIO_RATIO = 50.0      # ou LIO/PIO >= 50x

# Defaults de campos HUMANOS (usados só no CREATE; no UPDATE vêm do arquivo).
DEFAULT_SCORING = {
    "maint_cost_hot_table": 0.6,
    "maint_cost_cold_table": 0.05,
    "coverage_cost_per_byte": 0.004,
    "wide_column_bytes": 30,
    "nl_explosion_factor": 100,
}
DEFAULT_FULL_SCAN_DISCOUNT = 0.85
DEFAULT_IO_SINGLE_BLOCK_US = 340
DEFAULT_IO_MBRC = 128
DEFAULT_INDEX_DDL = {"parallel": None, "tablespace": None}


def _cache_hit_very_high(m: AwrMetrics) -> bool:
    if m.buffer_hit_pct is not None and m.buffer_hit_pct >= CACHE_HIT_VERY_HIGH_PCT:
        return True
    if m.logical_reads_per_s and m.physical_reads_per_s:
        return (m.logical_reads_per_s / max(m.physical_reads_per_s, 1)) >= CACHE_HIT_LIO_PIO_RATIO
    return False


def build_profile(
    metrics: AwrMetrics,
    existing: Optional[dict[str, Any]] = None,
    name: Optional[str] = None,
    rac_nodes: Optional[int] = None,
    exadata: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Monta o dict do env_profile.

    existing  : dict de um YAML já carregado (modo UPDATE) ou None (CREATE).
    name      : sobrescreve identity.name (senão usa AWR; senão o existente).
    rac_nodes : sobrescreve identity.rac_nodes.
    exadata   : sobrescreve identity.exadata (AWR não detecta com confiança).
    """
    existing = existing or {}

    def keep(section: str, key: str, default):
        """Valor preservado do existente (UPDATE) ou default (CREATE)."""
        return existing.get(section, {}).get(key, default)

    # ---- identity (AWR atualiza; exadata é humano) ----------------------
    ident_name = (name or metrics.db_name or keep("identity", "name", "NEWDB"))
    nodes = (rac_nodes if rac_nodes is not None
             else metrics.rac_instances
             or keep("identity", "rac_nodes", 2 if metrics.rac else 1))
    is_exa = (exadata if exadata is not None
              else keep("identity", "exadata", False))
    identity = {
        "name": ident_name,
        "rac_nodes": int(nodes),
        "exadata": bool(is_exa),
        "oracle_version": metrics.oracle_version or keep("identity", "oracle_version", "19.0.0"),
        "db_block_size": metrics.db_block_size or keep("identity", "db_block_size", 8192),
    }

    # ---- workload (tudo do AWR; preserva se AWR não achou) --------------
    cpu_pct = metrics.db_cpu_pct_of_dbtime
    if cpu_pct is None:
        cpu_pct = keep("workload", "db_cpu_pct_of_dbtime", None)
    workload = {
        "cpu_bound": (cpu_pct >= CPU_BOUND_THRESHOLD) if cpu_pct is not None
                     else keep("workload", "cpu_bound", True),
        "db_cpu_pct_of_dbtime": cpu_pct if cpu_pct is not None
                                else keep("workload", "db_cpu_pct_of_dbtime", 0.69),
        "cache_hit_very_high": _cache_hit_very_high(metrics)
                               if (metrics.buffer_hit_pct is not None or metrics.logical_reads_per_s)
                               else keep("workload", "cache_hit_very_high", True),
        "benefit_metric": keep("workload", "benefit_metric", "buffer_gets_and_rows"),
        "redo_mb_per_s": metrics.redo_mb_per_s
                         if metrics.redo_mb_per_s is not None
                         else keep("workload", "redo_mb_per_s", None),
        "block_changes_per_s": metrics.block_changes_per_s
                               if metrics.block_changes_per_s is not None
                               else keep("workload", "block_changes_per_s", None),
    }

    # ---- io (single block do AWR; resto humano) -------------------------
    io = {
        "single_block_read_us": metrics.single_block_read_us
                                if metrics.single_block_read_us is not None
                                else keep("io", "single_block_read_us", DEFAULT_IO_SINGLE_BLOCK_US),
        "multiblock_read_count": metrics.multiblock_read_count
                                 if metrics.multiblock_read_count is not None
                                 else keep("io", "multiblock_read_count", DEFAULT_IO_MBRC),
        "full_scan_block_discount": keep("io", "full_scan_block_discount", DEFAULT_FULL_SCAN_DISCOUNT),
    }

    # ---- rac_contention (do AWR; hot_segments substitui se AWR achou) ---
    idx_cont = metrics.index_contention_in_top_events
    gc_busy = metrics.gc_buffer_busy_in_top_events
    seq_hot = metrics.index_in_buffer_busy_segments
    rac_contention = {
        "index_contention_in_top_events": idx_cont if idx_cont is not None
                                          else keep("rac_contention", "index_contention_in_top_events", False),
        "sequential_index_hotblock_observed": seq_hot if seq_hot is not None
                                              else keep("rac_contention", "sequential_index_hotblock_observed", False),
        "gc_buffer_busy_in_top_events": gc_busy if gc_busy is not None
                                        else keep("rac_contention", "gc_buffer_busy_in_top_events", False),
        "hot_segments": _build_hot_segments(metrics, existing),
    }

    # ---- scoring (HUMANO: defaults no CREATE, preserva no UPDATE) -------
    scoring = {k: keep("scoring", k, v) for k, v in DEFAULT_SCORING.items()}

    # ---- optimizer (init.ora do AWR) ------------------------------------
    optimizer = {
        "index_cost_adj": metrics.optimizer_index_cost_adj
                          if metrics.optimizer_index_cost_adj is not None
                          else keep("optimizer", "index_cost_adj", 100),
        "index_caching": metrics.optimizer_index_caching
                         if metrics.optimizer_index_caching is not None
                         else keep("optimizer", "index_caching", 0),
        "adaptive_plans": metrics.optimizer_adaptive_plans
                          if metrics.optimizer_adaptive_plans is not None
                          else keep("optimizer", "adaptive_plans", True),
    }

    # ---- index_ddl (HUMANO: preservado integralmente) -------------------
    index_ddl = {
        "parallel": keep("index_ddl", "parallel", DEFAULT_INDEX_DDL["parallel"]),
        "tablespace": keep("index_ddl", "tablespace", DEFAULT_INDEX_DDL["tablespace"]),
    }

    return {
        "identity": identity,
        "workload": workload,
        "io": io,
        "rac_contention": rac_contention,
        "scoring": scoring,
        "optimizer": optimizer,
        "index_ddl": index_ddl,
    }


def _build_hot_segments(metrics: AwrMetrics, existing: dict[str, Any]) -> list[dict]:
    """
    O AWR é a fonte de verdade do que está quente AGORA: se ele trouxe
    segmentos, eles SUBSTITUEM a lista. Se não trouxe (seção ausente), o que
    existia no perfil é preservado.
    """
    if metrics.hot_segments:
        # dedup mantendo a 1ª ocorrência (ordem das seções é a de relevância)
        out, seen = [], set()
        for s in metrics.hot_segments:
            key = (s.owner, s.name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"owner": s.owner, "name": s.name, "type": s.type})
        return out
    return copy.deepcopy(existing.get("rac_contention", {}).get("hot_segments", []) or [])


# ===========================================================================
# Emissor de YAML comentado (re-emite o arquivo inteiro, preservando estilo)
# ===========================================================================
def _y(v: Any) -> str:
    """Formata um escalar para YAML (bool minúsculo, None -> vazio)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        # evita 0.69000000001; mantém inteiros .0 como int-ish
        return ("%g" % v)
    return str(v)


def emit_yaml(profile: dict[str, Any], awr_window_note: str = "") -> str:
    """dict do env_profile -> texto YAML comentado (mesmo estilo do rawdb)."""
    p = profile
    ident, wl, io, rac = p["identity"], p["workload"], p["io"], p["rac_contention"]
    sc, opt, ddl = p["scoring"], p["optimizer"], p["index_ddl"]

    seg_lines = []
    for s in rac.get("hot_segments", []) or []:
        seg_lines.append(
            f"    - {{owner: {s['owner']}, name: {s['name']}, type: {s['type']}}}"
        )
    seg_block = "\n".join(seg_lines) if seg_lines else "    []"

    window = awr_window_note or "gerado automaticamente de AWR (advisor.awr_cli)"

    return f"""\
# =============================================================================
# env_profile {ident['name']}
# Perfil do ambiente extraído de AWR(s) — {window}.
# Edite este arquivo para recalibrar a engine sem tocar em código. Cada chave
# alimenta pesos/limiares das regras. Campos marcados [humano] NÃO vêm do AWR e
# são preservados quando você reexecuta o advisor.awr_cli em modo --update.
# =============================================================================

identity:
  name: {ident['name']}
  rac_nodes: {_y(ident['rac_nodes'])}
  exadata: {_y(ident['exadata'])}            # [humano] AWR não detecta com confiança
  oracle_version: "{ident['oracle_version']}"
  db_block_size: {_y(ident['db_block_size'])}

# --- Natureza da carga (define o que "benefício" significa no scoring) -------
workload:
  cpu_bound: {_y(wl['cpu_bound'])}              # DB CPU >= 50% do DB time
  db_cpu_pct_of_dbtime: {_y(wl['db_cpu_pct_of_dbtime'])}
  cache_hit_very_high: {_y(wl['cache_hit_very_high'])}    # Buffer Hit% alto ou LIO>>PIO
  # alvo de otimização: reduzir gets/linhas (proxy de CPU), não IO físico
  benefit_metric: {wl['benefit_metric']}
  redo_mb_per_s: {_y(wl['redo_mb_per_s'])}
  block_changes_per_s: {_y(wl['block_changes_per_s'])}

# --- Latências de IO reais (break-even índice vs full scan) ------------------
io:
  single_block_read_us: {_y(io['single_block_read_us'])}    # db file sequential read médio
  multiblock_read_count: {_y(io['multiblock_read_count'])}   # db_file_multiblock_read_count
  # [humano] custo relativo de 1 multiblock read vs 1 single block
  full_scan_block_discount: {_y(io['full_scan_block_discount'])}

# --- Contenção em RAC já existente (regras de mitigação ativas) --------------
rac_contention:
  index_contention_in_top_events: {_y(rac['index_contention_in_top_events'])}   # enq: TX - index contention no top
  sequential_index_hotblock_observed: {_y(rac['sequential_index_hotblock_observed'])}
  gc_buffer_busy_in_top_events: {_y(rac['gc_buffer_busy_in_top_events'])}
  # objetos confirmadamente quentes pelo AWR (Segments by ...):
  hot_segments:
{seg_block}

# --- Pesos do scoring [humano] — NÃO vêm do AWR; calibração manual -----------
scoring:
  maint_cost_hot_table: {_y(sc['maint_cost_hot_table'])}        # penalidade base p/ índice em tabela quente
  maint_cost_cold_table: {_y(sc['maint_cost_cold_table'])}      # tabelas enriquecidas (carga em lote)
  coverage_cost_per_byte: {_y(sc['coverage_cost_per_byte'])}    # custo de cobertura por byte extra
  wide_column_bytes: {_y(sc['wide_column_bytes'])}              # limiar de "coluna larga"
  nl_explosion_factor: {_y(sc['nl_explosion_factor'])}          # explosão de NESTED LOOPS p/ severidade crítica

# --- Optimizer (de init.ora no AWR; engine não compensa distorção) -----------
optimizer:
  index_cost_adj: {_y(opt['index_cost_adj'])}
  index_caching: {_y(opt['index_caching'])}
  adaptive_plans: {_y(opt['adaptive_plans'])}

# --- Geração de DDL de índice [humano] (afeta SÓ o texto do CREATE INDEX) ----
index_ddl:
  # DOP para acelerar a CRIAÇÃO do índice (vazio = sem PARALLEL).
  parallel: {_y(ddl['parallel'])}
  # TABLESPACE de destino do índice (vazio = default do schema).
  tablespace: {_y(ddl['tablespace'])}
"""
