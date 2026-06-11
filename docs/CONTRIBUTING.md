# Como contribuir / evoluir

## Regra de ouro

Toda nova capacidade de tuning é uma **regra-plugin** em `src/advisor/rules/`,
nunca código dentro de `engine.py`. O motor permanece genérico.

## Criar uma regra nova

1. Crie `src/advisor/rules/rule_minha_coisa.py`:

```python
from ..models import Recommendation, Severity
from ..rule_base import Rule, RuleContext
from . import build_index_name, build_index_ddl, existing_index_covering

class MinhaCoisaRule(Rule):
    rule_id = "R0XX_minha_coisa"
    description = "o que detecta, em uma linha"
    priority = 50          # menor roda primeiro

    def evaluate(self, ctx: RuleContext) -> list[Recommendation]:
        recs = []
        # ler ctx.query, ctx.plan, ctx.metadata, ctx.env
        # ... lógica determinística ...
        return recs
```

2. Se gerar índice, **respeite as 5 convenções** (ver CLAUDE.md):
   nome com owner, `LOCAL` em tabela particionada (use `ctx.is_partitioned`),
   `build_index_ddl` (inclui GATHER_INDEX_STATS), checar índice existente
   (`existing_index_covering`), deixar a consolidação ao reporter.

3. O motor descobre a regra automaticamente. Para ligar/desligar em runtime:
   `--allow R0XX_minha_coisa` ou `--deny R0XX_minha_coisa`.

## Adicionar um caso de teste (obrigatório)

Todo caso real novo vira regressão. Em `tests/`:
- Salve a query em `examples/` e o plano (XML/texto) em `examples/`.
- Crie um `fixtures_xxx.py` com `get_metadata()` (cardinalidade real coletada).
- Adicione asserts em um `test_*.py` validando o que a regra deve produzir.

```bash
pytest -q                 # tudo deve passar antes de commitar
```

## Testes de integração (com banco real)

Marque com `@pytest.mark.integration` e proteja por variável de ambiente:

```python
import os, pytest
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ORACLE_DSN"),
                    reason="requer banco (ORACLE_DSN)")
def test_coletor_real():
    ...
```

Rodar só os unitários: `pytest -q -m "not integration"`.
Rodar integração: `ORACLE_DSN=... ORACLE_USER=... ORACLE_PASSWORD=... pytest -m integration`.

## Estilo

- Regras determinísticas e auditáveis; IA (se algum dia) só explica, não decide.
- Preferir prosa clara no `rationale` — o relatório é lido por DBAs e diretores.
- Não quebrar contratos de `models.py` sem atualizar todos os consumidores.
