"""
rule_massive_rowid_access.py — Regra R011.

Detecta TABLE ACCESS BY [LOCAL] INDEX ROWID [BATCHED] que devolve um volume
MASSIVO de linhas numa única passagem (poucas Execs) — ou seja, o otimizador usou
um índice para buscar, linha a linha (ROWID), uma fração enorme da tabela. Para
esse volume o índice é o caminho ERRADO: cada linha vira um acesso quase
aleatório (db file sequential/parallel read, e em RAC gc cr block), enquanto um
FULL SCAN da partição leria o mesmo dado em blocos contíguos (multibloco), muito
mais barato.

É o inverso da R002 (que troca full scan por índice). Aqui queremos o oposto:
trocar o índice por full/partition scan. A causa quase sempre é a mesma da R004 —
estimativa colapsada (E-Rows≈1): achando que processa "1 linha", o otimizador
prefere o índice. No caso real (MERGE 86kwg7rukwx07) o TABLE ACCESS BY LOCAL
INDEX ROWID de F_R4G_ADJL (id 8) devolveu 389 milhões de linhas via PK por
TIME_KEY, gerando ~5M requisições de I/O.

A recomendação NÃO é índice — é recolher estatística (para o otimizador escolher
full scan), e/ou forçar FULL + PARALLEL no caminho de varredura.
"""
from __future__ import annotations

from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext


# acima disto, buscar por ROWID é caro demais vs. um full/partition scan
_MASSIVE_ROWS = 5_000_000
# acima disto a severidade sobe (varredura claramente equivocada)
_HIGH_ROWS = 50_000_000
# se a operação tem MUITAS Execs, é provavelmente o lado interno de um NESTED
# LOOPS (domínio da R001) — não é o caso de "uma varredura única massiva"
_MAX_EXECS_SINGLE = 4


class MassiveRowidAccessRule(Rule):
    rule_id = "R011_massive_rowid_access"
    description = "TABLE ACCESS BY INDEX ROWID de volume massivo (deveria ser full scan)"
    priority = 7  # contexto/diagnóstico: precede as regras que geram índice

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []

        for op in ctx.plan.operations:
            up = op.operation.upper()
            if "TABLE ACCESS" not in up or "INDEX ROWID" not in up:
                continue
            rows = op.actual_rows
            if rows is None or rows < _MASSIVE_ROWS:
                continue
            # exclui o lado interno de um NESTED LOOPS (muitas Execs) → é R001
            if op.executions is not None and op.executions > _MAX_EXECS_SINGLE:
                continue

            table = op.object_name or "(tabela)"
            owner = op.object_owner or ctx.resolve_owner(table)
            partitioned = ctx.is_partitioned(owner, table)
            sev = Severity.HIGH if rows >= _HIGH_ROWS else Severity.MEDIUM

            # a divergência de estimativa que levou o otimizador ao índice
            mis = ""
            if op.estim_rows is not None and op.estim_rows > 0 and rows / op.estim_rows >= 1000:
                mis = (f" O otimizador estimou apenas {op.estim_rows:,.0f} linha(s) "
                       f"(E-Rows) — por isso escolheu o índice; corrigir a estatística "
                       f"deve, sozinho, virar o plano para full scan.")

            scan = ("FULL SCAN da partição (já há pruning por PARTITION RANGE)"
                    if partitioned else "FULL SCAN da tabela")
            recs.append(Recommendation(
                rule_id=self.rule_id,
                title=(f"Acesso por ROWID devolvendo {rows:,.0f} linhas em "
                       f"{table} — deveria ser full scan"),
                severity=sev,
                rationale=(
                    f"A operação id {op.op_id} ({op.operation}) devolveu "
                    f"{rows:,.0f} linhas de {table} buscando-as por ROWID via índice. "
                    f"Para esse volume o índice é o caminho errado: cada linha é um "
                    f"acesso quase aleatório (single/parallel read; em RAC, gc cr "
                    f"block), enquanto um {scan} leria o mesmo dado em blocos "
                    f"contíguos com leitura multibloco — muito mais barato em ambiente "
                    f"não-Exadata e CPU/IO-bound.{mis}"
                ),
                ddl=None,
                target_table=table,
                estimated_benefit=0.0, estimated_maint_cost=0.0,
                tags=["full-scan", "rowid", "access-path", "statistics"],
                warnings=[
                    self._gather_stmt(owner, table, ctx.env.index_parallel, partitioned),
                    f"Como mitigação imediata, force a varredura: hint FULL(\"{table}\") "
                    f"(e PARALLEL) no bloco do SELECT, e habilite 'ALTER SESSION ENABLE "
                    f"PARALLEL DML;' se for DML — assim a varredura usa leitura "
                    f"multibloco em paralelo em vez de ROWID serial.",
                ],
            ))
        return recs

    @staticmethod
    def _gather_stmt(owner: str | None, table: str, degree: int | None,
                     partitioned: bool) -> str:
        """GATHER_TABLE_STATS para destravar o full scan; granularity AUTO cobre
        a partição recém-carregada (causa típica do E-Rows=1)."""
        own = owner or "<OWNER>"
        degree_val = str(degree) if degree else "DBMS_STATS.AUTO_DEGREE"
        extra = (" — em tabela particionada, recolha a partição do dia "
                 "(granularity AUTO já cobre)." if partitioned else "")
        return (
            f"Recolha estatística para o otimizador escolher full scan:\n"
            f"        EXEC DBMS_STATS.GATHER_TABLE_STATS(ownname=> '{own}', "
            f"tabname=> '{table}', estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE, "
            "method_opt=> 'FOR ALL COLUMNS SIZE AUTO', granularity=> 'AUTO', "
            f"degree=> {degree_val}, cascade=> TRUE, options=> 'GATHER AUTO', "
            f"force=> TRUE);{extra}"
        )
