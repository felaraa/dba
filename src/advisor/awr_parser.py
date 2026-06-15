"""
awr_parser.py — Extrai métricas de um AWR report (HTML) para alimentar o
env_profile.

Filosofia (igual ao metadata_collector): RESILIENTE. Cada métrica é extraída
de forma independente; uma seção ausente ou em formato diferente NUNCA derruba
o parse. O que não foi encontrado é registrado em `AwrMetrics.missing` para o
`--diag` apontar exatamente o que faltou.

Não há regra de tuning aqui: este módulo só LÊ o AWR e devolve números crus.
A decisão de o que vira `cpu_bound`, `cache_hit_very_high` etc. (limiares) fica
em profile_builder.py — assim "como lemos o AWR" e "como calibramos a engine"
continuam separados.

Formato suportado: AWR em HTML (saída de `?/rdbms/admin/awrrpt.sql` escolhendo
'html', ou `awrrpti.sql` por instância). O AWR-texto não é suportado: gere o
HTML, que é o formato estável e o documentado em docs/GUIA_ENV_PROFILE.md.

Âncoras de busca: cada tabela de dados do AWR carrega um atributo `summary`
("This table displays load profile", etc.). Casamos por palavras-chave nesse
summary OU no cabeçalho (h1..h4) imediatamente anterior — case-insensitive,
tolerante a variações de versão.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional


# ===========================================================================
# 1. Extrator genérico de tabelas do HTML (stdlib, sem dependências novas)
# ===========================================================================
@dataclass
class _Table:
    summary: str
    heading: str
    rows: list[list[str]] = field(default_factory=list)

    def haystack(self) -> str:
        return f"{self.summary} ||| {self.heading}".lower()


class _AwrHtmlTables(HTMLParser):
    """
    Varre o HTML e coleta TODA tabela que tenha atributo `summary` (as tabelas
    de dados do AWR sempre têm). Para cada tabela guarda: o summary, o último
    cabeçalho h1..h4 visto antes dela, e as linhas como listas de texto de
    célula. Tabelas de layout (sem summary) são ignoradas. Suporta aninhamento
    via pilha.
    """

    _HEADINGS = {"h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._last_heading = ""
        self._heading_buf: list[str] = []
        self._in_heading = False
        # pilha de tabelas abertas: (_Table | None). None = tabela sem summary
        self._stack: list[Optional[_Table]] = []
        self._cell_buf: Optional[list[str]] = None

    # -- cabeçalhos -------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self._HEADINGS:
            self._in_heading = True
            self._heading_buf = []
        elif tag == "table":
            summ = a.get("summary")
            if summ:
                self.tables.append(_Table(summary=summ, heading=self._last_heading))
                self._stack.append(self.tables[-1])
            else:
                self._stack.append(None)
        elif tag == "tr" and self._stack and self._stack[-1] is not None:
            self._stack[-1].rows.append([])
        elif tag in ("td", "th") and self._stack and self._stack[-1] is not None:
            self._cell_buf = []

    def handle_endtag(self, tag):
        if tag in self._HEADINGS:
            self._in_heading = False
            self._last_heading = " ".join("".join(self._heading_buf).split())
        elif tag == "table":
            if self._stack:
                self._stack.pop()
        elif tag in ("td", "th"):
            if self._cell_buf is not None and self._stack and self._stack[-1] is not None:
                cell = " ".join("".join(self._cell_buf).split())
                tbl = self._stack[-1]
                if tbl.rows:
                    tbl.rows[-1].append(cell)
                else:  # célula sem <tr> explícito — abre uma linha
                    tbl.rows.append([cell])
            self._cell_buf = None

    def handle_data(self, data):
        if self._in_heading:
            self._heading_buf.append(data)
        elif self._cell_buf is not None:
            self._cell_buf.append(data)


# ===========================================================================
# 2. Métricas cruas extraídas (Optional = "não encontrado no AWR")
# ===========================================================================
@dataclass
class HotSegment:
    owner: str
    name: str
    type: str           # TABLE | INDEX
    source: str = ""    # de qual seção do AWR veio (diag)


@dataclass
class AwrMetrics:
    """Números crus lidos do AWR. None = não encontrado (vide `missing`)."""
    # identity
    db_name: Optional[str] = None
    oracle_version: Optional[str] = None
    rac: Optional[bool] = None
    rac_instances: Optional[int] = None
    db_block_size: Optional[int] = None
    platform: Optional[str] = None
    # workload (Load Profile / Time Model / Instance Efficiency)
    db_cpu_pct_of_dbtime: Optional[float] = None
    buffer_hit_pct: Optional[float] = None
    redo_mb_per_s: Optional[float] = None
    block_changes_per_s: Optional[float] = None
    logical_reads_per_s: Optional[float] = None
    physical_reads_per_s: Optional[float] = None
    # io
    single_block_read_us: Optional[float] = None     # db file sequential read
    multiblock_read_count: Optional[int] = None
    # rac contention (varredura dos top events)
    index_contention_in_top_events: Optional[bool] = None
    gc_buffer_busy_in_top_events: Optional[bool] = None
    index_in_buffer_busy_segments: Optional[bool] = None
    # optimizer (init.ora)
    optimizer_index_cost_adj: Optional[int] = None
    optimizer_index_caching: Optional[int] = None
    optimizer_adaptive_plans: Optional[bool] = None
    # segmentos quentes (union de várias seções "Segments by ...")
    hot_segments: list[HotSegment] = field(default_factory=list)
    # diag
    source_files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)

    def _mark(self, field_name: str, value):
        (self.found if value not in (None, [], "") else self.missing).append(field_name)


# ===========================================================================
# 3. Helpers de parsing numérico (tolerantes a "1,234.5", "%", "N/A")
# ===========================================================================
def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _truthy_yes(s: Optional[str]) -> Optional[bool]:
    if s is None:
        return None
    s = s.strip().lower()
    if s in ("yes", "true", "y"):
        return True
    if s in ("no", "false", "n"):
        return False
    return None


# ===========================================================================
# 4. Parse principal
# ===========================================================================
class _AwrView:
    """Conveniência: localizar tabelas e células por palavras-chave."""

    def __init__(self, tables: list[_Table]):
        self.tables = tables

    def find(self, *keywords: str) -> Optional[_Table]:
        """Primeira tabela cujo summary/heading contém TODAS as keywords."""
        kws = [k.lower() for k in keywords]
        for t in self.tables:
            hay = t.haystack()
            if all(k in hay for k in kws):
                return t
        return None

    def find_all(self, *keywords: str) -> list[_Table]:
        kws = [k.lower() for k in keywords]
        return [t for t in self.tables if all(k in t.haystack() for k in kws)]

    @staticmethod
    def header_index(tbl: _Table, *keywords: str) -> Optional[int]:
        """Índice da coluna cujo cabeçalho (1ª linha) contém as keywords."""
        if not tbl.rows:
            return None
        kws = [k.lower() for k in keywords]
        for i, cell in enumerate(tbl.rows[0]):
            c = cell.lower()
            if all(k in c for k in kws):
                return i
        return None

    @staticmethod
    def row_starting(tbl: _Table, *prefixes: str) -> Optional[list[str]]:
        """Primeira linha de dados cuja 1ª célula começa com algum prefixo."""
        pre = [p.lower() for p in prefixes]
        for row in tbl.rows[1:]:
            if not row:
                continue
            c0 = row[0].strip().lower()
            if any(c0.startswith(p) for p in pre):
                return row
        return None


def parse_awr(html_text: str, source_name: str = "") -> AwrMetrics:
    """AWR HTML -> AwrMetrics. Nunca lança por seção ausente; só registra."""
    m = AwrMetrics()
    if source_name:
        m.source_files.append(source_name)

    if "<table" not in html_text.lower():
        m.missing.append("(arquivo não parece HTML — gere o AWR em formato HTML)")
        return m

    parser = _AwrHtmlTables()
    try:
        parser.feed(html_text)
    except Exception:  # parser de HTML nunca deve derrubar a coleta
        pass
    v = _AwrView(parser.tables)

    _parse_identity(v, m)
    _parse_load_profile(v, m)
    _parse_time_model(v, m)
    _parse_instance_efficiency(v, m)
    _parse_top_events(v, m)
    _parse_fg_wait_events(v, m)
    _parse_init_params(v, m)
    _parse_segments(v, m)

    # consolidação de flags derivadas de eventos/segmentos
    m._mark("db_name", m.db_name)
    m._mark("oracle_version", m.oracle_version)
    m._mark("db_block_size", m.db_block_size)
    m._mark("db_cpu_pct_of_dbtime", m.db_cpu_pct_of_dbtime)
    m._mark("buffer_hit_pct", m.buffer_hit_pct)
    m._mark("redo_mb_per_s", m.redo_mb_per_s)
    m._mark("block_changes_per_s", m.block_changes_per_s)
    m._mark("single_block_read_us", m.single_block_read_us)
    m._mark("multiblock_read_count", m.multiblock_read_count)
    m._mark("optimizer_index_cost_adj", m.optimizer_index_cost_adj)
    m._mark("hot_segments", m.hot_segments)
    return m


# -- seções individuais -----------------------------------------------------
def _parse_identity(v: _AwrView, m: AwrMetrics) -> None:
    t = v.find("database instance information") or v.find("db name", "db id")
    if t and len(t.rows) >= 2:
        hdr, data = t.rows[0], t.rows[1]

        def col(*kw):
            i = v.header_index(t, *kw)
            return data[i] if i is not None and i < len(data) else None

        m.db_name = (col("db name") or m.db_name)
        m.oracle_version = (col("release") or m.oracle_version)
        m.rac = _truthy_yes(col("rac"))
    # número de instâncias do RAC (awrgrpt lista todas; awrrpti mostra 1)
    insts = _count_rac_instances(v)
    if insts:
        m.rac_instances = insts
    # plataforma / Exadata
    th = v.find("host configuration") or v.find("platform", "cpus")
    if th and len(th.rows) >= 2:
        i = v.header_index(th, "platform")
        if i is not None and i < len(th.rows[1]):
            m.platform = th.rows[1][i]


def _count_rac_instances(v: _AwrView) -> Optional[int]:
    # tabela "RAC Statistics"/"Instances" ou o cabeçalho de snapshot por instância
    t = v.find("number of instances")
    if t:
        for row in t.rows:
            for j, c in enumerate(row):
                if "number of instances" in c.lower():
                    val = _num(row[j + 1]) if j + 1 < len(row) else None
                    if val:
                        return int(val)
    return None


def _parse_load_profile(v: _AwrView, m: AwrMetrics) -> None:
    t = v.find("load profile")
    if not t:
        return
    persec = v.header_index(t, "per second")
    if persec is None:
        persec = 1  # 1ª coluna de números costuma ser Per Second

    def per_sec(*prefixes):
        row = v.row_starting(t, *prefixes)
        return _num(row[persec]) if row and persec < len(row) else None

    redo_bytes = per_sec("redo size")
    if redo_bytes is not None:
        m.redo_mb_per_s = round(redo_bytes / (1024 * 1024), 1)
    m.block_changes_per_s = per_sec("block changes")
    m.logical_reads_per_s = per_sec("logical read")
    m.physical_reads_per_s = per_sec("physical read")


def _parse_time_model(v: _AwrView, m: AwrMetrics) -> None:
    if m.db_cpu_pct_of_dbtime is not None:
        return
    t = v.find("time model")
    if not t:
        return
    val_col = v.header_index(t, "time") or 1
    db_time = db_cpu = None
    for row in t.rows[1:]:
        if not row:
            continue
        name = row[0].strip().lower()
        val = _num(row[val_col]) if val_col < len(row) else None
        if name == "db time" or name.startswith("db time"):
            db_time = val
        elif name == "db cpu" or name.startswith("db cpu"):
            db_cpu = val
    if db_time and db_cpu:
        m.db_cpu_pct_of_dbtime = round(db_cpu / db_time, 2)


def _parse_instance_efficiency(v: _AwrView, m: AwrMetrics) -> None:
    t = v.find("instance efficiency")
    if not t:
        return
    # tabela em pares (label, valor) possivelmente 2 pares por linha
    flat: list[str] = []
    for row in t.rows:
        flat.extend(row)
    for i, cell in enumerate(flat):
        if "buffer hit" in cell.lower() and i + 1 < len(flat):
            val = _num(flat[i + 1])
            if val is not None:
                m.buffer_hit_pct = val
                break


def _parse_top_events(v: _AwrView, m: AwrMetrics) -> None:
    t = (v.find("top 10") or v.find("top", "events by total wait")
         or v.find("top 5 timed"))
    if not t:
        m.index_contention_in_top_events = m.index_contention_in_top_events or False
        m.gc_buffer_busy_in_top_events = m.gc_buffer_busy_in_top_events or False
        return
    blob = " ".join(c.lower() for row in t.rows for c in row)
    m.index_contention_in_top_events = "index contention" in blob
    m.gc_buffer_busy_in_top_events = "gc buffer busy" in blob
    # DB CPU % DB time como fallback do time model
    if m.db_cpu_pct_of_dbtime is None:
        pct_col = v.header_index(t, "db time")  # "% DB time"
        for row in t.rows[1:]:
            if row and row[0].strip().lower() == "db cpu" and pct_col and pct_col < len(row):
                val = _num(row[pct_col])
                if val is not None:
                    m.db_cpu_pct_of_dbtime = round(val / 100.0, 2)


def _parse_fg_wait_events(v: _AwrView, m: AwrMetrics) -> None:
    # 'db file sequential read' Avg wait (ms) -> single block read em µs
    for t in (v.find_all("foreground wait events") + v.find_all("wait events")):
        avg_col = v.header_index(t, "avg wait")
        if avg_col is None:
            avg_col = v.header_index(t, "avg")
        row = v.row_starting(t, "db file sequential read")
        if row and avg_col is not None and avg_col < len(row):
            ms = _num(row[avg_col])
            if ms is not None:
                m.single_block_read_us = round(ms * 1000.0, 0)
                return


def _parse_init_params(v: _AwrView, m: AwrMetrics) -> None:
    # AWR pode ter VÁRIAS tabelas de parâmetros (modificados pelo container,
    # herdados, multi-valor). Um parâmetro no default (ex.: db_block_size) só
    # aparece na de "herdados". Funde todas num só dicionário nome->valor.
    tables = (v.find_all("initialization parameter")
              + v.find_all("init.ora parameter")
              + v.find_all("database parameter"))
    if not tables:
        t = v.find("parameter", "value")
        tables = [t] if t else []
    if not tables:
        return

    params: dict[str, str] = {}
    for t in tables:
        name_col = v.header_index(t, "parameter")
        name_col = name_col if name_col is not None else 0
        # valor ATUAL no snapshot = "Begin value"; "End value (if different)"
        # costuma estar vazio. Preferimos begin e caímos para end/seguinte.
        begin_col = v.header_index(t, "begin value")
        end_col = v.header_index(t, "end value")
        for row in t.rows[1:]:
            if not row or name_col >= len(row):
                continue
            name = row[name_col].strip().lower()
            if not name or name in params:
                continue
            val = ""
            for c in (begin_col, end_col, name_col + 1):
                if c is not None and c < len(row) and row[c].strip():
                    val = row[c].strip()
                    break
            if val:
                params[name] = val

    def get(param):
        return params.get(param)

    bs = _num(get("db_block_size"))
    if bs:
        m.db_block_size = int(bs)
    mbrc = _num(get("db_file_multiblock_read_count"))
    if mbrc:
        m.multiblock_read_count = int(mbrc)
    oica = _num(get("optimizer_index_cost_adj"))
    if oica is not None:
        m.optimizer_index_cost_adj = int(oica)
    oic = _num(get("optimizer_index_caching"))
    if oic is not None:
        m.optimizer_index_caching = int(oic)
    oap = _truthy_yes(get("optimizer_adaptive_plans"))
    if oap is not None:
        m.optimizer_adaptive_plans = oap


_SEG_TYPE_RE = re.compile(r"\b(INDEX|TABLE)\b", re.I)

# Schemas mantidos pela Oracle: seus segmentos quentes são "ruído" de dicionário
# (SEG$, WRI$_OPTSTAT_*, etc.) e não interessam para tuning de aplicação.
_ORACLE_MAINTAINED = {
    "SYS", "SYSTEM", "SYSAUX", "DBSNMP", "OUTLN", "AUDSYS", "GSMADMIN_INTERNAL",
    "WMSYS", "XDB", "ORDSYS", "ORDDATA", "ORDPLUGINS", "MDSYS", "CTXSYS",
    "LBACSYS", "OLAPSYS", "OJVMSYS", "DVSYS", "DVF", "APPQOSSYS", "DBSFWUSER",
    "GGSYS", "REMOTE_SCHEDULER_AGENT", "SYS$UMF", "ANONYMOUS", "XS$NULL",
    "FLOWS_FILES", "ORACLE_OCM", "SYSRAC", "SYSKM", "SYSBACKUP", "DGPDB_INT",
    "MGDSYS", "GSMCATUSER", "GSMUSER", "GSMROOTUSER", "AUDIT_VIEWER",
}
_ORACLE_PREFIXES = ("APEX_", "FLOWS_", "SYS$", "C##")


def _is_application_segment(owner: str, name: str) -> bool:
    """True se for um segmento de APLICAÇÃO (não dicionário/sistema)."""
    o = (owner or "").upper()
    if o in _ORACLE_MAINTAINED or any(o.startswith(p) for p in _ORACLE_PREFIXES):
        return False
    if "$" in (name or ""):       # objetos de dicionário (SEG$, *_OPTSTAT_*$, ...)
        return False
    return True


def _norm_seg_type(s: str) -> str:
    mt = _SEG_TYPE_RE.search(s or "")
    return mt.group(1).upper() if mt else "TABLE"


def _parse_segments(v: _AwrView, m: AwrMetrics) -> None:
    """
    Une as várias seções 'Segments by ...' em hot_segments. As de contenção
    (Buffer Busy / Row Lock / ITL) também marcam o flag de hot block em índice.
    """
    sections = [
        ("logical reads", "logical"),
        ("physical reads", "physical"),
        ("buffer busy", "buffer_busy"),
        ("row lock", "row_lock"),
        ("itl waits", "itl"),
        ("gc buffer busy", "gc_buffer_busy"),
    ]
    seen: set[tuple[str, str]] = set()
    # mantém a ordem de relevância: segmentos já vistos por seções anteriores
    # não são reinseridos
    seen.update((s.owner, s.name) for s in m.hot_segments)
    for kw, src in sections:
        for t in v.find_all("segments by", kw):
            owner_i = v.header_index(t, "owner")
            obj_i = v.header_index(t, "object name")
            type_i = v.header_index(t, "obj. type") or v.header_index(t, "obj type") \
                or v.header_index(t, "type")
            if owner_i is None or obj_i is None:
                continue
            for row in t.rows[1:]:
                if obj_i >= len(row) or owner_i >= len(row):
                    continue
                owner = row[owner_i].strip()
                name = row[obj_i].strip()
                if not name or not owner or name.startswith("**"):
                    continue
                if not _is_application_segment(owner, name):
                    continue   # descarta ruído de dicionário/sistema (SYS.SEG$ ...)
                seg_type = _norm_seg_type(row[type_i]) if (type_i is not None and type_i < len(row)) else "TABLE"
                key = (owner, name)
                if key in seen:
                    continue
                seen.add(key)
                m.hot_segments.append(HotSegment(owner, name, seg_type, src))
                if src in ("buffer_busy", "row_lock", "itl", "gc_buffer_busy") and seg_type == "INDEX":
                    m.index_in_buffer_busy_segments = True


# ===========================================================================
# 5. Agregação de múltiplos AWRs (ex.: 1 por nó do RAC, ou várias janelas)
# ===========================================================================
def _avg(vals: list[Optional[float]]) -> Optional[float]:
    nums = [x for x in vals if x is not None]
    return round(sum(nums) / len(nums), 3) if nums else None


def _first(vals: list) -> Optional[object]:
    for v in vals:
        if v not in (None, ""):
            return v
    return None


def _any_true(vals: list[Optional[bool]]) -> Optional[bool]:
    seen = [v for v in vals if v is not None]
    if not seen:
        return None
    return any(seen)


def aggregate_metrics(metrics_list: list[AwrMetrics]) -> AwrMetrics:
    """
    Funde N AwrMetrics num só. Numéricos de carga -> média (representativo por
    nó/janela); flags -> OR; segmentos quentes -> união dedup; identidade ->
    primeiro não-nulo. Para totais de cluster, prefira o AWR global (awrgrpt).
    """
    if not metrics_list:
        return AwrMetrics()
    if len(metrics_list) == 1:
        return metrics_list[0]

    out = AwrMetrics()
    g = metrics_list

    out.db_name = _first([m.db_name for m in g])
    out.oracle_version = _first([m.oracle_version for m in g])
    out.platform = _first([m.platform for m in g])
    out.rac = _any_true([m.rac for m in g])
    out.rac_instances = max(
        [m.rac_instances or 0 for m in g] + [sum(1 for m in g if m.db_name)]
    ) or None
    out.db_block_size = _first([m.db_block_size for m in g])

    out.db_cpu_pct_of_dbtime = _avg([m.db_cpu_pct_of_dbtime for m in g])
    out.buffer_hit_pct = _avg([m.buffer_hit_pct for m in g])
    out.redo_mb_per_s = _avg([m.redo_mb_per_s for m in g])
    out.block_changes_per_s = _avg([m.block_changes_per_s for m in g])
    out.logical_reads_per_s = _avg([m.logical_reads_per_s for m in g])
    out.physical_reads_per_s = _avg([m.physical_reads_per_s for m in g])
    out.single_block_read_us = _avg([m.single_block_read_us for m in g])

    out.multiblock_read_count = _first([m.multiblock_read_count for m in g])
    out.optimizer_index_cost_adj = _first([m.optimizer_index_cost_adj for m in g])
    out.optimizer_index_caching = _first([m.optimizer_index_caching for m in g])
    out.optimizer_adaptive_plans = _any_true([m.optimizer_adaptive_plans for m in g])

    out.index_contention_in_top_events = _any_true([m.index_contention_in_top_events for m in g])
    out.gc_buffer_busy_in_top_events = _any_true([m.gc_buffer_busy_in_top_events for m in g])
    out.index_in_buffer_busy_segments = _any_true([m.index_in_buffer_busy_segments for m in g])

    seen: set[tuple[str, str]] = set()
    for m in g:
        for s in m.hot_segments:
            key = (s.owner, s.name)
            if key not in seen:
                seen.add(key)
                out.hot_segments.append(s)

    for m in g:
        out.source_files.extend(m.source_files)
        out.found.extend(m.found)
        out.missing.extend(m.missing)
    # dedup preservando ordem
    out.found = list(dict.fromkeys(out.found))
    out.missing = list(dict.fromkeys(x for x in out.missing if x not in out.found))
    return out
