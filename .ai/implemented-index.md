# Implemented Index

Ultima revisao: 2026-06-25.

Este arquivo e o inventario vivo do que ja esta implementado no
`oracle-query-otim`. Use junto com `.ai/context-index.md` para localizar
rapidamente comportamento existente, arquivos responsaveis, testes e limites
conhecidos antes de pedir ou executar uma mudanca.

## Core Pipeline And Contracts

Status: implemented

Files:
- `src/advisor/models.py`
- `src/advisor/rule_base.py`
- `src/advisor/engine.py`
- `src/advisor/reporter.py`
- `docs/ARQUITETURA.md`

Behavior:
- O pipeline transforma SQL, plano, metadados, perfil de ambiente e historico
  de planos em um `RuleContext` imutavel.
- `models.py` define os contratos compartilhados: `ParsedQuery`, `ParsedPlan`,
  `PlanOperation`, `PlanHistory`, `SchemaMetadata`, `Recommendation`.
- `RuleEngine` descobre automaticamente subclasses de `Rule` em
  `src/advisor/rules/`, respeita allowlist/denylist e isola excecoes por regra.
- Recomendacoes sao ranqueadas por `net_score` (`estimated_benefit -
  estimated_maint_cost`).
- `reporter.py` consolida indices redundantes e anexa warnings de mitigacao a
  recomendacoes de indice pelo `target_table`.

Tests:
- `tests/test_pipeline.py`
- `tests/test_unused_index_case.py`
- `tests/test_index_collection_fixes.py`

Known limitations:
- Regras nao veem a saida umas das outras por contrato; mitigacoes precisam ser
  emitidas separadamente e fundidas no reporter.
- Mudancas nos dataclasses de `models.py` exigem revisar parsers, regras,
  reporter, CLI e fixtures.

## SQL Parser

Status: implemented

Files:
- `src/advisor/sql_parser.py`
- `src/advisor/models.py`
- `examples/query.sql`
- `examples/query_*.sql`

Behavior:
- Usa `sqlglot` no dialeto Oracle.
- Normaliza binds numericos Oracle de `:1` para `:b1`.
- Extrai tabelas com owner opcional, nome e alias.
- Extrai joins por igualdade entre colunas de aliases distintos.
- Extrai filtros de igualdade, range e `IN`.
- Agrupa comparacoes range por coluna.
- Extrai colunas projetadas e de `GROUP BY` em todos os `SELECT`.
- Ignora colunas sem alias quando seriam ambiguas.

Tests:
- `tests/test_pipeline.py`

Known limitations:
- O parser e tolerante, mas nao cobre todo SQL Oracle possivel.
- Colunas nao qualificadas por alias nao viram `ColumnRef`.
- Transformacoes complexas podem exigir novo teste com SQL real.

## Plan Parser

Status: implemented

Files:
- `src/advisor/plan_parser.py`
- `src/advisor/models.py`
- `examples/plan.txt`
- `examples/plan_*.xml`

Behavior:
- Detecta automaticamente SQL Monitor XML versus DBMS_XPLAN texto.
- Parser XML combina a secao estatica `<plan>` com runtime `<plan_monitor>`.
- Extrai SQL_ID, plan hash, SQL Profile/Baseline/Outline, operacoes, objetos,
  predicados access/filter, E-Rows, A-Rows, execucoes e hierarquia.
- Em XML, extrai `object_owner` e metricas de workarea/TEMP:
  `temp_bytes`, `spill_count`, `write_bytes`.
- Parser DBMS_XPLAN texto reconstrui parent/child por indentacao e anexa a
  secao `Predicate Information` por id de operacao.

Tests:
- `tests/test_pipeline.py`
- `tests/test_cartesian_case.py`
- `tests/test_workarea_spill.py`
- `tests/test_owner_resolution.py`

Known limitations:
- Planos sem estatisticas de runtime reduzem a capacidade de detectar explosoes.
- DBMS_XPLAN texto nao traz todos os campos de SQL Monitor XML, como workarea.
- Variacoes incomuns do formato Oracle podem precisar de fixtures novas.

## Metadata Collection

Status: implemented

Files:
- `src/advisor/metadata_collector.py`
- `src/advisor/models.py`
- `tests/fixtures_*.py`
- `docs/GUIA_DE_COLETA.md`

Behavior:
- `OracleMetadataCollector` coleta metadados reais via views DBA.
- Coleta tabelas e views, particionamento, chave de particao, estatisticas de
  tabela, estatisticas de coluna, indices, colunas de indice e uso do indice.
- Trata cada tabela de forma resiliente e reporta faltantes via `collector.missing`.
- Marca tabelas quentes a partir da lista de segmentos quentes do perfil.
- Coleta saude de estatisticas: `last_analyzed`, `stale_stats` e particoes
  obsoletas.
- `FixtureMetadataCollector` suporta testes e analise offline.
- `_indexes` materializa o result set com `fetchall()` antes de subconsultas no
  mesmo cursor, evitando perda silenciosa de indices.

Tests:
- `tests/test_index_collection_fixes.py`
- `tests/test_improvements_v3.py`
- `tests/test_global_index_rule.py`
- `tests/fixtures_rawdb.py`
- `tests/fixtures_cartesian.py`
- `tests/fixtures_stale_stats.py`
- `tests/fixtures_unused_idx.py`
- `tests/fixtures_plan_instability.py`

Known limitations:
- Requer privilegios nas views `DBA_*` em modo banco real.
- Sem metadados completos, algumas regras continuam defensivas, mas podem perder
  precisao sobre indices existentes ou particionamento.
- Fixtures precisam ser atualizadas manualmente para cada caso real novo.

## DB Connection

Status: implemented

Files:
- `src/advisor/db_connection.py`
- `config/db.yaml.example`
- `docs/MANUAL_DE_USO.md`

Behavior:
- Resolve conexao por prioridade: argumentos CLI, variaveis `ORACLE_*`, YAML e
  wallet/TNS.
- Aceita YAML com secao `database:` ou campos na raiz.
- Suporta modo thin por padrao e modo thick com `client_lib_dir`.
- Suporta wallet via `wallet_location`, `wallet_password` e `config_dir`.
- `oracledb` e dependencia opcional para fluxos com banco.

Tests:
- Cobertura direta limitada.
- Fluxos offline exercitam partes superiores sem abrir conexao.

Known limitations:
- Nao ha teste unitario dedicado para todas as combinacoes de resolucao de
  config.
- Falhas de permissao/conectividade so aparecem em execucao com banco real.
- Credenciais reais nao devem ser versionadas.

## Env Profile Loader

Status: implemented

Files:
- `src/advisor/env_profile.py`
- `config/env_profile_rawdb.yaml`
- `config/env_profile_datadb.yaml`
- `tests/fixtures/env_profile_rawdb.yaml`

Behavior:
- Carrega YAML do ambiente e expoe propriedades usadas pelas regras.
- Expõe identidade, Exadata, CPU-bound, metrica de beneficio, contenção RAC,
  segmentos quentes, pesos de scoring, limite de coluna larga e fator de
  explosao de nested loops.
- Expõe opcoes humanas de DDL: `index_ddl.parallel` e `index_ddl.tablespace`.
- `env_profile_*.yaml` e a fonte de verdade do ambiente; regras nao devem
  hardcodar calibracao por banco.

Tests:
- `tests/test_index_ddl_options.py`
- `tests/test_awr_profile.py`
- `tests/test_pipeline.py`

Known limitations:
- Loader assume chaves esperadas no YAML; perfis incompletos podem falhar.
- Alterar sem cuidado `scoring.*` ou `index_ddl.*` muda recomendacoes e DDL.

## AWR To Env Profile

Status: implemented

Files:
- `src/advisor/awr_parser.py`
- `src/advisor/profile_builder.py`
- `src/advisor/awr_cli.py`
- `docs/GUIA_ENV_PROFILE.md`
- `tests/fixtures/awr_sample.html`

Behavior:
- `awr_parser.py` extrai metricas cruas de AWR HTML de forma resiliente.
- Captura identidade, versao, RAC, block size, workload, CPU/DB time, cache hit,
  redo, block changes, IO single block, parametros do otimizador, eventos de
  contencao e segmentos quentes.
- Filtra segmentos de dicionario e schemas mantidos pela Oracle.
- `aggregate_metrics` agrega varios AWRs para RAC, fazendo media de metricas
  numericas e uniao de segmentos quentes.
- `profile_builder.py` aplica limiares para `cpu_bound` e cache alto.
- `emit_yaml` gera YAML comentado.
- `awr_cli.py` cria ou atualiza perfil; `--update` preserva campos humanos como
  `scoring.*`, `index_ddl.*`, `identity.exadata`, `io.full_scan_block_discount`
  e `workload.benefit_metric`.

Tests:
- `tests/test_awr_profile.py`

Known limitations:
- Suporta AWR HTML, nao AWR texto.
- Parser depende de palavras-chave/cabecalhos; versoes diferentes podem exigir
  extensao.
- AWR pode envolver Diagnostics Pack/licenciamento no ambiente Oracle.

## Plan History

Status: implemented

Files:
- `src/advisor/plan_history.py`
- `src/advisor/models.py`
- `src/advisor/rules/rule_plan_instability.py`
- `tests/fixtures_plan_instability.py`

Behavior:
- Coleta historico de planos por SQL_ID a partir de `GV$SQL` e
  `DBA_HIST_SQLSTAT`.
- Funde fontes por `plan_hash_value`.
- Calcula medias por execucao para elapsed, buffer gets, CPU e linhas.
- Retorna `PlanHistory` defensivamente mesmo se uma fonte falhar.
- `PlanHistory.best()` e `worst()` ranqueiam por elapsed/exec com fallback para
  buffer gets/exec.

Tests:
- `tests/test_plan_instability.py`

Known limitations:
- Coleta real depende de privilegios e, para AWR, Diagnostics Pack.
- Fixture mode usa historico vazio salvo quando o teste injeta explicitamente.

## Rule R005 Existing Intervention

Status: implemented

Files:
- `src/advisor/rules/rule_existing_intervention.py`
- `src/advisor/plan_parser.py`

Behavior:
- Detecta SQL Profile, SQL Plan Baseline ou Stored Outline no plano.
- Emite alerta antes das regras de indice (`priority = 1`).
- Sinaliza que um indice novo pode nao ser usado se a intervencao fixar o plano.
- Detecta prefixo `coe_` em SQL Profile e recomenda reavaliar/remover se
  obsoleto.

Tests:
- `tests/test_cartesian_case.py`

Known limitations:
- Depende do parser de plano reconhecer as notas/intervencoes.
- Nao altera nem remove profiles; apenas alerta.

## Rule R009 Plan Instability

Status: implemented

Files:
- `src/advisor/rules/rule_plan_instability.py`
- `src/advisor/plan_history.py`
- `src/advisor/models.py`

Behavior:
- Detecta mais de um plan hash para o mesmo SQL_ID.
- Identifica melhor e pior plano observado por custo medio por execucao.
- Compara o plano do arquivo com o melhor plano quando possivel.
- Recomenda estabilizar o melhor plano via SQL Plan Baseline/DBMS_SPM.
- Roda cedo (`priority = 2`) antes das regras de indice.

Tests:
- `tests/test_plan_instability.py`
- `tests/fixtures_plan_instability.py`

Known limitations:
- Inerte quando `ctx.plan_history` esta vazio.
- Nao cria baseline automaticamente.
- Melhor plano observado ainda precisa de validacao operacional.

## Rule R004 Cartesian And Bad Estimates

Status: implemented

Files:
- `src/advisor/rules/rule_cartesian_and_bad_estimates.py`
- `src/advisor/metadata_collector.py`

Behavior:
- Detecta `MERGE JOIN CARTESIAN`.
- Detecta E-Rows absurdamente alto (`>= 1e15`).
- Detecta divergencia grande entre E-Rows e A-Rows (`>= 1000x`) quando nao ha
  cartesiano.
- Usa diagnostico de estatisticas coletado do banco para apontar tabelas ou
  particoes obsoletas.
- Recomenda `DBMS_STATS.GATHER_TABLE_STATS` com `AUTO_SAMPLE_SIZE`, histogramas
  AUTO, `GATHER AUTO`, `cascade=>TRUE` e grau vindo do env profile.
- Nao gera indice; trata estimativa como causa raiz.

Tests:
- `tests/test_cartesian_case.py`
- `tests/test_improvements_v3.py`

Known limitations:
- Diagnostico de stale stats depende de metadados coletados no banco.
- Thresholds sao heuristicas e podem precisar ajuste para novos casos.

## Rule R010 Workarea Spill To TEMP

Status: implemented

Files:
- `src/advisor/rules/rule_workarea_spill.py`
- `src/advisor/plan_parser.py`

Behavior:
- Detecta operacoes de workarea (`SORT`, `HASH`, `GROUP BY`, `WINDOW`,
  `BUFFER`) com spill para TEMP >= 1 GiB.
- Classifica severidade por volume: medio, alto e critico.
- Usa metricas de SQL Monitor XML (`temp_bytes`, `spill_count`, `write_bytes`).
- Sinaliza quando a query tem hint `PARALLEL` mas o plano nao tem PX.
- Recomenda corrigir cardinalidade, habilitar paralelismo real/Parallel DML e
  reavaliar PGA se ainda houver spill.
- Nao gera indice.

Tests:
- `tests/test_workarea_spill.py`

Known limitations:
- Depende de SQL Monitor XML para metricas de TEMP/workarea.
- Nao mede PGA real nem altera parametros.

## Rule R011 Massive ROWID Access

Status: implemented

Files:
- `src/advisor/rules/rule_massive_rowid_access.py`
- `src/advisor/plan_parser.py`
- `src/advisor/rule_base.py`

Behavior:
- Detecta `TABLE ACCESS BY INDEX ROWID` com volume massivo em poucas execucoes.
- Exclui lado interno de Nested Loops com muitas execucoes, que e dominio da
  R001.
- Trata o caso inverso da R002: indice usado para buscar linhas demais quando
  full/partition scan seria mais adequado.
- Recomenda recolher estatisticas e, como mitigacao, forcar `FULL` e
  `PARALLEL` quando apropriado.
- Usa `ctx.resolve_owner()` e `ctx.is_partitioned()` para qualificar mensagem.

Tests:
- `tests/test_massive_rowid_access.py`
- `tests/test_owner_resolution.py`

Known limitations:
- Thresholds de linhas sao heuristicas.
- Nao altera hints nem SQL; apenas recomenda.

## Rule R007 Unused Existing Index

Status: implemented

Files:
- `src/advisor/rules/rule_unused_existing_index.py`
- `src/advisor/rules/__init__.py`

Behavior:
- Detecta tabela em `TABLE ACCESS FULL` quando ja existe indice adequado para
  as colunas de igualdade do join.
- Usa `existing_index_covering`, que compara o conjunto das colunas lideres de
  igualdade, tolerando ordem diferente.
- Nao recomenda criar novo indice.
- Lista hipoteses acionaveis: cartesiano/estimativa quebrada, estatisticas
  velhas, indice invisivel/unusable, conversao implicita/função, skew sem
  histograma.

Tests:
- `tests/test_unused_index_case.py`
- `tests/test_index_collection_fixes.py`

Known limitations:
- Depende de metadados de indice completos.
- Nao comprova a causa; fornece checklist de verificacao.

## Rule R001 Filter Should Be Access

Status: implemented

Files:
- `src/advisor/rules/rule_filter_should_be_access.py`
- `src/advisor/rules/__init__.py`

Behavior:
- Detecta join aplicado como predicado `filter` pos-acesso em plano com
  estatisticas de runtime.
- Usa A-Rows/Execs para confirmar explosao de Nested Loops.
- Recomenda indice de probe liderado pelas colunas de igualdade do join, seguido
  de colunas range.
- Evita recomendar indice se `existing_index_covering` indicar cobertura ja
  existente.
- Gera DDL owner-qualificado, `LOCAL` quando particionado, com stats do indice e
  opcoes `parallel`/`tablespace` do env profile.

Tests:
- `tests/test_pipeline.py`
- `tests/test_cartesian_case.py`

Known limitations:
- Requer runtime stats para confirmar explosao.
- Casamento de predicado depende do texto access/filter do plano.

## Rule R002 Avoidable Full Scan

Status: implemented

Files:
- `src/advisor/rules/rule_full_scan.py`
- `src/advisor/rules/__init__.py`

Behavior:
- Detecta `TABLE ACCESS FULL` em tabela que participa de join por igualdade.
- Usa cardinalidade de coluna/tabela para evitar recomendacao quando o join e
  pouco seletivo.
- Pode incluir colunas de cobertura estreitas de projeção/group-by se o custo
  calculado for baixo.
- Evita duplicar indice existente.
- Gera DDL com as convencoes de owner, `LOCAL`, stats, parallel e tablespace.

Tests:
- Coberta indiretamente por pipeline e testes de helpers/DDL.
- `tests/test_pipeline.py`
- `tests/test_index_ddl_options.py`

Known limitations:
- Seletividade depende de `num_distinct` e `num_rows` coletados.
- Heuristica foi calibrada para ambiente nao-Exadata/CPU-bound.

## Rule R006 Buffer Sort Materialization

Status: implemented

Files:
- `src/advisor/rules/rule_buffer_sort_materialization.py`

Behavior:
- Detecta `BUFFER SORT`/`SORT JOIN` materializando muitas linhas para join.
- Propõe indice quando a materializacao indica caminho de acesso ruim e ha
  predicados que podem virar probe.
- Segue helpers compartilhados de DDL e convencoes de indice.

Tests:
- Cobertura indireta nos casos de pipeline/agregacao.

Known limitations:
- Sem teste dedicado identificado para todos os cenarios da regra.
- Requer cuidado ao alterar por interagir com R001/R002/R003.

## Rule R003 Covering For Aggregation

Status: implemented

Files:
- `src/advisor/rules/rule_covering_aggregation.py`
- `src/advisor/rules/__init__.py`

Behavior:
- Detecta `TABLE ACCESS BY ROWID` pesado cujo papel e buscar colunas de
  projecao/agregacao nao cobertas pelo indice.
- Considera pesado quando ha muitos bytes lidos ou muitas linhas.
- Propõe indice de cobertura com colunas range, join e colunas projetadas
  estreitas.
- Exclui colunas largas conforme `env.wide_column_bytes`.
- Penaliza custo de cobertura e custo de manutencao em tabela quente.

Tests:
- `tests/test_pipeline.py`

Known limitations:
- Pode gerar score liquido negativo em tabela quente; isso e sinal de trade-off,
  nao erro.
- Depende de `avg_col_len` coletado ou fallback padrao.

## Rule R008 Global Index On Partitioned

Status: implemented

Files:
- `src/advisor/rules/rule_global_index_on_partitioned.py`
- `sql/audit_global_indexes_on_partitioned.sql`

Behavior:
- Audita indices globais existentes em tabelas particionadas da query.
- Emite alerta de divida de manutencao, sem gerar indice novo.
- Ignora indices gerados pelo sistema (`IDX$$`, `SYS_IL`, `SYS_IOT`,
  `SYS_C00`) e indices compostos apenas por colunas virtuais ocultas `SYS_NC%`.
- Orienta avaliar conversao para `LOCAL`, respeitando unicidade e chave de
  particao.

Tests:
- `tests/test_global_index_rule.py`
- `tests/test_index_collection_fixes.py`

Known limitations:
- Depende de metadados indicarem tabela particionada e localidade do indice.
- Nao valida automaticamente se um indice unico pode virar LOCAL.

## Rule R900 RAC Hotblock Mitigation

Status: implemented

Files:
- `src/advisor/rules/rule_rac_hotblock_mitigation.py`
- `src/advisor/reporter.py`
- `config/env_profile_rawdb.yaml`

Behavior:
- Ativa apenas se o env profile indicar contencao de indice e hotblock
  sequencial observados.
- Procura tabela quente com filtro range em coluna de nome monotônico
  (`TIME`, `DATE`, `SEQ`, `ID`, `TS`, `TIMESTAMP`).
- Emite warning de mitigacao RAC para indice novo sobre tabela quente.
- Reporter pode anexar o warning a recomendacoes de indice da mesma tabela.
- Sugere hash partition global, INITRANS/PCTFREE ou coluna lider mais
  distribuida.

Tests:
- `tests/test_pipeline.py`

Known limitations:
- Heuristica baseada em nomes de colunas monotônicas.
- Como regras sao isoladas, R900 nao enxerga diretamente indices propostos; o
  merge depende de `target_table`.

## Index DDL Helpers And Existing Index Matching

Status: implemented

Files:
- `src/advisor/rules/__init__.py`
- `tests/test_index_ddl_options.py`
- `tests/test_improvements_v3.py`
- `tests/test_index_collection_fixes.py`

Behavior:
- `build_index_name` gera nomes deterministas, com indicio do owner, sem
  underscores duplos e ate 30 caracteres.
- O token da tabela (ate 12 chars) preserva um sufixo numerico final via
  `_shorten_table` (ex.: `LTE_EUTRANCELLFDD_247` -> `LTE_EUTRA247`), evitando
  colisao de nome entre tabelas irmas que só diferem por um ID numerico
  (comum em esquemas RAN particionados, ex.: `..._247` vs `..._248`).
- `build_index_ddl` gera `CREATE INDEX owner.idx ON owner.table`, adiciona
  `LOCAL` quando pedido, `TABLESPACE`, `PARALLEL`, `ALTER INDEX ... NOPARALLEL`
  e `DBMS_STATS.GATHER_INDEX_STATS`.
- `order_columns` aplica ordem canonica: igualdade, range, cobertura.
- `covering_cost` penaliza cobertura por largura de coluna.
- `existing_index_covering` detecta indice existente para colunas lideres de
  igualdade comparando conjunto das colunas.
- `existing_index_exact_or_superset` detecta prefixo exato/superset em ordem.

Tests:
- `tests/test_index_ddl_options.py`
- `tests/test_improvements_v3.py`
- `tests/test_index_collection_fixes.py`
- `tests/test_owner_resolution.py`

Known limitations:
- DDL e textual; execucao real so ocorre no validador.
- Nomes com limite Oracle podem truncar informacao quando tabela/colunas sao
  longas.

## Single Query CLI

Status: implemented

Files:
- `src/advisor/cli.py`
- `src/advisor/db_connection.py`
- `src/advisor/reporter.py`
- `README.md`
- `docs/MANUAL_DE_USO.md`

Behavior:
- Suporta entrada por arquivos `--sql` + `--plan`.
- Suporta entrada por `--sql-id` em modo banco, buscando SQL e plano no banco.
- `--sql-id` e mutuamente exclusivo com `--sql`/`--plan`.
- Suporta `--source fixture` com modulo `get_metadata()`.
- Suporta `--source <banco>` com credenciais de `config/<source>.yaml` ou
  override por CLI/env.
- Coleta metadados, historico de planos, executa engine, consolida indices,
  anexa mitigacoes e imprime texto ou Markdown.
- `--diag` imprime detalhes de coleta e historico no stderr.
- `--save-temp` salva artefatos de SQL_ID em `temp/<sql_id>/`.
- `--allow` e `--deny` controlam regras por `rule_id`.

Tests:
- `tests/test_pipeline.py`

Known limitations:
- Pouca cobertura unitária direta para validacao de argumentos CLI.
- `--sql-id` depende de banco, permissoes e plano disponivel no cursor/monitor.

## Batch CLI

Status: implemented

Files:
- `src/advisor/batch.py`
- `src/advisor/batch_cli.py`
- `src/advisor/db_connection.py`
- `src/advisor/reporter.py`

Behavior:
- `advisor-batch` analisa as N queries mais quentes do banco.
- Seleciona SQL_IDs em `GV$SQL` na ultima hora, com execucoes > 0 e elapsed
  medio > 10 minutos, ordenados por buffer gets.
- Busca SQL text em `GV$SQLTEXT`.
- Busca plano via SQL Monitor XML, com fallback para DBMS_XPLAN.
- Salva SQL/plano em `temp/<sql_id>/`.
- Executa parser, coletor, plan history, engine, consolidacao e merge de
  mitigacoes por SQL_ID.
- Produz relatorio consolidado texto ou Markdown.

Tests:
- Cobertura direta limitada.
- Mudancas compartilhadas sao exercitadas por testes de pipeline/reporter.

Known limitations:
- Requer banco real; fixture nao e suportada.
- Thresholds de selecao do top SQL estao hardcoded.
- Sem teste automatizado completo para consulta real nas views Oracle.

## Reporter

Status: implemented

Files:
- `src/advisor/reporter.py`
- `src/advisor/batch_cli.py`
- `examples/resultado_*.md`

Behavior:
- `consolidate_indexes` remove recomendacoes de indice redundantes na mesma
  tabela quando uma lista de colunas e prefixo de outra.
- Recomendacoes consolidadas herdam tags de regras descartadas.
- `merge_mitigation_warnings` move warnings de recomendacoes sem DDL para
  recomendacoes de indice da mesma tabela.
- `to_text` e `to_markdown` formatam relatorio final com severidade, regra,
  score, DDL, justificativa e mitigacoes.
- Batch CLI tem formatadores especificos para sumario consolidado por SQL_ID.

Tests:
- `tests/test_pipeline.py`
- `tests/test_unused_index_case.py`

Known limitations:
- Comparacao de redundancia extrai tabela/colunas do texto DDL por regex.
- Alteracoes de formato podem afetar consumidores humanos e exemplos.

## Validation With Invisible Index

Status: implemented

Files:
- `src/advisor/validator.py`
- `src/advisor/cli.py`
- `docs/MANUAL_DE_USO.md`

Behavior:
- `InvisibleIndexValidator` valida recomendacoes com DDL.
- Mede baseline executando query com `GATHER_PLAN_STATISTICS`.
- Cria indice como `INVISIBLE`.
- Liga `optimizer_use_invisible_indexes=TRUE` apenas na sessao.
- Reexecuta a query, captura plano e compara buffer gets/elapsed.
- Detecta se o novo indice aparece no plano.
- Tenta remover o indice de teste no `finally`.
- CLI executa validacao apenas com `--validate` e ignora em fixture.

Tests:
- Sem cobertura automatizada completa por depender de banco real.

Known limitations:
- `_as_invisible` apenas acrescenta `INVISIBLE` ao DDL textual.
- `_extract_gets` e heuristico.
- Cria indice real temporario e consome recursos/redo; exige aprovacao
  operacional.

## Examples And Regression Cases

Status: implemented

Files:
- `examples/query.sql`
- `examples/plan.txt`
- `examples/query_cartesian.sql`
- `examples/plan_cartesian.xml`
- `examples/query_unused_idx.sql`
- `examples/plan_unused_idx.xml`
- `examples/query_stale_stats.sql`
- `examples/plan_stale_stats.xml`
- `examples/query_plan_instability.sql`
- `examples/plan_instability.xml`
- `examples/query_agg_merge_spill.sql`
- `examples/plan_agg_merge_spill.xml`
- `examples/query_agg_merge_adjn.sql`
- `examples/plan_agg_merge_adjn.xml`
- `examples/resultado_*.md`

Behavior:
- Mantem artefatos de casos reais usados como regressao.
- Caso baseline `24h537gmxw93d`: explosao de Nested Loops e filtro que deveria
  ser access.
- Caso cartesiano/profile: MERGE JOIN CARTESIAN com SQL Profile ativo.
- Caso unused index: indice adequado ja existe mas o otimizador nao usa.
- Caso stale stats/local inference: estatistica obsoleta e inferencia de LOCAL
  pelo plano quando metadados faltam.
- Caso plan instability: multiplos plan hashes para o mesmo SQL_ID.
- Casos de agregacao/MERGE: workarea spill e rowid massivo.
- Caso owner resolution: query sem owner gerava DDL `None.*`; resolucao pelo
  plano/metadados corrige.

Tests:
- `tests/test_pipeline.py`
- `tests/test_cartesian_case.py`
- `tests/test_unused_index_case.py`
- `tests/test_improvements_v3.py`
- `tests/test_plan_instability.py`
- `tests/test_workarea_spill.py`
- `tests/test_massive_rowid_access.py`
- `tests/test_owner_resolution.py`

Known limitations:
- Alguns XMLs sao grandes; leia somente o caso relevante.
- Novos casos reais precisam de query, plano, fixture e teste assertivo.

## SQL Support Scripts

Status: implemented

Files:
- `sql/audit_global_indexes_on_partitioned.sql`
- `sql/top_sql_awr.sql`
- `docs/GUIA_DE_COLETA.md`

Behavior:
- `audit_global_indexes_on_partitioned.sql` apoia auditoria de indices globais
  sobre tabelas particionadas.
- `top_sql_awr.sql` apoia coleta/analise de top SQL via AWR.
- Guia de coleta documenta como capturar query, SQL Monitor XML, DBMS_XPLAN,
  metadados, estatisticas, profiles/baselines e AWR HTML.

Tests:
- Scripts SQL nao possuem harness automatizado.
- Conceitos relacionados sao cobertos por regras e testes Python quando
  aplicavel.

Known limitations:
- Saidas dependem de privilegios Oracle e ambiente.
- Scripts precisam de revisao manual antes de uso em producao.

## Documentation

Status: implemented

Files:
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.ai/project-brief.md`
- `.ai/architecture-map.md`
- `.ai/context-index.md`
- `.ai/implemented-index.md`
- `.ai/decision-log.md`
- `.ai/prompt-recipes.md`
- `docs/ARQUITETURA.md`
- `docs/CONTRIBUTING.md`
- `docs/MANUAL_DE_USO.md`
- `docs/GUIA_DE_COLETA.md`
- `docs/GUIA_ENV_PROFILE.md`
- `docs/plano_tuning_rawdb.md`

Behavior:
- README descreve objetivo, quickstart, estrutura e docs principais.
- `AGENTS.md` orienta Codex com regras operacionais, memoria e economia de
  tokens.
- `CLAUDE.md` orienta Claude Code com contexto de boot e regra local de criacao
  de regras.
- `.ai/project-brief.md` descreve objetivo, contexto de negocio, usuarios,
  escopo, dominios, stack, restricoes, riscos e glossario.
- `.ai/architecture-map.md` descreve fluxo, modulos, contratos, pastas,
  fronteiras e caminhos comuns de mudanca.
- `.ai/context-index.md` roteia contexto por dominio.
- Este arquivo indexa comportamento implementado.
- `.ai/decision-log.md` registra decisoes duraveis para evitar reabrir escolhas
  de arquitetura/produto/operacao sem motivo.
- `.ai/prompt-recipes.md` fornece prompts reutilizaveis para feature, bug,
  regra nova, parser, AWR, CLI, reporter, refactor, review e memoria.
- Docs em `docs/` cobrem arquitetura, contribuicao, manual de uso, coleta,
  env profile/AWR e tuning RAWDB.

Tests:
- Documentacao nao possui testes automatizados.
- Exemplos de comando devem ser validados manualmente ou por testes quando
  alterarem comportamento executavel.

Known limitations:
- `.ai/coding-rules.md`, `.ai/testing-rules.md` ainda precisam ser criados.

## Packaging And Scripts

Status: implemented

Files:
- `pyproject.toml`
- `requirements.txt`
- `scripts/bootstrap.sh`
- `src/advisor/__init__.py`

Behavior:
- Projeto usa Python >= 3.10 e layout `src`.
- Build backend: setuptools.
- Dependencias core: `sqlglot`, `PyYAML`.
- Extras: `db` com `oracledb`, `dev` com `pytest`.
- Console scripts:
  - `advisor = advisor.cli:main`
  - `advisor-awr = advisor.awr_cli:main`
  - `advisor-batch = advisor.batch_cli:main`
- Pytest usa `pythonpath = ["src"]` e `testpaths = ["tests"]`.
- Marker `integration` reservado para testes com banco real.

Tests:
- `python -m pytest -q`

Known limitations:
- `requirements.txt` lista tambem dependencias opcionais para producao/teste,
  enquanto `pyproject.toml` separa extras.
- Alteracoes de packaging devem ser testadas em ambiente limpo quando possivel.

## Current Known Gaps

Status: known

Files:
- `AGENTS.md`
- `CLAUDE.md`
- `.ai/project-brief.md`
- `.ai/architecture-map.md`
- `.ai/context-index.md`
- `.ai/decision-log.md`
- `.ai/prompt-recipes.md`
- This file

Behavior:
- A estrutura `.ai/` esta em construcao incremental.
- A memoria operacional ja exige atualizacao apos mudancas significativas.

Tests:
- N/A for memory gaps.

Known limitations:
- Ainda faltam arquivos de memoria especializados:
  `.ai/coding-rules.md`, `.ai/testing-rules.md`.
- Alguns dominios implementados possuem cobertura indireta, mas nao testes
  unitarios dedicados para todos os caminhos: batch, DB connection, validation e
  alguns detalhes de reporter/CLI.
