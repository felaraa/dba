"""
rule_filter_should_be_access.py — Regra R001.

Detecta o padrão que matou a query alvo: uma operação de TABLE ACCESS BY ROWID
(ou INDEX) em que o predicado de JOIN aparece como `filter` em vez de `access`,
combinada com explosão de linhas (A-Rows/Execs >> linhas finais). É o sintoma
de "falta um índice cuja coluna líder seja a coluna de join (igualdade)".

No caso real: k era acessada pela PK (STARTTIME) e `a.OBJECT = k.NE_NAME` era
aplicado como filtro pós-acesso → 609M linhas. A correção é um índice
(NE_NAME, STARTTIME) que transforma o filtro em probe direto.
"""
from __future__ import annotations

from ..models import (PredicateKind, Recommendation, Severity)
from ..rule_base import Rule, RuleContext
from . import build_index_name, build_index_ddl, covering_cost, order_columns


class FilterShouldBeAccessRule(Rule):
    rule_id = "R001_filter_should_be_access"
    description = "Predicado de join aplicado como filtro pós-acesso (índice de probe ausente)"
    priority = 10

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []
        if not ctx.plan.has_runtime_stats():
            return recs  # precisa de A-Rows para confirmar a explosão

        explosion_factor = ctx.env.nl_explosion_factor
        final_rows = ctx.plan.operations[0].actual_rows or 1
        by_id = ctx.plan.by_id()
        children = self._children_map(ctx)

        for op in ctx.plan.operations:
            # interessa onde há predicado de filtro de igualdade entre colunas
            join_filters = [p for p in op.filter_predicates if "=" in p and "." in p]
            if not join_filters:
                continue

            # A explosão de trabalho em NESTED LOOPS manifesta-se como um número
            # de EXECUÇÕES altíssimo na operação que carrega o filtro (a op é
            # executada uma vez por linha vinda do lado externo), ou como A-Rows
            # alto na própria op / em um filho INDEX. Tomamos o máximo desses
            # sinais como o "trabalho desperdiçado".
            candidate_rows = [op.actual_rows or 0, op.executions or 0]
            for child in children.get(op.op_id, []):
                if child.actual_rows is not None:
                    candidate_rows.append(child.actual_rows)
            if op.parent_id is not None:
                for sib in children.get(op.parent_id, []):
                    if sib.op_id != op.op_id and sib.actual_rows is not None:
                        candidate_rows.append(sib.actual_rows)
            work_rows = max(candidate_rows)
            if work_rows < final_rows * explosion_factor:
                continue

            # identifica a tabela alvo e as colunas de join/filtro a indexar
            target = self._match_table(ctx, op.object_name)
            if target is None:
                continue
            owner, table_name, alias = target

            eq_cols = self._equality_join_cols(ctx, alias)
            range_cols = self._range_filter_cols(ctx, alias)
            if not eq_cols:
                continue

            cols = order_columns(eq_cols, range_cols, covering=[])
            idx_name = build_index_name(table_name, cols, owner=owner)
            local = ctx.is_partitioned(owner, table_name)

            # Já existe índice que serve para probe liderado por estas colunas?
            from . import existing_index_covering
            existing = existing_index_covering(ctx.metadata, table_name, eq_cols)
            if existing:
                continue  # índice adequado já existe → não recomendar (ver R007)

            ddl = build_index_ddl(owner, table_name, idx_name, cols, local)

            # benefício: proporcional ao trabalho desperdiçado (work_rows vs
            # resultado final). Em ambiente CPU-bound, linhas processadas a menos
            # é o ganho direto.
            ratio = work_rows / max(final_rows, 1)
            benefit = min(1.0, 0.6 + ratio / (explosion_factor * 50))
            hot = ctx.is_table_hot(owner, table_name)
            maint = (ctx.env.score("maint_cost_hot_table") if hot
                     else ctx.env.score("maint_cost_cold_table"))

            recs.append(Recommendation(
                rule_id=self.rule_id,
                title=f"Índice de probe em {table_name} para eliminar filtro pós-acesso",
                severity=Severity.CRITICAL,
                rationale=(
                    f"O join {join_filters[0]} é aplicado como FILTRO (id {op.op_id}) "
                    f"após um acesso que percorre ~{work_rows:,.0f} linhas, contra "
                    f"apenas {final_rows:,.0f} no resultado final — desperdício de "
                    f"~{ratio:,.0f}x. Existe índice em {table_name} liderado por outra "
                    f"coluna (ex.: chave de partição), o que leva o otimizador a varrer "
                    f"e filtrar. Um índice liderado por {cols[0]} transforma o filtro "
                    f"em probe direto."
                ),
                ddl=ddl,
                target_table=table_name,
                estimated_benefit=benefit,
                estimated_maint_cost=maint,
                tags=["join", "access-path", "nested-loops"],
            ))
        return recs

    @staticmethod
    def _children_map(ctx: RuleContext) -> dict[int, list]:
        m: dict[int, list] = {}
        for op in ctx.plan.operations:
            if op.parent_id is not None:
                m.setdefault(op.parent_id, []).append(op)
        return m

    # ---- helpers internos da regra --------------------------------------
    def _match_table(self, ctx: RuleContext, object_name: str | None):
        """Liga o nome do objeto do plano (tabela ou índice) a uma TableRef."""
        if not object_name:
            return None
        for t in ctx.query.tables:
            if t.name == object_name:
                return (t.owner, t.name, t.alias)
        # objeto pode ser um índice; tenta casar pelo dono via metadados
        for idx in ctx.metadata.indexes:
            if idx.index_name == object_name:
                for t in ctx.query.tables:
                    if t.name == idx.table_name:
                        return (t.owner, t.name, t.alias)
        return None

    def _equality_join_cols(self, ctx: RuleContext, alias: str) -> list[str]:
        cols: list[str] = []
        for jp in ctx.query.join_predicates:
            if jp.left.table_alias == alias:
                cols.append(jp.left.column)
            elif jp.right.table_alias == alias:
                cols.append(jp.right.column)
        # dedup preservando ordem
        seen, out = set(), []
        for c in cols:
            if c not in seen:
                seen.add(c); out.append(c)
        return out

    def _range_filter_cols(self, ctx: RuleContext, alias: str) -> list[str]:
        return [fp.column.column for fp in ctx.query.filter_predicates
                if fp.column.table_alias == alias and fp.kind == PredicateKind.RANGE]
