"""
rule_unused_existing_index.py — Regra R007.

Detecta o caso em que JÁ EXISTE um índice adequado para o probe de um join (as
colunas de igualdade do join são prefixo do índice), mas o plano NÃO o usa —
em vez disso faz TABLE ACCESS FULL na tabela ou usa outro caminho.

Isto é diferente de "falta índice" (R001/R002): aqui o índice existe e o
otimizador o ignora. As causas típicas, que a regra enumera como hipóteses
acionáveis:
  - estimativa de cardinalidade quebrada (ex.: dentro de um MERGE JOIN
    CARTESIAN, o otimizador acha que o full scan é mais barato);
  - estatísticas do índice/tabela desatualizadas;
  - índice INVISIBLE ou UNUSABLE;
  - conversão implícita de tipo / função na coluna anulando o índice;
  - skew de dados sem histograma adequado.

Não recomenda criar índice (ele existe). Emite diagnóstico + passos de
verificação. Prioridade baixa-numérica para aparecer junto ao contexto.
"""
from __future__ import annotations

from ..models import PredicateKind, Recommendation, Severity
from ..rule_base import Rule, RuleContext
from . import existing_index_covering


class UnusedExistingIndexRule(Rule):
    rule_id = "R007_unused_existing_index"
    description = "Índice adequado existe mas o otimizador não o usa"
    priority = 8

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []

        # tabelas que sofrem FULL SCAN no plano
        full_scan_tables = {op.object_name for op in ctx.plan.operations
                            if "TABLE ACCESS FULL" in op.operation.upper()
                            and op.object_name}
        if not full_scan_tables:
            return recs

        has_cartesian = any("CARTESIAN" in op.operation.upper()
                            for op in ctx.plan.operations)
        alias_map = ctx.query.alias_to_table()

        for alias, tref in alias_map.items():
            if tref.name not in full_scan_tables:
                continue
            # colunas de igualdade de join desta tabela
            eq_cols = [jp.left.column if jp.left.table_alias == alias else jp.right.column
                       for jp in ctx.query.join_predicates
                       if alias in (jp.left.table_alias, jp.right.table_alias)]
            eq_cols = list(dict.fromkeys(eq_cols))
            if not eq_cols:
                continue

            existing = existing_index_covering(ctx.metadata, tref.name, eq_cols)
            if not existing:
                continue  # não há índice adequado → é caso de R001/R002, não R007

            causes = self._hypotheses(ctx, existing, has_cartesian)
            recs.append(Recommendation(
                rule_id=self.rule_id,
                title=(f"Índice {existing.index_name} existe e serve ao join, "
                       f"mas {tref.name} sofre FULL SCAN"),
                severity=Severity.HIGH,
                rationale=(
                    f"As colunas de join ({', '.join(eq_cols)}) já são prefixo do "
                    f"índice {existing.index_name} ({', '.join(existing.columns)}), "
                    f"porém o otimizador escolheu TABLE ACCESS FULL em {tref.name}. "
                    f"Criar índice novo é desnecessário — o problema é o índice "
                    f"existente não estar sendo usado. Causas prováveis:\n      - "
                    + "\n      - ".join(causes)
                ),
                ddl=None,
                target_table=tref.name,
                estimated_benefit=0.0, estimated_maint_cost=0.0,
                tags=["unused-index", "access-path"],
                warnings=self._verifications(existing, tref),
            ))
        return recs

    def _hypotheses(self, ctx, existing, has_cartesian):
        h = []
        if has_cartesian:
            h.append("o plano contém MERGE JOIN CARTESIAN: a estimativa quebrada "
                     "faz o otimizador preferir full scan + cartesiano ao probe "
                     "indexado — corrija a estimativa (estatísticas) primeiro")
        h.append("estatísticas da tabela/índice ou das partições desatualizadas")
        h.append("índice INVISIBLE ou em estado UNUSABLE")
        h.append("conversão implícita de tipo ou função sobre a coluna de join "
                 "anulando o uso do índice")
        h.append("skew de dados sem histograma, levando a estimativa de "
                 "seletividade ruim")
        return h

    def _verifications(self, existing, tref):
        return [
            f"Verifique visibilidade/estado: "
            f"SELECT status, visibility FROM dba_indexes "
            f"WHERE index_name='{existing.index_name}';",
            f"Verifique idade das estatísticas: "
            f"SELECT last_analyzed, num_rows FROM dba_tables WHERE table_name='{tref.name}'; "
            f"e dba_ind_statistics para o índice.",
            f"Force o índice em teste para comparar custo: "
            f"SELECT /*+ INDEX(@... {existing.index_name}) */ ... e compare o plano.",
            "Se há MERGE JOIN CARTESIAN, recolha estatísticas das tabelas/partições "
            "ANTES de qualquer ação no índice — o cartesiano é a causa raiz provável.",
        ]
