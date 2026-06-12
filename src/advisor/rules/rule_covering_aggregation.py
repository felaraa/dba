"""
rule_covering_aggregation.py — Regra R003.

Detecta TABLE ACCESS BY [LOCAL/GLOBAL] INDEX ROWID com leitura significativa
cujo único propósito é buscar colunas de SELECT/agregação não presentes no
índice usado. Propõe estender o índice de acesso com as colunas leves de
projeção/agregação (cobertura), eliminando o salto à tabela.

No caso real: id 7 fazia 69MB / 8.813 reqs para buscar OBJECT/LINKNO/
GRANULARITYPERIOD sobre 4M de linhas. GRANULARITYPERIOD tem 2 distintos
(trivial de cobrir). A regra prioriza cobrir colunas estreitas.
"""
from __future__ import annotations

from ..models import PredicateKind, Recommendation, Severity
from ..rule_base import Rule, RuleContext
from . import build_index_name, build_index_ddl, covering_cost, order_columns


class CoveringAggregationRule(Rule):
    rule_id = "R003_covering_for_aggregation"
    description = "TABLE ACCESS BY ROWID custoso só para projeção/agregação"
    priority = 30

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []
        for op in ctx.plan.operations:
            if "BY" not in op.operation.upper() or "ROWID" not in op.operation.upper():
                continue
            # custo relevante? muitos bytes lidos ou muitas linhas
            heavy_bytes = (op.read_bytes or 0) > 10 * 1024 * 1024
            heavy_rows = (op.actual_rows or 0) > 1_000_000
            heavy = heavy_bytes or heavy_rows
            if not heavy:
                continue
            target = self._match(ctx, op.object_name)
            if target is None:
                continue
            owner, table_name, alias = target

            # colunas range (chave de partição/filtro) + join + projeção leve
            range_cols = [fp.column.column for fp in ctx.query.filter_predicates
                          if fp.column.table_alias == alias and fp.kind == PredicateKind.RANGE]
            eq_cols = [jp.left.column if jp.left.table_alias == alias else jp.right.column
                       for jp in ctx.query.join_predicates
                       if alias in (jp.left.table_alias, jp.right.table_alias)]
            eq_cols = list(dict.fromkeys(eq_cols))
            proj = [c.column for c in ctx.query.projected_columns
                    if c.table_alias == alias]
            proj = [c for c in dict.fromkeys(proj) if c not in eq_cols + range_cols]

            col_len = {c: ctx.avg_col_len(table_name, c) for c in proj}
            # só cobre colunas estreitas; descarta as largas
            covering = [c for c in proj if col_len.get(c, 8) <= ctx.env.wide_column_bytes]
            if not covering:
                continue

            cols = order_columns(range_cols, eq_cols, covering)
            idx_name = build_index_name(table_name, cols, suffix="C", owner=owner)
            local = ctx.is_partitioned(owner, table_name)
            ddl = build_index_ddl(owner, table_name, idx_name, cols, local,
                                  parallel=ctx.env.index_parallel,
                                  tablespace=ctx.env.index_tablespace)

            hot = ctx.is_table_hot(owner, table_name)
            cov_cost = covering_cost(ctx.env, col_len, covering)
            maint = ((ctx.env.score("maint_cost_hot_table") if hot
                      else ctx.env.score("maint_cost_cold_table")) + cov_cost)

            recs.append(Recommendation(
                rule_id=self.rule_id,
                title=f"Cobertura em {table_name} para evitar table access by rowid",
                severity=Severity.MEDIUM,
                rationale=(
                    (f"Operação id {op.op_id} lê {(op.read_bytes or 0)/1024/1024:,.0f}MB "
                     f"da tabela" if heavy_bytes else
                     f"Operação id {op.op_id} percorre {op.actual_rows:,.0f} linhas da tabela")
                    + f" apenas para obter {', '.join(covering)}. Incluí-las no "
                    f"índice de acesso elimina o salto à tabela. Colunas largas foram "
                    f"deliberadamente excluídas da cobertura para conter o tamanho do índice."
                ),
                ddl=ddl,
                target_table=table_name,
                estimated_benefit=0.45,
                estimated_maint_cost=maint,
                tags=["covering", "aggregation"],
            ))
        return recs

    def _match(self, ctx: RuleContext, object_name: str | None):
        if not object_name:
            return None
        for t in ctx.query.tables:
            if t.name == object_name:
                return (t.owner, t.name, t.alias)
        return None
