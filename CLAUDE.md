# CLAUDE.md — Contexto do Projeto para o Claude Code

> Este arquivo é lido automaticamente pelo Claude Code a cada sessão. Ele
> condensa a arquitetura, as decisões de design e o histórico do projeto para
> que qualquer evolução continue coerente com o que já foi construído.

## O que é este projeto

Advisor de **índices e tuning para Oracle 19c RAC**. Recebe **query + plano de
execução + cardinalidade** e produz recomendações de índice ranqueadas (com DDL
pronto, score custo/benefício e mitigações de RAC), além de diagnósticos de
estatística, cartesiano e SQL Profile. Opcionalmente valida índices criando-os
como `INVISIBLE` e medindo o ganho real.

Foi calibrado com o ambiente real **RAWDB** (2 nós RAC, 19c, NÃO-Exadata,
192 CPUs/nó, 1 TB RAM/nó), cujo perfil foi extraído de AWRs.

## Princípio de design central (NÃO QUEBRAR)

**Motor de regras determinístico + regras como plugins desacoplados.**
- `src/advisor/engine.py` NÃO contém nenhuma regra de tuning. Ele descobre
  plugins em `src/advisor/rules/`, passa um `RuleContext` imutável a cada um e
  ranqueia a saída. Uma regra com exceção é isolada (não derruba o pipeline).
- Cada regra é um arquivo em `src/advisor/rules/` com uma subclasse de `Rule`.
  Adicionar = criar arquivo; remover = apagar; desligar = `--deny RULE_ID`.
- O ambiente é **configuração** (`config/env_profile_rawdb.yaml`), não código.
- IA (futuro) entra só como **camada de explicação/raciocínio**, NUNCA
  sobrescrevendo um achado determinístico das regras.

## Arquitetura

```
src/advisor/
  models.py              dataclasses imutáveis (contratos entre módulos)
  env_profile.py         carrega perfil do ambiente (YAML)
  sql_parser.py          SQL  -> ParsedQuery (via sqlglot)
  plan_parser.py         plano -> ParsedPlan (SQL Monitor XML | DBMS_XPLAN texto)
  metadata_collector.py  cardinalidade (Oracle DBA_* | fixture). É resiliente:
                         coleta cada tabela isolada, trata views, reporta faltantes.
  db_connection.py       resolução de credenciais (CLI > env > YAML > wallet)
  rule_base.py           Rule + RuleContext (ponto de desacoplamento)
  engine.py              descobre e executa regras-plugin; ranqueia por net_score
  rules/                 PLUGINS (uma regra por arquivo)
  validator.py           loop de índice INVISIBLE (medição real do ganho)
  reporter.py            consolidação de índices + merge de mitigações + saída
  cli.py                 orquestrador (--source db|fixture, --validate, --diag)
```

## Regras implementadas (ordem de prioridade = ordem de execução)

| ID | Prioridade | O que detecta |
|----|-----------|---------------|
| R005_existing_intervention | 1 | SQL Profile / Baseline / Outline já ativo no plano |
| R004_cartesian_or_bad_estimates | 5 | MERGE JOIN CARTESIAN; E-Rows overflow; divergência E-Rows×A-Rows. NO modo db, identifica QUAL tabela está com estatística obsoleta |
| R007_unused_existing_index | 8 | índice adequado já existe mas o otimizador faz FULL SCAN (explica o porquê) |
| R001_filter_should_be_access | 10 | join aplicado como `filter` pós-acesso + explosão de NESTED LOOPS |
| R002_avoidable_full_scan | 20 | TABLE ACCESS FULL evitável por join seletivo |
| R006_buffer_sort_materialization | 25 | BUFFER SORT/SORT JOIN materializando muitas linhas para join |
| R003_covering_for_aggregation | 30 | TABLE ACCESS BY ROWID custoso só para projeção/agregação |
| R008_global_index_on_partitioned | 40 | índice GLOBAL existente sobre tabela PARTICIONADA (dívida de manutenção) |
| R900_rac_hotblock_mitigation | 900 | hot leaf block em índice de chave crescente (RAC) — anexa mitigação |

R005 e R004 rodam ANTES das regras de índice de propósito: cartesiano se corrige
com estatística (não índice) e um índice pode nem ser usado se um SQL Profile
fixa o plano.

## Convenções de geração de índice (FIRMADAS — manter)

1. **Nome com owner, sem `__` duplo, <=30 chars.** Ex.:
   `IX_DBN0_ENR_RADIO_5G_NE_N_STAR`. Gerado por `build_index_name(...)`.
2. **Índice em tabela particionada SEMPRE `LOCAL`.** Se a tabela não foi
   coletada, o particionamento é INFERIDO do plano (`ctx.is_partitioned`,
   procura `PARTITION RANGE` ancestral). Nunca gerar índice global em tabela
   particionada por engano.
3. **GATHER_INDEX_STATS após todo CREATE**, no formato:
   `EXEC DBMS_STATS.GATHER_INDEX_STATS(OWNNAME=>'...', INDNAME=>'...',
   GRANULARITY=>'ALL', DEGREE=>16, FORCE=>TRUE);` (via `build_index_ddl`).
4. **Não recomendar índice que já existe.** As regras checam
   `existing_index_covering` (prefixo de colunas) antes de propor.
5. **Consolidar redundâncias.** `reporter.consolidate_indexes` funde índices
   sobrepostos na mesma tabela (mantém o superset).

## Perfil do ambiente RAWDB (de AWRs)

- **CPU-bound** (DB CPU 67-71% do DB time) → benefício medido em buffer gets /
  linhas processadas, não IO físico (cache hit altíssimo).
- **Contenção de índice em RAC já presente**: `enq: TX - index contention`,
  `gc buffer busy` no top 10; índices `*_SEQ_IDX` dominam Buffer Busy. Por isso
  R900 emite mitigação (hash global / INITRANS) para índices de chave crescente
  em tabelas quentes.
- Tabelas quentes confirmadas no AWR (em `config/env_profile_rawdb.yaml`):
  `T1542455817`, `T1526726713`, `LTE_SCTPASSOCIATION`, índices `NAMF_STATS_*`.
- HugePages: 650 GB reservados, ~305 GB em uso → folga para crescer SGA.
- 2 PDBs (1 irrelevante) → memória dimensionada no CDB, não por PDB.

## Casos reais já analisados (regressão viva em tests/)

1. **24h537gmxw93d** — explosão de NL (609M linhas), filtro que deveria ser
   access. Índice `(NE_NAME, STARTTIME)` resolveu. → test_pipeline.py
2. **bz8c7u3h7cv5m / cartesian** — MERGE JOIN CARTESIAN + SQL Profile coe_.
   → test_cartesian_case.py
3. **3fjgnfugy2kd6** — índice adequado já existia mas não era usado (R007).
   → test_unused_index_case.py
4. **bs541hud638cr** — estatística obsoleta identificada; LOCAL inferido do
   plano quando a tabela não foi coletada. → test_improvements_v3.py

## Pendências / próximos passos conhecidos

- **Investigar coleta incompleta**: no banco real, `T1526726713` não foi
  coletada (rodar `--source db --diag` mostra tabelas faltantes). Descobrir a
  causa (permissão/owner/nome) com conexão real.
- **Rodar `--validate` de verdade** contra o RAWDB (até agora só testado em
  fixture) para fechar o loop previsão→medição.
- **Regra R-global-on-partitioned**: auditar/sinalizar índices globais sobre
  tabelas particionadas como dívida de manutenção (query base em sql/).
- **Modo `--from-awr`**: varrer top SQL do AWR e analisar em lote.
- **Camada de IA opcional** (`--explain`): modelo via Ollama para explicação em
  linguagem natural; o motor de regras continua a fonte de verdade.

## Como rodar

```bash
# setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[db,dev]"

# testes (sem banco)
pytest -q

# análise offline (fixture)
python -m advisor.cli --sql examples/query.sql --plan examples/plan.txt \
  --env config/env_profile_rawdb.yaml --source fixture \
  --fixture tests.fixtures_rawdb

# análise real (banco) + diagnóstico de coleta
python -m advisor.cli --sql q.sql --plan p.xml \
  --env config/env_profile_rawdb.yaml --source db --diag \
  --dsn HOST:1521/RAWDB --user USUARIO   # senha via ORACLE_PASSWORD ou config/db.yaml

# validar índice recomendado com INVISIBLE (mede ganho real)
python -m advisor.cli ... --source db --validate
```

## Regras de ouro ao evoluir

- Toda nova capacidade de tuning é uma REGRA nova em `rules/`, não código no
  engine. **Use a skill `.claude/skills/criar-regra/` — ela padroniza o ritual
  (interface Rule, 5 convenções, teste obrigatório).**
- Todo caso real novo vira um teste em `tests/` (mantém a regressão viva).
- Nunca quebrar as 5 convenções de geração de índice acima.
- Em dúvida sobre o ambiente, o perfil YAML é a fonte; recalibrar editando o
  YAML, não o código.
