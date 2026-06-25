# Prompt Recipes

Ultima revisao: 2026-06-25.

Este arquivo contem prompts curtos e reutilizaveis para trabalhar com IA neste
projeto. Substitua os trechos entre `<...>` pela tarefa concreta. Antes de usar
um recipe, leia `AGENTS.md` ou `CLAUDE.md` e escolha o dominio em
`.ai/context-index.md`.

## Implementar uma mudanca pequena

Prompt:
```text
Leia AGENTS.md e .ai/context-index.md.
Use o dominio relevante para <mudanca>.
Inspecione a implementacao existente antes de editar.
Implemente a menor mudanca correta.
Adicione ou atualize testes se houver mudanca de comportamento.
Atualize .ai/implemented-index.md se comportamento, arquivos ou testes mudarem.
Atualize .ai/decision-log.md apenas se houver decisao duravel.
No final, informe arquivos alterados e testes executados.
```

Use for:
- Pequenas melhorias de comportamento.
- Ajustes em regra existente.
- Mudancas em CLI, reporter ou parser com escopo claro.

## Criar uma nova regra de tuning

Prompt:
```text
Leia AGENTS.md, CLAUDE.md, .ai/context-index.md e .ai/implemented-index.md.
Use a secao "New Or Changed Tuning Rule" do context-index.
Se estiver no Claude Code, use .claude/skills/criar-regra/SKILL.md.
Crie uma regra-plugin em src/advisor/rules/ sem tocar em engine.py.
Leia uma regra semelhante e siga RuleContext + Recommendation.
Se gerar indice, use ctx.resolve_owner, ctx.is_partitioned, build_index_name,
build_index_ddl e existing_index_covering/exact_or_superset.
Crie fixture e teste de regressao para o caso.
Rode o teste especifico e, se tocar contratos compartilhados, python -m pytest -q.
Atualize .ai/implemented-index.md e, se mudar prioridade/design de regras,
.ai/decision-log.md.
```

Use for:
- "Adicionar regra R0XX para detectar..."
- "O advisor deveria recomendar..."
- "Sinalizar um novo padrao de plano Oracle."

## Debugar um bug

Prompt:
```text
Leia AGENTS.md e .ai/context-index.md.
Classifique o bug por dominio: SQL parser, plan parser, metadata collector,
rule, env profile/AWR, CLI, batch, reporter ou validator.
Leia apenas os arquivos e testes indicados para esse dominio.
Reproduza ou localize um teste/fixture proximo.
Explique a causa raiz em uma frase.
Corrija com a menor mudanca segura.
Adicione teste de regressao que falharia antes da correcao.
Rode o teste especifico; rode a suite se contrato compartilhado mudou.
Atualize .ai/implemented-index.md se o comportamento mudou.
Atualize .ai/decision-log.md se a correcao firmar uma nova decisao.
```

Use for:
- Owner errado no DDL.
- Plano XML/texto parseado incorretamente.
- Indice existente nao detectado.
- Recomendacao duplicada ou ausente.

## Investigar uma query real

Prompt:
```text
Leia AGENTS.md, .ai/context-index.md e a secao Examples And Input Artifacts.
Use os artefatos: SQL <arquivo.sql>, plano <arquivo.xml/txt>, fixture <fixture>
ou fonte DB <source>.
Nao leia outros XMLs grandes.
Rode a analise offline se houver fixture:
python -m advisor.cli --sql <sql> --plan <plan> --env <env> --source fixture --fixture <fixture>
Identifique quais regras disparam e se ha lacuna de metadados.
Se virar caso novo, salve query/plano em examples/, crie fixture e teste.
Atualize .ai/implemented-index.md com o novo caso real.
```

Use for:
- Analisar novo SQL_ID exportado.
- Transformar caso manual em regressao.
- Comparar comportamento de regras em plano novo.

## Ajustar parser SQL

Prompt:
```text
Leia .ai/context-index.md > SQL Parser.
Abra src/advisor/sql_parser.py, src/advisor/models.py e tests/test_pipeline.py.
Use um SQL minimo que reproduza <caso>.
Preserve tolerancia: o parser deve extrair o que conseguir sem ampliar escopo
desnecessariamente.
Adicione assertion focada para tabela, alias, join, filtro, projection ou group by.
Rode python -m pytest -q tests/test_pipeline.py.
Atualize .ai/implemented-index.md se o parser passar a suportar novo padrao.
```

Use for:
- Alias/owner nao extraido.
- Join/filtro faltando.
- Bind Oracle causando erro.

## Ajustar parser de plano

Prompt:
```text
Leia .ai/context-index.md > Plan Parser.
Abra src/advisor/plan_parser.py, src/advisor/models.py e o teste mais proximo.
Use apenas o plano XML/texto relevante ao caso.
Preserve suporte a SQL Monitor XML e DBMS_XPLAN texto.
Se adicionar campo em PlanOperation/ParsedPlan, atualize todos consumidores.
Adicione teste para hierarquia, predicado, runtime stats, owner ou workarea.
Rode os testes especificos indicados no context-index.
Atualize .ai/implemented-index.md e .ai/decision-log.md se o contrato mudar.
```

Use for:
- Erro em A-Rows/E-Rows.
- SQL Profile/Baseline nao detectado.
- Workarea/TEMP ausente.
- Owner do objeto nao resolvido.

## Ajustar coleta de metadados

Prompt:
```text
Leia .ai/context-index.md > Metadata Collection.
Abra src/advisor/metadata_collector.py, models.py e tests/test_index_collection_fixes.py.
Preserve resiliencia por tabela e collector.missing.
Nao introduza dependencia de banco real em teste unitario.
Use cursor fake ou fixture para reproduzir <caso>.
Rode python -m pytest -q tests/test_index_collection_fixes.py tests/test_improvements_v3.py.
Atualize .ai/implemented-index.md se metadados coletados ou comportamento mudarem.
```

Use for:
- Indices faltando.
- View/tabela nao coletada.
- Stale stats ou particionamento incorreto.

## Ajustar AWR/env profile

Prompt:
```text
Leia .ai/context-index.md > Env Profile And AWR.
Abra awr_parser.py, profile_builder.py, awr_cli.py, docs/GUIA_ENV_PROFILE.md
e tests/test_awr_profile.py.
Separe fatos crus do AWR de politica/calibracao do profile_builder.
Preserve campos humanos no --update, ou registre decisao se isso mudar.
Use tests/fixtures/awr_sample.html ou fixture nova pequena.
Rode python -m pytest -q tests/test_awr_profile.py.
Atualize .ai/implemented-index.md; atualize .ai/decision-log.md para novos
limiares, campos humanos ou politica de update.
```

Use for:
- Novo campo do env profile.
- Nova secao de AWR.
- Mudanca em thresholds CPU/cache/hot segments.

## Ajustar CLI ou batch

Prompt:
```text
Leia .ai/context-index.md > CLI Single Query And SQL_ID Flow ou Batch Analysis.
Abra src/advisor/cli.py ou batch.py/batch_cli.py e docs/MANUAL_DE_USO.md.
Preserve modos: arquivo vs --sql-id; fixture vs DB; --validate opt-in.
Nao exponha credenciais em logs ou exemplos.
Adicione teste unitario se alterar validacao de argumentos ou formatacao pura.
Rode tests/test_pipeline.py e testes novos.
Atualize README/docs se comando publico mudar.
Atualize .ai/implemented-index.md; atualize .ai/decision-log.md se mudar
contrato de CLI, thresholds de batch ou politica operacional.
```

Use for:
- Nova flag.
- Mudanca em `--sql-id`.
- Mudanca em batch top SQL.
- Ajuste de diagnostico.

## Ajustar reporter/output

Prompt:
```text
Leia .ai/context-index.md > Reporting And Output Formatting.
Abra src/advisor/reporter.py, models.py e testes test_pipeline/test_unused_index_case.
Preserve separacao: engine decide, reporter apresenta/consolida.
Se mudar formato, considere exemplos em examples/resultado_*.md.
Adicione teste para consolidacao, merge de warnings ou ordenacao.
Rode python -m pytest -q tests/test_pipeline.py tests/test_unused_index_case.py.
Atualize .ai/implemented-index.md se output ou consolidacao mudarem.
```

Use for:
- Recomendacoes duplicadas no relatorio.
- Warnings nao anexados.
- Markdown/texto incorreto.

## Refatorar com preservacao de comportamento

Prompt:
```text
Leia AGENTS.md, .ai/context-index.md e .ai/decision-log.md.
Preserve comportamento e contratos publicos.
Nao altere rule_id, CLI flags, dataclasses ou formato de relatorio sem pedido
explicito.
Faça refatoracao pequena e mecanica.
Rode os testes do dominio e a suite completa se tocar contrato compartilhado.
Nao atualize .ai/decision-log.md a menos que uma decisao arquitetural nova seja
tomada.
Atualize .ai/implemented-index.md somente se arquivos/responsabilidades mudarem.
```

Use for:
- Extrair helper.
- Reduzir duplicacao.
- Reorganizar codigo sem mudar comportamento.

## Revisar codigo

Prompt:
```text
Leia .ai/context-index.md para o dominio da mudanca.
Revise em postura de code review.
Priorize bugs, regressões comportamentais, contratos quebrados, riscos Oracle
e testes ausentes.
Liste findings por severidade com arquivo/linha.
Se nao houver issues, diga isso claramente e cite riscos/testes residuais.
Nao proponha refatoracao ampla fora do escopo.
```

Use for:
- Revisar PR/diff.
- Validar alteracao feita por outro agente.
- Procurar regressao antes de commit.

## Atualizar memoria IA

Prompt:
```text
Leia AGENTS.md, CLAUDE.md e .ai/context-index.md > Project Memory.
Atualize o menor conjunto de arquivos .ai necessario para <mudanca>.
Use:
- implemented-index.md para comportamento/arquivos/testes.
- decision-log.md para decisoes duraveis.
- context-index.md para novo dominio/modulo/grupo de arquivos.
- architecture-map.md/coding-rules.md/testing-rules.md quando existirem e forem
  afetados.
Nao atualize memoria por typo ou formatacao trivial.
No final, diga quais memorias foram atualizadas e por que.
```

Use for:
- Criar novos arquivos `.ai/`.
- Registrar decisao.
- Atualizar inventario apos feature/regra.

## Preparar commit

Prompt:
```text
Confira git status.
Separe mudancas suas de arquivos nao relacionados.
Revise diffs dos arquivos alterados.
Confirme testes executados ou explique por que nao foram necessarios.
Sugira mensagem de commit curta no formato imperativo.
Nao reverta mudancas nao relacionadas.
```

Use for:
- Fechar uma etapa.
- Preparar resumo para commit manual.
- Conferir se memoria foi atualizada.
