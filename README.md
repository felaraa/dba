# Oracle Query Otimização — Index & Tuning Advisor

Ferramenta de recomendação automatizada de índices e diagnóstico de tuning para
**Oracle 19c RAC**. Recebe **query + plano de execução + cardinalidade** e
devolve recomendações ranqueadas com DDL pronto, score de custo/benefício,
mitigações de RAC e diagnósticos (estatística obsoleta, cartesiano, SQL Profile).
Valida índices opcionalmente com índice `INVISIBLE`, medindo o ganho real.

O motor de regras é **desacoplado**: cada regra é um plugin; adicionar/remover
não afeta o restante. Calibrado com o perfil real do cluster **RAWDB**.

## Início rápido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[db,dev]"      # 'db' = driver Oracle; 'dev' = pytest

# testes (não precisam de banco)
pytest -q

# análise offline com dados de exemplo
python -m advisor.cli \
  --sql examples/query.sql --plan examples/plan.txt \
  --env config/env_profile_rawdb.yaml \
  --source fixture --fixture tests.fixtures_rawdb
```

## Análise com banco real

```bash
# credenciais: CLI > variáveis de ambiente > config/db.yaml > wallet
cp config/db.yaml.example config/db.yaml && chmod 600 config/db.yaml  # edite

python -m advisor.cli \
  --sql minha_query.sql --plan plan.xml \
  --env config/env_profile_rawdb.yaml \
  --source db --diag --format md
```

- `--diag` mostra o que o coletor enxergou e quais tabelas faltaram.
- `--validate` cria o índice como `INVISIBLE`, mede gets antes/depois e remove.

## Perfil do ambiente a partir de um AWR

O `env_profile_*.yaml` (CPU-bound, latência de IO, contenção em RAC, segmentos
quentes) é gerado/atualizado automaticamente de um AWR HTML — você não digita os
números a mão:

```bash
# criar um perfil novo
python -m advisor.awr_cli --awr awr_prod.html --out config/env_profile_prod.yaml --diag

# atualizar com um AWR mais recente (preserva scoring/index_ddl ajustados a mão)
python -m advisor.awr_cli --awr awr_novo.html --out config/env_profile_prod.yaml --update
```

Passo a passo em `docs/GUIA_ENV_PROFILE.md`.

Veja `docs/MANUAL_DE_USO.md` (passo a passo) e `docs/GUIA_DE_COLETA.md`
(como coletar query, plano e cardinalidade).

## Estrutura

```
oracle-query-otim/
├── CLAUDE.md                 contexto do projeto (lido pelo Claude Code)
├── .claude/skills/           Agent Skills do Claude Code
│   └── criar-regra/          skill que padroniza a criação de regras novas
├── pyproject.toml            pacote instalável (src layout) + config pytest
├── README.md
├── config/
│   ├── env_profile_rawdb.yaml   perfil calibrado do ambiente (editável)
│   └── db.yaml.example          modelo de conexão (copie p/ db.yaml)
├── src/advisor/              código-fonte
│   ├── engine.py             motor (descobre/executa regras-plugin)
│   ├── rules/                PLUGINS de regra (R001..R007, R900)
│   ├── sql_parser.py  plan_parser.py  metadata_collector.py
│   ├── db_connection.py  validator.py  reporter.py  cli.py
│   └── models.py  env_profile.py  rule_base.py
├── docs/                     MANUAL_DE_USO, GUIA_DE_COLETA, ARQUITETURA, ...
├── examples/                 queries, planos e relatórios de exemplo
├── sql/                      scripts de apoio (auditoria, coleta no banco)
├── scripts/                  bootstrap e utilitários
└── tests/                    suite (unit + casos reais) e fixtures
```

## Documentação

| Documento | Conteúdo |
|-----------|----------|
| `CLAUDE.md` | Arquitetura, decisões, regras, casos, pendências (para o Claude Code) |
| `docs/MANUAL_DE_USO.md` | Passo a passo de uso, conexão, regras, validação |
| `docs/GUIA_DE_COLETA.md` | Scripts SQL para coletar query/plano/cardinalidade |
| `docs/GUIA_ENV_PROFILE.md` | Criar/atualizar um `env_profile` a partir de um AWR (`advisor-awr`) |
| `docs/ARQUITETURA.md` | Visão técnica dos módulos e do fluxo |
| `docs/CONTRIBUTING.md` | Como criar uma regra nova sem tocar no motor |
| `docs/plano_tuning_rawdb.md` | Plano de tuning de ambiente (parâmetros, INITRANS, memória) |

## Licença / uso interno

Projeto interno de engenharia de banco de dados. Não versionar `config/db.yaml`.
