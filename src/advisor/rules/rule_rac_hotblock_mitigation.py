"""
rule_rac_hotblock_mitigation.py — Regra R900 (pós-processamento / mitigação).

Roda com prioridade ALTA-numérica (depois das que geram índices) e inspeciona
as recomendações já produzidas no contexto? Não — regras não veem a saída umas
das outras por contrato. Em vez disso, esta regra emite recomendações de
MITIGAÇÃO independentes quando o ambiente exibe o padrão de contenção e a query
alvo tem índice proposto sobre tabela quente liderado por coluna crescente.

Como o contrato mantém as regras isoladas, esta regra reanalisa o mesmo
gatilho (índice liderado por coluna de range/crescente em tabela quente) e
produz um alerta acionável. O orquestrador (cli) faz o merge dos warnings nas
recomendações de índice correspondentes pelo target_table.

Justificativa pelo AWR RAWDB: 'enq: TX - index contention' no top 10 e índices
de chave sequencial dominando Buffer Busy Waits. Logo, qualquer índice novo
liderado por coluna crescente (timestamp/sequence) em tabela de alto DML
reproduz esse padrão.
"""
from __future__ import annotations

from ..models import PredicateKind, Recommendation, Severity
from ..rule_base import Rule, RuleContext


# heurística simples: colunas cujo nome sugere valor crescente/monotônico
_MONOTONIC_HINTS = ("TIME", "DATE", "SEQ", "ID", "TS", "TIMESTAMP")


class RacHotblockMitigationRule(Rule):
    rule_id = "R900_rac_hotblock_mitigation"
    description = "Mitigação de hot leaf block em RAC para índice de chave crescente"
    priority = 900  # roda por último

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        if not (ctx.env.index_contention_present
                and ctx.env.sequential_hotblock_observed):
            return []  # ambiente sem o padrão → nada a mitigar

        recs: list[Recommendation] = []
        alias_map = ctx.query.alias_to_table()

        for alias, table in alias_map.items():
            if not ctx.is_table_hot(table.owner, table.name):
                continue
            # a tabela quente seria indexada por uma coluna de range/crescente?
            range_cols = [fp.column.column for fp in ctx.query.filter_predicates
                          if fp.column.table_alias == alias
                          and fp.kind == PredicateKind.RANGE]
            leading_monotonic = [c for c in range_cols
                                 if any(h in c.upper() for h in _MONOTONIC_HINTS)]
            if not leading_monotonic:
                continue

            col = leading_monotonic[0]
            recs.append(Recommendation(
                rule_id=self.rule_id,
                title=f"Mitigar hot block em índice de {table.name} liderado por {col}",
                severity=Severity.HIGH,
                rationale=(
                    f"O ambiente {ctx.env.name} já apresenta 'enq: TX - index "
                    f"contention' no top de eventos e índices de chave sequencial "
                    f"dominando Buffer Busy Waits. Um índice em {table.name} liderado "
                    f"por {col} (coluna crescente) sobre tabela de alto DML reproduz "
                    f"esse padrão de hot leaf block entre as {ctx.env.raw['identity']['rac_nodes']} "
                    f"instâncias RAC."
                ),
                ddl=None,  # não é índice; é orientação de como criá-lo
                target_table=table.name,
                estimated_benefit=0.0,
                estimated_maint_cost=0.0,
                tags=["rac", "mitigation", "hot-block"],
                warnings=[
                    f"Ao criar índice liderado por {col} em {table.name}, mitigue a "
                    f"contenção de leaf block: (a) considere índice GLOBAL com "
                    f"particionamento HASH nas colunas de probe, ou (b) eleve INITRANS "
                    f"do índice (ex.: INITRANS 8) e ajuste PCTFREE, ou (c) se a query "
                    f"permitir, lidere o índice por uma coluna de igualdade mais "
                    f"distribuída em vez da coluna crescente.",
                ],
            ))
        return recs
