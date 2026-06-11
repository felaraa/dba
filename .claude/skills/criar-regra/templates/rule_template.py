"""
rule_<nome>.py — Regra R0XX.

<Descreva em 2-4 linhas O QUE a regra detecta, POR QUE é um problema, e QUAL a
ação recomendada. Inclua um exemplo concreto se ajudar (ex.: "no caso real X,
a operação id N processava M linhas para retornar K").>
"""
from __future__ import annotations

from ..models import PredicateKind, Recommendation, Severity
from ..rule_base import Rule, RuleContext
# Importe os helpers SÓ se a regra gerar índice:
# from . import (build_index_name, build_index_ddl, order_columns,
#                covering_cost, existing_index_covering)


class NomeDaRegraRule(Rule):
    rule_id = "R0XX_nome_curto"
    description = "frase única do que detecta"
    priority = 50  # 1-9 contexto | 10-30 gera índice | 900+ mitigação

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []

        # 1) Pré-condições / gatilho. Ex.: precisa de A-Rows?
        # if not ctx.plan.has_runtime_stats():
        #     return recs

        # 2) Varra o plano / a query procurando o padrão-alvo.
        for op in ctx.plan.operations:
            # ... condição de disparo usando op.operation, op.actual_rows,
            #     op.executions, op.filter_predicates, etc. ...
            if not self._matches(op):
                continue

            # 3a) SE A REGRA APENAS DIAGNOSTICA (não gera índice):
            recs.append(Recommendation(
                rule_id=self.rule_id,
                title="título legível do achado",
                severity=Severity.HIGH,
                rationale="explicação em prosa, citando ids e números do plano.",
                ddl=None,
                target_table=None,
                estimated_benefit=0.0, estimated_maint_cost=0.0,
                tags=["categoria"],
                warnings=["ação recomendada / verificação no banco, se houver."],
            ))

            # 3b) SE A REGRA GERA ÍNDICE, descomente e siga as 5 convenções:
            # owner, table_name, alias = self._target(ctx, op.object_name)
            # eq_cols = self._equality_cols(ctx, alias)
            # if existing_index_covering(ctx.metadata, table_name, eq_cols):
            #     continue  # já existe índice adequado
            # cols = order_columns(eq_cols, range_cols=[], covering=[])
            # idx_name = build_index_name(table_name, cols, owner=owner)
            # local = ctx.is_partitioned(owner, table_name)
            # ddl = build_index_ddl(owner, table_name, idx_name, cols, local)
            # hot = ctx.is_table_hot(owner, table_name)
            # maint = (ctx.env.score("maint_cost_hot_table") if hot
            #          else ctx.env.score("maint_cost_cold_table"))
            # recs.append(Recommendation(
            #     rule_id=self.rule_id, title=..., severity=Severity.HIGH,
            #     rationale=..., ddl=ddl, target_table=table_name,
            #     estimated_benefit=0.6, estimated_maint_cost=maint, tags=[...]))

        return recs

    # ---- helpers internos da regra ----
    def _matches(self, op) -> bool:
        raise NotImplementedError
