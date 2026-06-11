"""
plan_parser.py — Produz ParsedPlan a partir de planos de execução Oracle.

Suporta duas fontes:
  1) XML do SQL Monitor: DBMS_SQLTUNE.REPORT_SQL_MONITOR(type=>'XML') — preferido,
     traz A-Rows, Execs, hierarquia pai-filho e predicados estruturados.
  2) Texto do DBMS_XPLAN.DISPLAY_CURSOR(format=>'ALLSTATS LAST +PREDICATE') —
     fallback quando não há SQL Monitor.

A hierarquia pai-filho é reconstruída corretamente (no XML vem explícita; no
texto, por indentação), o que permite à regra R001 correlacionar o range-scan
filho/irmão que infla as linhas com o table-access que filtra.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional

from .models import ParsedPlan, PlanOperation


# ---------------------------------------------------------------------------
# Fonte 1: XML do SQL Monitor
# ---------------------------------------------------------------------------
class SqlMonitorXmlParser:
    """
    Parser do XML do SQL Monitor. O relatório tem DUAS seções por operação:
      (a) <plan> estática: object, depth, <predicates type="access|filter">,
          <cardinality> (E-Rows);
      (b) <plan_monitor>: parent_id explícito e <stat> de runtime
          (starts = Execs, cardinality = A-Rows, read_reqs, read_bytes).
    Combinamos as duas casando por id da operação.
    """
    def parse(self, xml_text: str) -> ParsedPlan:
        start = xml_text.find("<report")
        if start > 0:
            xml_text = xml_text[start:]
        root = ET.fromstring(xml_text)

        sql_id = self._findtext(root, ".//sql_id")
        plan_hash = self._info(root, "plan_hash")
        elapsed = self._report_float(root, "elapsed_time")

        # intervenções no plano (SQL Profile, baseline, outline)
        sql_profile = self._info(root, "sql_profile")
        notes = []
        if sql_profile:
            notes.append(f"SQL Profile ativo: {sql_profile}")
        if self._info(root, "baseline") or self._info(root, "sql_plan_baseline"):
            notes.append("SQL Plan Baseline ativo")
        if self._info(root, "outline"):
            notes.append("Stored Outline ativo")

        # (a) seção estática: objeto, depth, predicados, E-Rows
        static = self._parse_static(root)
        # (b) seção plan_monitor: parent_id e stats de runtime
        runtime = self._parse_runtime(root)

        ops: list[PlanOperation] = []
        all_ids = sorted(set(static) | set(runtime))
        for op_id in all_ids:
            s = static.get(op_id, {})
            r = runtime.get(op_id, {})
            parent_id = r.get("parent_id", s.get("parent_id"))
            ops.append(PlanOperation(
                op_id=op_id,
                operation=(s.get("operation") or r.get("operation") or "").upper(),
                object_name=s.get("object") or None,
                estim_rows=s.get("card"),
                actual_rows=r.get("cardinality"),   # A-Rows (output rows)
                executions=r.get("starts"),         # Execs
                buffer_gets=None,
                read_bytes=r.get("read_bytes"),
                access_predicates=s.get("access", ()),
                filter_predicates=s.get("filter", ()),
                parent_id=parent_id,
            ))
        ops.sort(key=lambda o: o.op_id)
        return ParsedPlan(sql_id=sql_id, plan_hash=plan_hash,
                          operations=tuple(ops), total_elapsed_s=elapsed,
                          notes=tuple(notes), sql_profile=sql_profile)

    # ---- seção estática (<plan>) ----
    def _parse_static(self, root):
        out = {}
        plan = root.find(".//plan")
        if plan is None:
            return out
        # reconstruir parent por depth
        stack = []
        for node in plan.iter("operation"):
            if node.get("id") is None:
                continue
            op_id = int(node.get("id"))
            depth = int(node.get("depth", 0))
            while stack and stack[-1][0] >= depth:
                stack.pop()
            parent_id = stack[-1][1] if stack else None
            stack.append((depth, op_id))

            operation = node.get("name") or ""
            opts = node.get("options")
            if opts:
                operation = f"{operation} {opts}"
            obj_node = node.find("object")
            obj = None
            if obj_node is not None:
                obj = obj_node.findtext("name") or (obj_node.text or "").strip() or None
            card = self._child_float(node, "card") or self._child_float(node, "cardinality")

            access, filt = [], []
            for pred in node.findall("predicates"):
                txt = (pred.text or "").strip()
                if not txt:
                    continue
                if pred.get("type") == "access":
                    access.append(txt)
                elif pred.get("type") == "filter":
                    filt.append(txt)
            out[op_id] = {"operation": operation, "object": obj, "card": card,
                          "parent_id": parent_id,
                          "access": tuple(access), "filter": tuple(filt)}
        return out

    # ---- seção runtime (<plan_monitor>) ----
    def _parse_runtime(self, root):
        out = {}
        pm = root.find(".//plan_monitor")
        if pm is None:
            return out
        for node in pm.iter("operation"):
            if node.get("id") is None:
                continue
            op_id = int(node.get("id"))
            parent = node.get("parent_id")
            rec = {"operation": node.get("name") or "",
                   "parent_id": int(parent) if parent is not None else None}
            stats_node = node.find("stats")
            if stats_node is not None:
                for st in stats_node.findall("stat"):
                    name = st.get("name")
                    if name in ("starts", "cardinality", "read_reqs", "read_bytes"):
                        try:
                            rec[name] = float(st.text)
                        except (ValueError, TypeError):
                            pass
            out[op_id] = rec
        return out

    # ---- helpers ----
    @staticmethod
    def _findtext(root, path):
        n = root.find(path)
        return n.text if n is not None and n.text else None

    @staticmethod
    def _info(root, type_name):
        for info in root.iter("info"):
            if info.get("type") == type_name and info.text:
                return info.text
        return None

    @staticmethod
    def _report_float(root, attr):
        v = root.get(attr)
        try:
            return float(v) if v else None
        except ValueError:
            return None

    @staticmethod
    def _child_float(node, tag):
        c = node.find(tag)
        try:
            return float(c.text) if c is not None and c.text else None
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
class DbmsXplanTextParser:
    """
    Parser do formato tabular do DBMS_XPLAN. Reconstrói a hierarquia pelos
    níveis de indentação da coluna Operation e associa a seção
    'Predicate Information' (id - access/filter) a cada operação.
    """
    _row_re = re.compile(r"^\|\s*\*?\s*(\d+)\s*\|(.+)$")
    _pred_re = re.compile(r"^\s*(\d+)\s*-\s*(access|filter)\((.+?)\)?\s*$")

    def parse(self, text: str) -> ParsedPlan:
        lines = text.splitlines()
        sql_id = self._grab(text, r"SQL_ID\s+(\w+)")
        plan_hash = self._grab(text, r"Plan hash value:\s*(\d+)")

        # localizar cabeçalho para mapear colunas
        header_idx = next((i for i, l in enumerate(lines)
                           if "Operation" in l and "Name" in l), None)
        cols = self._columns(lines[header_idx]) if header_idx is not None else {}

        ops: list[PlanOperation] = []
        indent_stack: list[tuple[int, int]] = []  # (indent, op_id)
        for line in lines:
            m = self._row_re.match(line)
            if not m:
                continue
            op_id = int(m.group(1))
            raw_cells = line.split("|")
            cells = [c.strip() for c in raw_cells]
            # indentação medida na célula CRUA (sem strip), senão vira sempre 0
            operation_cell_raw = raw_cells[2] if len(raw_cells) > 2 else ""
            indent = len(operation_cell_raw) - len(operation_cell_raw.lstrip())
            operation = cells[2].lstrip("*").strip() if len(cells) > 2 else ""
            name = cells[3].strip() if len(cells) > 3 else ""

            estim = self._num(cells, cols.get("E-Rows"))
            actual = self._num(cells, cols.get("A-Rows"))
            execs = self._num(cells, cols.get("Starts"))
            buffers = self._num(cells, cols.get("Buffers"))

            parent_id = self._parent_from_indent(indent_stack, indent, op_id)

            ops.append(PlanOperation(
                op_id=op_id, operation=operation.upper(), object_name=name or None,
                estim_rows=estim, actual_rows=actual, executions=execs,
                buffer_gets=buffers, read_bytes=None, parent_id=parent_id,
            ))

        preds = self._parse_predicates(lines)
        ops = [self._attach_preds(o, preds) for o in ops]
        ops.sort(key=lambda o: o.op_id)
        return ParsedPlan(sql_id=sql_id, plan_hash=plan_hash, operations=tuple(ops))

    # ---- helpers ----
    @staticmethod
    def _grab(text, pat) -> Optional[str]:
        m = re.search(pat, text)
        return m.group(1) if m else None

    def _columns(self, header: str) -> dict[str, int]:
        cells = [c.strip() for c in header.split("|")]
        return {name: i for i, name in enumerate(cells) if name}

    @staticmethod
    def _num(cells, idx) -> Optional[float]:
        if idx is None or idx >= len(cells):
            return None
        v = cells[idx].strip().replace(",", "")
        if not v:
            return None
        mult = 1
        if v[-1] in "KMG":
            mult = {"K": 1e3, "M": 1e6, "G": 1e9}[v[-1]]
            v = v[:-1]
        try:
            return float(v) * mult
        except ValueError:
            return None

    def _parent_from_indent(self, stack, indent, op_id) -> Optional[int]:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else None
        stack.append((indent, op_id))
        return parent

    def _parse_predicates(self, lines) -> dict[int, dict[str, list[str]]]:
        preds: dict[int, dict[str, list[str]]] = {}
        in_section = False
        buffer = ""
        for line in lines:
            if "Predicate Information" in line:
                in_section = True
                continue
            if not in_section:
                continue
            m = self._pred_re.match(line)
            if m:
                if buffer:
                    self._store_pred(preds, buffer)
                buffer = f"{m.group(1)}|{m.group(2)}|{m.group(3)}"
            elif buffer and line.strip() and not line.startswith("-"):
                buffer += " " + line.strip()  # continuação de predicado multilinha
        if buffer:
            self._store_pred(preds, buffer)
        return preds

    @staticmethod
    def _store_pred(preds, buffer):
        op_id_s, kind, body = buffer.split("|", 2)
        body = body.rstrip(") ").strip()
        op_id = int(op_id_s)
        preds.setdefault(op_id, {"access": [], "filter": []})[kind].append(body)

    @staticmethod
    def _attach_preds(op: PlanOperation, preds) -> PlanOperation:
        p = preds.get(op.op_id)
        if not p:
            return op
        from dataclasses import replace
        return replace(op,
                       access_predicates=tuple(p["access"]),
                       filter_predicates=tuple(p["filter"]))


def parse_plan(text: str) -> ParsedPlan:
    """Detecta automaticamente XML do SQL Monitor vs texto do DBMS_XPLAN."""
    if "<report" in text[:2000] or "<sql_monitor_report" in text[:2000]:
        return SqlMonitorXmlParser().parse(text)
    return DbmsXplanTextParser().parse(text)
