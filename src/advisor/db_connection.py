"""
db_connection.py — Resolução de credenciais e conexão Oracle (python-oracledb).

Resolve a configuração de conexão em ordem de prioridade (a primeira que
estiver completa vence):

  1) Parâmetros explícitos passados ao programa (--dsn/--user/--password)
  2) Variáveis de ambiente   (ORACLE_DSN, ORACLE_USER, ORACLE_PASSWORD, ...)
  3) Arquivo de config YAML  (config/db.yaml, ou caminho em --db-config)
  4) Oracle Wallet / TNS     (apenas --dsn = alias do tnsnames + wallet externo)

A senha NUNCA precisa ir na linha de comando. Prefira variável de ambiente,
arquivo de config com permissão restrita (chmod 600), ou wallet.

Modo thin x thick: por padrão usa thin (não exige Oracle Client). Se precisar
de thick (ex.: recursos que o thin não suporta), defina ORACLE_CLIENT_LIB_DIR
(ou client_lib_dir no YAML) apontando para o Instant Client.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class DbConfig:
    dsn: Optional[str] = None          # "host:porta/serviço" ou alias TNS
    user: Optional[str] = None
    password: Optional[str] = None
    # opcionais
    mode: str = "thin"                 # "thin" | "thick"
    client_lib_dir: Optional[str] = None
    wallet_location: Optional[str] = None
    wallet_password: Optional[str] = None
    config_dir: Optional[str] = None   # diretório do tnsnames.ora/sqlnet.ora

    def is_usable(self) -> bool:
        # com wallet, user/password podem vir do wallet → basta dsn
        if self.dsn and self.wallet_location:
            return True
        return bool(self.dsn and self.user and self.password)


# ---------------------------------------------------------------------------
# Resolução em camadas
# ---------------------------------------------------------------------------
_ENV_MAP = {
    "dsn": "ORACLE_DSN",
    "user": "ORACLE_USER",
    "password": "ORACLE_PASSWORD",
    "mode": "ORACLE_MODE",
    "client_lib_dir": "ORACLE_CLIENT_LIB_DIR",
    "wallet_location": "ORACLE_WALLET_LOCATION",
    "wallet_password": "ORACLE_WALLET_PASSWORD",
    "config_dir": "ORACLE_CONFIG_DIR",
}


def _from_env() -> dict:
    out = {}
    for field, env_name in _ENV_MAP.items():
        val = os.environ.get(env_name)
        if val:
            out[field] = val
    return out


def _from_yaml(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    # aceita seção "database:" ou raiz
    return data.get("database", data)


def resolve_db_config(
    cli_dsn: Optional[str] = None,
    cli_user: Optional[str] = None,
    cli_password: Optional[str] = None,
    config_path: Optional[str] = None,
) -> DbConfig:
    """
    Funde as fontes na ordem de prioridade. Campos do CLI sobrescrevem env,
    que sobrescreve YAML.
    """
    merged: dict = {}

    # 4) YAML (menor prioridade)
    yaml_path = config_path or os.environ.get("ORACLE_DB_CONFIG") or "config/db.yaml"
    merged.update(_from_yaml(yaml_path))

    # 3) variáveis de ambiente
    merged.update(_from_env())

    # 1) parâmetros explícitos (maior prioridade)
    if cli_dsn:
        merged["dsn"] = cli_dsn
    if cli_user:
        merged["user"] = cli_user
    if cli_password:
        merged["password"] = cli_password

    return DbConfig(**{k: v for k, v in merged.items()
                       if k in DbConfig.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------
def connect(cfg: DbConfig):
    """Abre a conexão Oracle conforme o DbConfig resolvido."""
    import oracledb

    if not cfg.is_usable():
        raise ValueError(
            "Configuração de banco incompleta. Forneça dsn+user+password "
            "(via --dsn/--user/--password, variáveis ORACLE_*, ou config/db.yaml), "
            "ou dsn+wallet_location para autenticação por wallet."
        )

    if cfg.mode == "thick":
        # modo thick requer Oracle Client (Instant Client)
        oracledb.init_oracle_client(lib_dir=cfg.client_lib_dir or None)

    connect_kwargs = {"dsn": cfg.dsn}
    if cfg.user:
        connect_kwargs["user"] = cfg.user
    if cfg.password:
        connect_kwargs["password"] = cfg.password
    if cfg.wallet_location:
        connect_kwargs["config_dir"] = cfg.config_dir or cfg.wallet_location
        connect_kwargs["wallet_location"] = cfg.wallet_location
        if cfg.wallet_password:
            connect_kwargs["wallet_password"] = cfg.wallet_password
    elif cfg.config_dir:
        connect_kwargs["config_dir"] = cfg.config_dir

    return oracledb.connect(**connect_kwargs)
