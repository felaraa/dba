"""
validator.py — Fecha o loop "previsão -> medição" com índice INVISIBLE.

Para cada recomendação com DDL, opcionalmente:
  1) cria o índice como INVISIBLE (não afeta nenhum outro plano/sessão);
  2) na sessão, liga OPTIMIZER_USE_INVISIBLE_INDEXES=TRUE;
  3) executa a query com GATHER_PLAN_STATISTICS e captura A-Rows/Buffers;
  4) compara com a baseline (sem o índice);
  5) reporta ganho; deixa a decisão de tornar VISIBLE/DROP com o operador.

SEGURANÇA: índice invisível é a forma mais segura de testar em produção, pois
o otimizador só o enxerga na sessão que habilitou o parâmetro. Ainda assim, a
CRIAÇÃO de índice consome recursos (e, em tabela quente, gera redo) — por isso
o validador é OPT-IN (--validate) e nunca roda sem flag explícita.

Sem banco, este módulo não executa nada; é instanciado apenas quando há conexão.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from .models import Recommendation

log = logging.getLogger("advisor.validator")


@dataclass
class ValidationResult:
    rule_id: str
    ddl: str
    baseline_buffer_gets: Optional[float]
    candidate_buffer_gets: Optional[float]
    baseline_elapsed_s: Optional[float]
    candidate_elapsed_s: Optional[float]
    plan_changed: bool
    used_new_index: bool
    note: str = ""

    @property
    def gets_reduction_pct(self) -> Optional[float]:
        if not self.baseline_buffer_gets or self.candidate_buffer_gets is None:
            return None
        if self.baseline_buffer_gets == 0:
            return None
        return 100.0 * (1 - self.candidate_buffer_gets / self.baseline_buffer_gets)


class InvisibleIndexValidator:
    def __init__(self, connection):
        self.conn = connection

    def validate(self, rec: Recommendation, sql: str,
                 binds: dict) -> Optional[ValidationResult]:
        if not rec.ddl:
            return None
        cur = self.conn.cursor()
        index_name = self._index_name(rec.ddl)
        try:
            base_gets, base_elapsed, _ = self._measure(cur, sql, binds)

            invisible_ddl = self._as_invisible(rec.ddl)
            log.info("Criando índice invisível: %s", invisible_ddl)
            cur.execute(invisible_ddl)

            cur.execute("ALTER SESSION SET optimizer_use_invisible_indexes=TRUE")
            cand_gets, cand_elapsed, plan_text = self._measure(cur, sql, binds)
            cur.execute("ALTER SESSION SET optimizer_use_invisible_indexes=FALSE")

            used = index_name.upper() in (plan_text or "").upper()
            return ValidationResult(
                rule_id=rec.rule_id, ddl=rec.ddl,
                baseline_buffer_gets=base_gets, candidate_buffer_gets=cand_gets,
                baseline_elapsed_s=base_elapsed, candidate_elapsed_s=cand_elapsed,
                plan_changed=(cand_gets != base_gets), used_new_index=used,
                note=("Índice usado pelo otimizador." if used else
                      "Índice NÃO usado — otimizador preferiu outro caminho."),
            )
        finally:
            # limpeza: remove o índice de teste (sempre)
            try:
                cur.execute(f"DROP INDEX {index_name}")
                log.info("Índice de teste removido: %s", index_name)
            except Exception:
                log.warning("Falha ao remover índice de teste %s", index_name)
            cur.close()

    # ---- helpers ----
    def _measure(self, cur, sql, binds):
        hinted = sql.replace("select", "select /*+ GATHER_PLAN_STATISTICS */", 1)
        t0 = time.time()
        cur.execute(hinted, binds)
        cur.fetchall()
        elapsed = time.time() - t0
        rows = cur.execute(
            "SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(NULL,NULL,"
            "'ALLSTATS LAST'))").fetchall()
        plan_text = "\n".join(r[0] for r in rows if r and r[0])
        gets = self._extract_gets(plan_text)
        return gets, elapsed, plan_text

    @staticmethod
    def _extract_gets(plan_text):
        import re
        m = re.search(r"Buffers\s*\|", plan_text)
        # soma simples: pega o maior 'Buffers' (linha raiz). fallback None.
        nums = re.findall(r"(\d[\d,]*)\s*\|", plan_text)
        try:
            return max(float(n.replace(",", "")) for n in nums) if nums else None
        except ValueError:
            return None

    @staticmethod
    def _as_invisible(ddl: str) -> str:
        d = ddl.rstrip(";").rstrip()
        return d + " INVISIBLE"

    @staticmethod
    def _index_name(ddl: str) -> str:
        import re
        m = re.search(r"CREATE\s+INDEX\s+(\S+)", ddl, re.I)
        return m.group(1) if m else "UNKNOWN_IDX"
