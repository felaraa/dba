"""
rule_full_scan.py — Regra R002.

Detecta TABLE ACCESS FULL onde a tabela participa de um join por igualdade
e o join é seletivo (num_distinct alto vs num_rows). Propõe índice de probe,
opcionalmente com cobertura das colunas projetadas (se forem estreitas).

Em ambiente NÃO-Exadata (sem Smart Scan) e CPU-bound, trocar full scan por
probe indexado seletivo costuma compensar. A regra respeita o break-even:
se o resultado que dirige o join for grande, mantém o full scan (não recomenda).
"""
from __future__ import annotations

from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext
from . import build_index_name, build_index_ddl, covering_cost, order_columns


class FullScanRule(Rule):
    rule_id = "R002_avoidable_full_scan"
    description = "TABLE ACCESS FULL evitável por índice de join seletivo"
    priority = 20

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []
        for op in ctx.plan.operations:
            if "TABLE ACCESS FULL" not in op.operation.upper():
                continue
            target = self._match(ctx, op.object_name)
            if target is None:
                continue
            owner, table_name, alias = target

            eq_cols = [jp.left.column if jp.left.table_alias == alias else jp.right.column
                       for jp in ctx.query.join_predicates
                       if alias in (jp.left.table_alias, jp.right.table_alias)]
            eq_cols = list(dict.fromkeys(eq_cols))
            if not eq_cols:
                continue

            # já existe índice que serve para o probe? não recomendar duplicata
            from . import existing_index_covering
            if existing_index_covering(ctx.metadata, table_name, eq_cols):
                continue
            sel = self._selectivity(ctx, table_name, eq_cols[0])
            if sel is not None and sel < 0.01:
                # join pouco seletivo → full scan + hash provavelmente melhor
                continue

            # cobertura: colunas projetadas/agrupadas dessa tabela, se estreitas
            proj = [c.column for c in ctx.query.projected_columns
                    if c.table_alias == alias]
            proj += [c.column for c in ctx.query.group_by_columns
                     if c.table_alias == alias]
            proj = [c for c in dict.fromkeys(proj) if c not in eq_cols]
            col_len = {c: ctx.avg_col_len(table_name, c) for c in eq_cols + proj}

            cov_cost = covering_cost(ctx.env, col_len, proj)
            # só cobre se barato; senão índice magro
            covering = proj if cov_cost < 0.4 else []

            cols = order_columns(eq_cols, [], covering)
            idx_name = build_index_name(table_name, cols, owner=owner)
            local = ctx.is_partitioned(owner, table_name)
            ddl = build_index_ddl(owner, table_name, idx_name, cols, local,
                                  parallel=ctx.env.index_parallel,
                                  tablespace=ctx.env.index_tablespace)

            hot = ctx.is_table_hot(owner, table_name)
            maint = ((ctx.env.score("maint_cost_hot_table") if hot
                      else ctx.env.score("maint_cost_cold_table"))
                     + (cov_cost if covering else 0.0))

            recs.append(Recommendation(
                rule_id=self.rule_id,
                title=f"Índice para eliminar full scan em {table_name}",
                severity=Severity.HIGH,
                rationale=(
                    f"{table_name} sofre TABLE ACCESS FULL (id {op.op_id}) e participa "
                    f"de join por igualdade em {eq_cols[0]}. Seletividade estimada do "
                    f"join é alta, então probe indexado tende a vencer o full scan "
                    f"(ambiente não-Exadata, sem Smart Scan)."
                    + (f" Inclui cobertura de {', '.join(covering)} para evitar table "
                       f"access." if covering else "")
                ),
                ddl=ddl,
                target_table=table_name,
                estimated_benefit=0.6,
                estimated_maint_cost=maint,
                tags=["full-scan", "join", "covering" if covering else "lean"],
            ))
        return recs

    def _match(self, ctx: RuleContext, object_name: str | None):
        if not object_name:
            return None
        for t in ctx.query.tables:
            if t.name == object_name:
                return (ctx.resolve_owner(t.name, t.owner), t.name, t.alias)
        return None

    def _selectivity(self, ctx: RuleContext, table: str, col: str):
        cs = ctx.metadata.column(table, col)
        meta = ctx.metadata.table(None, table)
        if not cs or not cs.num_distinct or not meta or not meta.num_rows:
            return None
        return cs.num_distinct / meta.num_rows
