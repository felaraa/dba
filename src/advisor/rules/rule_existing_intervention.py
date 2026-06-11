"""
rule_existing_intervention.py — Regra R005.

Detecta intervenções de tuning já presentes no plano: SQL Profile, SQL Plan
Baseline ou Stored Outline. Isso muda toda a estratégia:

  - Um índice novo pode não ser usado se um SQL Profile/baseline fixa o plano
    atual (o otimizador pode ignorar o índice por causa da intervenção).
  - Um SQL Profile com prefixo 'coe_' indica uso do script coe_xfr (SQL Tuning
    Advisor / suporte Oracle) — ou seja, alguém já tentou corrigir esta query.
    Se o plano ainda está ruim, o profile pode estar OBSOLETO após mudança de
    dados/estatísticas e precisa ser reavaliado ou removido.

Não gera índice; gera um alerta de alta prioridade para o operador considerar a
intervenção existente ANTES de aplicar qualquer recomendação de índice.
"""
from __future__ import annotations

from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext


class ExistingInterventionRule(Rule):
    rule_id = "R005_existing_intervention"
    description = "SQL Profile / Baseline / Outline já aplicado ao plano"
    priority = 1  # roda primeiro: contextualiza tudo o que vem depois

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        plan = ctx.plan
        if not plan.notes and not plan.sql_profile:
            return []

        is_coe = bool(plan.sql_profile and plan.sql_profile.lower().find("coe_") >= 0)
        warnings = [
            "Um índice recomendado pode NÃO ser usado enquanto a intervenção fixar "
            "o plano atual. Valide o índice como INVISIBLE e verifique se o "
            "otimizador o adota mesmo com a intervenção ativa.",
        ]
        if is_coe:
            warnings.append(
                "O SQL Profile tem prefixo 'coe_' (gerado via coe_xfr / SQL Tuning "
                "Advisor). Se o plano ainda está ruim, este profile pode estar "
                "obsoleto após mudança de dados/estatísticas — reavalie ou remova "
                "(DBMS_SQLTUNE.DROP_SQL_PROFILE) e recolha estatísticas antes de "
                "decidir por índice."
            )

        return [Recommendation(
            rule_id=self.rule_id,
            title="Intervenção de tuning já ativa neste plano",
            severity=Severity.HIGH,
            rationale=(
                "Detectada(s) intervenção(ões): " + "; ".join(plan.notes) +
                ". Isso altera a estratégia: o plano atual pode estar sendo "
                "forçado por essa intervenção, e recomendações de índice precisam "
                "ser validadas nesse contexto."
            ),
            ddl=None, target_table=None,
            estimated_benefit=0.0, estimated_maint_cost=0.0,
            tags=["sql-profile", "baseline", "intervention"],
            warnings=warnings,
        )]
