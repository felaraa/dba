# Project Brief

Ultima revisao: 2026-06-25.

## 1. Project Name

`oracle-query-otim` / Oracle Query Optimization - Index & Tuning Advisor.

## 2. Project Objective

Este projeto fornece um advisor deterministico de indices e tuning para Oracle
19c RAC. Ele analisa SQL, plano de execucao com estatisticas de runtime,
metadados de schema e perfil do ambiente para produzir recomendacoes auditaveis:
DDL de indices, diagnosticos de plano, score de beneficio/custo e mitigacoes de
RAC. O foco principal e transformar casos reais de degradacao em regras
reprodutiveis, testadas e seguras para apoio ao DBA.

## 3. Business Context

O projeto existe para reduzir tempo de analise manual de queries Oracle caras,
especialmente em ambientes RAC com alto volume, tabelas particionadas,
contenção de indices e planos instaveis.

Who uses this project:
- DBAs e engenheiros de performance: analisam SQLs lentos, planos ruins,
  estatisticas e recomendacoes de indice.
- Times de operacao/infra Oracle: usam o diagnostico para priorizar mitigacoes
  de RAC, estatisticas, paralelismo e validacao segura.
- Desenvolvedores de ETL/BI/aplicacao: recebem DDL e explicacoes sobre por que
  uma query precisa de ajuste.
- Agentes de IA no repositorio: usam a memoria `.ai/` para evoluir regras,
  parser, docs e testes com menos contexto carregado.

Main business problem solved:
- Queries criticas podem degradar por Nested Loops explosivo, cardinalidade
  errada, estatisticas obsoletas, plano instavel, full scans evitaveis,
  workarea spill, rowid massivo ou indices existentes ignorados.
- A investigacao manual desses casos e lenta e pode gerar recomendacoes
  inconsistentes sem regressao viva.

Expected outcome:
- Relatorios claros com recomendacoes acionaveis e justificadas.
- DDL padronizado e seguro para avaliacao por DBA.
- Casos reais transformados em testes para evitar regressao.
- Melhor aproveitamento de AWR/env profile para calibrar custo e risco por
  ambiente.

## 4. Main Users

- DBA Oracle: roda o advisor com SQL/plano/metadados e avalia recomendacoes.
- Engenheiro de performance: adiciona regras, fixtures e testes para novos
  padroes de plano.
- Operador de ambiente Oracle RAC: usa alertas de hot block, estatisticas,
  paralelismo, SQL Profile/Baseline e plano instavel.
- Desenvolvedor/analista SQL: recebe explicacao e DDL candidato para corrigir
  query ou ajustar caminho de acesso.
- Sistema Oracle DB: fonte opcional de SQL text, planos, metadados, AWR e
  validacao por indice invisivel.
- Agente de IA: le `AGENTS.md`, `CLAUDE.md` e `.ai/*` para trabalhar com
  escopo menor e atualizar memoria quando comportamento muda.

## 5. Core Responsibilities

This project is responsible for:

- Parsear SQL Oracle para extrair tabelas, aliases, joins, filtros, projecoes e
  group by.
- Parsear planos SQL Monitor XML e DBMS_XPLAN texto para extrair operacoes,
  hierarquia, predicados, runtime stats, notes e metricas de workarea.
- Coletar metadados de schema via Oracle DBA views ou fixtures offline.
- Carregar e aplicar perfil de ambiente `env_profile_*.yaml`.
- Gerar/atualizar env profiles a partir de AWR HTML.
- Executar regras deterministicas de diagnostico e recomendacao.
- Gerar DDL padronizado de indices candidatos.
- Consolidar recomendacoes e produzir relatorios texto/Markdown.
- Validar recomendacoes com indice invisivel quando solicitado explicitamente.
- Manter regressao viva com exemplos, fixtures e testes.

This project is not responsible for:

- Executar DDL definitivo em producao sem aprovacao humana.
- Substituir julgamento do DBA sobre impacto global no workload.
- Corrigir automaticamente estatisticas, baselines, profiles ou parametros do
  banco.
- Gerenciar credenciais, wallets ou conexoes como servico central.
- Ser uma API web, scheduler ou plataforma de monitoramento continua.
- Fazer tuning por IA nao deterministica dentro das regras.

## 6. Current Scope

Currently implemented:

- CLI single-query por `--sql`/`--plan` ou por `--sql-id` em modo DB.
- CLI batch para top SQL_IDs de banco real.
- Parser SQL via `sqlglot`.
- Parser de plano para SQL Monitor XML e DBMS_XPLAN texto.
- Coletor Oracle de metadados e coletor por fixture.
- Loader de env profile YAML.
- AWR HTML para env profile com create/update.
- Plan history por `GV$SQL` + `DBA_HIST_SQLSTAT`.
- Engine de regras-plugin.
- Regras R001, R002, R003, R004, R005, R006, R007, R008, R009, R010, R011 e
  R900.
- Reporter texto/Markdown, consolidacao de indices e merge de mitigacoes.
- Validador opt-in com indice invisivel.
- Testes offline com fixtures de casos reais.
- Memoria IA inicial: `context-index`, `implemented-index`, `decision-log` e
  `prompt-recipes`.

Planned or partially implemented:

- Completar memoria IA com `architecture-map.md`, `coding-rules.md` e
  `testing-rules.md`.
- Validar `--validate` em ambiente real controlado.
- Fortalecer cobertura unitária de CLI, batch, DB connection e validator.
- Estender parser AWR para novas variacoes reais conforme aparecerem.
- Evoluir analise batch/AWR de top SQL conforme necessidade operacional.
- Possivel camada futura de explicacao por IA, sem substituir regras.

Not planned:

- Criar indices definitivos automaticamente sem DBA.
- Fazer alteracoes globais de parametros do otimizador como recomendacao
  automatica.
- Transformar o projeto em web service ou dashboard neste momento.
- Guardar credenciais reais no repositorio.
- Usar IA como motor decisorio de tuning.

## 7. Main Domains

| Domain | Description | Main Location |
|---|---|---|
| SQL Parser | Extrai estrutura da query Oracle | `src/advisor/sql_parser.py` |
| Plan Parser | Lê SQL Monitor XML e DBMS_XPLAN texto | `src/advisor/plan_parser.py` |
| Metadata Collection | Coleta schema/stats/indices em Oracle ou fixture | `src/advisor/metadata_collector.py` |
| Env Profile | Carrega calibracao do ambiente | `src/advisor/env_profile.py`, `config/` |
| AWR Profile Builder | Converte AWR HTML em env profile | `src/advisor/awr_parser.py`, `src/advisor/profile_builder.py`, `src/advisor/awr_cli.py` |
| Rule Engine | Descobre e executa regras-plugin | `src/advisor/engine.py`, `src/advisor/rule_base.py` |
| Tuning Rules | Diagnosticos e recomendacoes deterministicas | `src/advisor/rules/` |
| Plan History | Coleta e ranqueia planos por SQL_ID | `src/advisor/plan_history.py` |
| Reporting | Consolida e formata recomendacoes | `src/advisor/reporter.py` |
| Validation | Mede ganho com indice invisivel | `src/advisor/validator.py` |
| CLI | Orquestra single-query e SQL_ID | `src/advisor/cli.py` |
| Batch | Analisa top SQLs de banco real | `src/advisor/batch.py`, `src/advisor/batch_cli.py` |
| Tests/Fixtures | Regressao viva offline | `tests/`, `examples/` |
| AI Memory | Contexto eficiente para agentes | `.ai/`, `AGENTS.md`, `CLAUDE.md` |

## 8. Tech Stack

- Language:
  - Python 3.10+
- Frameworks:
  - Sem web framework; biblioteca/CLI em layout `src`.
- Database / Warehouse:
  - Oracle Database 19c RAC como alvo operacional.
- Infrastructure:
  - Console scripts via setuptools.
  - Pytest para testes.
  - Fixtures offline para regressao.
- External services:
  - Oracle DB opcional via `python-oracledb`.
  - AWR HTML gerado pelo Oracle.
- Main dependencies:
  - `sqlglot`
  - `PyYAML`
  - `oracledb` opcional
  - `pytest` opcional/dev

## 9. Runtime / Execution Model

- Application type:
  - CLI, biblioteca Python e jobs manuais/on-demand de analise.
- Entry points:
  - `advisor = advisor.cli:main`
  - `advisor-awr = advisor.awr_cli:main`
  - `advisor-batch = advisor.batch_cli:main`
- Typical commands:
  - `python -m advisor.cli --sql examples/query.sql --plan examples/plan.txt --env config/env_profile_rawdb.yaml --source fixture --fixture tests.fixtures_rawdb`
  - `python -m advisor.awr_cli --awr awr_prod.html --out config/env_profile_prod.yaml --diag`
  - `python -m advisor.batch_cli --env config/env_profile_rawdb.yaml --source rawdb`
- Scheduling:
  - Manual/on-demand. Nao ha scheduler proprio.
- Deployment:
  - Projeto Python interno; instalado/editavel com `pip install -e ".[db,dev]"`.
  - Requer acesso Oracle apenas para fluxos DB, batch e validate.

## 10. Critical Rules

These rules must always be followed:

1. `engine.py` deve continuar generico; novas capacidades de tuning entram como
   regras em `src/advisor/rules/`.
2. Regras devem ser deterministicas, auditaveis e ler apenas `RuleContext`.
3. Nao mude contratos publicos (`models.py`, CLI flags, rule_id, formato de
   relatorio, YAML) sem atualizar testes e documentacao.
4. Siga padroes existentes antes de criar novas abstrações.
5. Mantenha mudancas pequenas e revisaveis.
6. Adicione ou atualize testes para mudancas de comportamento.
7. Nao adicione dependencias sem justificativa clara.
8. Nao versionar credenciais reais, wallets ou `config/db.yaml`.
9. `--validate` so deve rodar por pedido/intent explicito, pois cria indice
   temporario real.
10. Atualize memoria `.ai/` quando comportamento, arquitetura, testes, contratos
    ou decisoes importantes mudarem.

## 11. Important Constraints

- Performance constraints:
  - O advisor deve evitar ler arquivos grandes sem necessidade.
  - Regras devem ser simples e deterministicas para rodar em lote.
  - Em ambientes CPU-bound, beneficio e medido principalmente por reducao de
    buffer gets/linhas processadas.
- Data constraints:
  - Planos precisam de runtime stats para varias regras.
  - Metadados podem estar incompletos; o pipeline deve ser defensivo.
  - AWR HTML e fonte de fatos para perfis, mas campos humanos devem ser
    preservados no update.
- Security constraints:
  - Sem segredos no repositorio, logs, docs ou testes.
  - Banco real exige cuidado com privilegios DBA, AWR e validacao.
- Compatibility constraints:
  - Suporte atual e focado em Oracle 19c RAC.
  - Parser deve manter suporte a SQL Monitor XML e DBMS_XPLAN texto.
  - Fixtures offline devem continuar rodando sem Oracle.
- Cost constraints:
  - `--validate` cria indice, gera redo e consome recursos.
  - Recomendacoes de indice em tabelas quentes devem explicitar custo de
    manutencao/RAC.

## 12. Known Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Recomendacao de indice redundante | Custo de manutencao e ruido operacional | Checar indices existentes e consolidar no reporter |
| Owner ausente no SQL | DDL gerado no schema errado | Usar `ctx.resolve_owner()` via plano/metadados |
| Metadados incompletos | Decisoes menos precisas | Coletor resiliente, `collector.missing`, fallbacks por plano |
| Plano sem runtime stats | Regras de explosao/spill podem nao disparar | Preferir SQL Monitor XML ou DBMS_XPLAN com ALLSTATS |
| Env profile desatualizado | Scoring/DDL inadequados | Regerar por AWR e preservar campos humanos |
| `--validate` em producao | Consumo de recursos/redo | Opt-in explicito e aprovacao operacional |
| Mudanca em regra sem regressao | Regressao em caso real | Criar fixture/teste para todo caso novo |
| AWR/DBA views sem permissao | Coleta parcial ou erro | Falhas defensivas e diagnostico claro |
| Credencial exposta | Risco de seguranca alto | Usar examples/env/wallet; nao versionar config real |

## 13. Glossary

| Term | Meaning |
|---|---|
| A-Rows | Linhas reais processadas por uma operacao do plano |
| AWR | Automatic Workload Repository, relatorio Oracle usado para perfil |
| DBMS_XPLAN | Pacote Oracle para exibir plano de execucao |
| Env profile | YAML que calibra ambiente, scoring, RAC e DDL |
| E-Rows | Linhas estimadas pelo otimizador |
| Fixture | Metadados/artefatos offline para teste sem banco |
| Hot block | Bloco de indice/tabela sob contencao concorrente |
| Invisible index | Indice Oracle invisivel para validar plano em sessao controlada |
| LOCAL index | Indice particionado localmente alinhado a tabela particionada |
| Plan hash | Identificador de forma de plano Oracle |
| SQL Monitor XML | Relatorio XML de execucao com runtime stats detalhados |
| SQL Profile/Baseline | Intervencao Oracle que influencia/fixa plano |
| Workarea spill | SORT/HASH que derrama para TEMP por memoria insuficiente/volume alto |

## 14. Useful Links

- Repository:
  - Local workspace: `D:\projetos\dba\dba`
- Documentation:
  - `README.md`
  - `docs/MANUAL_DE_USO.md`
  - `docs/ARQUITETURA.md`
  - `docs/CONTRIBUTING.md`
  - `docs/GUIA_DE_COLETA.md`
  - `docs/GUIA_ENV_PROFILE.md`
- AI memory:
  - `.ai/context-index.md`
  - `.ai/implemented-index.md`
  - `.ai/decision-log.md`
  - `.ai/prompt-recipes.md`
- Operational configs:
  - `config/env_profile_rawdb.yaml`
  - `config/env_profile_datadb.yaml`
  - `config/db.yaml.example`
- Related systems:
  - Oracle DB 19c RAC environments such as RAWDB/DBN0 and DATADB/DBN1.

## 15. AI Agent Guidance

When working on this project:

1. Read this file first for objective, scope and constraints.
2. Use `.ai/context-index.md` to identify the smallest relevant context.
3. Use `.ai/implemented-index.md` to verify current behavior and tests.
4. Check `.ai/decision-log.md` before changing architecture, contracts,
   thresholds, rule design or operational policy.
5. Inspect existing implementation before creating new code.
6. Prefer modifying existing patterns over introducing new ones.
7. Add or update tests for behavior changes.
8. Update `.ai/implemented-index.md` if behavior, files or tests change.
9. Update `.ai/decision-log.md` if an architectural, product or operational
   decision is made.
10. Do not read unrelated large plan XMLs; use `.ai/context-index.md` routing.
