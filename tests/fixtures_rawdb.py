"""
fixtures_rawdb.py — Metadados reais (cardinalidade) coletados do RAWDB.

Expõe get_metadata() consumido pelo cli quando --source fixture. Em produção
estes mesmos dados vêm do OracleMetadataCollector lendo os DBA_*.
Valores extraídos de dba_tab_col_statistics / dba_part_tables / dba_indexes.
"""
from advisor.models import (ColumnStats, IndexMeta, SchemaMetadata, TableMeta)


def get_metadata() -> SchemaMetadata:
    return SchemaMetadata(
        tables=(
            TableMeta("DBN0_HUA_RAN", "T1542455817", 100_000_000, True,
                      ("RESULTTIME",), is_hot=True),
            TableMeta("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", 500_000, True,
                      ("STARTTIME",), is_hot=False),
            TableMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", 33_000, False,
                      (), is_hot=False),
        ),
        columns=(
            ColumnStats("DBN0_HUA_RAN", "T1542455817", "OBJECT", 25319, 36368, 20, "HYBRID"),
            ColumnStats("DBN0_HUA_RAN", "T1542455817", "LINKNO", 10331, 36368, 12, "HYBRID"),
            ColumnStats("DBN0_HUA_RAN", "T1542455817", "RESULTTIME", 2340, 0, 8, "HYBRID"),
            ColumnStats("DBN0_HUA_RAN", "T1542455817", "GRANULARITYPERIOD", 2, 0, 4, "NONE"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "NE_NAME", 20632, 0, 22, "HYBRID"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "STARTTIME", 17, 0, 8, "FREQUENCY"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "SITE_TYPE", 5, 0, 10, "NONE"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "MOBILE_SITE_NAME", 18000, 0, 28, "NONE"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "GNODEB_LATITUDE", 9000, 0, 44, "NONE"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "GNODEB_LONGITUDE", 9000, 0, 44, "NONE"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", "NE_NAME", 14062, 0, 22, "NONE"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", "LINKNO", 3282, 0, 12, "HYBRID"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", "PEERNAME", 97, 0, 18, "FREQUENCY"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", "PEERIP", 97, 0, 15, "NONE"),
            ColumnStats("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", "ENODEB_NAME", 14054, 0, 24, "NONE"),
        ),
        indexes=(
            IndexMeta("DBN0_HUA_RAN", "T1542455817", "T15424558172", ("RESULTTIME",),
                      False, True, True),
            IndexMeta("DBN0_EXT_ENRICH", "ENR_RADIO_5G_GNODEB", "PK_ENR_RADIO_5G_GNODEB",
                      ("STARTTIME", "NE_NAME"), True, True, False),
            IndexMeta("DBN0_EXT_ENRICH", "ENR_RADIO_4G5G_HUA_SCTP", "IX_ENRSCTP_NE_LINK",
                      ("NE_NAME", "LINKNO", "PEERNAME", "PEERIP"), False, False, False),
        ),
    )
