# CLAUDE.md - Contexto de inicializacao para Claude Code

Este e o contexto curto de sessao para Claude Code. Ele deve orientar decisoes
sem obrigar a carregar a historia inteira do projeto. Detalhes extensos devem
ficar nos arquivos `.ai/` conforme forem criados.

## Missao do projeto

Construir e evoluir um advisor deterministico de indices e tuning para Oracle
19c RAC. A ferramenta analisa SQL, plano de execucao e metadados reais ou
fixtures, detecta padroes de risco em regras auditaveis e entrega recomendacoes
com DDL, score e justificativa para DBAs. O foco e reduzir custo de CPU/gets,
evitar indices redundantes e explicitar trade-offs de manutencao em ambientes
RAC quentes.

## Resumo tecnico

- Pacote Python: `oracle-query-otim`, layout `src/advisor`.
- Entradas principais: SQL, SQL Monitor XML ou DBMS_XPLAN texto, YAML de
  ambiente e metadados Oracle/fixture.
- Saidas: relatorio texto/Markdown, DDL de indices, avisos de mitigacao,
  validacao opcional com indice invisivel.
- Banco alvo: Oracle 19c RAC, especialmente RAWDB/DBN0 e casos DATADB/DBN1.
- Dependencias: `sqlglot`, `PyYAML`; opcionais `oracledb` e `pytest`.
- CLIs declaradas: `advisor`, `advisor-awr`, `advisor-batch`.

## Arquitetura em uma tela

```text
SQL -> sql_parser -> ParsedQuery
Plano -> plan_parser -> ParsedPlan
DB/fixture -> metadata_collector -> SchemaMetadata
YAML -> env_profile -> EnvProfile

ParsedQuery + ParsedPlan + SchemaMetadata + EnvProfile + PlanHistory
  -> RuleContext -> RuleEngine -> Recommendation[]
  -> reporter.consolidate_indexes + merge_mitigation_warnings
  -> relatorio texto/Markdown
```

`engine.py` so descobre plugins, executa regras e ranqueia por `net_score`.
Qualquer diagnostico de tuning deve morar em `src/advisor/rules/`.

## Onde procurar

- Contratos: `src/advisor/models.py`.
- Interface das regras: `src/advisor/rule_base.py`.
- Descoberta/execucao: `src/advisor/engine.py`.
- Helpers de indice: `src/advisor/rules/__init__.py`.
- Regras existentes: `src/advisor/rules/rule_*.py`.
- CLI single-query e `--sql-id`: `src/advisor/cli.py`.
- Batch top SQL: `src/advisor/batch.py` e `src/advisor/batch_cli.py`.
- AWR para perfil YAML: `src/advisor/awr_parser.py`,
  `src/advisor/profile_builder.py`, `src/advisor/awr_cli.py`.
- Docs operacionais: `docs/MANUAL_DE_USO.md`, `docs/GUIA_DE_COLETA.md`,
  `docs/GUIA_ENV_PROFILE.md`, `docs/ARQUITETURA.md`.
- Testes de regressao: `tests/test_*.py` e `tests/fixtures_*.py`.

## Contexto `.ai/`

Leia arquivos `.ai/` somente quando forem relevantes e existirem:

- `context-index.md`: roteador de contexto por tipo de tarefa.
- `project-brief.md`: escopo, objetivo e limites.
- `architecture-map.md`: mapa de modulos e fluxo.
- `implemented-index.md`: regras implementadas, casos reais e fixtures.
- `coding-rules.md`: padroes de codigo e DDL.
- `testing-rules.md`: comandos e matriz de teste.
- `decision-log.md`: decisoes que nao devem ser reabertas sem motivo.
- `prompt-recipes.md`: prompts curtos para tarefas repetidas.

Enquanto `.ai/` nao existir, use este arquivo mais `docs/` e os testes
especificos. Evite reler planos XML grandes sem necessidade.

## Regras implementadas

- `R005_existing_intervention` - SQL Profile/Baseline/Outline ativo.
- `R009_plan_instability` - mais de um `plan_hash_value`; recomenda estabilizar
  o melhor plano observado.
- `R004_cartesian_or_bad_estimates` - cartesiano, overflow ou grande divergencia
  E-Rows x A-Rows, incluindo estatistica obsoleta quando o banco informa.
- `R010_workarea_spill_to_temp` - spill relevante de SORT/HASH para TEMP.
- `R011_massive_rowid_access` - acesso por ROWID massivo via indice pouco seletivo.
- `R007_unused_existing_index` - indice adequado existe, mas nao e usado.
- `R001_filter_should_be_access` - join aplicado como filtro pos-acesso em
  Nested Loops explosivo.
- `R002_avoidable_full_scan` - full scan evitavel por join/filtro seletivo.
- `R006_buffer_sort_materialization` - materializacao custosa para join.
- `R003_covering_for_aggregation` - cobertura para evitar table access em
  agregacao/projecao.
- `R008_global_index_on_partitioned` - indice global em tabela particionada.
- `R900_rac_hotblock_mitigation` - mitigacoes RAC para blocos quentes.

Prioridade numerica menor roda primeiro. Regras de contexto precedem regras que
geram indice; mitigacoes rodam no fim e podem ser anexadas pelo reporter.

## Convenções firmadas para indices

1. Nome de indice deterministico, com indicio do owner, sem `__`, ate 30 chars:
   use `build_index_name`.
2. Tabela particionada deve receber indice `LOCAL`: use `ctx.is_partitioned`.
3. DDL deve ser owner-qualificado e incluir coleta de estatisticas: use
   `build_index_ddl` com `ctx.env.index_parallel` e `ctx.env.index_tablespace`.
4. Nunca recomende indice ja coberto por indice existente: use os helpers de
   `rules/__init__.py`.
5. Redundancia entre recomendacoes e responsabilidade do `reporter`, nao da regra.

Tambem use `ctx.resolve_owner` antes de gerar DDL; queries reais podem nao
qualificar owner, mas o plano SQL Monitor ou os metadados costumam ter essa
informacao.

## Regra de memoria do projeto

Depois de qualquer mudanca significativa, atualize a memoria em `.ai/` no mesmo
trabalho. Considere significativa qualquer alteracao de comportamento, regra,
modulo, contrato publico, CLI, formato de relatorio, perfil YAML, fixture, teste
ou decisao de arquitetura/produto.

- Atualize `.ai/implemented-index.md` se comportamento, regras, arquivos
  importantes, comandos ou testes mudarem.
- Atualize `.ai/decision-log.md` se houver decisao arquitetural, operacional ou
  de produto nova ou revisada.
- Atualize `.ai/context-index.md` se surgir novo dominio, modulo, fluxo,
  documento ou grupo importante de arquivos.
- Atualize `.ai/architecture-map.md`, `.ai/coding-rules.md` ou
  `.ai/testing-rules.md` quando a mudanca afetar arquitetura, padroes de codigo
  ou estrategia de testes.
- Se `.ai/` ainda nao existir, informe no resumo final qual memoria devera ser
  criada ou atualizada quando a estrutura for implantada.
- Nao atualize memoria para formatacao, typo ou comentario sem impacto tecnico.

## Workflow para Claude Code

1. Identifique o tipo de tarefa: regra, parser, coletor, CLI, AWR, relatorio,
   docs ou teste.
2. Leia apenas os arquivos do dominio e um teste parecido.
3. Para nova regra de tuning, use a skill local `.claude/skills/criar-regra/`.
4. Implemente mudanca pequena e deterministica.
5. Adicione fixture/teste para todo caso real novo.
6. Rode o teste mais proximo; rode a suite inteira se tocar contratos comuns.
7. Atualize `CLAUDE.md` ou `.ai/*` quando a mudanca alterar memoria do projeto.

## Testes e comandos

```bash
python -m pytest -q
python -m pytest -q tests/test_pipeline.py
python -m pytest -q tests/test_awr_profile.py
python -m advisor.cli --sql examples/query.sql --plan examples/plan.txt --env config/env_profile_rawdb.yaml --source fixture --fixture tests.fixtures_rawdb
```

Testes unitarios nao precisam de Oracle. Testes de integracao devem ser
marcados com `@pytest.mark.integration` e protegidos por variaveis `ORACLE_*`.

## Cuidados de producao

- Nao registrar nem commitar senha, wallet ou `config/db.yaml`.
- `--validate` cria indice invisivel e consome recursos no banco; use somente
  por pedido explicito.
- AWR, `DBA_HIST_*` e SQL Monitor podem envolver licencas/privilegios Oracle;
  mantenha falhas defensivas e diagnosticos claros.
- `env_profile_*.yaml` e fonte de verdade do ambiente; nao hardcode ambiente em
  regra.
- Se o coletor nao enxergar uma tabela, preserve o pipeline e exponha diagnostico.

## Economia de contexto

- Comece com busca direcionada (`rg`) e abra arquivos pequenos primeiro.
- Nao carregar `plan.xml`, `plan2.xml`, `plan3.xml`, `examples/plan_*.xml` ou
  `temp/` se a tarefa nao depender deles.
- Para uma regra, normalmente bastam: regra similar, `rule_base.py`,
  `rules/__init__.py`, fixture/teste relacionado e, se necessario, `models.py`.
- Respostas devem explicar a mudanca atual, nao recontar todo o projeto.
