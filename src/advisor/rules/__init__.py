"""
advisor.rules — pacote de regras (plugins).

Cada módulo aqui dentro define uma ou mais subclasses de Rule e é descoberto
automaticamente pelo RuleEngine. Este __init__ expõe apenas helpers puros e
reutilizáveis (montagem de DDL, ordenação de colunas, custo de cobertura).
Helpers NÃO tomam decisões de tuning — são utilidades; a decisão fica na regra.
"""
from __future__ import annotations

from ..env_profile import EnvProfile
from ..models import ColumnRef, TableRef


def _clean_token(s: str) -> str:
    """Normaliza um pedaço de nome: maiúsculo, sem underscores nas pontas."""
    return s.upper().strip("_")


def build_index_name(table: str, columns: list[str], suffix: str = "",
                     owner: str | None = None) -> str:
    """
    Gera nome de índice determinístico, <=30 chars (limite Oracle), incluindo
    um prefixo do owner, sem underscores duplicados nem nas pontas.

    Ex.: owner=DBN0_EXT_ENRICH, table=ENR_RADIO_5G_GNODEB, cols=[NE_NAME,STARTTIME]
         -> IX_DBN0_ENR_RADIO_NE_ST  (truncado e limpo, <=30)
    """
    parts = ["IX"]
    if owner:
        # primeiro segmento do owner (antes do 1º '_') como abreviação
        parts.append(_clean_token(owner.split("_")[0])[:6])
    parts.append(_clean_token(table)[:12])
    if columns:
        col_tok = "_".join(_clean_token(c)[:4] for c in columns[:3])
        parts.append(_clean_token(col_tok))
    if suffix:
        parts.append(_clean_token(suffix))

    # junta, colapsa underscores múltiplos, remove das pontas, limita a 30
    name = "_".join(p for p in parts if p)
    while "__" in name:
        name = name.replace("__", "_")
    name = name.strip("_")
    return name[:30].rstrip("_")


def order_columns(equality: list[str], range_cols: list[str],
                  covering: list[str]) -> list[str]:
    """
    Ordem canônica de colunas num índice composto:
      1) colunas de igualdade (melhor seletividade no probe)
      2) coluna de range (permite range scan eficiente)
      3) colunas de cobertura (evitam table access)
    Remove duplicatas preservando a ordem.
    """
    ordered: list[str] = []
    for group in (equality, range_cols, covering):
        for c in group:
            if c not in ordered:
                ordered.append(c)
    return ordered


def covering_cost(env: EnvProfile, col_lengths: dict[str, float],
                  covering: list[str]) -> float:
    """
    Custo estimado de adicionar colunas de cobertura, em unidades de score.
    Penaliza fortemente colunas largas (lat/long/nomes) conforme o perfil.
    """
    cost = 0.0
    per_byte = env.score("coverage_cost_per_byte", 0.004)
    wide = env.wide_column_bytes
    for c in covering:
        length = col_lengths.get(c, 8.0)
        cost += length * per_byte
        if length > wide:
            cost += 0.15  # penalidade extra por coluna larga
    return cost


def is_local_index(table: TableRef, partition_key: tuple[str, ...],
                   leading_col: str) -> bool:
    """
    Índice deve ser LOCAL se a tabela é particionada e a coluna líder casa
    (ou se a query filtra pela chave de partição). Caso contrário, GLOBAL.
    """
    if not partition_key:
        return False
    return True  # particionada → LOCAL por padrão (alinha pruning)


def build_index_ddl(owner: str, table: str, index_name: str,
                    columns: list[str], local: bool) -> str:
    """
    Monta o DDL completo: CREATE INDEX + coleta de estatísticas do índice.
    O GATHER_INDEX_STATS segue o padrão pedido (GRANULARITY=ALL, DEGREE=16,
    FORCE=TRUE) e é essencial: um índice novo sem estatísticas pode não ser
    usado pelo otimizador.
    """
    create = (f"CREATE INDEX {index_name} ON {owner}.{table} "
              f"({', '.join(columns)}){' LOCAL' if local else ''};")
    gather = (f"EXEC DBMS_STATS.GATHER_INDEX_STATS"
              f"(OWNNAME=>'{owner}', INDNAME=>'{index_name}', "
              f"GRANULARITY=>'ALL', DEGREE=>16, FORCE=>TRUE);")
    return create + "\n" + gather


def qualified(owner: str | None, name: str) -> str:
    return f"{owner}.{name}" if owner else name


def _norm(cols) -> list[str]:
    return [c.upper() for c in cols]


def existing_index_covering(metadata, table_name: str,
                            leading_cols: list[str]):
    """
    Retorna o IndexMeta existente que já SERVE para um probe pelas colunas de
    IGUALDADE `leading_cols`, ou None. "Serve" = as primeiras N colunas do
    índice são EXATAMENTE o CONJUNTO `leading_cols` (N = len(leading_cols)),
    com colunas extras à direita (range/cobertura) permitidas.

    A comparação é por CONJUNTO, não por sequência: para predicados de
    IGUALDADE a ordem entre as colunas líderes não muda a utilidade do índice
    no probe. Assim um índice (MOBILE_SITE_NAME, CELL_NAME, STARTTIME) é
    reconhecido como adequado para um join por (CELL_NAME, MOBILE_SITE_NAME) —
    evitando recomendar um índice REDUNDANTE que só difere na ordem das colunas
    de igualdade (bug real: a query a3yqht3qtyyhy recebia uma sugestão de índice
    idêntico, em outra ordem, ao IX_ENR4G_MSITE_CELL_START já existente).

    Como exatidão-de-ordem é um caso particular de igualdade-de-conjunto, esta
    versão nunca deixa de reconhecer o que a versão por sequência reconhecia.
    """
    want = _norm(leading_cols)
    if not want:
        return None
    want_set = set(want)
    for ix in metadata.indexes_of(table_name):
        have = _norm(ix.columns)
        if len(have) >= len(want) and set(have[:len(want)]) == want_set:
            return ix
    return None


def existing_index_exact_or_superset(metadata, table_name: str,
                                     cols: list[str]):
    """
    Retorna índice existente cujo conjunto inicial de colunas é exatamente
    `cols` ou um superconjunto com `cols` como prefixo (mesma ordem).
    Usado para detectar recomendação redundante de índice composto/cobertura.
    """
    want = _norm(cols)
    for ix in metadata.indexes_of(table_name):
        have = _norm(ix.columns)
        if have[:len(want)] == want:
            return ix
    return None
