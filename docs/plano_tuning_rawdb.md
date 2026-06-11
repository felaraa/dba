# Plano de Tuning — Cluster RAWDB (Oracle 19c RAC)

**Base:** análise dos AWRs das instâncias 1 e 2 (janela ~900 min/instância), parâmetros de instância e configuração de memória/HugePages do host. Ambiente **não-Exadata**, 2 nós RAC, 192 CPUs e 1 TB RAM por nó, `db_block_size` 8 KB.

> **Aviso de execução:** nenhuma alteração deste plano deve ir direto a produção. Todos os itens devem ser validados em homologação. Mudanças em RAC pesado têm efeito colateral cruzado entre instâncias; aplicar em *rolling* sempre que possível.

---

## Sumário do diagnóstico

O ambiente é **CPU-bound** (DB CPU 67–71% do DB time) com **cache hit altíssimo** (LIO 6,67M/s vs PIO 88K/s). O tempo não-CPU é dominado por **contenção de blocos de índice em RAC** e por **pressão de parsing/cursores**, não por IO físico. Logo, o maior retorno vem de reduzir contenção e CPU de parse — não de adicionar buffer cache.

Evidências-chave:
- `enq: TX - index contention`, `buffer busy waits`, `gc buffer busy acquire`, `gc current block busy` no top 10 de eventos.
- Buffer Busy concentrado em índices de chave sequencial (`NAMF_STATS_SEQ_IDX` com 27–32% sozinho).
- `library cache: mutex X` no top 10; **7.126 parses/s** com apenas **1,4 hard parse/s** (99,98% soft parse); **794M cursores abertos** no período.
- Work areas **98%+ optimal** (`sorts(disk)` desprezível) → PGA atual já suficiente.
- HugePages: **650 GB reservados**, apenas ~305 GB em uso → **~345 GB ociosos**.

---

## Prioridade 1 — Contenção de índice e sequences (maior ganho)

O padrão `enq: TX - index contention` + Buffer Busy em índices `*_SEQ_IDX` é a assinatura de **leaf block direito quente**: inserções de valores crescentes (sequence/timestamp) competindo pelo mesmo bloco-folha, agravado em RAC pelo trânsito do bloco entre os 2 nós (`gc buffer busy`).

### 1.1. Verificar cache/order das sequences
Sequences com `CACHE` baixo ou `ORDER` são causa frequente e a correção mais barata.
```sql
SELECT sequence_owner, sequence_name, cache_size, order_flag
FROM   dba_sequences
WHERE  cache_size < 1000 OR order_flag = 'Y'
ORDER  BY cache_size;
```
Para PKs/índices de alto insert em RAC, o alvo é **`CACHE` grande e `NOORDER`** (cada instância consome faixas distintas, reduzindo colisão no leaf block):
```sql
ALTER SEQUENCE <owner>.<seq> CACHE 1000 NOORDER;
```

### 1.2. Espalhar o leaf block quente dos índices sequenciais
Para os índices que lideram Buffer Busy (`NAMF_STATS_SEQ_IDX`, `NAMF_STATS_DATA_SEQ_IDX`, `PK_NAMF_STATS`), avaliar **hash partitioning global do índice** — distribui inserts por N folhas em vez de uma:
```sql
-- preferir hash global a reverse key: preserva range scan
CREATE INDEX <idx> ON <tab>(<col>)
  GLOBAL PARTITION BY HASH (<col>) PARTITIONS 32;
```
**Verificar antes** se o índice faz range scan (se faz, NÃO usar reverse key):
```sql
-- inspecionar se há predicados de range usando o índice nos planos correntes
SELECT sql_id, object_name, options
FROM   v$sql_plan
WHERE  object_name IN ('NAMF_STATS_SEQ_IDX','PK_NAMF_STATS')
AND    operation = 'INDEX';
```
Reverse key (`ALTER INDEX ... REBUILD REVERSE`) resolve a contenção mas inutiliza range scan — só usar em índices de igualdade pura.

---

## Prioridade 2 — Parsing e cursores (grande ganho de CPU)

Em ambiente CPU-bound, **794M cursores abertos** e 7.126 parses/s consomem CPU significativa mesmo sendo soft parse. O `library cache: mutex X` é consequência direta.

### 2.1. Aplicação (maior retorno)
Habilitar **statement caching** no pool JDBC e reusar `PreparedStatement` com binds:
- Driver Oracle JDBC: `oracle.jdbc.implicitStatementCacheSize` = 50–100.
- Garantir pool de conexões com cursores mantidos abertos (evitar abrir/fechar por execução).

Isto ataca diretamente os 794M cursores e o `mutex X`. Provável **maior ganho de CPU** do ambiente depois da contenção de índice.

### 2.2. Banco (paliativo barato e seguro)
Confirmar e, se baixo, elevar `SESSION_CACHED_CURSORS` (default 50):
```sql
SHOW PARAMETER session_cached_cursors;
-- se no default, avaliar:
ALTER SYSTEM SET session_cached_cursors=300 SCOPE=SPFILE SID='*';
-- (requer reinício; aplicar em rolling)
```
As session cursor cache hits já são altas (~18–26K/s), mas mais cache retém cursores adicionais e reduz soft parse.

---

## Prioridade 3 — Memória SGA/PGA (ganho "quase de graça")

**Decisão de PDB:** com 2 PDBs (1 irrelevante, só tabelas de config), **não** configurar memória por PDB. Dimensionar no **CDB** e deixar o RAWDB usar o necessário. Configuração por PDB só adicionaria complexidade sem ganho.

### 3.1. SGA — ocupar os HugePages já reservados
Há **650 GB de HugePages reservados** e só ~305 GB em uso (`HugePages_Free` ≈ 345 GB). Esses 345 GB estão travados: nem o Oracle usa, nem o SO aproveita. Como o ambiente é CPU/contention-bound com RAM sobrando, **crescer a SGA para ocupar o que já foi reservado** é o caminho:
```sql
-- cabe nos 650 GB de HugePages já reservados, com folga p/ overhead
ALTER SYSTEM SET sga_target=560G SCOPE=SPFILE SID='*';
-- aplicar em rolling; observar se gc buffer busy NÃO piora
```
`USE_LARGE_PAGES=TRUE` já está correto e a SGA está em HugePages (protege do custo de TLB).

> **Alternativa, se NÃO for crescer a SGA:** reduzir o pool de HugePages de 650 GB para ~330 GB (cobrir a SGA atual com folga) e devolver ~320 GB ao SO. Deixar 345 GB de HugePages ociosos é o pior cenário — ou cresce a SGA, ou encolhe o pool.

### 3.2. PGA — aumento modesto (retorno marginal)
Work areas já são 98%+ optimal e `sorts(disk)` é desprezível → o PGA atual (104 GB) é suficiente. Aumento dá margem às queries analíticas grandes, mas sem salto:
```sql
ALTER SYSTEM SET pga_aggregate_target=150G SCOPE=SPFILE SID='*';
ALTER SYSTEM SET pga_aggregate_limit=300G  SCOPE=SPFILE SID='*';
```
Orçamento total por nó: 560 (SGA) + 150 (PGA) + ~100 (SO/overhead) ≈ 810 GB, dentro de ~80% de 1 TB.

---

## Prioridade 4 — INITRANS / PCTFREE nos objetos quentes

Princípio: cada transação concorrente que toca um bloco precisa de um slot ITL. Defaults (`INITRANS` 1 tabela / 2 índice) são insuficientes com ~37 sessões ativas/nó, gerando espera por ITL (visível em ITL Waits: `SEG$`, `LTE_SCTPASSOCIATIONPK`).

### 4.1. INITRANS (aplica só a blocos novos → exige rebuild/move)
```sql
-- índices de alto insert concorrente
ALTER INDEX <owner>.<idx> REBUILD INITRANS 16 ONLINE;
-- tabelas quentes
ALTER TABLE <owner>.<tab> MOVE INITRANS 8;   -- + rebuild de índices afetados
```
Alvos: índices em ITL/Buffer Busy (`LTE_SCTPASSOCIATIONPK`, `PK_NAMF_STATS`) e tabelas quentes (`T1526726713`, `T1542455817`, `NAMF_STATS`).

### 4.2. PCTFREE
Para tabelas **insert-only** que não sofrem update que cresça a linha (típico de coleta/métricas RAN), `PCTFREE` baixo aumenta densidade → menos blocos → menos LIO → menos CPU (favorável ao cenário CPU-bound):
```sql
ALTER TABLE <owner>.<tab> MOVE PCTFREE 5;   -- confirmar padrão de DML antes
```
**Pré-requisito:** confirmar que a tabela não sofre updates que aumentem o tamanho da linha (senão causa row migration). Verificar:
```sql
SELECT table_name, num_rows, avg_row_len, chain_cnt
FROM   dba_tables
WHERE  owner='<owner>' AND table_name IN ('T1542455817','T1526726713');
```

### 4.3. MAXTRANS
Ignorar. Desde 10g é fixado internamente em 255 e o parâmetro não tem efeito.

---

## Prioridade 5 — Estatísticas e otimizador

### 5.1. Estatísticas incrementais (tabelas particionadas por dia)
Reduz drasticamente o custo do gather diário (coleta só a partição nova, não a tabela inteira) e melhora a qualidade das estatísticas da partição quente — combate planos ruins por bind peeking (como o `E-Rows=1` observado).
```sql
EXEC DBMS_STATS.SET_TABLE_PREFS('<owner>','<tab>','INCREMENTAL','TRUE');
EXEC DBMS_STATS.SET_TABLE_PREFS('<owner>','<tab>','INCREMENTAL_LEVEL','PARTITION');
```

### 5.2. Otimizador — NÃO mexer globalmente
`optimizer_index_cost_adj=100` e `optimizer_index_caching=0` estão no default. Apesar do cache hit alto tentar a reduzir o `cost_adj`, **alterar globalmente afeta todos os planos** e pode regredir outras queries. Para favorecer índice em uma query específica, usar **SQL Profile / SQL Patch / hint**, mantendo o global em 100.

`db_file_multiblock_read_count=128` está alto mas inofensivo em ambiente OLTP indexado (full scans não são o caminho). Pode deixar como está ou remover o ajuste para o Oracle autocalibrar.

---

## Prioridade 6 — Redo / log file sync

`log file sync` no top 10 com 91 MB/s de redo e 206K block changes/s. Não é parâmetro de otimizador; verificar:
- Tamanho/número de redo log groups (logs pequenos → switches frequentes).
- Latência de IO do LGWR; idealmente redo em storage separado dos datafiles.
- **Causa raiz provável:** padrão de commit da aplicação. Com 2M+ execuções OLTP, commit linha-a-linha gera o `log file sync`. Revisar se há commits desnecessários por linha em vez de batch.

`commit_write BATCH/NOWAIT` relaxa durabilidade — só considerar com o negócio ciente do risco. Não recomendado por padrão.

---

## Ordem de implementação sugerida (do maior ao menor retorno)

| # | Ação | Esforço | Risco | Ganho esperado |
|---|------|---------|-------|----------------|
| 1 | Sequences: CACHE alto + NOORDER | Baixo | Baixo | Alto (contenção) |
| 2 | Hash-partition global / INITRANS nos índices quentes | Médio | Médio | Alto (contenção) |
| 3 | Statement caching JDBC + session_cached_cursors | Médio (app) | Baixo | Alto (CPU) |
| 4 | SGA → 560G (ocupar HugePages reservados) | Baixo | Médio (RAC) | Médio |
| 5 | INITRANS/PCTFREE tabelas quentes | Médio | Médio | Médio |
| 6 | Estatísticas incrementais | Baixo | Baixo | Médio (planos) |
| 7 | PGA → 150G | Baixo | Baixo | Marginal |
| 8 | Redo/commit (revisão app) | Médio | Baixo | Médio |

Os itens 1–3 concentram o maior retorno. O item 4 é "quase de graça" porque os HugePages já estão reservados — é só fazer a SGA usar o que já foi pago. Otimizador (5.2) permanece intocado globalmente.

---

## Verificações de acompanhamento (pós-mudança)

Após cada mudança, comparar no próximo AWR:
- Top 10 events: queda de `enq: TX - index contention`, `gc buffer busy`, `library cache: mutex X`.
- Instance Activity: queda de `parse count (total)` e `opened cursors cumulative`.
- DB CPU % do DB time (alvo: cair do patamar 67–71%).
- Segment Stats: redução de Buffer Busy/ITL nos objetos tratados.
