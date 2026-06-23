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
  plan_history.py        histórico de planos do SQL_ID (GV$SQL + AWR) -> PlanHistory.
                         Detecta instabilidade (vários plan_hash). Só no modo db.
  metadata_collector.py  cardinalidade (Oracle DBA_* | fixture). É resiliente:
                         coleta cada tabela isolada, trata views, reporta faltantes.
  awr_parser.py          AWR HTML -> AwrMetrics (números crus). Resiliente: cada
                         métrica isolada, reporta o que faltou. NÃO tem regra.
  profile_builder.py     AwrMetrics (+ perfil existente) -> env_profile YAML.
                         Aplica os LIMIARES (cpu_bound, cache_hit) e re-emite o
                         YAML COMENTADO. Preserva campos humanos no --update.
  awr_cli.py             orquestrador AWR->env_profile (create/update; agrega RAC)
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
| R009_plan_instability | 2 | vários plan_hash_value para o mesmo SQL_ID (instabilidade de plano). Identifica o MELHOR plano observado (menor elapsed/exec) e recomenda fixá-lo via SQL Plan Baseline. Depende do histórico de planos coletado de GV$SQL + AWR (só no modo db) |
| R004_cartesian_or_bad_estimates | 5 | MERGE JOIN CARTESIAN; E-Rows overflow; divergência E-Rows×A-Rows. NO modo db, identifica QUAL tabela está com estatística obsoleta |
| R007_unused_existing_index | 8 | índice adequado já existe mas o otimizador faz FULL SCAN (explica o porquê) |
| R001_filter_should_be_access | 10 | join aplicado como `filter` pós-acesso + explosão de NESTED LOOPS |
| R002_avoidable_full_scan | 20 | TABLE ACCESS FULL evitável por join seletivo |
| R006_buffer_sort_materialization | 25 | BUFFER SORT/SORT JOIN materializando muitas linhas para join |
| R010_workarea_spill_to_temp | 6 | SORT/HASH (GROUP BY/JOIN) derramando volume grande para o TEMP (workarea spill). Aponta a operação que mais derrama, liga a causa à estimativa colapsada (R004) e recomenda estatística + paralelismo (HASH GROUP BY paralelo, ENABLE PARALLEL DML). Sinaliza plano SERIAL apesar de hint PARALLEL. Consome `temp_bytes`/`spill_count`/`write_bytes` do SQL Monitor |
| R011_massive_rowid_access | 7 | TABLE ACCESS BY [LOCAL] INDEX ROWID devolvendo volume MASSIVO numa única passagem (inverso da R002): índice usado para varrer fração enorme da tabela. Recomenda full/partition scan + estatística + FULL/PARALLEL. Exclui o lado interno de NESTED LOOPS (muitas Execs → R001) |
| R003_covering_for_aggregation | 30 | TABLE ACCESS BY ROWID custoso só para projeção/agregação |
| R008_global_index_on_partitioned | 40 | índice GLOBAL existente sobre tabela PARTICIONADA (dívida de manutenção) |
| R900_rac_hotblock_mitigation | 900 | hot leaf block em índice de chave crescente (RAC) — anexa mitigação |

R005 e R004 rodam ANTES das regras de índice de propósito: cartesiano se corrige
com estatística (não índice) e um índice pode nem ser usado se um SQL Profile
fixa o plano. R009 (prioridade 2) também é contexto: se a query tem vários
planos, a primeira coisa é estabilizar o melhor — um índice novo é inútil se o
otimizador continua trocando de plano.

`R009` consome um dado novo no `RuleContext`: `ctx.plan_history` (um
`PlanHistory`), preenchido por `plan_history.collect_plan_history(conn, sql_id)`
a partir de **GV$SQL** (cursores vivos em todos os nós do RAC) + **DBA_HIST_SQLSTAT**
(AWR), fundidos por `plan_hash_value` com médias por execução. Em `--source
fixture` o histórico vem vazio e a regra fica inerte (a coleta é só no modo db).

## Convenções de geração de índice (FIRMADAS — manter)

1. **Nome com owner, sem `__` duplo, <=30 chars.** Ex.:
   `IX_DBN0_ENR_RADIO_5G_NE_N_STAR`. Gerado por `build_index_name(...)`.
2. **Índice em tabela particionada SEMPRE `LOCAL`.** Se a tabela não foi
   coletada, o particionamento é INFERIDO do plano (`ctx.is_partitioned`,
   procura `PARTITION RANGE` ancestral). Nunca gerar índice global em tabela
   particionada por engano.
3. **DDL via `build_index_ddl` — owner-qualificado + GATHER_INDEX_STATS.**
   O índice é SEMPRE criado no MESMO owner da tabela
   (`CREATE INDEX owner.idx ON owner.tab ...`). Seguido de
   `EXEC DBMS_STATS.GATHER_INDEX_STATS(OWNNAME=>'...', INDNAME=>'...',
   GRANULARITY=>'ALL', DEGREE=>16, FORCE=>TRUE);`. Opções vindas do env
   (`index_ddl:`) afetam só o texto: `parallel` adiciona `PARALLEL n` ao CREATE
   e emite `ALTER INDEX ... NOPARALLEL;` em seguida; `tablespace` adiciona
   `TABLESPACE <ts>`. As regras passam `parallel=ctx.env.index_parallel,
   tablespace=ctx.env.index_tablespace`.
4. **Não recomendar índice que já existe.** As regras checam
   `existing_index_covering` antes de propor. O match das colunas líderes de
   IGUALDADE é por CONJUNTO, não por sequência: um índice `(MOBILE_SITE_NAME,
   CELL_NAME, STARTTIME)` é reconhecido como adequado para um join por
   `(CELL_NAME, MOBILE_SITE_NAME)` — não se gera um índice redundante que só
   difere na ordem das colunas de igualdade.
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
5. **a3yqht3qtyyhy** — instabilidade de plano (2 planos; NL 3,8x pior que o
   HASH JOIN). Expôs e fechou dois bugs de coleta de índice:
   (a) cursor reusado em `_indexes` perdia índices silenciosamente (tabela com 5
   índices voltava com 0) → fix `fetchall()` antes do loop;
   (b) índice existente em outra ordem das colunas de igualdade não era
   reconhecido → `existing_index_covering` passou a comparar por CONJUNTO.
   → test_index_collection_fixes.py

## Pendências / próximos passos conhecidos

- **Investigar coleta incompleta**: no banco real, `T1526726713` não foi
  coletada (rodar `--source db --diag` mostra tabelas faltantes). Descobrir a
  causa (permissão/owner/nome) com conexão real.
- **Rodar `--validate` de verdade** contra o RAWDB (até agora só testado em
  fixture) para fechar o loop previsão→medição.
- **Regra R-global-on-partitioned**: auditar/sinalizar índices globais sobre
  tabelas particionadas como dívida de manutenção (query base em sql/).
- **Geração de env_profile a partir de AWR**: FEITO — `advisor.awr_cli`
  (create/update) + `docs/GUIA_ENV_PROFILE.md`. Próximo: validar o parser contra
  AWRs reais de outras versões e estender as palavras-chave conforme aparecerem.
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

# criar/atualizar um env_profile a partir de um AWR HTML (ver docs/GUIA_ENV_PROFILE.md)
python -m advisor.awr_cli --awr awr_prod.html --out config/env_profile_prod.yaml --diag
python -m advisor.awr_cli --awr awr_novo.html --out config/env_profile_prod.yaml --update
```

## Como nasce/atualiza um env_profile (AWR -> YAML)

O perfil do ambiente NÃO é digitado a mão a partir do zero: `advisor.awr_cli` lê
um (ou vários) AWR HTML e emite o `env_profile_*.yaml` comentado.

- `awr_parser.py` extrai os fatos crus (resiliente, reporta o que faltou);
- `profile_builder.py` aplica os LIMIARES de calibração (`CPU_BOUND_THRESHOLD`,
  `CACHE_HIT_VERY_HIGH_PCT`, ...) e re-emite o YAML inteiro pelo template
  comentado — por isso `--update` NUNCA perde comentários nem campos humanos;
- campos HUMANOS (`scoring.*`, `index_ddl.*`, `identity.exadata`,
  `io.full_scan_block_discount`, `workload.benefit_metric`) recebem default no
  create e são PRESERVADOS no update. O resto é refrescado do AWR.
- Caso real novo de AWR vira teste com fixture HTML em `tests/fixtures/`.

Passo a passo completo em `docs/GUIA_ENV_PROFILE.md`.

## Regras de ouro ao evoluir

- Toda nova capacidade de tuning é uma REGRA nova em `rules/`, não código no
  engine. **Use a skill `.claude/skills/criar-regra/` — ela padroniza o ritual
  (interface Rule, 5 convenções, teste obrigatório).**
- Todo caso real novo vira um teste em `tests/` (mantém a regressão viva).
- Nunca quebrar as 5 convenções de geração de índice acima.
- Em dúvida sobre o ambiente, o perfil YAML é a fonte; recalibrar editando o
  YAML, não o código.
