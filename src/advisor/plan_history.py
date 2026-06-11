"""
plan_history.py — Coleta o histórico de planos de um SQL_ID.

O resto do advisor analisa UM plano (o do arquivo). Este módulo responde a
outra pergunta: "quantos planos DIFERENTES o otimizador já escolheu para este
SQL_ID, e qual deles é o melhor?". Uma query com vários plan_hash_value sofre
de INSTABILIDADE DE PLANO; basta um plano ruim entrar em cena para degradar o
serviço (o caso clássico no RAWDB: cardinality feedback / bind peeking trocando
o plano de uma query quente).

Duas fontes, fundidas por plan_hash_value:
  1) GV$SQL  — cursores vivos no shared pool de TODOS os nós do RAC (por isso
     GV$, não V$): executions, elapsed_time, buffer_gets, cpu_time, rows.
  2) DBA_HIST_SQLSTAT — histórico do AWR (deltas por snapshot). Requer
     Diagnostics Pack; se não houver acesso, é silenciosamente ignorado.

Tudo é defensivo: qualquer falha de view/privilégio retorna o que já foi
coletado, nunca derruba o pipeline. As médias são calculadas por execução a
partir dos totais, para comparar planos com volumes de execução distintos.
"""
from __future__ import annotations

import logging
from typing import Optional

from .models import PlanHistory, PlanStat

log = logging.getLogger("advisor.plan_history")

# microssegundos -> segundos (elapsed_time/cpu_time em Oracle vêm em µs)
_US = 1_000_000.0


class _Acc:
    """Acumulador de totais por plan_hash, fundindo cursor + AWR."""
    __slots__ = ("execs", "elapsed_us", "buffer_gets", "cpu_us", "rows",
                 "sources", "first_seen", "last_seen")

    def __init__(self) -> None:
        self.execs = 0.0
        self.elapsed_us = 0.0
        self.buffer_gets = 0.0
        self.cpu_us = 0.0
        self.rows = 0.0
        self.sources: set[str] = set()
        self.first_seen: Optional[str] = None
        self.last_seen: Optional[str] = None

    def add(self, source, execs, elapsed_us, gets, cpu_us, rows, first, last):
        self.sources.add(source)
        self.execs += float(execs or 0)
        self.elapsed_us += float(elapsed_us or 0)
        self.buffer_gets += float(gets or 0)
        self.cpu_us += float(cpu_us or 0)
        self.rows += float(rows or 0)
        if first and (self.first_seen is None or first < self.first_seen):
            self.first_seen = first
        if last and (self.last_seen is None or last > self.last_seen):
            self.last_seen = last

    def to_stat(self, plan_hash: str) -> PlanStat:
        n = self.execs or 1.0  # evita divisão por zero; execs=0 vira médias brutas
        per = (lambda total: total / n) if self.execs else (lambda total: None)
        return PlanStat(
            plan_hash=plan_hash,
            sources=tuple(sorted(self.sources)),
            executions=self.execs,
            avg_elapsed_s=(self.elapsed_us / n / _US) if self.execs else None,
            avg_buffer_gets=per(self.buffer_gets),
            avg_cpu_s=(self.cpu_us / n / _US) if self.execs else None,
            avg_rows=per(self.rows),
            first_seen=self.first_seen,
            last_seen=self.last_seen,
        )


def collect_plan_history(connection, sql_id: Optional[str]) -> PlanHistory:
    """
    Retorna o PlanHistory do SQL_ID consolidando GV$SQL e DBA_HIST_SQLSTAT.
    Nunca lança: em erro/sem acesso, devolve o que conseguiu (possivelmente vazio).
    """
    if not sql_id:
        return PlanHistory(sql_id=None, plans=())

    acc: dict[str, _Acc] = {}
    cur = connection.cursor()
    try:
        _collect_cursor(cur, sql_id, acc)
        _collect_awr(cur, sql_id, acc)
    finally:
        try:
            cur.close()
        except Exception:
            pass

    plans = tuple(a.to_stat(ph) for ph, a in acc.items())
    # ordena por custo por execução (melhor primeiro), planos sem métrica ao fim
    plans = tuple(sorted(
        plans, key=lambda p: (p.cost_metric is None, p.cost_metric or 0.0)))
    return PlanHistory(sql_id=sql_id, plans=plans)


def _collect_cursor(cur, sql_id, acc) -> None:
    """GV$SQL: cursores vivos em todos os nós do RAC (ignora plan_hash 0)."""
    simple = """
        SELECT TO_CHAR(plan_hash_value) ph,
               SUM(executions), SUM(elapsed_time), SUM(buffer_gets),
               SUM(cpu_time), SUM(rows_processed),
               MIN(first_load_time), MAX(last_active_time)
        FROM gv$sql
        WHERE sql_id = :sid AND plan_hash_value > 0
        GROUP BY plan_hash_value
    """
    try:
        rows = cur.execute(simple, {"sid": sql_id}).fetchall()
    except Exception:
        log.debug("GV$SQL indisponível para %s", sql_id, exc_info=True)
        return
    for ph, ex, el, bg, cpu, rp, first, last in rows:
        acc.setdefault(ph, _Acc()).add(
            "cursor", ex, el, bg, cpu, rp,
            str(first) if first else None, str(last) if last else None)


def _collect_awr(cur, sql_id, acc) -> None:
    """DBA_HIST_SQLSTAT: deltas históricos (requer Diagnostics Pack)."""
    sql = """
        SELECT TO_CHAR(s.plan_hash_value),
               SUM(s.executions_delta), SUM(s.elapsed_time_delta),
               SUM(s.buffer_gets_delta), SUM(s.cpu_time_delta),
               SUM(s.rows_processed_delta),
               TO_CHAR(MIN(s.begin_interval_time), 'YYYY-MM-DD HH24:MI'),
               TO_CHAR(MAX(s.end_interval_time), 'YYYY-MM-DD HH24:MI')
        FROM dba_hist_sqlstat s
        JOIN dba_hist_snapshot sn
          ON sn.snap_id = s.snap_id AND sn.dbid = s.dbid
         AND sn.instance_number = s.instance_number
        WHERE s.sql_id = :sid AND s.plan_hash_value > 0
        GROUP BY s.plan_hash_value
    """
    try:
        rows = cur.execute(sql, {"sid": sql_id}).fetchall()
    except Exception:
        log.debug("DBA_HIST_SQLSTAT indisponível para %s (sem Diagnostics "
                  "Pack?)", sql_id, exc_info=True)
        return
    for ph, ex, el, bg, cpu, rp, first, last in rows:
        acc.setdefault(ph, _Acc()).add("awr", ex, el, bg, cpu, rp, first, last)
