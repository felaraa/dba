"""
fixtures_plan_instability.py — Metadados + histórico de planos do caso real
SQL_ID 2z54xtcs69rhf (query LTE_EUTRANCELLFDD_0 x ENR_RADIO_4G_CELLS).

Além de get_metadata() (cardinalidade), expõe get_plan_history(), que simula o
que o coletor de planos (GV$SQL + AWR) traria: VÁRIOS plan_hash_value para o
mesmo SQL_ID. O plano do arquivo (3126586065) é o que explode em NESTED LOOPS;
um plano alternativo (HASH JOIN) é dramaticamente melhor por execução.
"""
from advisor.models import (ColumnStats, IndexMeta, PlanHistory, PlanStat,
                            SchemaMetadata, TableMeta)


def get_metadata() -> SchemaMetadata:
    return SchemaMetadata(
        tables=(
            TableMeta("DBN0_ERI_RAN", "LTE_EUTRANCELLFDD_0", 2_000_000_000, True,
                      ("MEASSTARTTIME",), is_hot=True),
            TableMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", 800_000, True,
                      ("STARTTIME",), is_hot=False),
        ),
        columns=(
            ColumnStats("DBN0_ERI_RAN", "LTE_EUTRANCELLFDD_0", "EUTRANCELLFDD", 60000, 0, 24),
            ColumnStats("DBN0_ERI_RAN", "LTE_EUTRANCELLFDD_0", "MECONTEXT", 18000, 0, 22),
            ColumnStats("DBN0_ERI_RAN", "LTE_EUTRANCELLFDD_0", "MEASSTARTTIME", 2000, 0, 8),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", "CELL_NAME", 60000, 0, 24),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", "MOBILE_SITE_NAME", 18000, 0, 28),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G_CELLS", "STARTTIME", 17, 0, 8),
        ),
        indexes=(
            IndexMeta("DBN0_ERI_RAN", "LTE_EUTRANCELLFDD_0", "LTE_EUTRANCELLFDD_02",
                      ("MEASSTARTTIME", "SEQ_NUMBER"), False, True, True),
        ),
    )


def get_plan_history() -> PlanHistory:
    """3 planos distintos; 814617906 (HASH JOIN) é o melhor, 3126586065 o pior."""
    return PlanHistory(
        sql_id="2z54xtcs69rhf",
        plans=(
            # plano do arquivo: NESTED LOOPS que explode — caríssimo por exec
            PlanStat("3126586065", ("cursor",), executions=42,
                     avg_elapsed_s=690.0, avg_buffer_gets=160_000_000.0,
                     avg_cpu_s=685.0, avg_rows=1359.0,
                     first_seen="2026-06-10 02:00", last_seen="2026-06-11 10:57"),
            # plano alternativo HASH JOIN: ordens de magnitude mais barato
            PlanStat("814617906", ("cursor", "awr"), executions=5100,
                     avg_elapsed_s=4.2, avg_buffer_gets=820_000.0,
                     avg_cpu_s=3.9, avg_rows=1402.0,
                     first_seen="2026-05-20 00:00", last_seen="2026-06-09 23:00"),
            # plano intermediário
            PlanStat("2274581002", ("awr",), executions=1200,
                     avg_elapsed_s=31.5, avg_buffer_gets=9_400_000.0,
                     avg_cpu_s=30.1, avg_rows=1380.0,
                     first_seen="2026-06-01 00:00", last_seen="2026-06-08 00:00"),
        ),
    )
