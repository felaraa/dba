# AGENTS.md - Guia operacional para Codex

Este arquivo deve ser o primeiro contexto lido por agentes Codex neste projeto.
Ele e intencionalmente curto: carregue detalhes sob demanda, a partir dos mapas
em `.ai/` quando eles existirem.

## Objetivo do projeto

O projeto `oracle-query-otim` e um advisor de indices e tuning para Oracle 19c
RAC. Ele recebe SQL, plano de execucao com estatisticas de runtime e metadados
de cardinalidade, entao produz recomendacoes ranqueadas com DDL, justificativa,
score de beneficio/custo e mitigacoes de RAC. O motor e deterministico: IA pode
ajudar a explicar resultados, mas nao deve substituir as regras auditaveis.

## Snapshot do sistema

- Runtime: Python 3.10+, pacote `src/` instalavel por `pyproject.toml`.
- Linguagem principal: Python.
- CLIs: `advisor`, `advisor-awr`, `advisor-batch`.
- Bibliotecas: `sqlglot`, `PyYAML`; opcionais `oracledb` e `pytest`.
- Banco alvo: Oracle 19c RAC, com modos offline por fixture e online por DBA/GV$/AWR.
- Dominios: parser SQL, parser de plano, coleta de metadados, regras-plugin,
  perfil AWR/YAML, relatorio, validacao por indice `INVISIBLE`, batch por SQL_ID.
- Servicos externos: somente Oracle DB quando `--source <banco>` ou `--validate`
  forem usados. Nao ha dependencia de rede para testes unitarios.

## Contexto sob demanda

Quando a pasta `.ai/` for criada, use estes arquivos em vez de reler o projeto
inteiro:

- `.ai/context-index.md` - ponto de entrada para escolher o menor contexto.
- `.ai/project-brief.md` - objetivo, escopo e limites.
- `.ai/architecture-map.md` - fluxo e responsabilidades por modulo.
- `.ai/implemented-index.md` - regras, casos reais e regressao viva.
- `.ai/coding-rules.md` - convencoes de implementacao.
- `.ai/testing-rules.md` - matriz de testes e comandos.
- `.ai/decision-log.md` - decisoes arquiteturais firmadas.
- `.ai/prompt-recipes.md` - prompts reutilizaveis para tarefas recorrentes.

Enquanto `.ai/` nao existir, leia preferencialmente `README.md`,
`docs/ARQUITETURA.md`, `docs/CONTRIBUTING.md`, `docs/MANUAL_DE_USO.md` e os
testes relacionados a tarefa.

## Mapa rapido de arquivos

- `src/advisor/models.py` - dataclasses que formam os contratos entre modulos.
- `src/advisor/rule_base.py` - `RuleContext` imutavel e interface `Rule`.
- `src/advisor/engine.py` - descobre e executa regras; nao contem tuning.
- `src/advisor/rules/` - regras-plugin e helpers de DDL/indices.
- `src/advisor/sql_parser.py` - SQL Oracle para `ParsedQuery`.
- `src/advisor/plan_parser.py` - SQL Monitor XML ou DBMS_XPLAN para `ParsedPlan`.
- `src/advisor/metadata_collector.py` - metadados Oracle ou fixtures.
- `src/advisor/env_profile.py` - leitura do YAML de ambiente.
- `src/advisor/awr_parser.py`, `profile_builder.py`, `awr_cli.py` - AWR para YAML.
- `src/advisor/cli.py` - analise de query por arquivo ou `--sql-id`.
- `src/advisor/batch.py`, `batch_cli.py` - top SQL em lote.
- `src/advisor/reporter.py` - consolidacao, merge de mitigacoes e formato final.
- `src/advisor/validator.py` - validacao opt-in com indice invisivel.
- `config/env_profile_rawdb.yaml` - perfil calibrado; dado, nao codigo.
- `tests/` - regressao viva dos casos reais e fixtures offline.
- `examples/` - SQLs, planos e relatorios de exemplo; alguns XMLs sao grandes.

## Regras centrais

1. Preserve o design: toda nova capacidade de tuning entra como regra em
   `src/advisor/rules/`, nunca como logica dentro de `engine.py`.
2. Leia o menor conjunto de arquivos que responde a tarefa. Use `rg` antes de
   abrir arquivos grandes.
3. Prefira mudancas pequenas e revisaveis, alinhadas aos padroes existentes.
4. Atualize ou adicione testes para qualquer mudanca de comportamento.
5. Nao adicione dependencia sem explicar o motivo e atualizar packaging/docs.
6. Nao mude contratos publicos silenciosamente: `models.py`, CLI flags, formato
   de relatorio, YAML e `rule_id` exigem cuidado extra.
7. Nao versionar credenciais. `config/db.yaml` deve ficar local; prefira
   `config/db.yaml.example` e variaveis `ORACLE_*` nos exemplos.
8. `--validate` cria e remove indice no banco. Use apenas quando a tarefa pedir
   explicitamente ou quando houver autorizacao operacional clara.
9. O perfil de ambiente e configuracao. Recalibrar ambiente significa editar ou
   regenerar `env_profile_*.yaml`, nao codificar excecoes nas regras.

## Convencoes obrigatorias para regras de indice

- Use `ctx.resolve_owner()` antes de gerar DDL; nao produza `None.TABELA`.
- Use `ctx.is_partitioned(owner, table)` para decidir `LOCAL`; ele infere pelo
  plano quando os metadados estao incompletos.
- Gere nome por `build_index_name(..., owner=owner)`; Oracle limita a 30 chars.
- Gere DDL por `build_index_ddl(..., parallel=ctx.env.index_parallel,
  tablespace=ctx.env.index_tablespace)`, incluindo `GATHER_INDEX_STATS`.
- Antes de recomendar indice, cheque indice existente com
  `existing_index_covering` ou `existing_index_exact_or_superset`.
- Nao consolide dentro da regra; `reporter.consolidate_indexes` faz isso.
- Regras devem ser deterministicas, sem chamadas de IA e sem efeitos colaterais.

## Fluxo de trabalho para Codex

1. Reescreva mentalmente a tarefa em uma frase e identifique o dominio.
2. Consulte este arquivo, depois o menor contexto relevante.
3. Inspecione implementacao e testes existentes antes de editar.
4. Faca a menor mudanca correta com `apply_patch`.
5. Rode o teste mais especifico; se a mudanca tocar contratos compartilhados,
   rode `python -m pytest -q`.
6. Atualize documentos de memoria quando a tarefa alterar arquitetura, regra,
   CLI, contrato, comportamento de teste ou decisao de design.
7. No resumo final, cite arquivos alterados e testes executados.

## Comandos uteis

```bash
python -m pytest -q
python -m pytest -q tests/test_pipeline.py
python -m advisor.cli --sql examples/query.sql --plan examples/plan.txt --env config/env_profile_rawdb.yaml --source fixture --fixture tests.fixtures_rawdb
python -m advisor.awr_cli --awr tests/fixtures/awr_sample.html --out temp/env_profile_test.yaml --diag
```

Para banco real, use `--source rawdb|datadb|db` com credenciais em `config/<source>.yaml`
ou variaveis `ORACLE_*`. Evite colocar senha em comandos, logs ou docs.

## Economia de tokens

- Comece por `rg -n "termo" src tests docs` ou `rg --files`.
- Nao abra `plan*.xml`, `plan.xml`, `plan2.xml`, `plan3.xml` ou `temp/` sem
  necessidade direta.
- Para nova regra, leia uma regra vizinha, `rules/__init__.py`,
  `rule_base.py`, o teste mais parecido e a fixture relevante.
- Para CLI, leia `cli.py` ou `batch_cli.py` mais o teste/documento relacionado.
- Para AWR/env profile, leia `awr_parser.py`, `profile_builder.py`,
  `awr_cli.py`, `docs/GUIA_ENV_PROFILE.md` e `tests/test_awr_profile.py`.
- Nao summarize o projeto inteiro em respostas; entregue somente o contexto da
  tarefa atual.
