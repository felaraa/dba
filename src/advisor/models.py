"""
models.py — Contratos de dados compartilhados entre todos os módulos.

Estes dataclasses são a "linguagem" que liga parser de SQL, parser de plano,
coletor de metadados, perfil de ambiente e motor de regras. Nenhum módulo
conhece a implementação interna do outro; todos falam via estes modelos.

São imutáveis (frozen) sempre que possível, para que uma regra não possa,
por engano, mutar o contexto que outra regra vai ler depois.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# SQL — saída do parser de SQL
# ---------------------------------------------------------------------------
class PredicateKind(str, Enum):
    EQUALITY = "equality"      # a.OBJECT = k.NE_NAME  ou  col = :bind
    RANGE = "range"            # col >= :b AND col < :b2
    IN_LIST = "in_list"
    OTHER = "other"


@dataclass(frozen=True)
class ColumnRef:
    """Referência a uma coluna qualificada por alias de tabela."""
    table_alias: str
    column: str

    def __str__(self) -> str:
        return f"{self.table_alias}.{self.column}"


@dataclass(frozen=True)
class JoinPredicate:
    """Predicado de junção entre duas colunas de tabelas distintas."""
    left: ColumnRef
    right: ColumnRef


@dataclass(frozen=True)
class FilterPredicate:
    """Predicado de filtro sobre uma coluna (vs bind/literal)."""
    column: ColumnRef
    kind: PredicateKind


@dataclass(frozen=True)
class TableRef:
    """Tabela referenciada na query, com seu alias."""
    owner: Optional[str]
    name: str
    alias: str


@dataclass(frozen=True)
class ParsedQuery:
    """Saída estruturada do sql_parser."""
    raw_sql: str
    tables: tuple[TableRef, ...]
    join_predicates: tuple[JoinPredicate, ...]
    filter_predicates: tuple[FilterPredicate, ...]
    # colunas projetadas/agrupadas por alias de tabela (para decidir cobertura)
    projected_columns: tuple[ColumnRef, ...]
    group_by_columns: tuple[ColumnRef, ...]

    def alias_to_table(self) -> dict[str, TableRef]:
        return {t.alias: t for t in self.tables}


# ---------------------------------------------------------------------------
# PLANO — saída do parser de plano (DBMS_XPLAN / SQL Monitor)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanOperation:
    """Uma linha do plano de execução com estatísticas de runtime."""
    op_id: int
    operation: str               # ex.: "NESTED LOOPS", "TABLE ACCESS FULL"
    object_name: Optional[str]   # ex.: "T1542455817", "PK_ENR_RADIO_5G_GNODEB"
    estim_rows: Optional[float]  # E-Rows
    actual_rows: Optional[float] # A-Rows (None se plano sem runtime)
    executions: Optional[float]  # Starts/Execs
    buffer_gets: Optional[float]
    read_bytes: Optional[float]
    # predicados associados a esta operação (texto bruto), separados por tipo
    access_predicates: tuple[str, ...] = ()
    filter_predicates: tuple[str, ...] = ()
    parent_id: Optional[int] = None

    @property
    def rows_per_exec(self) -> Optional[float]:
        if self.actual_rows is None or not self.executions:
            return None
        return self.actual_rows / self.executions


@dataclass(frozen=True)
class ParsedPlan:
    """Saída estruturada do plan_parser."""
    sql_id: Optional[str]
    plan_hash: Optional[str]
    operations: tuple[PlanOperation, ...]
    total_elapsed_s: Optional[float] = None
    total_buffer_gets: Optional[float] = None
    # intervenções detectadas no plano: sql_profile, baseline, outline, etc.
    notes: tuple[str, ...] = ()
    sql_profile: Optional[str] = None

    def by_id(self) -> dict[int, PlanOperation]:
        return {op.op_id: op for op in self.operations}

    def has_runtime_stats(self) -> bool:
        return any(op.actual_rows is not None for op in self.operations)


# ---------------------------------------------------------------------------
# HISTÓRICO DE PLANOS — saída do coletor de planos por SQL_ID
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanStat:
    """
    Métricas agregadas de UM plan_hash_value de um SQL_ID. As médias são
    SEMPRE por execução, derivadas dos totais — assim planos com contagens de
    execução muito diferentes ficam comparáveis. Vem de GV$SQL (cursores no
    shared pool) e/ou DBA_HIST_SQLSTAT (AWR), já fundidas pelo coletor.
    """
    plan_hash: str
    sources: tuple[str, ...]          # ('cursor',), ('awr',) ou ambos
    executions: float                 # total de execuções somadas
    avg_elapsed_s: Optional[float]    # elapsed por execução (s)
    avg_buffer_gets: Optional[float]  # buffer gets por execução
    avg_cpu_s: Optional[float]        # cpu por execução (s)
    avg_rows: Optional[float]         # linhas processadas por execução
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None

    @property
    def cost_metric(self) -> Optional[float]:
        """Métrica única para ranquear: elapsed/exec; cai para buffer_gets/exec."""
        if self.avg_elapsed_s is not None:
            return self.avg_elapsed_s
        return self.avg_buffer_gets


@dataclass(frozen=True)
class PlanHistory:
    """
    Conjunto de planos distintos observados para um SQL_ID. Uma query com mais
    de um plan_hash sofre de INSTABILIDADE DE PLANO — o otimizador escolhe
    planos diferentes ao longo do tempo (bind peeking, cardinality feedback,
    estatística obsoleta, etc.), e basta um plano ruim para degradar o serviço.
    """
    sql_id: Optional[str]
    plans: tuple[PlanStat, ...] = ()

    def distinct_count(self) -> int:
        return len({p.plan_hash for p in self.plans})

    def _eligible(self) -> list[PlanStat]:
        """Planos com pelo menos uma execução e métrica de custo conhecida."""
        return [p for p in self.plans
                if p.executions and p.cost_metric is not None]

    def best(self) -> Optional[PlanStat]:
        """Plano com menor custo por execução (o 'melhor plano' candidato)."""
        elig = self._eligible()
        return min(elig, key=lambda p: p.cost_metric) if elig else None

    def worst(self) -> Optional[PlanStat]:
        elig = self._eligible()
        return max(elig, key=lambda p: p.cost_metric) if elig else None

    def find(self, plan_hash: Optional[str]) -> Optional[PlanStat]:
        if plan_hash is None:
            return None
        for p in self.plans:
            if p.plan_hash == str(plan_hash):
                return p
        return None


# ---------------------------------------------------------------------------
# METADADOS — saída do coletor (python-oracledb) ou entrada manual
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnStats:
    owner: str
    table_name: str
    column_name: str
    num_distinct: Optional[float]
    num_nulls: Optional[float]
    avg_col_len: Optional[float]   # bytes — usado p/ custo de cobertura
    histogram: Optional[str] = None


@dataclass(frozen=True)
class TableMeta:
    owner: str
    name: str
    num_rows: Optional[float]
    partitioned: bool
    partition_key: tuple[str, ...] = ()   # colunas da chave de partição
    # marcação de "tabela quente" derivada do AWR (alto DML / contenção)
    is_hot: bool = False
    # diagnóstico de estatísticas (preenchido pelo coletor Oracle)
    last_analyzed: Optional[str] = None
    stale_stats: Optional[bool] = None    # USER_TAB_STATISTICS.STALE_STATS='YES'
    stale_partitions: tuple[str, ...] = ()  # partições com estatística obsoleta


@dataclass(frozen=True)
class IndexMeta:
    owner: str
    table_name: str
    index_name: str
    columns: tuple[str, ...]
    unique: bool
    partitioned: bool
    local: bool
    last_used: Optional[str] = None       # de DBA_INDEX_USAGE
    used: bool = True


@dataclass(frozen=True)
class SchemaMetadata:
    """Tudo que o coletor sabe sobre as tabelas envolvidas."""
    tables: tuple[TableMeta, ...]
    columns: tuple[ColumnStats, ...]
    indexes: tuple[IndexMeta, ...]

    def table(self, owner: Optional[str], name: str) -> Optional[TableMeta]:
        for t in self.tables:
            if t.name == name and (owner is None or t.owner == owner):
                return t
        return None

    def column(self, table_name: str, column_name: str) -> Optional[ColumnStats]:
        for c in self.columns:
            if c.table_name == table_name and c.column_name == column_name:
                return c
        return None

    def indexes_of(self, table_name: str) -> list[IndexMeta]:
        return [i for i in self.indexes if i.table_name == table_name]


# ---------------------------------------------------------------------------
# RECOMENDAÇÃO — saída de cada regra e do motor
# ---------------------------------------------------------------------------
class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Recommendation:
    """O que uma regra produz. Pode ser um índice, ou um alerta de mitigação."""
    rule_id: str
    title: str
    severity: Severity
    rationale: str                       # explicação legível
    ddl: Optional[str] = None            # CREATE INDEX ... (None p/ alertas)
    target_table: Optional[str] = None
    estimated_benefit: float = 0.0       # score relativo (0..1+) p/ ranquear
    estimated_maint_cost: float = 0.0    # penalidade de manutenção (0..1+)
    tags: list[str] = field(default_factory=list)
    # avisos anexados (ex.: mitigação de RAC para índice em tabela quente)
    warnings: list[str] = field(default_factory=list)
    # campo auxiliar usado pela consolidação no reporter (não exibido)
    _cols: list[str] = field(default_factory=list)

    @property
    def net_score(self) -> float:
        return self.estimated_benefit - self.estimated_maint_cost
