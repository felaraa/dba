"""
reporter.py — Formata o resultado da análise para humanos.

Faz duas coisas que o motor não faz (porque são apresentação, não decisão):
  - merge dos warnings de regras de mitigação (R900) nas recomendações de
    índice correspondentes, casando por target_table;
  - geração de relatório em texto e markdown.
"""
from __future__ import annotations

from .models import Recommendation, Severity

_SEV_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2,
              Severity.LOW: 3, Severity.INFO: 4}


def _norm_cols_from_ddl(ddl: str):
    """Extrai (tabela, [colunas]) de um CREATE INDEX para comparar sobreposição."""
    import re
    m = re.search(r"ON\s+(\S+)\s*\(([^)]+)\)", ddl, re.I)
    if not m:
        return None, []
    table = m.group(1).split(".")[-1].upper()
    cols = [c.strip().upper() for c in m.group(2).split(",")]
    return table, cols


def consolidate_indexes(recs: list[Recommendation]) -> list[Recommendation]:
    """
    Funde recomendações de índice redundantes na mesma tabela: quando o conjunto
    de colunas de uma é prefixo da outra (mesma ordem), mantém a MAIS COMPLETA
    (superset) e descarta a contida. Evita propor dois índices quase iguais
    vindos de regras diferentes (ex.: R002 e R006).
    """
    index_recs = [r for r in recs if r.ddl]
    others = [r for r in recs if not r.ddl]

    # agrupa por tabela
    by_table: dict[str, list[Recommendation]] = {}
    for r in index_recs:
        table, cols = _norm_cols_from_ddl(r.ddl)
        r._cols = cols  # anexa para comparação
        by_table.setdefault(table, []).append(r)

    kept: list[Recommendation] = []
    for table, group in by_table.items():
        # ordena por número de colunas desc (superset primeiro)
        group.sort(key=lambda r: len(getattr(r, "_cols", [])), reverse=True)
        survivors: list[Recommendation] = []
        for r in group:
            rcols = getattr(r, "_cols", [])
            redundant = False
            for s in survivors:
                scols = getattr(s, "_cols", [])
                # r é prefixo de s (s já cobre r) → r é redundante
                if scols[:len(rcols)] == rcols:
                    redundant = True
                    # herda o melhor score e funde regras na nota do sobrevivente
                    if r.net_score > s.net_score:
                        s.estimated_benefit = max(s.estimated_benefit, r.estimated_benefit)
                    s.tags = list(set(s.tags + r.tags + [f"consolida:{r.rule_id}"]))
                    break
            if not redundant:
                survivors.append(r)
        kept.extend(survivors)

    return kept + others


def merge_mitigation_warnings(recs: list[Recommendation]) -> list[Recommendation]:
    """
    Move os warnings de recomendações sem DDL (mitigações) para as recomendações
    de índice (com DDL) da mesma tabela. Mitigações sem destino permanecem como
    item próprio.
    """
    mitig = [r for r in recs if r.ddl is None and r.warnings]
    indexed = [r for r in recs if r.ddl is not None]
    consumed = set()
    for m in mitig:
        for r in indexed:
            if r.target_table and r.target_table == m.target_table:
                r.warnings.extend(m.warnings)
                consumed.add(id(m))
    # mantém mitigações não consumidas como itens informativos
    leftover = [m for m in mitig if id(m) not in consumed]
    others = [r for r in recs if r.ddl is not None or (r.ddl is None and not r.warnings)]
    # remove duplicatas preservando: indexed + leftover + recs sem ddl/sem warning
    result = indexed + leftover + [r for r in recs
                                   if r.ddl is None and not r.warnings]
    return result


def to_text(recs: list[Recommendation], sql_id: str | None = None,
            plan_notes: tuple[str, ...] = ()) -> str:
    recs = sorted(recs, key=lambda r: (_SEV_ORDER.get(r.severity, 9), -r.net_score))
    lines = []
    head = "RELATÓRIO DE RECOMENDAÇÃO DE ÍNDICES"
    if sql_id:
        head += f"  (SQL_ID {sql_id})"
    lines.append(head)
    lines.append("=" * len(head))
    if plan_notes:
        lines.append("")
        lines.append("CONTEXTO DO PLANO:")
        for n in plan_notes:
            lines.append(f"  • {n}")
    if not recs:
        lines.append("Nenhuma recomendação. O plano não apresentou padrões acionáveis.")
        return "\n".join(lines)

    for i, r in enumerate(recs, 1):
        lines.append("")
        lines.append(f"[{i}] {r.severity.value.upper()} — {r.title}")
        lines.append(f"    Regra: {r.rule_id}")
        if r.ddl:
            lines.append(f"    Score líquido: {r.net_score:+.3f} "
                         f"(benefício {r.estimated_benefit:.2f} / "
                         f"manutenção {r.estimated_maint_cost:.2f})")
            lines.append(f"    DDL: {r.ddl}")
        lines.append(f"    Justificativa: {r.rationale}")
        for w in r.warnings:
            lines.append(f"    ⚠ MITIGAÇÃO: {w}")
    return "\n".join(lines)


def to_markdown(recs: list[Recommendation], sql_id: str | None = None,
                plan_notes: tuple[str, ...] = ()) -> str:
    recs = sorted(recs, key=lambda r: (_SEV_ORDER.get(r.severity, 9), -r.net_score))
    md = [f"# Recomendação de Índices{f' — SQL_ID `{sql_id}`' if sql_id else ''}\n"]
    if plan_notes:
        md.append("**Contexto do plano:** " + "; ".join(plan_notes) + "\n")
    if not recs:
        md.append("_Nenhuma recomendação acionável._")
        return "\n".join(md)
    for i, r in enumerate(recs, 1):
        md.append(f"## {i}. [{r.severity.value.upper()}] {r.title}\n")
        md.append(f"- **Regra:** `{r.rule_id}`")
        if r.ddl:
            md.append(f"- **Score líquido:** {r.net_score:+.3f} "
                      f"(benefício {r.estimated_benefit:.2f} / manutenção "
                      f"{r.estimated_maint_cost:.2f})")
            md.append(f"- **DDL:**\n  ```sql\n  {r.ddl}\n  ```")
        md.append(f"- **Justificativa:** {r.rationale}")
        for w in r.warnings:
            md.append(f"- ⚠ **Mitigação:** {w}")
        md.append("")
    return "\n".join(md)
