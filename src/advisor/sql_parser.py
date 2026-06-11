"""
sql_parser.py — Produz ParsedQuery a partir do texto SQL usando sqlglot.

Lida com o padrão da query alvo: subquery interna com joins na cláusula WHERE
(estilo Oracle "vírgula"), agregação e GROUP BY. Extrai:
  - tabelas e aliases (resolvendo owner.table)
  - predicados de join por igualdade entre colunas de tabelas distintas
  - predicados de filtro (range / igualdade / in) sobre coluna vs bind/literal
  - colunas projetadas e de GROUP BY, por alias

Robustez: o parser nunca lança para o chamador; se algo não casar, devolve o
que conseguiu extrair. Binds Oracle (:1, :3) são normalizados para sqlglot.
"""
from __future__ import annotations

import re
from typing import Optional

import sqlglot
from sqlglot import exp

from .models import (ColumnRef, FilterPredicate, JoinPredicate, ParsedQuery,
                     PredicateKind, TableRef)


def _normalize_binds(sql: str) -> str:
    """sqlglot entende :name; normaliza :1 -> :b1 para não quebrar o lexer."""
    return re.sub(r":(\d+)", r":b\1", sql)


def _split_owner(table_name: str) -> tuple[Optional[str], str]:
    if "." in table_name:
        owner, name = table_name.split(".", 1)
        return owner.upper(), name.upper()
    return None, table_name.upper()


class SqlParser:
    def parse(self, sql: str) -> ParsedQuery:
        norm = _normalize_binds(sql)
        tree = sqlglot.parse_one(norm, read="oracle")

        tables = self._extract_tables(tree)
        alias_set = {t.alias for t in tables}
        joins, filters = self._extract_predicates(tree, alias_set)
        projected, grouped = self._extract_projection(tree, alias_set)

        return ParsedQuery(
            raw_sql=sql,
            tables=tuple(tables),
            join_predicates=tuple(joins),
            filter_predicates=tuple(filters),
            projected_columns=tuple(projected),
            group_by_columns=tuple(grouped),
        )

    # ---- tabelas ---------------------------------------------------------
    def _extract_tables(self, tree: exp.Expression) -> list[TableRef]:
        seen: dict[str, TableRef] = {}
        for tbl in tree.find_all(exp.Table):
            name = tbl.name
            owner = tbl.db or None
            alias = (tbl.alias or name).upper()
            owner = owner.upper() if owner else None
            if alias not in seen:
                seen[alias] = TableRef(owner=owner, name=name.upper(), alias=alias)
        return list(seen.values())

    # ---- predicados ------------------------------------------------------
    def _extract_predicates(self, tree: exp.Expression, aliases: set[str]):
        joins: list[JoinPredicate] = []
        filters: list[FilterPredicate] = []

        # range: agrupar col >= X e col < Y na mesma coluna
        range_cols: dict[tuple[str, str], int] = {}

        for cond in tree.find_all(exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE):
            left, right = cond.this, cond.expression
            lcol = self._as_colref(left, aliases)
            rcol = self._as_colref(right, aliases)

            if lcol and rcol and lcol.table_alias != rcol.table_alias:
                # join entre duas colunas de tabelas distintas
                if isinstance(cond, exp.EQ):
                    joins.append(JoinPredicate(lcol, rcol))
                continue

            # filtro: coluna (de um lado) vs bind/literal (do outro)
            col = lcol or rcol
            if not col:
                continue
            if isinstance(cond, exp.EQ):
                filters.append(FilterPredicate(col, PredicateKind.EQUALITY))
            elif isinstance(cond, (exp.GT, exp.GTE, exp.LT, exp.LTE)):
                key = (col.table_alias, col.column)
                range_cols[key] = range_cols.get(key, 0) + 1

        # colunas com >=1 comparação de desigualdade viram RANGE (uma entrada)
        for (alias, colname) in range_cols:
            filters.append(FilterPredicate(ColumnRef(alias, colname), PredicateKind.RANGE))

        # IN-lists
        for inexp in tree.find_all(exp.In):
            col = self._as_colref(inexp.this, aliases)
            if col:
                filters.append(FilterPredicate(col, PredicateKind.IN_LIST))

        # dedup
        joins = list({(j.left, j.right): j for j in joins}.values())
        filters = list({(f.column, f.kind): f for f in filters}.values())
        return joins, filters

    def _as_colref(self, node: exp.Expression, aliases: set[str]) -> Optional[ColumnRef]:
        if isinstance(node, exp.Column):
            alias = (node.table or "").upper()
            if alias and alias in aliases:
                return ColumnRef(alias, node.name.upper())
            if not alias:
                return None  # coluna sem qualificação: ignora (ambígua)
        return None

    # ---- projeção e group by --------------------------------------------
    def _extract_projection(self, tree: exp.Expression, aliases: set[str]):
        projected: list[ColumnRef] = []
        grouped: list[ColumnRef] = []

        # projeções de TODOS os selects (inclui a subquery interna)
        for select in tree.find_all(exp.Select):
            for proj in select.expressions:
                for col in proj.find_all(exp.Column):
                    cr = self._as_colref(col, aliases)
                    if cr and cr not in projected:
                        projected.append(cr)
            grp = select.args.get("group")
            if grp:
                for col in grp.find_all(exp.Column):
                    cr = self._as_colref(col, aliases)
                    if cr and cr not in grouped:
                        grouped.append(cr)
        return projected, grouped
