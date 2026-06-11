"""
env_profile.py — Carrega o perfil do ambiente de um YAML e o expõe como objeto.

O perfil é DADO, não código: editar config/env_profile_*.yaml recalibra a engine
sem alterar nenhum módulo. Isto isola "como é o cluster" de "como decidimos".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class EnvProfile:
    raw: dict[str, Any]

    # ---- atalhos de leitura usados pelas regras --------------------------
    @property
    def name(self) -> str:
        return self.raw["identity"]["name"]

    @property
    def is_exadata(self) -> bool:
        return bool(self.raw["identity"].get("exadata", False))

    @property
    def is_cpu_bound(self) -> bool:
        return bool(self.raw["workload"].get("cpu_bound", False))

    @property
    def benefit_metric(self) -> str:
        return self.raw["workload"].get("benefit_metric", "buffer_gets_and_rows")

    @property
    def index_contention_present(self) -> bool:
        return bool(self.raw["rac_contention"].get("index_contention_in_top_events", False))

    @property
    def sequential_hotblock_observed(self) -> bool:
        return bool(self.raw["rac_contention"].get("sequential_index_hotblock_observed", False))

    def is_hot_segment(self, owner: str | None, name: str) -> bool:
        for seg in self.raw["rac_contention"].get("hot_segments", []):
            if seg["name"] == name and (owner is None or seg["owner"] == owner):
                return True
        return False

    def score(self, key: str, default: float = 0.0) -> float:
        return float(self.raw.get("scoring", {}).get(key, default))

    @property
    def wide_column_bytes(self) -> float:
        return self.score("wide_column_bytes", 30)

    @property
    def nl_explosion_factor(self) -> float:
        return self.score("nl_explosion_factor", 100)


def load_env_profile(path: str | Path) -> EnvProfile:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return EnvProfile(raw=data)
