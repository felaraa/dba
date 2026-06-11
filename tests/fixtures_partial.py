from advisor.models import SchemaMetadata, TableMeta, ColumnStats, IndexMeta
def get_metadata():
    # Simula o cenário real: T1526726713 NÃO foi coletada (falta nos metadados),
    # só ENR_RADIO_4G_CELLS veio. T1526726713 é particionada no PLANO.
    return SchemaMetadata(
        tables=(
            TableMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS",7466672,True,("STARTTIME",),is_hot=False,
                      last_analyzed="2026-06-10 20:45", stale_stats=True),
        ),
        columns=(
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS","MOBILE_SITE_NAME",16000,0,28),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS","CELL_NAME",70000,0,20),
        ),
        indexes=(),
    )
