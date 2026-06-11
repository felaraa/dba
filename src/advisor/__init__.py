"""advisor — Oracle Index Advisor (motor de regras desacoplado)."""
from .engine import RuleEngine
from .env_profile import load_env_profile, EnvProfile
from .rule_base import Rule, RuleContext

__all__ = ["RuleEngine", "load_env_profile", "EnvProfile", "Rule", "RuleContext"]
