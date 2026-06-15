# Guia — Criar e Atualizar um `env_profile` a partir de um AWR

O `env_profile_*.yaml` é a **fonte de verdade do ambiente** para a engine: ele
diz se o banco é CPU-bound, qual a latência de IO, se há contenção de índice em
RAC, quais segmentos estão quentes e quais parâmetros do otimizador valem. Editar
esse YAML recalibra a engine **sem tocar em código**.

Este guia mostra como gerar/atualizar esse perfil **automaticamente a partir de
um AWR report**, usando a ferramenta `advisor-awr` (módulo
[`advisor.awr_cli`](../src/advisor/awr_cli.py)).

> Princípio: o AWR fornece os **fatos** (números crus). A ferramenta aplica os
> **limiares** de calibração e monta o YAML. Os **pesos de scoring** e as opções
> de DDL **não** vêm do AWR — são ajuste humano e ficam preservados nas
> atualizações.

---

## 0. Visão geral do fluxo

```
AWR HTML ─▶ awr_parser ─▶ AwrMetrics ─┐
(1 ou N)    (resiliente)              ├─▶ profile_builder ─▶ env_profile_X.yaml
                       perfil atual ──┘   (limiares + merge)   (YAML comentado)
                       (só no --update)
```

- **awr_parser.py** — lê o AWR HTML. Resiliente: cada métrica é extraída
  isolada; seção ausente nunca derruba o parse, só entra em "não encontrado".
- **profile_builder.py** — decide `cpu_bound`, `cache_hit_very_high` etc. a
  partir dos números, e emite o YAML **comentado** (mesmo estilo do
  `env_profile_rawdb.yaml`).
- **awr_cli.py** — orquestra: lê arquivos, agrega (RAC), cria ou atualiza.

---

## 1. Gerar o AWR em **HTML**

A ferramenta lê AWR em **HTML** (formato estável entre versões). Gere assim:

```sql
-- conecte no CDB$ROOT (ou no PDB, conforme seu padrão) como usuário com acesso a AWR
@?/rdbms/admin/awrrpt.sql
-- responda:
--   Enter value for report_type: html        <-- IMPORTANTE: html (não text)
--   num_days / begin_snap / end_snap          <-- janela representativa
--   report_name: awr_PRODDB.html
```

Para **RAC**, gere **um AWR por instância** (mais fiel para latência/contenção
por nó) com `awrrpti.sql`, ou um AWR **global** com `awrgrpt.sql`:

```sql
@?/rdbms/admin/awrrpti.sql   -- escolha 'html', a instância (1, depois 2) e os snaps
-- gere awr_PRODDB_inst1.html e awr_PRODDB_inst2.html
```

> Escolha uma janela **representativa** da carga que você quer otimizar (ex.: o
> horário do batch pesado, ou um pico OLTP típico) — não um período ocioso.

---

## 2. Criar um perfil **novo**

```bash
# perfil de um único AWR
python -m advisor.awr_cli \
  --awr awr_PRODDB.html \
  --out config/env_profile_proddb.yaml \
  --diag
```

```bash
# RAC: agregue um AWR por nó (médias por nó, união dos segmentos quentes)
python -m advisor.awr_cli \
  --awr awr_PRODDB_inst1.html awr_PRODDB_inst2.html \
  --name PRODDB --rac-nodes 2 \
  --out config/env_profile_proddb.yaml \
  --diag
```

Opções úteis:

| Flag | Para quê |
|------|----------|
| `--awr a.html [b.html …]` | um ou mais AWRs HTML (RAC: um por nó) |
| `--out caminho.yaml` | arquivo a gravar |
| `--name NOME` | sobrescreve `identity.name` (senão usa o *DB Name* do AWR) |
| `--rac-nodes N` | sobrescreve `identity.rac_nodes` |
| `--exadata` | marca `identity.exadata: true` (o AWR não detecta sozinho) |
| `--stdout` | imprime o YAML em vez de (ou além de) gravar |
| `--diag` | mostra o que foi extraído e **o que faltou** no AWR |

> **Atenção:** sem `--update`, um `--out` que já existe é **sobrescrito** (e os
> ajustes humanos de scoring/DDL se perdem). Para preservá-los, use `--update`.

---

## 3. **Atualizar** um perfil existente (com um AWR mais recente)

```bash
python -m advisor.awr_cli \
  --awr awr_PRODDB_nova_janela.html \
  --out config/env_profile_proddb.yaml \
  --update --diag
```

No modo `--update`, a ferramenta:

- **REFRESCA** os campos derivados do AWR (workload, IO, contenção, segmentos
  quentes, optimizer, identidade);
- **PRESERVA** os campos humanos: `scoring.*`, `index_ddl.*`,
  `identity.exadata`, `io.full_scan_block_discount` e `workload.benefit_metric`;
- **re-emite o arquivo inteiro** pelo template comentado — então **os
  comentários nunca se perdem** (diferente de um `yaml.dump`).

Sobre `hot_segments` no update: se o AWR trouxe segmentos, eles **substituem** a
lista (o AWR é a fonte do que está quente *agora*). Se o AWR não trouxe nenhum
(seção ausente), a lista anterior é **preservada**.

---

## 4. Ler o `--diag`

```
[awr] modo: CREATE
[awr] arquivos lidos: awr_PRODDB.html
[awr] CAMPOS ENCONTRADOS (11): db_name, oracle_version, db_block_size, ...
[awr] AVISO — NÃO encontrados no AWR (1): multiblock_read_count
[awr]   (esses campos ficam com default no CREATE, ou são preservados ... no UPDATE)
[awr] segmentos quentes capturados: 5
    DBN0_HUA_RAN.T1542455817 (TABLE)
    ...
[awr] cpu_bound=True db_cpu%=0.71 cache_hit_very_high=True
[awr] destino: config/env_profile_proddb.yaml
```

Se algo importante aparecer em **NÃO encontrados**, normalmente é porque:

- o AWR foi gerado em **texto**, não HTML → regere em HTML;
- o parâmetro do otimizador está no **default** e o AWR não o lista (a seção
  init.ora costuma listar só parâmetros não-default) → ajuste a mão se quiser
  fixar o valor;
- a seção tem um cabeçalho diferente na sua versão → ajuste o valor a mão e,
  se for recorrente, abra um caso (o parser casa por palavra-chave e é fácil de
  estender).

---

## 5. De onde vem cada campo

| Campo | Origem | Como é derivado |
|-------|--------|-----------------|
| `identity.name` | AWR (DB Name) | ou `--name` |
| `identity.rac_nodes` | AWR (RAC / nº instâncias) | ou `--rac-nodes`; default 2 se RAC=YES |
| `identity.oracle_version` | AWR (Release) | — |
| `identity.db_block_size` | AWR (init.ora) | — |
| `identity.exadata` | **humano** | `--exadata` ou preservado |
| `workload.cpu_bound` | AWR (Time Model) | `DB CPU / DB time ≥ 0.50` |
| `workload.db_cpu_pct_of_dbtime` | AWR (Time Model / Top Events) | DB CPU ÷ DB time |
| `workload.cache_hit_very_high` | AWR (Instance Efficiency / Load Profile) | `Buffer Hit % ≥ 99` ou `LIO/PIO ≥ 50` |
| `workload.redo_mb_per_s` | AWR (Load Profile) | Redo size/s ÷ 1 MB |
| `workload.block_changes_per_s` | AWR (Load Profile) | Block changes / s |
| `workload.benefit_metric` | **humano** | preservado / default |
| `io.single_block_read_us` | AWR (Foreground Wait Events) | `db file sequential read` Avg(ms) × 1000 |
| `io.multiblock_read_count` | AWR (init.ora) | `db_file_multiblock_read_count` |
| `io.full_scan_block_discount` | **humano** | preservado / default 0.85 |
| `rac_contention.index_contention_in_top_events` | AWR (Top Events) | há `enq: TX - index contention` |
| `rac_contention.gc_buffer_busy_in_top_events` | AWR (Top Events) | há `gc buffer busy` |
| `rac_contention.sequential_index_hotblock_observed` | AWR (Segments by Buffer Busy/Row Lock) | há **índice** em contenção |
| `rac_contention.hot_segments` | AWR (Segments by …) | união das seções; descarta schemas Oracle (SYS, SYSTEM, …) e objetos de dicionário (`*$`) |
| `scoring.*` | **humano** | defaults no create; preservado no update |
| `optimizer.*` | AWR (init.ora) | `optimizer_index_cost_adj` etc. |
| `index_ddl.*` | **humano** | preservado / vazio |

Os limiares (`0.50`, `99`, `50`) ficam em
[`profile_builder.py`](../src/advisor/profile_builder.py) (`CPU_BOUND_THRESHOLD`,
`CACHE_HIT_VERY_HIGH_PCT`, `CACHE_HIT_LIO_PIO_RATIO`). Ajuste lá se quiser mudar
a definição de "CPU-bound" para todos os perfis.

---

## 6. Conferir e usar o perfil

```bash
# o YAML é carregável pelo loader do projeto; rode uma análise apontando p/ ele
python -m advisor.cli \
  --sql examples/query.sql --plan examples/plan.txt \
  --env config/env_profile_proddb.yaml \
  --source fixture --fixture tests.fixtures_rawdb
```

Depois, **revise a mão** os campos humanos:

- `scoring.maint_cost_hot_table` — quão agressivo é punir índice em tabela
  quente (ambiente com muito redo/contenção → mantenha alto);
- `index_ddl.parallel` / `index_ddl.tablespace` — DOP de criação e tablespace de
  destino dos índices recomendados;
- `identity.exadata` — se for Exadata, marque (`--exadata`), pois muda o
  break-even de full scan.

---

## 7. Recalibração 100% manual (sem AWR)

Se você não tem o AWR mas conhece o ambiente, copie um perfil existente e edite
os valores. A seção §5 acima diz o que cada campo significa. O YAML é a fonte;
recalibrar é editar o YAML, **nunca** o código (ver
[CLAUDE.md](../CLAUDE.md) — princípio "o ambiente é configuração").

---

## 8. Limites honestos

- **Parsing de AWR é por palavra-chave** (summary/cabeçalho das tabelas). É
  tolerante a variações, mas uma versão muito diferente pode esconder uma
  seção → o `--diag` aponta o que faltou e você completa a mão.
- **Só HTML.** AWR em texto não é suportado — gere em HTML.
- **Médias por nó (RAC).** A agregação de vários AWRs faz **média** dos números
  de carga (representativo por nó), não soma de cluster. Para totais de cluster,
  use o AWR global (`awrgrpt`).
- **A ferramenta calibra; o DBA aprova.** Sempre revise os campos humanos antes
  de usar o perfil em produção.
