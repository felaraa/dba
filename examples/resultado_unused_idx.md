# Recomendação de Índices — SQL_ID `3fjgnfugy2kd6`

## 1. [CRITICAL] MERGE JOIN CARTESIAN no plano — estimativa de cardinalidade quebrada

- **Regra:** `R004_cartesian_or_bad_estimates`
- **Justificativa:** O plano contém MERGE JOIN CARTESIAN (id 5). Um produto cartesiano é escolhido quando o otimizador estima ~1 linha em um dos lados do join; se a estimativa estiver errada, o resultado explode. Cartesiano raramente se corrige com índice — a causa é estatística/estimativa. Recolha estatísticas atualizadas das tabelas e, em tabelas particionadas, das partições consultadas; verifique se há colunas correlacionadas que pediriam extended statistics; e reavalie qualquer SQL Profile/baseline existente.
- ⚠ **Mitigação:** Antes de criar índices, corrija a estimativa: DBMS_STATS.GATHER_TABLE_STATS nas tabelas/partições envolvidas (T1542455302, ENR_RADIO_4G5G_HUA_IPPATH, ENR_RADIO_4G_ENODEB). Se o cartesiano persistir com estatísticas frescas, avalie extended stats (column groups) para colunas correlacionadas e/ou um SQL Plan Baseline fixando um plano sem cartesiano.

## 2. [HIGH] Índice para eliminar full scan em ENR_RADIO_4G5G_HUA_IPPATH

- **Regra:** `R002_avoidable_full_scan`
- **Score líquido:** +0.322 (benefício 0.60 / manutenção 0.28)
- **DDL:**
  ```sql
  CREATE INDEX IX_ENR_RADIO__IPPA_NE_N_PEER ON DBN0_EXT_ENRICH.ENR_RADIO_4G5G_HUA_IPPATH (IPPATH, NE_NAME, PEERNAME, ENODEB_NAME, PEERIP);
  ```
- **Justificativa:** ENR_RADIO_4G5G_HUA_IPPATH sofre TABLE ACCESS FULL (id 9) e participa de join por igualdade em IPPATH. Seletividade estimada do join é alta, então probe indexado tende a vencer o full scan (ambiente não-Exadata, sem Smart Scan). Inclui cobertura de PEERNAME, ENODEB_NAME, PEERIP para evitar table access.

## 3. [HIGH] Índice IX_4G_ENODEB_NE_START existe e serve ao join, mas ENR_RADIO_4G_ENODEB sofre FULL SCAN

- **Regra:** `R007_unused_existing_index`
- **Justificativa:** As colunas de join (NE_NAME) já são prefixo do índice IX_4G_ENODEB_NE_START (NE_NAME, STARTTIME), porém o otimizador escolheu TABLE ACCESS FULL em ENR_RADIO_4G_ENODEB. Criar índice novo é desnecessário — o problema é o índice existente não estar sendo usado. Causas prováveis:
      - o plano contém MERGE JOIN CARTESIAN: a estimativa quebrada faz o otimizador preferir full scan + cartesiano ao probe indexado — corrija a estimativa (estatísticas) primeiro
      - estatísticas da tabela/índice ou das partições desatualizadas
      - índice INVISIBLE ou em estado UNUSABLE
      - conversão implícita de tipo ou função sobre a coluna de join anulando o uso do índice
      - skew de dados sem histograma, levando a estimativa de seletividade ruim
- ⚠ **Mitigação:** Verifique visibilidade/estado: SELECT status, visibility FROM dba_indexes WHERE index_name='IX_4G_ENODEB_NE_START';
- ⚠ **Mitigação:** Verifique idade das estatísticas: SELECT last_analyzed, num_rows FROM dba_tables WHERE table_name='ENR_RADIO_4G_ENODEB'; e dba_ind_statistics para o índice.
- ⚠ **Mitigação:** Force o índice em teste para comparar custo: SELECT /*+ INDEX(@... IX_4G_ENODEB_NE_START) */ ... e compare o plano.
- ⚠ **Mitigação:** Se há MERGE JOIN CARTESIAN, recolha estatísticas das tabelas/partições ANTES de qualquer ação no índice — o cartesiano é a causa raiz provável.

## 4. [HIGH] Mitigar hot block em índice de T1542455302 liderado por RESULTTIME

- **Regra:** `R900_rac_hotblock_mitigation`
- **Justificativa:** O ambiente RAWDB já apresenta 'enq: TX - index contention' no top de eventos e índices de chave sequencial dominando Buffer Busy Waits. Um índice em T1542455302 liderado por RESULTTIME (coluna crescente) sobre tabela de alto DML reproduz esse padrão de hot leaf block entre as 2 instâncias RAC.
- ⚠ **Mitigação:** Ao criar índice liderado por RESULTTIME em T1542455302, mitigue a contenção de leaf block: (a) considere índice GLOBAL com particionamento HASH nas colunas de probe, ou (b) eleve INITRANS do índice (ex.: INITRANS 8) e ajuste PCTFREE, ou (c) se a query permitir, lidere o índice por uma coluna de igualdade mais distribuída em vez da coluna crescente.

