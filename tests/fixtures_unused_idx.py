from advisor.models import SchemaMetadata, TableMeta, ColumnStats, IndexMeta
def get_metadata():
    return SchemaMetadata(
        tables=(
            TableMeta("DBN0_HUA_RAN","T1542455302",90_000_000,True,("RESULTTIME",),is_hot=True),
            TableMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G5G_HUA_IPPATH",17_500,False,(),is_hot=False),
            TableMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB",500_000,True,("STARTTIME",),is_hot=False),
        ),
        columns=(
            ColumnStats("DBN0_HUA_RAN","T1542455302","OBJECT",25000,0,20),
            ColumnStats("DBN0_HUA_RAN","T1542455302","IPPATHID",40000,0,12),
            ColumnStats("DBN0_HUA_RAN","T1542455302","RESULTTIME",2340,0,8),
            ColumnStats("DBN0_HUA_RAN","T1542455302","GRANULARITYPERIOD",2,0,4),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G5G_HUA_IPPATH","IPPATH",16000,0,12),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G5G_HUA_IPPATH","NE_NAME",15000,0,22),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G5G_HUA_IPPATH","PEERNAME",97,0,18),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G5G_HUA_IPPATH","PEERIP",97,0,15),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G5G_HUA_IPPATH","ENODEB_NAME",15000,0,24),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB","NE_NAME",16000,0,22),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB","STARTTIME",17,0,8),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB","MOBILE_SITE_NAME",16000,0,28),
        ),
        indexes=(
            IndexMeta("DBN0_HUA_RAN","T1542455302","IX_T1542455302_OBJ_RTIME",("OBJECT","RESULTTIME"),False,True,True),
            # O ÍNDICE QUE JÁ EXISTE no banco real:
            IndexMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB","IX_4G_ENODEB_NE_START",("NE_NAME","STARTTIME"),False,True,True),
        ),
    )
