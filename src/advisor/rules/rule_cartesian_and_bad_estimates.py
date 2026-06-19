"""
rule_cartesian_and_bad_estimates.py — Regra R004.

Detecta dois sintomas correlacionados e graves:

  (1) MERGE JOIN CARTESIAN no plano — produto cartesiano entre dois conjuntos.
      Quase sempre é sinal de estimativa de cardinalidade quebrada: o otimizador
      acha que um dos lados tem ~1 linha e decide que o cartesiano é barato,
      quando na prática explode (no caso real: cartesiano alimentou um NL que
      processou 2,16 bilhões de linhas para retornar 0).

  (2) Estimativas degeneradas: E-Rows absurdamente alto (overflow numérico tipo
      4e16) ou A-Rows/E-Rows divergindo por ordens de magnitude. Indica
      estatísticas desatualizadas/ausentes ou bind peeking patológico.

A recomendação NÃO é índice — é recolher estatísticas (sobretudo das partições
quentes) e/ou reavaliar SQL Profile/baseline. Um cartesiano não se resolve
criando índice; resolve-se corrigindo a estimativa que o gerou.
"""
from __future__ import annotations

from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext


# acima disto, E-Rows é considerado "impossível" (overflow de estimativa)
_INSANE_EROWS = 1e15


class CartesianAndBadEstimatesRule(Rule):
    rule_id = "R004_cartesian_or_bad_estimates"
    description = "MERGE JOIN CARTESIAN ou estimativas de cardinalidade degeneradas"
    priority = 5  # roda cedo: contextualiza as demais (cartesiano > índice)

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []

        cartesian_ops = [op for op in ctx.plan.operations
                         if "CARTESIAN" in op.operation.upper()]
        insane_ops = [op for op in ctx.plan.operations
                      if op.estim_rows is not None and op.estim_rows >= _INSANE_EROWS]
        misestimated = self._misestimated(ctx)

        if cartesian_ops:
            tables = ", ".join(t.name for t in ctx.query.tables)
            # diagnóstico de estatísticas por tabela (preenchido no --source db)
            stale_report = self._stale_report(ctx)
            extra = ""
            warn_stats = (
                "Antes de criar índices, corrija a estimativa: "
                "DBMS_STATS.GATHER_TABLE_STATS nas tabelas/partições envolvidas "
                f"({tables}). Se o cartesiano persistir com estatísticas frescas, "
                "avalie extended stats (column groups) para colunas correlacionadas "
                "e/ou um SQL Plan Baseline fixando um plano sem cartesiano."
            )
            if stale_report:
                extra = ("\n\n      DIAGNÓSTICO DE ESTATÍSTICAS (coletado do banco):\n      - "
                         + "\n      - ".join(stale_report))
                suspects = self._stale_suspects(ctx)
                if suspects:
                    cmds = "\n".join(
                        self._gather_stmt(o, t, ctx.env.index_parallel)
                        for o, t in suspects)
                    warn_stats = (
                        f"Tabela(s) com estatística OBSOLETA identificada(s): "
                        f"{', '.join(t for _, t in suspects)}. Recolha primeiro:\n{cmds}"
                    )

            recs.append(Recommendation(
                rule_id=self.rule_id,
                title="MERGE JOIN CARTESIAN no plano — estimativa de cardinalidade quebrada",
                severity=Severity.CRITICAL,
                rationale=(
                    f"O plano contém MERGE JOIN CARTESIAN (id "
                    f"{', '.join(str(o.op_id) for o in cartesian_ops)}). Um produto "
                    f"cartesiano é escolhido quando o otimizador estima ~1 linha em um "
                    f"dos lados do join; se a estimativa estiver errada, o resultado "
                    f"explode. Cartesiano raramente se corrige com índice — a causa é "
                    f"estatística/estimativa. Tabelas a investigar: {tables}.{extra}"
                ),
                ddl=None,
                target_table=None,
                estimated_benefit=0.0, estimated_maint_cost=0.0,
                tags=["cartesian", "statistics", "estimate"],
                warnings=[warn_stats],
            ))

        if insane_ops:
            recs.append(Recommendation(
                rule_id=self.rule_id,
                title="Estimativa de cardinalidade com overflow (estatísticas degeneradas)",
                severity=Severity.HIGH,
                rationale=(
                    f"Operações {', '.join(str(o.op_id) for o in insane_ops)} têm E-Rows "
                    f"da ordem de {max(o.estim_rows for o in insane_ops):.1e}, valor "
                    f"impossível que denuncia estatísticas ausentes/corrompidas ou "
                    f"aritmética de seletividade degenerada (frequentemente em joins "
                    f"múltiplos sobre colunas sem estatísticas estendidas)."
                ),
                ddl=None, target_table=None,
                estimated_benefit=0.0, estimated_maint_cost=0.0,
                tags=["estimate", "statistics"],
                warnings=["Recolher estatísticas e considerar extended statistics "
                          "para os grupos de colunas usados nos joins."],
            ))

        if misestimated and not cartesian_ops:
            op, factor = misestimated
            suspects = self._stale_suspects(ctx)
            stale_report = self._stale_report(ctx)
            warns = ["Recolher estatísticas atualizadas; investigar bind peeking "
                     "se a query usa binds com ranges variáveis."]
            extra = ""
            if stale_report:
                extra = ("\n\n      DIAGNÓSTICO DE ESTATÍSTICAS (coletado do banco):\n      - "
                         + "\n      - ".join(stale_report))
            if suspects:
                cmds = "\n".join(
                    self._gather_stmt(o, t, ctx.env.index_parallel)
                    for o, t in suspects)
                warns = [f"Tabela(s) com estatística OBSOLETA: "
                         f"{', '.join(t for _, t in suspects)}. Recolha primeiro:\n{cmds}"]
            recs.append(Recommendation(
                rule_id=self.rule_id,
                title="Divergência grande entre E-Rows e A-Rows",
                severity=Severity.MEDIUM,
                rationale=(
                    f"Na operação id {op.op_id} a estimativa (E-Rows={op.estim_rows:,.0f}) "
                    f"diverge do real (A-Rows={op.actual_rows:,.0f}) por ~{factor:,.0f}x. "
                    f"O otimizador está decidindo com base em números errados; planos "
                    f"construídos sobre essa estimativa são frágeis.{extra}"
                ),
                ddl=None, target_table=None,
                estimated_benefit=0.0, estimated_maint_cost=0.0,
                tags=["estimate", "statistics"],
                warnings=warns,
            ))
        return recs

    @staticmethod
    def _gather_stmt(owner: str, table: str, degree: int | None) -> str:
        """Comando DBMS_STATS.GATHER_TABLE_STATS com parâmetros completos.

        Usa AUTO_SAMPLE_SIZE + histogramas AUTO + GATHER AUTO (só o que está
        obsoleto). CASCADE recolhe também os índices. O `degree` vem do
        paralelismo configurado no env_profile (`index_ddl.parallel`); na
        ausência, usa DBMS_STATS.AUTO_DEGREE.
        """
        degree_val = str(degree) if degree else "DBMS_STATS.AUTO_DEGREE"
        return (
            "        EXEC DBMS_STATS.GATHER_TABLE_STATS(\n"
            f"                 ownname          => '{owner}',\n"
            f"                 tabname          => '{table}',\n"
            "                 estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,\n"
            "                 method_opt       => 'FOR ALL COLUMNS SIZE AUTO',\n"
            "                 granularity      => 'AUTO',\n"
            f"                 degree           => {degree_val},\n"
            "                 cascade          => TRUE,\n"
            "                 options          => 'GATHER AUTO',\n"
            "                 force            => TRUE);"
        )

    @staticmethod
    def _stale_report(ctx: RuleContext) -> list[str]:
        """Linhas legíveis sobre a saúde das estatísticas de cada tabela."""
        out = []
        for t in ctx.query.tables:
            meta = ctx.metadata.table(t.owner, t.name)
            if not meta:
                continue
            # só reporta se houver diagnóstico coletado (modo --source db)
            if meta.last_analyzed is None and meta.stale_stats is None:
                continue
            parts = [f"{t.name}: last_analyzed={meta.last_analyzed or 'NUNCA'}"]
            if meta.stale_stats:
                parts.append("STALE=YES")
            if meta.num_rows in (None, 0):
                parts.append("num_rows ausente/zero")
            if meta.stale_partitions:
                n = len(meta.stale_partitions)
                ex = ", ".join(meta.stale_partitions[:3])
                parts.append(f"{n} partição(ões) obsoleta(s) (ex.: {ex})")
            out.append(" — ".join(parts))
        return out

    @staticmethod
    def _stale_suspects(ctx: RuleContext) -> list[tuple[str, str]]:
        """Tabelas suspeitas: stale, sem num_rows, ou com partições obsoletas."""
        suspects = []
        for t in ctx.query.tables:
            meta = ctx.metadata.table(t.owner, t.name)
            if not meta:
                continue
            if meta.stale_stats or meta.num_rows in (None, 0) or meta.stale_partitions:
                suspects.append((meta.owner, meta.name))
        return suspects

    @staticmethod
    def _misestimated(ctx: RuleContext):
        """Maior divergência E-Rows vs A-Rows (fator) entre as operações."""
        worst = None
        for op in ctx.plan.operations:
            if op.estim_rows and op.actual_rows and op.estim_rows < _INSANE_EROWS:
                hi, lo = max(op.estim_rows, op.actual_rows), min(op.estim_rows, op.actual_rows)
                if lo > 0:
                    factor = hi / lo
                    if factor >= 1000 and (worst is None or factor > worst[1]):
                        worst = (op, factor)
        return worst
