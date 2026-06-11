from advisor.models import SchemaMetadata, TableMeta, ColumnStats, IndexMeta
def get_metadata():
    return SchemaMetadata(
        tables=(
            TableMeta("DBN0_HUA_RAN","T1526726696",80_000_000,True,("RESULTTIME",),is_hot=True),
            TableMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G_HUA_X2INTERFACE",4_000_000,False,(),is_hot=False),
            TableMeta("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB",500_000,True,("STARTTIME",),is_hot=False),
        ),
        columns=(
            ColumnStats("DBN0_HUA_RAN","T1526726696","ENODEB_NAME",20000,0,22),
            ColumnStats("DBN0_HUA_RAN","T1526726696","X2INTERFACE_ID",50000,0,12),
            ColumnStats("DBN0_HUA_RAN","T1526726696","OBJECT",25000,0,20),
            ColumnStats("DBN0_HUA_RAN","T1526726696","RESULTTIME",2340,0,8),
            ColumnStats("DBN0_HUA_RAN","T1526726696","GRANULARITYPERIOD",2,0,4),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_HUA_X2INTERFACE","ENODEB_NAME",18000,0,22),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_HUA_X2INTERFACE","INTERFACEID",45000,0,12),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_HUA_X2INTERFACE","PEERIP",100,0,15),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_HUA_X2INTERFACE","PEERENODEB",18000,0,22),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB","MOBILE_SITE_NAME",16000,0,28),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB","NE_NAME",16000,0,22),
            ColumnStats("DBN0_EXT_ENRICH","ENR_RADIO_4G_ENODEB","STARTTIME",17,0,8),
        ),
        indexes=(
            IndexMeta("DBN0_HUA_RAN","T1526726696","T15267266962",("RESULTTIME",),False,True,True),
        ),
    )
