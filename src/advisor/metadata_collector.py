"""
metadata_collector.py — Coleta SchemaMetadata.

Define uma interface (MetadataCollector) com duas implementações:
  - OracleMetadataCollector: conecta via python-oracledb e lê os dicionários
    DBA_* reais. Use em produção (--source db).
  - FixtureMetadataCollector: devolve metadados pré-carregados (dicts), para
    demonstração/testes sem banco (--source fixture).

A interface permite trocar a fonte sem afetar engine, regras ou parsers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .models import (ColumnStats, IndexMeta, SchemaMetadata, TableMeta)


class MetadataCollector(ABC):
    @abstractmethod
    def collect(self, tables: list[tuple[Optional[str], str]]) -> SchemaMetadata:
        """tables: lista de (owner, table_name). Retorna metadados consolidados."""
        ...


# ---------------------------------------------------------------------------
# Produção: Oracle via python-oracledb
# ---------------------------------------------------------------------------
class OracleMetadataCollector(MetadataCollector):
    """
    Lê estatísticas reais. Requer python-oracledb e privilégio de leitura nos
    DBA_* (ou ALL_* / USER_* — ajuste as views se não tiver DBA).

    Marca is_hot via lista de segmentos quentes opcional (vinda do AWR / perfil).
    """
    def __init__(self, connection, hot_segments: Optional[set[str]] = None):
        self.conn = connection
        self.hot = hot_segments or set()

    def collect(self, tables):
        # pares (owner, name); owner pode ser None se não veio na query
        pairs = [(o, n) for o, n in tables]
        names = [n for _, n in pairs]
        owners = [o for o, _ in pairs if o]
        cur = self.conn.cursor()

        tmeta = self._tables(cur, owners, names)
        cmeta = self._columns(cur, owners, names)
        imeta = self._indexes(cur, owners, names)
        cur.close()

        # diagnóstico de cobertura: o que a query pediu vs o que foi coletado
        collected = {t.name for t in tmeta}
        self.missing = [(o, n) for o, n in pairs if n not in collected]
        return SchemaMetadata(tables=tuple(tmeta), columns=tuple(cmeta),
                              indexes=tuple(imeta))

    def _in_clause(self, items, prefix="b"):
        """Gera placeholders nomeados (:b0,:b1,...) e o dict de binds."""
        binds = {f"{prefix}{i}": v for i, v in enumerate(items)}
        placeholders = ",".join(f":{k}" for k in binds) or "NULL"
        return placeholders, binds

    def _owner_filter(self, owners):
        """Cláusula opcional AND owner IN (...) — só se houver owners conhecidos."""
        if not owners:
            return "", {}
        ph, binds = self._in_clause(list(set(owners)), prefix="o")
        return f" AND {{tbl}}.owner IN ({ph})", binds

    def _tables(self, cur, owners, names):
        ph, binds = self._in_clause(list(set(names)))
        ofilt, obinds = self._owner_filter(owners)
        binds.update(obinds)
        # DBA_TABLES não inclui VIEWS; um UNION com DBA_VIEWS garante que views
        # (ex.: V_ENR_RADIO_4G_CELLS) também sejam reconhecidas (como não
        # particionadas, sem num_rows próprio).
        sql = f"""
            SELECT t.owner, t.table_name, t.num_rows,
                   NVL2(pt.table_name,'YES','NO') partitioned, 'TABLE' kind
            FROM dba_tables t
            LEFT JOIN dba_part_tables pt
              ON t.owner=pt.owner AND t.table_name=pt.table_name
            WHERE t.table_name IN ({ph}){ofilt.format(tbl='t')}
            UNION ALL
            SELECT v.owner, v.view_name, NULL, 'NO', 'VIEW'
            FROM dba_views v
            WHERE v.view_name IN ({ph}){ofilt.format(tbl='v')}
        """
        # binds repetidos para o 2º bloco do UNION
        binds2 = {f"{k}_2" if False else k: v for k, v in binds.items()}
        # python-oracledb reusa o mesmo bind nomeado em múltiplas posições, então
        # não precisamos duplicar; o mesmo :b0.. e :o0.. servem aos dois blocos.

        out = []
        try:
            rows = cur.execute(sql, binds).fetchall()
        except Exception:
            # fallback sem o UNION de views, caso DBA_VIEWS não esteja acessível
            sql_t = f"""
                SELECT t.owner, t.table_name, t.num_rows,
                       NVL2(pt.table_name,'YES','NO') partitioned, 'TABLE' kind
                FROM dba_tables t
                LEFT JOIN dba_part_tables pt
                  ON t.owner=pt.owner AND t.table_name=pt.table_name
                WHERE t.table_name IN ({ph}){ofilt.format(tbl='t')}
            """
            rows = cur.execute(sql_t, binds).fetchall()

        for owner, name, num_rows, part, kind in rows:
            # cada tabela é processada isoladamente: uma falha de stats em uma
            # NÃO impede a coleta das demais
            try:
                pkey = self._part_key(cur, owner, name) if part == "YES" else ()
            except Exception:
                pkey = ()
            try:
                la, stale, stale_parts = self._stats_health(cur, owner, name,
                                                            part == "YES")
            except Exception:
                la, stale, stale_parts = None, None, ()
            out.append(TableMeta(owner, name, num_rows, part == "YES", pkey,
                                 name in self.hot, last_analyzed=la,
                                 stale_stats=stale, stale_partitions=stale_parts))
        return out

    def _stats_health(self, cur, owner, name, partitioned):
        """Coleta last_analyzed, flag stale e partições com estatística obsoleta."""
        last_analyzed = stale = None
        stale_parts: list[str] = []
        try:
            row = cur.execute("""
                SELECT TO_CHAR(last_analyzed,'YYYY-MM-DD HH24:MI'), stale_stats
                FROM dba_tab_statistics
                WHERE owner=:o AND table_name=:n AND object_type='TABLE'
            """, {"o": owner, "n": name}).fetchone()
            if row:
                last_analyzed, stale_flag = row
                stale = (stale_flag == "YES")
        except Exception:
            pass
        if partitioned:
            try:
                rows = cur.execute("""
                    SELECT partition_name
                    FROM dba_tab_statistics
                    WHERE owner=:o AND table_name=:n AND object_type='PARTITION'
                      AND stale_stats='YES'
                    ORDER BY partition_name
                """, {"o": owner, "n": name}).fetchall()
                stale_parts = [r[0] for r in rows]
            except Exception:
                pass
        return last_analyzed, stale, tuple(stale_parts)

    def _part_key(self, cur, owner, name):
        rows = cur.execute("""
            SELECT column_name FROM dba_part_key_columns
            WHERE owner=:o AND name=:n ORDER BY column_position
        """, {"o": owner, "n": name}).fetchall()
        return tuple(r[0] for r in rows)

    def _columns(self, cur, owners, names):
        ph, binds = self._in_clause(list(set(names)))
        ofilt, obinds = self._owner_filter(owners)
        binds.update(obinds)
        sql = f"""
            SELECT owner, table_name, column_name, num_distinct, num_nulls,
                   avg_col_len, histogram
            FROM dba_tab_col_statistics s
            WHERE table_name IN ({ph}){ofilt.format(tbl='s')}
        """
        return [ColumnStats(o, t, c, nd, nn, acl, hist)
                for (o, t, c, nd, nn, acl, hist) in cur.execute(sql, binds)]

    def _indexes(self, cur, owners, names):
        ph, binds = self._in_clause(list(set(names)))
        if owners:
            oph, obinds = self._in_clause(list(set(owners)), prefix="o")
            owner_clause = f" AND i.table_owner IN ({oph})"
            binds.update(obinds)
        else:
            owner_clause = ""
        # LOCALITY vem de DBA_PART_INDEXES (pi), não de DBA_INDEXES.
        # IMPORTANTE: em DBA_INDEXES, i.owner é o owner do ÍNDICE e i.table_owner
        # é o owner da TABELA. Filtramos pela tabela via i.table_owner.
        sql = f"""
            SELECT i.owner, i.table_name, i.index_name, i.uniqueness,
                   i.partitioned, NVL(pi.locality,'NONE') locality
            FROM dba_indexes i
            LEFT JOIN dba_part_indexes pi
              ON i.owner=pi.owner AND i.index_name=pi.index_name
            WHERE i.table_name IN ({ph}){owner_clause}
        """
        out = []
        # IMPORTANTE: materializar com fetchall() ANTES do loop. _index_cols e
        # _index_usage reexecutam neste MESMO cursor; se iterássemos o cursor de
        # forma preguiçosa, a primeira subconsulta interna descartaria o result
        # set externo e quase todos os índices seriam perdidos silenciosamente
        # (bug real: tabela com 5 índices voltava com 0). fetchall() isola.
        rows = cur.execute(sql, binds).fetchall()
        for o, t, iname, uniq, part, loc in rows:
            cols = self._index_cols(cur, o, iname)
            usage = self._index_usage(cur, o, iname)
            out.append(IndexMeta(o, t, iname, cols, uniq == "UNIQUE",
                                 part == "YES", loc == "LOCAL",
                                 last_used=usage.get("last_used"),
                                 used=usage.get("used", True)))
        return out

    def _index_cols(self, cur, owner, index_name):
        rows = cur.execute("""
            SELECT column_name FROM dba_ind_columns
            WHERE index_owner=:o AND index_name=:i ORDER BY column_position
        """, {"o": owner, "i": index_name}).fetchall()
        return tuple(r[0] for r in rows)

    def _index_usage(self, cur, owner, index_name):
        # DBA_INDEX_USAGE (19c) chaveia por OBJECT_ID; resolvemos o object_id
        # do índice por owner+name para não confundir índices homônimos.
        try:
            row = cur.execute("""
                SELECT u.total_access_count, u.last_used
                FROM   dba_index_usage u
                JOIN   dba_objects o ON o.object_id = u.object_id
                WHERE  o.owner = :o AND o.object_name = :i
                  AND  o.object_type = 'INDEX'
            """, {"o": owner, "i": index_name}).fetchone()
            if row:
                return {"used": (row[0] or 0) > 0, "last_used": str(row[1])}
        except Exception:
            # view ausente, sem privilégio, ou esquema diferente — assume usado
            pass
        return {"used": True, "last_used": None}


# ---------------------------------------------------------------------------
# Demonstração/testes: fixture (sem banco)
# ---------------------------------------------------------------------------
class FixtureMetadataCollector(MetadataCollector):
    def __init__(self, metadata: SchemaMetadata):
        self._md = metadata

    def collect(self, tables) -> SchemaMetadata:
        return self._md
