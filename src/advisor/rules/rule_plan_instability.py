"""
rule_plan_instability.py — Regra R009.

Detecta INSTABILIDADE DE PLANO: o mesmo SQL_ID executou com mais de um
plan_hash_value. Isso significa que o otimizador trocou de plano ao longo do
tempo — causas típicas no RAWDB: cardinality feedback, bind peeking (binds com
seletividades muito diferentes), estatística obsoleta ou coleta parcial. Basta
um plano ruim entrar em rotação para degradar uma query quente.

A regra não gera índice. Ela:
  1) sinaliza que há vários planos para o SQL_ID;
  2) identifica o MELHOR plano observado (menor elapsed/exec, com fallback para
     buffer_gets/exec), comparando-o com o pior e com o plano do arquivo;
  3) recomenda estabilizar o melhor plano via SQL Plan Baseline (DBMS_SPM) e
     investigar a causa-raiz da troca.

Depende de ctx.plan_history, preenchido pelo coletor de planos (GV$SQL + AWR)
quando --source db. Em --source fixture o histórico vem vazio e a regra é inerte.
"""
from __future__ import annotations

from ..models import PlanStat, Recommendation, Severity
from ..rule_base import Rule, RuleContext

# razão pior/melhor a partir da qual um plano ruim em rotação é grave
_BAD_RATIO = 3.0


class PlanInstabilityRule(Rule):
    rule_id = "R009_plan_instability"
    description = "vários plan_hash_value para o mesmo SQL_ID (instabilidade de plano)"
    priority = 2  # contexto: roda logo após intervenção (R005), antes dos índices

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        hist = ctx.plan_history
        if hist is None or hist.distinct_count() < 2:
            return []

        best = hist.best()
        worst = hist.worst()
        current = hist.find(ctx.plan.plan_hash)
        n = hist.distinct_count()

        ratio = self._ratio(best, worst)
        severe = (ratio is not None and ratio >= _BAD_RATIO) or n >= 3
        severity = Severity.HIGH if severe else Severity.MEDIUM

        rationale = self._rationale(ctx, hist, best, worst, current, ratio)
        warnings = self._warnings(ctx, best, current)

        return [Recommendation(
            rule_id=self.rule_id,
            title=f"Instabilidade de plano: {n} planos distintos para este SQL_ID",
            severity=severity,
            rationale=rationale,
            ddl=None,
            target_table=None,
            estimated_benefit=0.0,
            estimated_maint_cost=0.0,
            tags=["plan-instability", "plan-stability", "spm"],
            warnings=warnings,
        )]

    # ---- helpers internos da regra ----
    @staticmethod
    def _ratio(best: PlanStat | None, worst: PlanStat | None):
        if (best is None or worst is None
                or best.cost_metric is None or not best.cost_metric):
            return None
        return worst.cost_metric / best.cost_metric

    def _fmt(self, ctx, p: PlanStat, best, current) -> str:
        marks = []
        if best is not None and p.plan_hash == best.plan_hash:
            marks.append("MELHOR")
        if current is not None and p.plan_hash == current.plan_hash:
            marks.append("plano do arquivo")
        elif str(ctx.plan.plan_hash) == p.plan_hash:
            marks.append("plano do arquivo")
        tag = f" [{', '.join(marks)}]" if marks else ""
        el = f"{p.avg_elapsed_s:.3f}s/exec" if p.avg_elapsed_s is not None else "elapsed n/d"
        bg = (f"{p.avg_buffer_gets:,.0f} gets/exec"
              if p.avg_buffer_gets is not None else "gets n/d")
        rows = f"{p.avg_rows:,.0f} linhas/exec" if p.avg_rows is not None else "linhas n/d"
        return (f"plan_hash {p.plan_hash} ({'/'.join(p.sources)}): "
                f"{p.executions:,.0f} execs, {el}, {bg}, {rows}{tag}")

    def _rationale(self, ctx, hist, best, worst, current, ratio) -> str:
        linhas = "; ".join(self._fmt(ctx, p, best, current) for p in hist.plans)
        partes = [
            f"O SQL_ID {hist.sql_id or ctx.plan.sql_id or '?'} executou com "
            f"{hist.distinct_count()} planos distintos — sinal de instabilidade "
            f"de plano. Planos observados: {linhas}."
        ]
        if best is not None:
            partes.append(
                f"Melhor plano observado: plan_hash {best.plan_hash} "
                f"(menor custo por execução)."
            )
        if best is not None and current is not None and best.plan_hash != current.plan_hash:
            if ratio is not None:
                partes.append(
                    f"O plano do arquivo (plan_hash {current.plan_hash}) NÃO é o "
                    f"melhor: está ~{ratio:.1f}x mais caro por execução que o "
                    f"melhor plano."
                )
            else:
                partes.append(
                    f"O plano do arquivo (plan_hash {current.plan_hash}) não é o "
                    f"melhor observado."
                )
        elif best is not None and str(ctx.plan.plan_hash) == best.plan_hash:
            partes.append(
                "O plano do arquivo já é o melhor observado — convém FIXÁ-LO para "
                "impedir que o otimizador volte a um plano pior."
            )
        return " ".join(partes)

    def _warnings(self, ctx, best, current) -> list[str]:
        ws = [
            "Causa-raiz provável: cardinality feedback, bind peeking (binds com "
            "seletividades diferentes), estatística obsoleta ou coleta parcial. "
            "Investigue antes de fixar — fixar um plano mascara, não corrige, "
            "estatística ruim.",
        ]
        if best is not None:
            ws.append(
                "Estabilize o melhor plano com SQL Plan Baseline (carregando-o do "
                "cursor cache):\n"
                "  DECLARE n NUMBER; BEGIN\n"
                f"    n := DBMS_SPM.LOAD_PLANS_FROM_CURSOR_CACHE(sql_id=>'"
                f"{ctx.plan.sql_id or '<SQL_ID>'}', "
                f"plan_hash_value=>{best.plan_hash}, fixed=>'YES', enabled=>'YES');\n"
                "  END;\n"
                "Se o melhor plano só existir no AWR (não no cursor cache), "
                "carregue via DBMS_SPM.LOAD_PLANS_FROM_AWR no intervalo de snapshot "
                "correspondente."
            )
        ws.append(
            "Depois de fixar, valide que o otimizador passou a usá-lo "
            "(V$SQL.SQL_PLAN_BASELINE) e monitore o elapsed/exec por alguns dias."
        )
        return ws
