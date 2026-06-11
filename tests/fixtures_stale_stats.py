from advisor.models import SchemaMetadata, TableMeta, ColumnStats, IndexMeta
def get_metadata():
    return SchemaMetadata(
        tables=(
            # tabela quente COM estatística obsoleta (simulando o problema real)
            TableMeta("DBN0_HUA_RAN","T1526726713",120_000_000,True,("RESULTTIME",),is_hot=True,
                      last_analyzed="2026-05-01 02:00", stale_stats=True,
                      stale_partitions=("SYS_P4521","SYS_P4522","SYS_P4523")),
            TableMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS",800_000,True,("STARTTIME",),is_hot=False,
                      last_analyzed="2026-06-09 02:00", stale_stats=False),
            TableMeta("DBN0_EXT_ENRICH","V_ENR_RADIO_4G_CELLS",None,False,(),is_hot=False),
        ),
        columns=(
            ColumnStats("DBN0_HUA_RAN","T1526726713","ENODEB_NAME",18000,0,22),
            ColumnStats("DBN0_HUA_RAN","T1526726713","LOCAL_CELL_NAME",60000,0,20),
            ColumnStats("DBN0_HUA_RAN","T1526726713","CELLID",80000,0,12),
            ColumnStats("DBN0_HUA_RAN","T1526726713","ENODEB_ID",16000,0,12),
            ColumnStats("DBN0_HUA_RAN","T1526726713","RESULTTIME",2340,0,8),
            ColumnStats("DBN0_HUA_RAN","T1526726713","GRANULARITYPERIOD",2,0,4),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS","MOBILE_SITE_NAME",16000,0,28),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS","CELL_NAME",70000,0,20),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS","STARTTIME",17,0,8),
        ),
        indexes=(
            IndexMeta("DBN0_HUA_RAN","T1526726713","T15267267132",("LOCAL_CELL_NAME","RESULTTIME"),False,True,True),
            IndexMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G_CELLS","PK_ENR_RADIO_4G_CELLS",("STARTTIME","MOBILE_SITE_NAME","CELL_NAME"),True,True,False),
        ),
    )
