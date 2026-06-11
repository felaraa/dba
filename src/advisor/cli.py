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
  --source db       conecta via python-oracledb (produção)
  --source fixture  usa metadados de um módulo Python (demo/teste)

Uso típico (produção):
  python -m advisor.cli \
      --sql query.sql --plan plan.xml \
      --env config/env_profile_rawdb.yaml \
      --source db --dsn host:1521/svc --user U --password P \
      [--validate]            # opcional: testa com índice invisível

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


def build_context(args):
    sql = _read(args.sql)
    plan_text = _read(args.plan)
    env = load_env_profile(args.env)

    query = SqlParser().parse(sql)
    plan = parse_plan(plan_text)

    targets = [(t.owner, t.name) for t in query.tables]
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
        cfg = resolve_db_config(args.dsn, args.user, args.password, args.db_config)
        conn = connect(cfg)
        hot = set(s["name"] for s in env.raw["rac_contention"].get("hot_segments", []))
        collector = OracleMetadataCollector(conn, hot)
        metadata = collector.collect(targets)
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

    return RuleContext(query=query, plan=plan, metadata=metadata, env=env), sql


def main(argv=None):
    p = argparse.ArgumentParser(description="Oracle Index Advisor")
    p.add_argument("--sql", required=True, help="arquivo .sql com a query")
    p.add_argument("--plan", required=True, help="plano (XML SQL Monitor ou texto XPLAN)")
    p.add_argument("--env", required=True, help="perfil de ambiente YAML")
    p.add_argument("--source", choices=["db", "fixture"], default="fixture")
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
        if args.source != "db":
            print("\n[validação ignorada: requer --source db]", file=sys.stderr)
        else:
            _run_validation(args, ctx, sql, recs)
    return 0


def _run_validation(args, ctx, sql, recs):
    from .db_connection import connect, resolve_db_config
    from .validator import InvisibleIndexValidator
    cfg = resolve_db_config(args.dsn, args.user, args.password, args.db_config)
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
