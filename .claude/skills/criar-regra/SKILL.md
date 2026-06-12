---
name: criar-regra
description: >
  Cria uma nova regra-plugin para o motor do advisor (oracle-query-otim).
  Use SEMPRE que o pedido for adicionar/implementar uma regra de detecção ou
  recomendação de tuning Oracle — por exemplo "adicione uma regra que detecta
  X", "crie uma regra para sinalizar Y", "o advisor deveria recomendar Z".
  Garante que a regra siga a interface Rule, as 5 convenções de geração de
  índice do projeto, e venha SEMPRE acompanhada de um caso de teste com fixture.
---

# Skill: Criar uma nova regra do advisor

Esta skill padroniza a criação de regras-plugin. O motor (`src/advisor/engine.py`)
descobre regras automaticamente em `src/advisor/rules/`; nunca edite o engine
para adicionar uma regra.

## Passo a passo (siga na ordem)

### 1. Definir identidade da regra
- `rule_id`: padrão `R0XX_nome_curto` (ex.: `R008_redundant_index`). Escolha o
  próximo número livre olhando os arquivos em `src/advisor/rules/`.
- `priority` (menor roda primeiro). Convenção do projeto:
  - 1–9: regras de **contexto/diagnóstico** que devem preceder índices
    (intervenção ativa, cartesiano, índice existente não usado).
  - 10–30: regras que **geram índice** (probe, full scan, materialização, cobertura).
  - 900+: regras de **mitigação** que anexam avisos (ex.: RAC hot block).

### 2. Criar o arquivo da regra
Copie `templates/rule_template.py` para
`src/advisor/rules/rule_<nome>.py` e implemente `evaluate`. Leia apenas o
`RuleContext` (`ctx.query`, `ctx.plan`, `ctx.metadata`, `ctx.env`). Regras NÃO
veem a saída umas das outras.

### 3. Se a regra gera índice, respeitar as 5 CONVENÇÕES (obrigatório)
1. **Nome com owner, sem `__`, ≤30 chars**: use
   `build_index_name(table, cols, owner=owner)`.
2. **LOCAL em tabela particionada**: use `local = ctx.is_partitioned(owner, table)`
   (infere do plano se a tabela não foi coletada). NUNCA gere índice global em
   tabela particionada por engano.
3. **DDL owner-qualificado + GATHER_INDEX_STATS**: monte o DDL com
   `build_index_ddl(owner, table, idx_name, cols, local,
   parallel=ctx.env.index_parallel, tablespace=ctx.env.index_tablespace)`.
   O índice é criado no MESMO owner da tabela; `parallel`/`tablespace` (do env)
   só ajustam o texto do CREATE.
4. **Não recomendar índice que já existe**: cheque
   `existing_index_covering(ctx.metadata, table, eq_cols)` e pule se retornar algo.
5. **Não deduplicar manualmente**: a consolidação de índices sobrepostos é feita
   pelo `reporter.consolidate_indexes`; só produza a recomendação.

Helpers ficam em `src/advisor/rules/__init__.py`.

### 4. Escolher severidade e score
- `Severity`: CRITICAL (explosão/cartesiano), HIGH (full scan, índice não usado),
  MEDIUM (cobertura, divergência), LOW/INFO (avisos).
- `estimated_benefit` e `estimated_maint_cost` (0..1+). Para tabela quente, o
  custo de manutenção vem alto (vem de `ctx.env.score(...)`), o que pode tornar
  `net_score` negativo — isso é desejado: sinaliza trade-off, não bug.

### 5. Criar o caso de teste (OBRIGATÓRIO — não pular)
Toda regra nova vira regressão viva. Copie `templates/test_template.py` para
`tests/test_<nome>.py` e:
- Se precisar de um plano/query específicos, salve em `examples/`.
- Se precisar de cardinalidade, crie `tests/fixtures_<nome>.py` com
  `get_metadata()` (espelhe um fixture existente).
- Escreva asserts validando o que a regra deve (e não deve) produzir.

### 6. Rodar e validar
```bash
pytest -q                      # TODOS devem passar (regressão + novo teste)
# inspeção manual da regra isolada:
python -m advisor.cli --sql examples/<q>.sql --plan examples/<p> \
  --env config/env_profile_rawdb.yaml --source fixture \
  --fixture tests.fixtures_<nome> --allow R0XX_nome_curto
```

### 7. Atualizar documentação
- Adicione a regra à tabela em `CLAUDE.md` (seção "Regras implementadas").
- Se introduziu um conceito novo, mencione em `docs/ARQUITETURA.md`.

## Checklist final
- [ ] `rule_id` único e `priority` na faixa correta
- [ ] lê só o `RuleContext`; sem efeitos colaterais
- [ ] (se gera índice) as 5 convenções aplicadas
- [ ] teste novo criado e `pytest -q` 100% verde
- [ ] `CLAUDE.md` atualizado

## Anti-padrões (NÃO faça)
- Não edite `engine.py` para "registrar" a regra — a descoberta é automática.
- Não deduplique ou reordene recomendações dentro da regra.
- Não assuma `local=False` quando a tabela não foi coletada — use `is_partitioned`.
- Não use IA/heurística não-determinística dentro da regra; regras são auditáveis.
- Não recomende índice sem antes checar `existing_index_covering`.
