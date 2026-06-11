"""
engine.py — O motor de regras.

Responsabilidade ÚNICA: descobrir regras no pacote advisor.rules, executá-las
sobre um RuleContext e devolver as recomendações ranqueadas. O motor não contém
nenhuma lógica de tuning — toda decisão mora nas regras (plugins).

Desacoplamento:
  * Descoberta automática por introspecção do pacote advisor.rules.
  * allowlist/denylist opcionais permitem ligar/desligar regras sem editar código.
  * Regras com erro são isoladas: uma regra que lança exceção não derruba as outras.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Iterable, Optional

from . import rules as rules_pkg
from .rule_base import Rule, RuleContext
from .models import Recommendation

log = logging.getLogger("advisor.engine")


class RuleEngine:
    def __init__(
        self,
        allowlist: Optional[Iterable[str]] = None,
        denylist: Optional[Iterable[str]] = None,
    ) -> None:
        self._allow = set(allowlist) if allowlist else None
        self._deny = set(denylist) if denylist else set()
        self._rules: list[Rule] = []
        self._discover()

    # ---- descoberta de plugins ------------------------------------------
    def _discover(self) -> None:
        """Importa todo módulo em advisor/rules/ e instancia subclasses de Rule."""
        for mod_info in pkgutil.iter_modules(rules_pkg.__path__):
            if mod_info.name.startswith("_"):
                continue
            module = importlib.import_module(f"{rules_pkg.__name__}.{mod_info.name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Rule) and obj is not Rule:
                    rule = obj()
                    if self._is_enabled(rule.rule_id):
                        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)
        log.info("Regras carregadas: %s", [r.rule_id for r in self._rules])

    def _is_enabled(self, rule_id: str) -> bool:
        if rule_id in self._deny:
            return False
        if self._allow is not None:
            return rule_id in self._allow
        return True

    @property
    def loaded_rule_ids(self) -> list[str]:
        return [r.rule_id for r in self._rules]

    # ---- execução --------------------------------------------------------
    def run(self, ctx: RuleContext) -> list[Recommendation]:
        recs: list[Recommendation] = []
        for rule in self._rules:
            try:
                produced = rule.evaluate(ctx) or []
                for r in produced:
                    recs.append(r)
                log.debug("Regra %s produziu %d recomendações", rule.rule_id, len(produced))
            except Exception:  # isolamento: uma regra ruim não quebra o pipeline
                log.exception("Regra %s falhou e foi ignorada", rule.rule_id)
        return self._rank(recs)

    @staticmethod
    def _rank(recs: list[Recommendation]) -> list[Recommendation]:
        # ordena por score líquido (benefício - custo de manutenção), desc
        return sorted(recs, key=lambda r: r.net_score, reverse=True)
