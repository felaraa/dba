# Arquitetura

Visão técnica do pipeline e dos módulos. Para uso, ver `MANUAL_DE_USO.md`.

## Fluxo

```
  query.sql ─┐
             ├─▶ sql_parser  ─▶ ParsedQuery ─┐
  plan.xml ──┼─▶ plan_parser ─▶ ParsedPlan ──┤
             │                               ├─▶ RuleContext ─▶ RuleEngine ─▶ [Recommendation]
  banco/DBA ─┼─▶ metadata_collector ─────────┤    (regras-plugin)              │
             │           ▲                    │                                ▼
  YAML ──────┴─▶ env_profile ─▶ EnvProfile ───┘                consolidate + merge_mitigation
                                                                              │
                                                                              ▼
                                                                    reporter (texto/md)
                                                                              │
                                                            (opcional) validator (INVISIBLE)
```

## Contratos de dados (`models.py`)

Dataclasses imutáveis que ligam todos os módulos sem que um conheça a
implementação do outro:
- `ParsedQuery` — tabelas, joins, filtros (range/igualdade), projeções, group by.
- `ParsedPlan` — operações com hierarquia pai-filho, A-Rows, Execs, predicados
  (access/filter), `sql_profile` e `notes`.
- `SchemaMetadata` — `TableMeta` (num_rows, partição, is_hot, stale_stats,
  stale_partitions), `ColumnStats`, `IndexMeta`.
- `Recommendation` — severidade, DDL, rationale, score (benefício/manutenção),
  warnings, tags.

## Parsers

- **`sql_parser`** (sqlglot): normaliza binds `:1`→`:b1`, extrai tabelas com
  owner/alias, joins por igualdade entre colunas de tabelas distintas, filtros
  range (agrupando `>=`/`<` na mesma coluna) e projeções de todos os SELECTs.
- **`plan_parser`**: detecta automaticamente XML do SQL Monitor vs texto do
  DBMS_XPLAN. No XML combina a seção estática (objeto, depth, predicados,
  E-Rows) com `<plan_monitor>` (parent_id, starts, cardinality = A-Rows). No
  texto reconstrói hierarquia por indentação e associa a seção Predicate
  Information. Reconhece SQL Profile/baseline/outline.

## Coletor de metadados

`MetadataCollector` é uma interface com duas implementações:
- `OracleMetadataCollector` (python-oracledb): lê `DBA_TAB_COL_STATISTICS`,
  `DBA_PART_TABLES`, `DBA_INDEXES`/`DBA_IND_COLUMNS`, `DBA_INDEX_USAGE`,
  `DBA_TAB_STATISTICS` (saúde de estatística). É **resiliente**: cada tabela é
  processada isolada (uma falha não derruba as demais), reconhece **views**
  (UNION com DBA_VIEWS), filtra por `table_owner`, e expõe `.missing` (tabelas
  da query que não foram coletadas).
- `FixtureMetadataCollector`: metadados pré-carregados (testes/offline).

## Motor e regras

`engine.py` descobre plugins em `rules/` por introspecção, instancia as
subclasses de `Rule`, executa em ordem de `priority` (isolando exceções) e
ranqueia por `net_score`. As regras leem só o `RuleContext` (imutável) —
nunca a saída umas das outras. Helpers compartilhados em `rules/__init__.py`:
`build_index_name`, `build_index_ddl`, `order_columns`, `covering_cost`,
`existing_index_covering`, `existing_index_exact_or_superset`.

`RuleContext.is_partitioned()` decide LOCAL vs GLOBAL: usa metadados se houver,
senão INFERE do plano (ancestral `PARTITION RANGE`).

## Pós-processamento (`reporter.py`)

- `consolidate_indexes`: funde índices sobrepostos na mesma tabela (mantém
  superset), evitando recomendações duplicadas entre regras.
- `merge_mitigation_warnings`: move avisos de regras de mitigação (ex.: R900)
  para a recomendação de índice correspondente, por tabela.
- `to_text` / `to_markdown`: saída final, com contexto do plano no topo.

## Validação (`validator.py`)

`InvisibleIndexValidator`: cria o índice como `INVISIBLE`, liga
`OPTIMIZER_USE_INVISIBLE_INDEXES` só na sessão, reexecuta a query com
`GATHER_PLAN_STATISTICS`, compara buffer gets antes/depois, verifica se o índice
foi usado, e remove o índice de teste. Opt-in via `--validate`.

## Conexão (`db_connection.py`)

`resolve_db_config` funde fontes por prioridade: parâmetros CLI > variáveis de
ambiente `ORACLE_*` > `config/db.yaml` > Oracle Wallet. Suporta thin (padrão) e
thick. Senha nunca precisa ir na linha de comando.
