# Recomendação de Índices — SQL_ID `9brm2zn013zu1`

**Contexto do plano:** SQL Profile ativo: "coe_9brm2zn013zu1_953480854"

## 1. [CRITICAL] Índice de probe em T1526726696 para eliminar filtro pós-acesso

- **Regra:** `R001_filter_should_be_access`
- **Score líquido:** +0.400 (benefício 1.00 / manutenção 0.60)
- **DDL:**
  ```sql
  CREATE INDEX IX_T152672669_OBJE_ENOD_X2IN ON DBN0_HUA_RAN.T1526726696 (OBJECT, ENODEB_NAME, X2INTERFACE_ID, RESULTTIME) LOCAL;
  ```
- **Justificativa:** O join ("A"."ENODEB_NAME"="L"."MOBILE_SITE_NAME" AND "A"."OBJECT"="L"."NE_NAME" AND "A"."X2INTERFACE_ID"="K"."INTERFACEID" AND "A"."ENODEB_NAME"="K"."ENODEB_NAME") é aplicado como FILTRO (id 12) após um acesso que percorre ~2,162,311,473 linhas, contra apenas 1 no resultado final — desperdício de ~2,162,311,473x. Existe índice em T1526726696 liderado por outra coluna (ex.: chave de partição), o que leva o otimizador a varrer e filtrar. Um índice liderado por OBJECT transforma o filtro em probe direto.
- ⚠ **Mitigação:** Ao criar índice liderado por RESULTTIME em T1526726696, mitigue a contenção de leaf block: (a) considere índice GLOBAL com particionamento HASH nas colunas de probe, ou (b) eleve INITRANS do índice (ex.: INITRANS 8) e ajuste PCTFREE, ou (c) se a query permitir, lidere o índice por uma coluna de igualdade mais distribuída em vez da coluna crescente.

## 2. [CRITICAL] MERGE JOIN CARTESIAN no plano — estimativa de cardinalidade quebrada

- **Regra:** `R004_cartesian_or_bad_estimates`
- **Justificativa:** O plano contém MERGE JOIN CARTESIAN (id 5). Um produto cartesiano é escolhido quando o otimizador estima ~1 linha em um dos lados do join; se a estimativa estiver errada, o resultado explode. Cartesiano raramente se corrige com índice — a causa é estatística/estimativa. Recolha estatísticas atualizadas das tabelas e, em tabelas particionadas, das partições consultadas; verifique se há colunas correlacionadas que pediriam extended statistics; e reavalie qualquer SQL Profile/baseline existente.
- ⚠ **Mitigação:** Antes de criar índices, corrija a estimativa: DBMS_STATS.GATHER_TABLE_STATS nas tabelas/partições envolvidas (T1526726696, ENR_RADIO_4G_HUA_X2INTERFACE, ENR_RADIO_4G_ENODEB). Se o cartesiano persistir com estatísticas frescas, avalie extended stats (column groups) para colunas correlacionadas e/ou um SQL Plan Baseline fixando um plano sem cartesiano.

## 3. [HIGH] Índice para eliminar full scan em ENR_RADIO_4G_ENODEB

- **Regra:** `R002_avoidable_full_scan`
- **Score líquido:** +0.550 (benefício 0.60 / manutenção 0.05)
- **DDL:**
  ```sql
  CREATE INDEX IX_ENR_RADIO__NE_N_MOBI ON DBN0_EXT_ENRICH.ENR_RADIO_4G_ENODEB (NE_NAME, MOBILE_SITE_NAME) LOCAL;
  ```
- **Justificativa:** ENR_RADIO_4G_ENODEB sofre TABLE ACCESS FULL (id 7) e participa de join por igualdade em NE_NAME. Seletividade estimada do join é alta, então probe indexado tende a vencer o full scan (ambiente não-Exadata, sem Smart Scan).

## 4. [HIGH] Intervenção de tuning já ativa neste plano

- **Regra:** `R005_existing_intervention`
- **Justificativa:** Detectada(s) intervenção(ões): SQL Profile ativo: "coe_9brm2zn013zu1_953480854". Isso altera a estratégia: o plano atual pode estar sendo forçado por essa intervenção, e recomendações de índice precisam ser validadas nesse contexto.
- ⚠ **Mitigação:** Um índice recomendado pode NÃO ser usado enquanto a intervenção fixar o plano atual. Valide o índice como INVISIBLE e verifique se o otimizador o adota mesmo com a intervenção ativa.
- ⚠ **Mitigação:** O SQL Profile tem prefixo 'coe_' (gerado via coe_xfr / SQL Tuning Advisor). Se o plano ainda está ruim, este profile pode estar obsoleto após mudança de dados/estatísticas — reavalie ou remova (DBMS_SQLTUNE.DROP_SQL_PROFILE) e recolha estatísticas antes de decidir por índice.

## 5. [HIGH] Estimativa de cardinalidade com overflow (estatísticas degeneradas)

- **Regra:** `R004_cartesian_or_bad_estimates`
- **Justificativa:** Operações 12 têm E-Rows da ordem de 4.1e+16, valor impossível que denuncia estatísticas ausentes/corrompidas ou aritmética de seletividade degenerada (frequentemente em joins múltiplos sobre colunas sem estatísticas estendidas).
- ⚠ **Mitigação:** Recolher estatísticas e considerar extended statistics para os grupos de colunas usados nos joins.

## 6. [MEDIUM] Cobertura em T1526726696 para evitar table access by rowid

- **Regra:** `R003_covering_for_aggregation`
- **Score líquido:** -0.166 (benefício 0.45 / manutenção 0.62)
- **DDL:**
  ```sql
  CREATE INDEX IX_T152672669_RESU_OBJE_ENOD_C ON DBN0_HUA_RAN.T1526726696 (RESULTTIME, OBJECT, ENODEB_NAME, X2INTERFACE_ID, GRANULARITYPERIOD) LOCAL;
  ```
- **Justificativa:** Operação id 12 lê 137MB da tabela apenas para obter GRANULARITYPERIOD. Incluí-las no índice de acesso elimina o salto à tabela. Colunas largas foram deliberadamente excluídas da cobertura para conter o tamanho do índice.
- ⚠ **Mitigação:** Ao criar índice liderado por RESULTTIME em T1526726696, mitigue a contenção de leaf block: (a) considere índice GLOBAL com particionamento HASH nas colunas de probe, ou (b) eleve INITRANS do índice (ex.: INITRANS 8) e ajuste PCTFREE, ou (c) se a query permitir, lidere o índice por uma coluna de igualdade mais distribuída em vez da coluna crescente.

