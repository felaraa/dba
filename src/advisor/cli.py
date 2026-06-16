#!/usr/bin/env python3
"""
cli.py — Orquestrador do Oracle Index Advisor.

Liga todas as camadas:
  SQL  -> sql_parser     -> ParsedQuery
  Plano-> plan_parser    -> ParsedPlan
  DB   -> metadata_collector -> SchemaMetadata
  YAML -> env_profile    -> EnvProfile
  -> RuleContext -> RuleEngine -> [Recommendation] -> reporter

Fontes de metadados:
  --source fixture   usa metadados de um módulo Python (demo/teste)
  --source <nome>    conecta ao banco cujas credenciais estão em
                     config/<nome>.yaml  (ex.: rawdb → config/rawdb.yaml,
                     datadb → config/datadb.yaml, db → config/db.yaml)

Modos de entrada (mutuamente exclusivos):
  1) Arquivos explícitos:  --sql query.sql --plan plan.xml
  2) SQL_ID direto do banco: --sql-id <sql_id> --source <banco>
     Busca o SQL full text em GV$SQLTEXT e o plano via SQL Monitor / DBMS_XPLAN.
     Use --save-temp para gravar os artefatos em temp/<sql_id>/ para inspeção.

Uso típico (produção com banco nomeado):
  python -m advisor.cli \\
      --sql query.sql --plan plan.xml \\
      --env config/env_profile_rawdb.yaml \\
      --source rawdb \\
      [--validate]

  # por SQL_ID (busca SQL + plano direto do banco):
  python -m advisor.cli \\
      --sql-id bz8c7u3h7cv5m \\
      --env config/env_profile_rawdb.yaml \\
      --source rawdb \\
      [--save-temp]

  # credenciais em config/rawdb.yaml  (db.yaml.example como modelo)

Uso de demonstração (sem banco):
  python -m advisor.cli \\
      --sql query.sql --plan plan.txt \\
      --env config/env_profile_rawdb.yaml \\
      --source fixture --fixture tests.fixtures_rawdb
"""
from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path

from .engine import RuleEngine
from .env_profile import load_env_profile
from .metadata_collector import OracleMetadataCollector
from .plan_parser import parse_plan
from .reporter import merge_mitigation_warnings, to_markdown, to_text
from .rule_base import RuleContext
from .sql_parser import SqlParser


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _db_config_path(args) -> str:
    """Resolve o caminho do YAML de conexão: explícito ou config/<source>.yaml."""
    if args.db_config:
        return args.db_config
    return f"config/{args.source}.yaml"


def _print_diag_plan_history(plan, plan_history):
    n = plan_history.distinct_count()
    print(f"[coleta] planos distintos para SQL_ID {plan.sql_id}: {n}",
          file=sys.stderr)
    for ps in plan_history.plans:
        cur_mark = " <== plano atual" if str(plan.plan_hash) == ps.plan_hash else ""
        el = f"{ps.avg_elapsed_s:.3f}s" if ps.avg_elapsed_s is not None else "?"
        bg = f"{ps.avg_buffer_gets:,.0f}" if ps.avg_buffer_gets is not None else "?"
        print(f"  plan_hash={ps.plan_hash} fontes={','.join(ps.sources)} "
              f"execs={ps.executions:,.0f} elapsed/exec={el} "
              f"gets/exec={bg}{cur_mark}", file=sys.stderr)


def _print_diag_metadata(metadata, collector):
    print("[coleta] tabelas/índices vistos pelo coletor:", file=sys.stderr)
    for t in metadata.tables:
        idxs = metadata.indexes_of(t.name)
        names = ", ".join(i.index_name for i in idxs) or "(nenhum)"
        print(f"  {t.owner}.{t.name}: num_rows={t.num_rows} part={t.partitioned} "
              f"stale={t.stale_stats} índices=[{names}]", file=sys.stderr)
    missing = getattr(collector, "missing", [])
    if missing:
        print("[coleta] AVISO — tabelas da query NÃO coletadas (sem "
              "metadados; índices podem sair sem LOCAL e regras de índice "
              "existente não funcionarão para elas):", file=sys.stderr)
        for o, n in missing:
            print(f"  {o or '?'}.{n}", file=sys.stderr)


def build_context(args):
    env = load_env_profile(args.env)
    sql_id_arg = getattr(args, "sql_id", None)

    # ------------------------------------------------------------------
    # Modo fixture (sem banco)
    # ------------------------------------------------------------------
    if args.source == "fixture":
        sql = _read(args.sql)
        plan_text = _read(args.plan)
        query = SqlParser().parse(sql)
        plan = parse_plan(plan_text)
        import os as _os
        if _os.getcwd() not in sys.path:
            sys.path.insert(0, _os.getcwd())
        mod = importlib.import_module(args.fixture)
        metadata = mod.get_metadata()
        from .models import PlanHistory
        plan_history = PlanHistory(sql_id=plan.sql_id, plans=())
        return RuleContext(query=query, plan=plan, metadata=metadata, env=env,
                           plan_history=plan_history), sql

    # ------------------------------------------------------------------
    # Modo DB (rawdb, datadb, etc.) — abre conexão uma única vez
    # ------------------------------------------------------------------
    from .db_connection import connect, resolve_db_config
    cfg = resolve_db_config(args.dsn, args.user, args.password, _db_config_path(args))
    conn = connect(cfg)

    if sql_id_arg:
        # Busca SQL text + plano direto do banco via GV$SQLTEXT / SQL Monitor
        from .batch import _fetch_sql_text, _fetch_plan as _fetch_db_plan, _save_to_temp
        sql = _fetch_sql_text(conn, sql_id_arg)
        if not sql:
            raise SystemExit(
                f"[erro] SQL_ID {sql_id_arg!r}: texto não encontrado em GV$SQLTEXT"
            )
        plan_text, plan_fmt = _fetch_db_plan(conn, sql_id_arg)
        if not plan_text:
            raise SystemExit(
                f"[erro] SQL_ID {sql_id_arg!r}: plano não disponível "
                f"(SQL fora do cursor pool / sem SQL Monitor)"
            )
        if getattr(args, "save_temp", False):
            temp_dir = Path(getattr(args, "temp_dir", "temp"))
            temp_dir.mkdir(exist_ok=True)
            sql_path, _ = _save_to_temp(
                temp_dir, sql_id_arg, sql, plan_text, plan_fmt or "text"
            )
            print(f"[sql-id] Arquivos salvos em {sql_path.parent}", file=sys.stderr)
    else:
        sql = _read(args.sql)
        plan_text = _read(args.plan)

    query = SqlParser().parse(sql)
    plan = parse_plan(plan_text)
    targets = [(t.owner, t.name) for t in query.tables]

    hot = set(s["name"] for s in env.raw["rac_contention"].get("hot_segments", []))
    collector = OracleMetadataCollector(conn, hot)
    metadata = collector.collect(targets)

    from .plan_history import collect_plan_history
    plan_history = collect_plan_history(conn, plan.sql_id or sql_id_arg)

    if getattr(args, "diag", False):
        _print_diag_plan_history(plan, plan_history)
        _print_diag_metadata(metadata, collector)

    from .models import PlanHistory
    if plan_history is None:
        plan_history = PlanHistory(sql_id=plan.sql_id or sql_id_arg, plans=())
    return RuleContext(query=query, plan=plan, metadata=metadata, env=env,
                       plan_history=plan_history), sql


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Oracle Index Advisor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  # arquivos locais (modo clássico)\n"
            "  advisor --sql q.sql --plan p.xml --env env.yaml --source rawdb\n\n"
            "  # SQL_ID direto do banco (busca SQL + plano automaticamente)\n"
            "  advisor --sql-id bz8c7u3h7cv5m --env env.yaml --source rawdb --save-temp\n\n"
            "  # sem banco (fixture)\n"
            "  advisor --sql q.sql --plan p.txt --env env.yaml --source fixture\n"
        ),
    )
    # entrada: arquivos OU sql-id (validação manual abaixo)
    p.add_argument("--sql", help="arquivo .sql com a query")
    p.add_argument("--plan", help="plano (XML SQL Monitor ou texto XPLAN)")
    p.add_argument("--sql-id",
                   help="busca SQL text + plano direto do banco pelo SQL_ID "
                        "(requer --source <banco>; alternativa a --sql/--plan)")
    p.add_argument("--save-temp", action="store_true",
                   help="salva o SQL e o plano buscados em temp/<sql_id>/ (com --sql-id)")
    p.add_argument("--temp-dir", default="temp",
                   help="diretório base para --save-temp (default: temp)")
    p.add_argument("--env", required=True, help="perfil de ambiente YAML")
    p.add_argument("--source", default="fixture",
                   help="'fixture' (sem banco) ou nome do banco cujas credenciais "
                        "estão em config/<nome>.yaml (ex.: rawdb, datadb, db)")
    p.add_argument("--fixture", default="tests.fixtures_rawdb",
                   help="módulo Python com get_metadata() (source=fixture)")
    p.add_argument("--dsn"); p.add_argument("--user"); p.add_argument("--password")
    p.add_argument("--db-config", help="caminho do YAML de conexão (default: config/<source>.yaml)")
    p.add_argument("--allow", nargs="*", help="apenas estas regras (rule_id)")
    p.add_argument("--deny", nargs="*", help="desligar estas regras (rule_id)")
    p.add_argument("--format", choices=["text", "md"], default="text")
    p.add_argument("--validate", action="store_true",
                   help="testar índices com INVISIBLE (requer --source db)")
    p.add_argument("--diag", action="store_true",
                   help="mostra o que o coletor enxergou (índices/stats por tabela)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    # Validação de argumentos de entrada
    if args.sql_id:
        if args.source == "fixture":
            p.error("--sql-id requer --source <banco> (ex.: rawdb). "
                    "Fixture não tem acesso ao GV$SQLTEXT.")
        if args.sql or args.plan:
            p.error("--sql-id é mutuamente exclusivo com --sql/--plan.")
    else:
        if not args.sql or not args.plan:
            p.error("Forneça --sql e --plan, ou use --sql-id <sql_id> com --source <banco>.")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    ctx, sql = build_context(args)
    engine = RuleEngine(allowlist=args.allow, denylist=args.deny)
    from .reporter import consolidate_indexes
    recs = engine.run(ctx)
    recs = consolidate_indexes(recs)
    recs = merge_mitigation_warnings(recs)

    out = (to_markdown if args.format == "md" else to_text)(
        recs, ctx.plan.sql_id, ctx.plan.notes)
    print(out)

    if args.validate:
        if args.source == "fixture":
            print("\n[validação ignorada: requer --source <banco> (ex.: rawdb)]",
                  file=sys.stderr)
        else:
            _run_validation(args, ctx, sql, recs)
    return 0


def _run_validation(args, ctx, sql, recs):
    from .db_connection import connect, resolve_db_config
    from .validator import InvisibleIndexValidator
    cfg = resolve_db_config(args.dsn, args.user, args.password, _db_config_path(args))
    conn = connect(cfg)
    validator = InvisibleIndexValidator(conn)
    print("\n\nVALIDAÇÃO COM ÍNDICE INVISÍVEL")
    print("=" * 40)
    for r in [x for x in recs if x.ddl]:
        res = validator.validate(r, sql, binds={})
        if not res:
            continue
        print(f"\n{r.rule_id}: {res.note}")
        if res.gets_reduction_pct is not None:
            print(f"  Buffer gets: {res.baseline_buffer_gets:,.0f} -> "
                  f"{res.candidate_buffer_gets:,.0f} "
                  f"({res.gets_reduction_pct:+.1f}%)")


if __name__ == "__main__":
    raise SystemExit(main())
