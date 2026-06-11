"""
rule_base.py — Contrato entre o motor e as regras.

Este é o ponto de desacoplamento pedido: o motor (engine.py) só conhece
a classe abstrata `Rule` e o `RuleContext`. Cada regra vive em um arquivo
próprio em advisor/rules/ e é descoberta automaticamente. Para adicionar uma
regra, crie um arquivo com uma subclasse de Rule; para remover, apague o
arquivo. Nenhum outro módulo muda.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .env_profile import EnvProfile
from .models import ParsedPlan, ParsedQuery, Recommendation, SchemaMetadata


@dataclass(frozen=True)
class RuleContext:
    """
    Pacote imutável de tudo que uma regra pode inspecionar.
    Passado a cada regra; regras NÃO se comunicam entre si — só leem o contexto.
    """
    query: ParsedQuery
    plan: ParsedPlan
    metadata: SchemaMetadata
    env: EnvProfile

    # ---- helpers de conveniência reutilizados por várias regras ----------
    def avg_col_len(self, table_name: str, column: str) -> float:
        c = self.metadata.column(table_name, column)
        return float(c.avg_col_len) if c and c.avg_col_len else 8.0

    def is_table_hot(self, owner: str | None, table_name: str) -> bool:
        # quente se o AWR marcou OU se o coletor de metadados marcou
        meta = self.metadata.table(owner, table_name)
        if meta and meta.is_hot:
            return True
        return self.env.is_hot_segment(owner, table_name)

    def is_partitioned(self, owner: str | None, table_name: str) -> bool:
        """
        Decide se a tabela é particionada (→ índice LOCAL). Usa metadados se
        disponíveis; senão INFERE do plano: se o acesso à tabela está sob um
        PARTITION RANGE/LIST/HASH (ITERATOR/ALL/SINGLE), é particionada. Isso
        evita gerar índice sem LOCAL quando o coletor não trouxe a tabela.
        """
        meta = self.metadata.table(owner, table_name)
        if meta is not None:
            return meta.partitioned
        # inferência pelo plano: achar a operação que acessa esta tabela e ver
        # se algum ancestral é uma operação de partição
        by_id = self.plan.by_id()
        access_ids = [op.op_id for op in self.plan.operations
                      if op.object_name == table_name
                      or (op.object_name and op.object_name.startswith(table_name))]
        for aid in access_ids:
            node = by_id.get(aid)
            hops = 0
            while node is not None and hops < 6:
                if "PARTITION" in node.operation.upper():
                    return True
                node = by_id.get(node.parent_id) if node.parent_id is not None else None
                hops += 1
        return False


class Rule(ABC):
    """
    Interface mínima de uma regra. Cada regra declara um id estável e um
    método evaluate() que devolve zero ou mais recomendações.
    """

    #: identificador estável (usado em logs, allowlist/denylist e nos resultados)
    rule_id: str = "abstract"
    #: descrição curta da regra
    description: str = ""
    #: prioridade de execução (menor roda primeiro); útil se uma regra de
    #: mitigação quiser anexar avisos a índices propostos por outras.
    priority: int = 100

    @abstractmethod
    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        """Analisa o contexto e retorna recomendações (possivelmente vazias)."""
        raise NotImplementedError
