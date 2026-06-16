"""
batch.py — Motor do modo batch: analisa as N queries mais quentes do banco.

Carrega as top N queries por buffer_gets (última hora), extrai SQL + plano
de cada uma, salva em temp/<sql_id>/, executa o advisor e devolve um
BatchReport consolidado com todas as recomendações.

Só funciona com --source <banco>; fixture não é suportada (dados vêm ao vivo
de GV$SQL, GV$SQLTEXT, SQL Monitor e DBMS_XPLAN).
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .engine import RuleEngine
from .env_profile import EnvProfile
from .metadata_collector import OracleMetadataCollector
from .models import PlanHistory, Recommendation
from .plan_history import collect_plan_history
from .plan_parser import parse_plan
from .reporter import consolidate_indexes, merge_mitigation_warnings
from .rule_base import RuleContext
from .sql_parser import SqlParser

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Queries SQL executadas no banco
# ---------------------------------------------------------------------------

# Top N por total_buffer_gets na última hora com avg_elapsed > 10 min (600s)
_TOP_SQL = """\
WITH sql_base AS (
    SELECT
        s.sql_id,
        SUM(s.buffer_gets)   AS total_buffer_gets,
        SUM(s.executions)    AS total_executions,
        SUM(s.elapsed_time)  AS total_elapsed_us
    FROM gv$sql s
    WHERE s.last_active_time >= SYSDATE - (1/24)
      AND s.executions > 0
      AND s.elapsed_time > 0
      AND s.parsing_schema_name NOT IN ('SYS')
    GROUP BY s.sql_id
    HAVING (SUM(s.elapsed_time) / NULLIF(SUM(s.executions), 0)) > 600000000
)
SELECT sql_id
FROM sql_base
ORDER BY total_buffer_gets DESC
FETCH FIRST :limit ROWS ONLY"""

# Texto completo do SQL — agrupa por piece para evitar duplicatas RAC
_FETCH_SQL_TEXT = """\
SELECT piece, MIN(sql_text) AS sql_text
FROM gv$sqltext
WHERE sql_id = :sql_id
GROUP BY piece
ORDER BY piece"""

# Plano via SQL Monitor (preferido — tem A-Rows, Execs, hierarquia)
_FETCH_SQL_MONITOR = """\
SELECT DBMS_SQLTUNE.REPORT_SQL_MONITOR(
    sql_id       => :sql_id,
    type         => 'XML',
    report_level => 'ALL'
) FROM DUAL"""

# Fallback: texto do DBMS_XPLAN
_FETCH_XPLAN = """\
SELECT plan_table_output
FROM TABLE(
    DBMS_XPLAN.DISPLAY_CURSOR(
        sql_id          => :sql_id,
        cursor_child_no => NULL,
        format          => 'ALLSTATS LAST +PREDICATE'
    )
)"""


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    """Resultado da análise de um único SQL_ID."""
    sql_id: str
    sql_text: Optional[str] = None
    plan_text: Optional[str] = None
    plan_format: Optional[str] = None      # 'xml' | 'text'
    recommendations: list[Recommendation] = field(default_factory=list)
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    sql_path: Optional[Path] = None
    plan_path: Optional[Path] = None


@dataclass
class BatchReport:
    """Relatório consolidado de todas as queries analisadas."""
    total_queries: int
    total_with_recommendations: int
    total_skipped: int
    total_errors: int
    results: list[QueryResult]

    def all_recommendations(self) -> list[tuple[str, Recommendation]]:
        """Retorna (sql_id, rec) de todos os resultados que têm recomendações."""
        out = []
        for r in self.results:
            for rec in r.recommendations:
                out.append((r.sql_id, rec))
        return out

    def all_ddls(self) -> list[tuple[str, Recommendation]]:
        """Retorna apenas as recomendações com DDL (índices a criar)."""
        return [(sid, rec) for sid, rec in self.all_recommendations() if rec.ddl]


# ---------------------------------------------------------------------------
# Funções de coleta no banco
# ---------------------------------------------------------------------------

def _fetch_top_sql_ids(conn, limit: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(_TOP_SQL, limit=limit)
        return [row[0] for row in cur.fetchall()]


def _fetch_sql_text(conn, sql_id: str) -> Optional[str]:
    try:
        with conn.cursor() as cur:
            cur.execute(_FETCH_SQL_TEXT, sql_id=sql_id)
            rows = cur.fetchall()
            if rows:
                return "".join(row[1] or "" for row in rows).strip()
    except Exception as exc:
        log.warning("Erro ao buscar sql_text para %s: %s", sql_id, exc)
    return None


def _read_lob(value) -> Optional[str]:
    """Lê um valor que pode ser LOB ou string."""
    if value is None:
        return None
    if hasattr(value, "read"):
        return value.read()
    return str(value)


def _fetch_plan(conn, sql_id: str) -> tuple[Optional[str], Optional[str]]:
    """
    Retorna (plan_text, format). Tenta SQL Monitor XML primeiro;
    cai para DBMS_XPLAN texto se não disponível.
    """
    # 1) SQL Monitor XML
    try:
        with conn.cursor() as cur:
            cur.execute(_FETCH_SQL_MONITOR, sql_id=sql_id)
            row = cur.fetchone()
            if row:
                text = _read_lob(row[0])
                if text and ("<sql_monitor_report" in text or "<report" in text):
                    return text, "xml"
    except Exception as exc:
        log.debug("SQL Monitor indisponível para %s: %s", sql_id, exc)

    # 2) DBMS_XPLAN texto
    try:
        with conn.cursor() as cur:
            cur.execute(_FETCH_XPLAN, sql_id=sql_id)
            rows = cur.fetchall()
            if rows:
                text = "\n".join(row[0] or "" for row in rows).strip()
                if text:
                    return text, "text"
    except Exception as exc:
        log.warning("DBMS_XPLAN indisponível para %s: %s", sql_id, exc)

    return None, None


def _save_to_temp(
    temp_dir: Path, sql_id: str, sql_text: str, plan_text: str, plan_format: str
) -> tuple[Path, Path]:
    query_dir = temp_dir / sql_id
    query_dir.mkdir(parents=True, exist_ok=True)

    sql_path = query_dir / "query.sql"
    sql_path.write_text(sql_text, encoding="utf-8")

    ext = "xml" if plan_format == "xml" else "txt"
    plan_path = query_dir / f"plan.{ext}"
    plan_path.write_text(plan_text, encoding="utf-8")

    return sql_path, plan_path


# ---------------------------------------------------------------------------
# Analisador batch
# ---------------------------------------------------------------------------

class BatchAnalyzer:
    """
    Orquestra a análise em lote: busca os top N SQL_IDs, extrai SQL + plano,
    coleta metadados e executa o motor de regras em cada um.
    """

    def __init__(
        self,
        conn,
        env: EnvProfile,
        temp_dir: Path,
        engine: RuleEngine,
        diag: bool = False,
    ):
        self.conn = conn
        self.env = env
        self.temp_dir = temp_dir
        self.engine = engine
        self.diag = diag
        self._hot = set(
            s["name"]
            for s in env.raw.get("rac_contention", {}).get("hot_segments", [])
        )

    def analyze(self, limit: int = 10) -> BatchReport:
        sql_ids = _fetch_top_sql_ids(self.conn, limit)
        if not sql_ids:
            print(
                "[batch] Nenhuma query encontrada no critério (última hora, "
                "avg_elapsed > 10 min). Tente ampliar a janela ou os thresholds.",
                file=sys.stderr,
            )

        if self.diag:
            print(
                f"[batch] {len(sql_ids)} SQL_ID(s) selecionados: {sql_ids}",
                file=sys.stderr,
            )

        results: list[QueryResult] = []
        for sql_id in sql_ids:
            result = self._analyze_one(sql_id)
            results.append(result)

        return BatchReport(
            total_queries=len(results),
            total_with_recommendations=sum(1 for r in results if r.recommendations),
            total_skipped=sum(1 for r in results if r.skipped),
            total_errors=sum(1 for r in results if r.error),
            results=results,
        )

    def _analyze_one(self, sql_id: str) -> QueryResult:
        result = QueryResult(sql_id=sql_id)

        # 1) SQL text
        sql_text = _fetch_sql_text(self.conn, sql_id)
        if not sql_text:
            result.skipped = True
            result.skip_reason = "SQL text não disponível em GV$SQLTEXT"
            return result
        result.sql_text = sql_text

        # 2) Plano
        plan_text, plan_format = _fetch_plan(self.conn, sql_id)
        if not plan_text:
            result.skipped = True
            result.skip_reason = "Plano não disponível (SQL fora do cursor pool / sem SQL Monitor)"
            return result
        result.plan_text = plan_text
        result.plan_format = plan_format

        # 3) Persiste no temp/
        sql_path, plan_path = _save_to_temp(
            self.temp_dir, sql_id, sql_text, plan_text, plan_format
        )
        result.sql_path = sql_path
        result.plan_path = plan_path

        # 4) Análise
        try:
            query = SqlParser().parse(sql_text)
            plan = parse_plan(plan_text)

            targets = [(t.owner, t.name) for t in query.tables]
            collector = OracleMetadataCollector(self.conn, self._hot)
            metadata = collector.collect(targets)

            plan_history = collect_plan_history(self.conn, sql_id)

            if self.diag:
                n = plan_history.distinct_count()
                print(
                    f"[batch][{sql_id}] planos distintos={n} "
                    f"tabelas={len(metadata.tables)}",
                    file=sys.stderr,
                )
                for t in metadata.tables:
                    idxs = metadata.indexes_of(t.name)
                    names = ", ".join(i.index_name for i in idxs) or "(nenhum)"
                    print(
                        f"  {t.owner}.{t.name}: rows={t.num_rows} "
                        f"stale={t.stale_stats} índices=[{names}]",
                        file=sys.stderr,
                    )
                missing = getattr(collector, "missing", [])
                if missing:
                    print(
                        f"  AVISO tabelas não coletadas: "
                        f"{[f'{o}.{n}' for o, n in missing]}",
                        file=sys.stderr,
                    )

            ctx = RuleContext(
                query=query,
                plan=plan,
                metadata=metadata,
                env=self.env,
                plan_history=plan_history,
            )
            recs = self.engine.run(ctx)
            recs = consolidate_indexes(recs)
            recs = merge_mitigation_warnings(recs)
            result.recommendations = recs

        except Exception as exc:
            log.exception("Erro ao analisar SQL_ID %s", sql_id)
            result.error = str(exc)

        return result
