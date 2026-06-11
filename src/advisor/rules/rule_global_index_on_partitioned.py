"""
rule_global_index_on_partitioned.py — Regra R008.

Audita índices GLOBAIS existentes sobre tabelas PARTICIONADAS envolvidas na
query. Um índice global em tabela particionada é dívida de manutenção: qualquer
operação de partição (DROP/TRUNCATE/EXCHANGE) invalida o índice inteiro
(status UNUSABLE), podendo degradar planos ou falhar DML conforme a config.

Não gera índice novo; emite alerta para o operador avaliar converter o índice
para LOCAL, quando a coluna líder e os acessos permitirem. Depende de o coletor
ter trazido os índices da tabela (modo --source db) com os flags partitioned/local.
"""
from __future__ import annotations

from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext


class GlobalIndexOnPartitionedRule(Rule):
    rule_id = "R008_global_index_on_partitioned"
    description = "índice GLOBAL existente sobre tabela PARTICIONADA (dívida de manutenção)"
    priority = 40

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []

        for tref in ctx.query.tables:
            meta = ctx.metadata.table(tref.owner, tref.name)
            # só avalia tabelas comprovadamente particionadas (via metadados)
            if not meta or not meta.partitioned:
                continue

            for ix in ctx.metadata.indexes_of(tref.name):
                # global = índice não-local; em tabela particionada é o alvo
                if ix.local:
                    continue
                # ignora índices GERADOS PELO SISTEMA (funcionais/virtuais): nomes
                # IDX$$_/SYS_ ou cujas colunas são todas virtuais ocultas (SYS_NC%).
                # São backing de colunas funcionais/JSON, não decisões de design do
                # usuário — aconselhar "converter para LOCAL" aqui só gera ruído.
                if self._is_system_generated(ix):
                    continue
                recs.append(Recommendation(
                    rule_id=self.rule_id,
                    title=(f"Índice GLOBAL {ix.index_name} sobre tabela particionada "
                           f"{tref.name}"),
                    severity=Severity.MEDIUM,
                    rationale=(
                        f"O índice {ix.index_name} ({', '.join(ix.columns)}) é GLOBAL "
                        f"sobre {tref.name}, que é particionada. Índice global em "
                        f"tabela particionada é dívida de manutenção: operações de "
                        f"partição (DROP/TRUNCATE/EXCHANGE) o invalidam por inteiro "
                        f"(status UNUSABLE), o que pode degradar planos ou falhar DML. "
                        f"Avalie converter para LOCAL se a coluna líder e os padrões "
                        f"de acesso permitirem (índices únicos exigem que a chave de "
                        f"partição faça parte do índice para serem LOCAL)."
                    ),
                    ddl=None,
                    target_table=tref.name,
                    estimated_benefit=0.0, estimated_maint_cost=0.0,
                    tags=["global-index", "partitioned", "maintenance-debt"],
                    warnings=[
                        f"Verifique o status atual e a unicidade antes de converter: "
                        f"SELECT status, uniqueness FROM dba_indexes "
                        f"WHERE index_name='{ix.index_name}'; "
                        f"Se UNIQUE, a chave de partição da tabela precisa estar nas "
                        f"colunas do índice para que ele possa ser LOCAL.",
                    ],
                ))
        return recs

    @staticmethod
    def _is_system_generated(ix) -> bool:
        name = (ix.index_name or "").upper()
        if name.startswith(("IDX$$", "SYS_IL", "SYS_IOT", "SYS_C00")):
            return True
        cols = [c.upper() for c in ix.columns]
        # todas as colunas são virtuais ocultas (function-based / JSON)
        return bool(cols) and all(c.startswith("SYS_NC") for c in cols)
