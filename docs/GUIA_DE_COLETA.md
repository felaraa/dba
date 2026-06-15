# Guia de Coleta de Dados para Análise

Este guia lista **exatamente o que coletar e como**, para alimentar o advisor
(ou para uma análise manual). Os scripts assumem SQL*Plus / SQLcl conectado ao
PDB correto. Substitua `&SQLID` e os nomes de tabela conforme o caso.

---

## 1. A query (sempre)

O texto SQL puro. Se você só tem o SQL_ID, recupere o texto completo:
```sql
SET LONG 1000000 LONGCHUNKSIZE 1000000 PAGESIZE 0 LINESIZE 32767
SELECT sql_fulltext FROM v$sql WHERE sql_id = '&SQLID' AND rownum = 1;
-- salve em query.txt
```

## 2. O plano com estatísticas de runtime (sempre)

**Preferido — SQL Monitor em XML** (traz A-Rows, Execs, hierarquia, SQL Profile):
```sql
SET LONG 2000000 LONGCHUNKSIZE 2000000 PAGESIZE 0 LINESIZE 32767 TRIMSPOOL ON
SPOOL plan.xml
SELECT DBMS_SQLTUNE.REPORT_SQL_MONITOR(
         sql_id => '&SQLID', type => 'XML', report_level => 'ALL') FROM dual;
SPOOL OFF
```
Ver se há execução monitorada antes:
```sql
SELECT sql_id, sql_exec_id, status, ROUND(elapsed_time/1e6,1) elapsed_s, inst_id
FROM   gv$sql_monitor WHERE sql_id = '&SQLID' ORDER BY sql_exec_start DESC;
```

**Alternativa — DBMS_XPLAN texto** (se não houver SQL Monitor / Tuning Pack):
```sql
-- execute a query 1x com o hint para coletar A-Rows, depois:
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(
  '&SQLID', NULL, 'ALLSTATS LAST +PREDICATE +PARTITION'));
-- salve em plan.txt
```
> Sem A-Rows o advisor não confirma explosões e pode dar falso "nenhuma
> recomendação". O parser avisa quando o plano não tem runtime stats.

## 3. Cardinalidade e metadados das tabelas (sempre)

Em produção o advisor coleta sozinho com `--source db`. Para coleta manual
(ou para montar fixture), rode para CADA tabela da query:

```sql
-- 3.1 num_rows, particionamento
SELECT t.owner, t.table_name, t.num_rows, t.avg_row_len, t.chain_cnt,
       NVL2(pt.table_name,'YES','NO') particionada
FROM   dba_tables t
LEFT JOIN dba_part_tables pt ON t.owner=pt.owner AND t.table_name=pt.table_name
WHERE  t.table_name IN ('TAB1','TAB2','TAB3');

-- 3.2 chave de partição
SELECT name, column_name, column_position
FROM   dba_part_key_columns
WHERE  name IN ('TAB1','TAB2','TAB3') ORDER BY name, column_position;

-- 3.3 cardinalidade das colunas de JOIN, FILTRO e PROJEÇÃO
SELECT table_name, column_name, num_distinct, num_nulls, avg_col_len, histogram
FROM   dba_tab_col_statistics
WHERE  table_name IN ('TAB1','TAB2','TAB3')
AND    column_name IN ('COL_JOIN1','COL_JOIN2','COL_FILTRO','...');

-- 3.4 índices existentes (evita duplicata e mostra o que estender)
SELECT i.owner, i.table_name, i.index_name, i.uniqueness, i.partitioned,
       NVL(i.locality,'NONE') locality, ic.column_name, ic.column_position
FROM   dba_indexes i
JOIN   dba_ind_columns ic
  ON   i.owner=ic.index_owner AND i.index_name=ic.index_name
WHERE  i.table_name IN ('TAB1','TAB2','TAB3')
ORDER  BY i.table_name, i.index_name, ic.column_position;

-- 3.5 uso real dos índices (19c) — detecta índices nunca usados
SELECT name, total_access_count, total_exec_count, last_used
FROM   dba_index_usage
WHERE  name IN (SELECT index_name FROM dba_indexes
                WHERE table_name IN ('TAB1','TAB2','TAB3'));
```

## 4. Quando o plano tem MERGE JOIN CARTESIAN ou estimativa ruim

Se o advisor disparar R004 (cartesiano/estimativa degenerada), colete também:

```sql
-- 4.1 quão velhas estão as estatísticas (tabela e partições)
SELECT table_name, partition_name, num_rows, last_analyzed
FROM   dba_tab_statistics
WHERE  table_name IN ('TAB1','TAB2','TAB3')
ORDER  BY table_name, last_analyzed;

-- 4.2 a query usa colunas correlacionadas no mesmo predicado? (extended stats)
--     liste os pares/trios de colunas de join da mesma tabela; ex.:
--     a.ENODEB_NAME + a.OBJECT + a.X2INTERFACE_ID
SELECT extension_name, extension
FROM   dba_stat_extensions
WHERE  table_name IN ('TAB1','TAB2','TAB3');
```

## 5. Quando há SQL Profile / Baseline ativo

Se o advisor disparar R005, colete os detalhes da intervenção:

```sql
-- 5.1 SQL Profiles existentes para o SQL
SELECT name, status, type, created, last_modified, description
FROM   dba_sql_profiles
WHERE  name LIKE '%&SQLID%' OR name LIKE 'coe_%';

-- 5.2 SQL Plan Baselines do SQL
SELECT sql_handle, plan_name, enabled, accepted, fixed, created
FROM   dba_sql_plan_baselines
WHERE  sql_text LIKE '%<trecho identificável da query>%';
```

## 6. Para recalibrar o perfil do ambiente (uma vez, ou ao mudar o cluster)

```sql
-- parâmetros de instância relevantes
SELECT name, value FROM v$parameter
WHERE  name IN ('db_block_size','optimizer_index_cost_adj','optimizer_index_caching',
  'db_file_multiblock_read_count','cpu_count','sga_target','pga_aggregate_target',
  'cluster_database','optimizer_features_enable','optimizer_adaptive_plans',
  'session_cached_cursors','use_large_pages');
```
E um **AWR report em HTML** de um período representativo, do qual se extraem:
CPU bound %, cache hit, redo, eventos de contenção (top 10), segmentos quentes
(Segment Statistics) e parâmetros do otimizador.

Não edite o YAML a mão para isso: passe o AWR para o gerador, que cria ou
atualiza o perfil automaticamente (ver **`docs/GUIA_ENV_PROFILE.md`**):

```bash
# criar
python -m advisor.awr_cli --awr awr_prod.html --out config/env_profile_prod.yaml --diag
# atualizar preservando os ajustes manuais (scoring/index_ddl)
python -m advisor.awr_cli --awr awr_novo.html --out config/env_profile_prod.yaml --update
```

Como gerar o AWR em HTML: `@?/rdbms/admin/awrrpt.sql` (escolha `html`); para RAC,
`awrrpti.sql` por instância (um arquivo por nó) ou `awrgrpt.sql` (global).

---

## Resumo — o que enviar para cada análise

| Situação | Arquivos/saídas a enviar |
|----------|--------------------------|
| Análise padrão de uma query | `query.txt` + `plan.xml` (ou `plan.txt`) + saídas do item 3 |
| Plano com cartesiano | acima + item 4 (idade das estatísticas, extended stats) |
| Plano com SQL Profile | acima + item 5 (detalhes do profile/baseline) |
| Calibrar/novo ambiente | item 6 (parâmetros + AWR HTML) |

Dica: para a análise padrão, os itens 1, 2 e 3 já bastam. Os itens 4 e 5 só são
necessários quando o próprio advisor sinalizar (R004/R005), então rode primeiro,
veja o que disparou, e colete o complemento só se preciso.
