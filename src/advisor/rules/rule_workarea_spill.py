"""
rule_workarea_spill.py — Regra R010.

Detecta operação de workarea (SORT/HASH GROUP BY, HASH JOIN, SORT ORDER/JOIN,
WINDOW SORT) que DERRAMA volume grande para o TEMP (one-pass/multi-pass). Um
spill grande é, quase sempre, o maior sorvedouro de tempo da query: o servidor
escreve e relê dezenas/centenas de GB em disco temporário.

No caso real (MERGE 86kwg7rukwx07, agregação diária → AGG_DD_F_R4G_ADJL): o
SORT GROUP BY (id 5) derramou ~212 GB para o TEMP, ainda em 50% após 73 min. A
causa-raiz é a estimativa colapsada (E-Rows=1 vs 389M reais; ver R004): com "1
linha" o otimizador escolhe SORT serial em vez de HASH GROUP BY PARALELO, e a
agregação inteira passa por uma única workarea.

A recomendação NÃO é índice — é (1) corrigir estatística para o otimizador
escolher agregação HASH paralela, (2) habilitar paralelismo de fato (inclusive
PARALLEL DML para o MERGE) de modo que cada slave use sua própria workarea, e
(3) reavaliar PGA se ainda derramar. A regra também sinaliza quando a query PEDE
paralelismo (hint PARALLEL) mas o plano executou SERIAL.
"""
from __future__ import annotations

from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext


_GIB = 1 << 30
# operações que usam workarea (e portanto podem derramar p/ TEMP)
_WORKAREA_TOKENS = ("SORT", "HASH", "GROUP BY", "WINDOW", "BUFFER")
# abaixo disto o spill é irrelevante; não vale alarmar
_MIN_TEMP = 1 * _GIB
# limiares de severidade pelo pico de TEMP
_TEMP_CRITICAL = 100 * _GIB
_TEMP_HIGH = 10 * _GIB


class WorkareaSpillRule(Rule):
    rule_id = "R010_workarea_spill_to_temp"
    description = "SORT/HASH derramando volume grande para o TEMP (workarea spill)"
    priority = 6  # contexto/diagnóstico: precede as regras que geram índice

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []

        spillers = [op for op in ctx.plan.operations
                    if self._is_workarea(op.operation)
                    and (op.temp_bytes or 0) >= _MIN_TEMP]
        if not spillers:
            return recs

        # pega o pior (maior TEMP) — é o gargalo dominante
        op = max(spillers, key=lambda o: o.temp_bytes or 0)
        temp_gb = (op.temp_bytes or 0) / _GIB
        write_gb = (op.write_bytes or 0) / _GIB
        spills = int(op.spill_count or 0)

        if (op.temp_bytes or 0) >= _TEMP_CRITICAL:
            sev = Severity.CRITICAL
        elif (op.temp_bytes or 0) >= _TEMP_HIGH:
            sev = Severity.HIGH
        else:
            sev = Severity.MEDIUM

        serial_note = self._serial_despite_parallel(ctx)

        warnings = [
            "Corrija primeiro a estimativa de cardinalidade (ver R004): com a "
            "estimativa certa o otimizador troca SORT serial por HASH GROUP BY "
            "PARALELO, e a agregação deixa de passar por uma única workarea.",
            "Habilite paralelismo de fato — para DML use "
            "'ALTER SESSION ENABLE PARALLEL DML;' antes do MERGE, de modo que as "
            "hints PARALLEL valham e cada slave use sua própria workarea (o spill "
            "se divide entre os escravos em vez de concentrar em um processo).",
            "Se ainda derramar mesmo paralelo, avalie pga_aggregate_target / "
            "workarea_size_policy; um spill multi-pass (spill_count>1) é sinal de "
            "PGA insuficiente para o volume agregado.",
        ]
        if serial_note:
            warnings.insert(0, serial_note)

        recs.append(Recommendation(
            rule_id=self.rule_id,
            title=(f"{op.operation} (id {op.op_id}) derramou ~{temp_gb:,.0f} GB "
                   f"para o TEMP — gargalo dominante"),
            severity=sev,
            rationale=(
                f"A operação id {op.op_id} ({op.operation}) usou ~{temp_gb:,.0f} GB "
                f"de TEMP"
                + (f" ({spills} spill(s))" if spills else "")
                + (f" e escreveu ~{write_gb:,.0f} GB em disco temporário" if write_gb else "")
                + ". Escrever e reler dezenas/centenas de GB em TEMP costuma ser o "
                "maior custo de tempo da query — aqui o I/O de TEMP supera de longe "
                "o trabalho de CPU útil. Derrame desse tamanho quase sempre nasce de "
                "uma agregação/ordenação SERIAL sobre volume massivo que o otimizador "
                "subestimou (E-Rows baixo), escolhendo SORT em vez de HASH paralelo."
            ),
            ddl=None,
            target_table=op.object_name,
            estimated_benefit=0.0, estimated_maint_cost=0.0,
            tags=["temp-spill", "workarea", "sort", "statistics", "parallel"],
            warnings=warnings,
        ))
        return recs

    @staticmethod
    def _is_workarea(operation: str) -> bool:
        up = operation.upper()
        return any(tok in up for tok in _WORKAREA_TOKENS)

    @staticmethod
    def _serial_despite_parallel(ctx: RuleContext) -> str | None:
        """Sinaliza quando há hint PARALLEL no SQL mas nenhuma operação PX no plano."""
        sql = (ctx.query.raw_sql or "").upper()
        if "PARALLEL" not in sql:
            return None
        has_px = any("PX " in op.operation.upper() or op.operation.upper().startswith("PX")
                     for op in ctx.plan.operations)
        if has_px:
            return None
        return (
            "A query PEDE paralelismo (hint PARALLEL) mas o plano executou SERIAL "
            "(nenhuma operação PX): um único processo carrega toda a workarea. Com "
            "a estimativa correta e PARALLEL DML habilitado, o caminho deve "
            "paralelizar e dividir o spill entre os escravos."
        )
