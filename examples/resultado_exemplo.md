# Recomendação de Índices — SQL_ID `24h537gmxw93d`

## 1. [CRITICAL] Índice de probe em ENR_RADIO_5G_GNODEB para eliminar filtro pós-acesso

- **Regra:** `R001_filter_should_be_access`
- **Score líquido:** +0.950 (benefício 1.00 / manutenção 0.05)
- **DDL:**
  ```sql
  CREATE INDEX IX_ENR_RADIO__NE_N_STAR ON DBN0_EXT_ENRICH.ENR_RADIO_5G_GNODEB (NE_NAME, STARTTIME) LOCAL;
  ```
- **Justificativa:** O join "A"."OBJECT"="K"."NE_NAME" é aplicado como FILTRO (id 11) após um acesso que percorre ~609,000,000 linhas, contra apenas 24,360 no resultado final — desperdício de ~25,000x. Existe índice em ENR_RADIO_5G_GNODEB liderado por outra coluna (ex.: chave de partição), o que leva o otimizador a varrer e filtrar. Um índice liderado por NE_NAME transforma o filtro em probe direto.

## 2. [MEDIUM] Cobertura em T1542455817 para evitar table access by rowid

- **Regra:** `R003_covering_for_aggregation`
- **Score líquido:** -0.166 (benefício 0.45 / manutenção 0.62)
- **DDL:**
  ```sql
  CREATE INDEX IX_T154245581_RESU_OBJE_LINK_C ON DBN0_HUA_RAN.T1542455817 (RESULTTIME, OBJECT, LINKNO, GRANULARITYPERIOD) LOCAL;
  ```
- **Justificativa:** Operação id 7 percorre 4,000,000 linhas da tabela apenas para obter GRANULARITYPERIOD. Incluí-las no índice de acesso elimina o salto à tabela. Colunas largas foram deliberadamente excluídas da cobertura para conter o tamanho do índice.
- ⚠ **Mitigação:** Ao criar índice liderado por RESULTTIME em T1542455817, mitigue a contenção de leaf block: (a) considere índice GLOBAL com particionamento HASH nas colunas de probe, ou (b) eleve INITRANS do índice (ex.: INITRANS 8) e ajuste PCTFREE, ou (c) se a query permitir, lidere o índice por uma coluna de igualdade mais distribuída em vez da coluna crescente.

