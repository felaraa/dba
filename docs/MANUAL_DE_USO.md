# Oracle Index Advisor — Manual de Utilização

Ferramenta de recomendação automatizada de índices para Oracle 19c RAC,
calibrada com o perfil real do cluster **RAWDB**. Recebe **query + plano de
execução + cardinalidade** e produz recomendações de índice ranqueadas, com
justificativa, score de custo/benefício e mitigações de RAC. Opcionalmente
**valida** cada índice criando-o como `INVISIBLE` e medindo o ganho real.

---

## 1. Conceito em uma figura

```
  query.sql ─┐
             ├─▶ sql_parser ─▶ ParsedQuery ─┐
  plan.txt ──┼─▶ plan_parser ─▶ ParsedPlan ─┤
             │                              ├─▶ RuleContext ─▶ RuleEngine ─▶ recomendações
  banco/DBA ─┼─▶ metadata_collector ────────┤        (regras-plugin)        (ranqueadas)
             │            ▲                  │
  AWR/YAML ──┴─▶ env_profile ─▶ EnvProfile ─┘
```

O **motor não contém regras**: cada regra é um arquivo-plugin em
`advisor/rules/`. Adicionar/alterar/remover uma regra não afeta nenhum outro
módulo. O **ambiente é configuração** (`config/env_profile_rawdb.yaml`).

---

## 2. Instalação

```bash
# Python 3.10+
cd oracle_index_advisor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`oracledb` só é necessário para `--source db` e `--validate`. Para a
demonstração offline (`--source fixture`) bastam `sqlglot` e `PyYAML`.

---

## 3. Os três insumos

### 3.1. A query (`--sql arquivo.sql`)
O texto SQL puro, com binds `:1`, `:3` etc. O parser resolve `owner.tabela`,
aliases, joins por igualdade, filtros range/igualdade e colunas projetadas.

### 3.2. O plano de execução (`--plan arquivo`)
Duas formas aceitas (detecção automática):

**(a) SQL Monitor em XML** — preferido, traz A-Rows, Execs e hierarquia:
```sql
SET LONG 2000000 LONGCHUNKSIZE 2000000 PAGESIZE 0 LINESIZE 32767
SELECT DBMS_SQLTUNE.REPORT_SQL_MONITOR(
         sql_id => '24h537gmxw93d', type => 'XML', report_level => 'ALL')
FROM dual;
-- salve a saída em plan.xml
```

**(b) DBMS_XPLAN em texto** — com estatísticas de runtime:
```sql
-- 1) execute a query com o hint para coletar A-Rows:
SELECT /*+ GATHER_PLAN_STATISTICS */ ... ;
-- 2) capture o plano com A-Rows, Execs, Buffers e predicados:
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(
  format => 'ALLSTATS LAST +PREDICATE'));
-- salve a saída em plan.txt
```
> Sem A-Rows o motor não confirma explosões de NESTED LOOPS; sempre use
> `GATHER_PLAN_STATISTICS` ou SQL Monitor.

### 3.3. A cardinalidade (metadados)
- **Produção (`--source db`)**: o coletor lê sozinho `DBA_TAB_COL_STATISTICS`,
  `DBA_PART_TABLES`, `DBA_INDEXES`/`DBA_IND_COLUMNS` e `DBA_INDEX_USAGE`.
- **Offline (`--source fixture`)**: um módulo Python com `get_metadata()`
  (ver `tests/fixtures_rawdb.py`) contendo os números já coletados.

---

## 4. Uso — passo a passo

### Passo 1 — gere a query e o plano
Salve a query em `examples/query.sql` e o plano (XML ou texto) em
`examples/plan.txt`, conforme a seção 3.2.

### Passo 2 — confira/edite o perfil do ambiente
`config/env_profile_rawdb.yaml` já vem calibrado com os AWRs do RAWDB
(CPU-bound, contenção de índice presente, tabelas quentes, latências de IO).
Para outro banco, copie o arquivo e ajuste os valores. **Editar o YAML
recalibra a engine sem tocar em código.**

### Passo 3 — rode a análise (offline, sem banco)
```bash
python -m advisor.cli \
  --sql examples/query.sql \
  --plan examples/plan.txt \
  --env config/env_profile_rawdb.yaml \
  --source fixture --fixture tests.fixtures_rawdb \
  --format text
```

### Passo 3' — rode contra o banco (produção)

A conexão é resolvida em ordem de prioridade (a primeira completa vence):
**parâmetros de CLI → variáveis de ambiente → `config/db.yaml` → Oracle Wallet**.
A senha não precisa ir na linha de comando.

**Opção A — arquivo de config (recomendado):**
```bash
cp config/db.yaml.example config/db.yaml
# edite config/db.yaml com dsn/user/password
chmod 600 config/db.yaml          # restrinja a permissão
python -m advisor.cli \
  --sql examples/query.sql --plan examples/plan.txt \
  --env config/env_profile_rawdb.yaml \
  --source db --format md
```

**Opção B — variáveis de ambiente (bom para CI / não deixa rastro):**
```bash
export ORACLE_DSN="rac-scan:1521/RAWDB"
export ORACLE_USER="USUARIO"
export ORACLE_PASSWORD="SENHA"
python -m advisor.cli --sql q.sql --plan p.xml \
  --env config/env_profile_rawdb.yaml --source db
```

**Opção C — parâmetros explícitos (evite a senha no histórico do shell):**
```bash
python -m advisor.cli ... --source db \
  --dsn HOST:1521/SERVICE --user U --password P
```

**Opção D — Oracle Wallet (sem senha em texto):** defina `wallet_location`
(e `config_dir`) no `config/db.yaml` ou nas variáveis `ORACLE_WALLET_LOCATION`
/`ORACLE_CONFIG_DIR`, e passe apenas o alias TNS em `dsn`.

O coletor puxa `DBA_TAB_COL_STATISTICS`, `DBA_PART_TABLES`, `DBA_INDEXES`/
`DBA_IND_COLUMNS` e `DBA_INDEX_USAGE` automaticamente; você não cola números.

**Thin vs thick:** o padrão é thin (não exige Oracle Client). Para thick,
defina `mode: thick` e `client_lib_dir` (ou `ORACLE_MODE=thick` +
`ORACLE_CLIENT_LIB_DIR`).

**Privilégios:** o usuário precisa ler as views `DBA_*`. Sem acesso a `DBA_*`,
ajuste o coletor para `ALL_*`/`USER_*` (ver `metadata_collector.py`).

### Passo 4 — leia o relatório
Cada recomendação traz: severidade, regra que disparou, **DDL pronto**,
**score líquido** (benefício − manutenção), justificativa e mitigações. Score
negativo é um aviso: o índice ajuda a query mas o custo de manutenção (em
tabela quente) é alto — decida com o contexto.

### Passo 5 (opcional, produção) — valide com índice invisível
```bash
python -m advisor.cli ... --source db --dsn ... --user ... --password ... \
  --validate
```
Para cada índice recomendado, a ferramenta: cria-o como `INVISIBLE` (não afeta
nenhuma outra sessão), liga `OPTIMIZER_USE_INVISIBLE_INDEXES` **só na sessão**,
reexecuta a query, compara buffer gets antes/depois, informa se o otimizador
usou o índice — e **remove o índice de teste ao final**. Você decide tornar
visível ou descartar.

> A validação CRIA índice (consome recursos e gera redo em tabela quente).
> É opt-in via `--validate` e nunca roda sem a flag.

---

## 5. Resultado concreto na query de exemplo

Aplicado à query real `24h537gmxw93d` (relatório 5G que rodava em **334s**,
**33M buffer gets**, com NESTED LOOPS tocando **609 milhões** de linhas):

| # | Severidade | Recomendação | Score |
|---|-----------|--------------|-------|
| 1 | CRITICAL | `CREATE INDEX ... ENR_RADIO_5G_GNODEB (NE_NAME, STARTTIME) LOCAL` | +0.95 |
| 2 | MEDIUM | `CREATE INDEX ... T1542455817 (RESULTTIME, OBJECT, LINKNO, GRANULARITYPERIOD) LOCAL` + mitigação RAC | −0.17 |

A recomendação #1 ataca a causa raiz: o join `A.OBJECT = K.NE_NAME` era
aplicado como **filtro pós-acesso**, fazendo o otimizador varrer todo o dia de
`STARTTIME` e produzir 609M linhas para entregar 24.360 (desperdício de
~25.000×). O índice `(NE_NAME, STARTTIME)` transforma o filtro em **probe
direto**. A #2 elimina o table-access da agregação, mas o motor sinaliza
(score negativo + mitigação) que, sendo `T1542455817` uma tabela quente com
contenção de índice já observada no AWR, a criação exige cuidado (INITRANS /
hash global).

O relatório completo está em `examples/resultado_exemplo.md`.

---

## 6. Operando o motor de regras (apartado)

### Listar/ligar/desligar regras
```bash
# apenas a regra crítica:
python -m advisor.cli ... --allow R001_filter_should_be_access
# desligar a cobertura:
python -m advisor.cli ... --deny R003_covering_for_aggregation
```

### Regras incluídas
| ID | Detecta | Prioridade |
|----|---------|-----------|
| `R005_existing_intervention` | SQL Profile / Baseline / Outline já ativo no plano | 1 (roda 1º) |
| `R004_cartesian_or_bad_estimates` | MERGE JOIN CARTESIAN, E-Rows com overflow, divergência E-Rows×A-Rows | 5 |
| `R007_unused_existing_index` | índice adequado já existe mas o otimizador faz FULL SCAN | 8 |
| `R001_filter_should_be_access` | join como `filter` pós-acesso + explosão de NL | 10 |
| `R002_avoidable_full_scan` | `TABLE ACCESS FULL` evitável por join seletivo | 20 |
| `R006_buffer_sort_materialization` | BUFFER SORT/SORT JOIN materializando muitas linhas p/ join | 25 |
| `R003_covering_for_aggregation` | table-access custoso só para projeção/agregação | 30 |
| `R900_rac_hotblock_mitigation` | hot leaf block em índice de chave crescente (RAC) | 900 |

As regras de menor prioridade numérica rodam primeiro. `R005` e `R004` rodam
antes das de índice de propósito: quando há SQL Profile ou cartesiano, o
diagnóstico de contexto deve preceder qualquer recomendação de índice — um
cartesiano se corrige com estatísticas, não com índice, e um índice pode nem
ser usado se um SQL Profile fixa o plano.

**Verificação de índice já existente.** Antes de recomendar, as regras de índice
(R001, R002, R006) checam o catálogo coletado: se já existe um índice cujas
primeiras colunas são as colunas de join (prefixo na mesma ordem), nenhuma
recomendação duplicada é emitida. Em vez disso, se a tabela ainda sofre FULL
SCAN, a **R007** dispara e explica por que o índice existente não está sendo
usado (cartesiano, estatísticas velhas, índice INVISIBLE/UNUSABLE, conversão de
tipo, skew), com os comandos de verificação.

**Consolidação de redundâncias.** Após as regras, o relatório funde índices
sobrepostos na mesma tabela: se uma recomendação é prefixo de outra (mesma
ordem de colunas), mantém só a mais completa. Evita propor dois índices quase
iguais vindos de regras diferentes (ex.: R002 e R006 na mesma tabela).

### Criar uma regra nova (sem tocar em nada mais)
Crie `advisor/rules/rule_minha.py`:
```python
from ..rule_base import Rule, RuleContext
from ..models import Recommendation, Severity

class MinhaRegra(Rule):
    rule_id = "R010_minha"
    description = "descrição curta"
    priority = 50          # menor roda primeiro
    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        # leia ctx.query, ctx.plan, ctx.metadata, ctx.env
        recs = []
        # ... sua lógica ...
        return recs
```
Salve. O motor descobre a regra automaticamente na próxima execução. Para
remover, apague o arquivo. Uma regra que lança exceção é isolada e não derruba
as demais.

---

## 7. Recalibrar para outro ambiente

Copie `config/env_profile_rawdb.yaml` e ajuste:
- `workload.cpu_bound` / `benefit_metric` — define se o ganho é medido em gets
  ou IO físico;
- `rac_contention.*` — liga as regras de mitigação de hot block e lista os
  segmentos quentes (por nome) extraídos do AWR;
- `scoring.*` — pesos de custo de manutenção (tabela quente vs fria), custo de
  cobertura por byte, limiar de coluna larga e fator de explosão de NL.

O parser de AWR validado (que extraiu o perfil RAWDB) pode ser reaproveitado
para gerar este YAML a partir de qualquer AWR HTML.

---

## 8. Testes

```bash
pytest -q                       # se tiver pytest
python tests/test_pipeline.py   # sem pytest
```
Cobrem parser de SQL, parser de plano (hierarquia, A-Rows, predicados) e o
pipeline completo reproduzindo o caso real.

---

## 9. Limites honestos (quando NÃO confiar cego)

- **Otimização local**: o motor analisa uma query. Antes de criar, verifique o
  impacto em outras (use `DBA_INDEX_USAGE` e o workload do AWR). Um índice ótimo
  para esta query pode ser redundante ou prejudicial a outras.
- **Trade-offs de tabela quente**: score negativo é decisão sua, não veto. O
  motor explicita o custo; o contexto operacional decide.
- **Validação fecha a lacuna**: para certeza, use `--validate`. É a diferença
  entre "previsão" e "medição".
- **A ferramenta recomenda; o DBA aprova.** Nenhum DDL é executado sem
  `--validate` (e mesmo este só cria índice invisível temporário).
