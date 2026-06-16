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

Uso típico (produção com banco nomeado):
  python -m advisor.cli \
      --sql query.sql --plan plan.xml \
      --env config/env_profile_rawdb.yaml \
      --source rawdb \
      [--validate]            # opcional: testa com índice invisível

  # credenciais em config/rawdb.yaml  (db.yaml.example como modelo)

Uso de demonstração (sem banco):
  python -m advisor.cli \
      --sql query.sql --plan plan.txt \
      --env config/env_profile_rawdb.yaml \
      --source fixture --fixture tests.fixtures_rawdb
"""
from __future__ import annotations

import argparse
import importlib
import logging
import sys

from .engine import RuleEngine
from .env_profile import load_env_profile
from .metadata_collector import (FixtureMetadataCollector,
                                  OracleMetadataCollector)
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


def build_context(args):
    sql = _read(args.sql)
    plan_text = _read(args.plan)
    env = load_env_profile(args.env)

    query = SqlParser().parse(sql)
    plan = parse_plan(plan_text)

    targets = [(t.owner, t.name) for t in query.tables]
    plan_history = None
    if args.source == "fixture":
        # garante que módulos de fixture do projeto (ex.: tests.fixtures_*) sejam
        # encontrados ao rodar pelo entry point a partir da raiz do projeto
        import os as _os
        if _os.getcwd() not in sys.path:
            sys.path.insert(0, _os.getcwd())
        mod = importlib.import_module(args.fixture)
        metadata = mod.get_metadata()
    else:
        from .db_connection import connect, resolve_db_config
        cfg = resolve_db_config(args.dsn, args.user, args.password, _db_config_path(args))
        conn = connect(cfg)
        hot = set(s["name"] for s in env.raw["rac_contention"].get("hot_segments", []))
        collector = OracleMetadataCollector(conn, hot)
        metadata = collector.collect(targets)

        # histórico de planos do SQL_ID: revela instabilidade de plano (vários
        # plan_hash_value) e alimenta a regra R009. Resiliente: nunca derruba.
        from .plan_history import collect_plan_history
        plan_history = collect_plan_history(conn, plan.sql_id)
        if getattr(args, "diag", False):
            import sys as _sys
            n = plan_history.distinct_count()
            print(f"[coleta] planos distintos para SQL_ID {plan.sql_id}: {n}",
                  file=_sys.stderr)
            for ps in plan_history.plans:
                cur_mark = " <== plano do arquivo" if str(plan.plan_hash) == ps.plan_hash else ""
                el = f"{ps.avg_elapsed_s:.3f}s" if ps.avg_elapsed_s is not None else "?"
                bg = f"{ps.avg_buffer_gets:,.0f}" if ps.avg_buffer_gets is not None else "?"
                print(f"  plan_hash={ps.plan_hash} fontes={','.join(ps.sources)} "
                      f"execs={ps.executions:,.0f} elapsed/exec={el} "
                      f"gets/exec={bg}{cur_mark}", file=_sys.stderr)
        # diagnóstico: o que o coletor enxergou e o que FALTOU coletar
        if getattr(args, "diag", False):
            import sys as _sys
            print("[coleta] tabelas/índices vistos pelo coletor:", file=_sys.stderr)
            for t in metadata.tables:
                idxs = metadata.indexes_of(t.name)
                names = ", ".join(i.index_name for i in idxs) or "(nenhum)"
                print(f"  {t.owner}.{t.name}: num_rows={t.num_rows} part={t.partitioned} "
                      f"stale={t.stale_stats} índices=[{names}]", file=_sys.stderr)
            missing = getattr(collector, "missing", [])
            if missing:
                print("[coleta] AVISO — tabelas da query NÃO coletadas (sem "
                      "metadados; índices podem sair sem LOCAL e regras de índice "
                      "existente não funcionarão para elas):", file=_sys.stderr)
                for o, n in missing:
                    print(f"  {o or '?'}.{n}", file=_sys.stderr)

    from .models import PlanHistory
    if plan_history is None:
        plan_history = PlanHistory(sql_id=plan.sql_id, plans=())
    return RuleContext(query=query, plan=plan, metadata=metadata, env=env,
                       plan_history=plan_history), sql


def main(argv=None):
    p = argparse.ArgumentParser(description="Oracle Index Advisor")
    p.add_argument("--sql", required=True, help="arquivo .sql com a query")
    p.add_argument("--plan", required=True, help="plano (XML SQL Monitor ou texto XPLAN)")
    p.add_argument("--env", required=True, help="perfil de ambiente YAML")
    p.add_argument("--source", default="fixture",
                   help="'fixture' (sem banco) ou nome do banco cujas credenciais "
                        "estão em config/<nome>.yaml (ex.: rawdb, datadb, db)")
    p.add_argument("--fixture", default="tests.fixtures_rawdb",
                   help="módulo Python com get_metadata() (source=fixture)")
    p.add_argument("--dsn"); p.add_argument("--user"); p.add_argument("--password")
    p.add_argument("--db-config", help="caminho do YAML de conexão (default: config/db.yaml)")
    p.add_argument("--allow", nargs="*", help="apenas estas regras (rule_id)")
    p.add_argument("--deny", nargs="*", help="desligar estas regras (rule_id)")
    p.add_argument("--format", choices=["text", "md"], default="text")
    p.add_argument("--validate", action="store_true",
                   help="testar índices com INVISIBLE (requer --source db)")
    p.add_argument("--diag", action="store_true",
                   help="mostra o que o coletor enxergou (índices/stats por tabela)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

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
