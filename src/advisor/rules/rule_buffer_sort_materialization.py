"""
rule_buffer_sort_materialization.py — Regra R006.

Detecta BUFFER SORT (ou SORT JOIN alimentando MERGE JOIN) que materializa um
volume grande de linhas em memória/temp para servir a um join — tipicamente o
lado interno de um MERGE JOIN [CARTESIAN]. Quando o volume é alto, isso indica
que falta um caminho de acesso indexado que permitiria um NESTED LOOPS/HASH
seletivo em vez de materializar tudo.

No caso real: BUFFER SORT (id 8) materializou ~3,99M linhas de
ENR_RADIO_4G_HUA_X2INTERFACE para alimentar um MERGE JOIN CARTESIAN. Um índice
nas colunas de join dessa tabela (ENODEB_NAME, INTERFACEID) permitiria probe
direto e evitaria a materialização.

A regra propõe índice de probe na tabela materializada, com cobertura leve das
colunas projetadas se forem estreitas.
"""
from __future__ import annotations

from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext
from . import build_index_name, build_index_ddl, covering_cost, order_columns


_MATERIALIZE_OPS = ("BUFFER SORT", "SORT JOIN")
_MIN_ROWS = 100_000  # abaixo disto, materializar é barato; não vale índice


class BufferSortMaterializationRule(Rule):
    rule_id = "R006_buffer_sort_materialization"
    description = "BUFFER SORT/SORT JOIN materializa muitas linhas para um join"
    priority = 25

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []
        children = self._children_map(ctx)

        for op in ctx.plan.operations:
            if not any(m in op.operation.upper() for m in _MATERIALIZE_OPS):
                continue
            if (op.actual_rows or 0) < _MIN_ROWS:
                continue

            # a tabela materializada é o objeto do filho TABLE ACCESS do BUFFER SORT
            child_table = self._child_table(ctx, children, op.op_id)
            if child_table is None:
                continue
            owner, table_name, alias = child_table

            eq_cols = [jp.left.column if jp.left.table_alias == alias else jp.right.column
                       for jp in ctx.query.join_predicates
                       if alias in (jp.left.table_alias, jp.right.table_alias)]
            eq_cols = list(dict.fromkeys(eq_cols))
            if not eq_cols:
                continue

            from . import existing_index_covering
            if existing_index_covering(ctx.metadata, table_name, eq_cols):
                continue

            proj = [c.column for c in ctx.query.projected_columns
                    if c.table_alias == alias]
            proj = [c for c in dict.fromkeys(proj) if c not in eq_cols]
            col_len = {c: ctx.avg_col_len(table_name, c) for c in eq_cols + proj}
            cov_cost = covering_cost(ctx.env, col_len, proj)
            covering = proj if cov_cost < 0.4 else []

            cols = order_columns(eq_cols, [], covering)
            idx_name = build_index_name(table_name, cols, owner=owner)
            local = ctx.is_partitioned(owner, table_name)
            ddl = build_index_ddl(owner, table_name, idx_name, cols, local)

            hot = ctx.is_table_hot(owner, table_name)
            maint = ((ctx.env.score("maint_cost_hot_table") if hot
                      else ctx.env.score("maint_cost_cold_table"))
                     + (cov_cost if covering else 0.0))

            recs.append(Recommendation(
                rule_id=self.rule_id,
                title=f"Índice em {table_name} para evitar materialização (BUFFER SORT)",
                severity=Severity.HIGH,
                rationale=(
                    f"A operação id {op.op_id} ({op.operation}) materializa "
                    f"{op.actual_rows:,.0f} linhas de {table_name} para alimentar um "
                    f"join. Um índice nas colunas de join ({', '.join(eq_cols)}) "
                    f"permite probe direto e evita materializar a tabela inteira — "
                    f"especialmente relevante quando o join vizinho é um MERGE JOIN "
                    f"ou CARTESIAN."
                ),
                ddl=ddl,
                target_table=table_name,
                estimated_benefit=0.55,
                estimated_maint_cost=maint,
                tags=["buffer-sort", "materialization", "join"],
            ))
        return recs

    @staticmethod
    def _children_map(ctx: RuleContext) -> dict[int, list]:
        m: dict[int, list] = {}
        for op in ctx.plan.operations:
            if op.parent_id is not None:
                m.setdefault(op.parent_id, []).append(op)
        return m

    def _child_table(self, ctx, children, op_id):
        """Desce a árvore a partir do BUFFER SORT até achar um TABLE ACCESS."""
        stack = list(children.get(op_id, []))
        while stack:
            node = stack.pop()
            if node.object_name:
                for t in ctx.query.tables:
                    if t.name == node.object_name:
                        return (t.owner, t.name, t.alias)
            stack.extend(children.get(node.op_id, []))
        return None
