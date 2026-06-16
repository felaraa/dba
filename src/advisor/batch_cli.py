#!/usr/bin/env python3
"""
batch_cli.py — CLI para o modo batch do Oracle Index Advisor.

Analisa as N queries mais quentes do banco (GV$SQL, última hora,
avg_elapsed > 10 min), extrai SQL + plano, salva em temp/<sql_id>/,
executa o advisor em cada uma e produz um relatório consolidado com
todos os índices a implementar.

Requer --source <banco>; não funciona com fixture.

Uso:
  python -m advisor.batch_cli \\
      --env config/env_profile_rawdb.yaml \\
      --source rawdb \\
      [--limit 10] \\
      [--format text|md] \\
      [--temp-dir temp] \\
      [--diag]

  # credenciais em config/rawdb.yaml  (db.yaml.example como modelo)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .batch import BatchAnalyzer, BatchReport, QueryResult
from .db_connection import connect, resolve_db_config
from .engine import RuleEngine
from .env_profile import load_env_profile
from .models import Severity
from .reporter import to_markdown, to_text


# ---------------------------------------------------------------------------
# Formatação do relatório batch
# ---------------------------------------------------------------------------

_SEV_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


def _sort_key(sql_id_rec):
    _, rec = sql_id_rec
    return (_SEV_ORDER.get(rec.severity, 9), -rec.net_score)


def batch_to_text(report: BatchReport) -> str:
    lines: list[str] = []

    # Cabeçalho
    title = "RELATÓRIO BATCH — TOP QUERIES (Oracle Index Advisor)"
    lines += [
        "=" * len(title),
        title,
        "=" * len(title),
        f"  Queries selecionadas : {report.total_queries}",
        f"  Com recomendações    : {report.total_with_recommendations}",
        f"  Sem plano/SQL text   : {report.total_skipped}",
        f"  Erros de análise     : {report.total_errors}",
        "",
    ]

    # Sumário: todos os índices a criar (de todos os SQL_IDs)
    all_ddls = sorted(report.all_ddls(), key=_sort_key)
    if all_ddls:
        lines += ["ÍNDICES A IMPLEMENTAR (consolidado):", "-" * 40]
        for i, (sql_id, rec) in enumerate(all_ddls, 1):
            sev = rec.severity.value.upper()
            lines += [
                f"",
                f"  [{i}] [{sev}] score={rec.net_score:+.3f}  regra={rec.rule_id}  SQL_ID={sql_id}",
                f"      {rec.title}",
                f"      DDL: {rec.ddl}",
            ]
            for w in rec.warnings:
                lines.append(f"      ⚠ MITIGAÇÃO: {w}")
        lines.append("")
    else:
        lines += ["Nenhum índice recomendado para as queries analisadas.", ""]

    # Detalhe por query
    lines += ["=" * 60, "DETALHE POR SQL_ID", "=" * 60]
    for r in report.results:
        lines += ["", f"── SQL_ID: {r.sql_id}"]
        if r.sql_path:
            lines.append(f"   Arquivos: {r.sql_path.parent}")
        if r.skipped:
            lines.append(f"   IGNORADO: {r.skip_reason}")
            continue
        if r.error:
            lines.append(f"   ERRO: {r.error}")
            continue
        if not r.recommendations:
            lines.append("   Sem recomendações.")
            continue
        # reutiliza o formatter padrão (indentado em bloco)
        detail = to_text(r.recommendations, sql_id=r.sql_id)
        lines.extend("   " + ln for ln in detail.splitlines())

    return "\n".join(lines)


def batch_to_markdown(report: BatchReport) -> str:
    md: list[str] = []

    md += [
        "# Relatório Batch — Top Queries (Oracle Index Advisor)\n",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Queries selecionadas | {report.total_queries} |",
        f"| Com recomendações | {report.total_with_recommendations} |",
        f"| Sem plano/SQL text | {report.total_skipped} |",
        f"| Erros de análise | {report.total_errors} |",
        "",
    ]

    # Sumário de índices
    all_ddls = sorted(report.all_ddls(), key=_sort_key)
    if all_ddls:
        md.append("## Índices a Implementar (Consolidado)\n")
        for i, (sql_id, rec) in enumerate(all_ddls, 1):
            sev = rec.severity.value.upper()
            md += [
                f"### {i}. [{sev}] {rec.title}\n",
                f"- **SQL_ID:** `{sql_id}`",
                f"- **Regra:** `{rec.rule_id}`",
                f"- **Score líquido:** {rec.net_score:+.3f} "
                f"(benefício {rec.estimated_benefit:.2f} / "
                f"manutenção {rec.estimated_maint_cost:.2f})",
                f"- **DDL:**\n  ```sql\n  {rec.ddl}\n  ```",
            ]
            for w in rec.warnings:
                md.append(f"- ⚠ **Mitigação:** {w}")
            md.append("")
    else:
        md.append("_Nenhum índice recomendado para as queries analisadas._\n")

    # Detalhe por query
    md.append("---\n")
    md.append("## Detalhe por SQL_ID\n")
    for r in report.results:
        md.append(f"### SQL_ID `{r.sql_id}`\n")
        if r.sql_path:
            md.append(f"_Arquivos salvos em `{r.sql_path.parent}`_\n")
        if r.skipped:
            md.append(f"_Ignorado: {r.skip_reason}_\n")
            continue
        if r.error:
            md.append(f"_Erro: {r.error}_\n")
            continue
        if not r.recommendations:
            md.append("_Sem recomendações._\n")
            continue
        md.append(to_markdown(r.recommendations, sql_id=r.sql_id))

    return "\n".join(md)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _db_config_path(args) -> str:
    if getattr(args, "db_config", None):
        return args.db_config
    return f"config/{args.source}.yaml"


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Oracle Index Advisor — Modo Batch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python -m advisor.batch_cli \\\n"
            "      --env config/env_profile_rawdb.yaml --source rawdb\n\n"
            "  python -m advisor.batch_cli \\\n"
            "      --env config/env_profile_rawdb.yaml --source rawdb \\\n"
            "      --limit 20 --format md > batch_report.md\n"
        ),
    )
    p.add_argument("--env", required=True, help="perfil de ambiente YAML")
    p.add_argument(
        "--source",
        required=True,
        help="nome do banco (config/<source>.yaml). Não aceita 'fixture'.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=10,
        help="número máximo de queries a analisar (default: 10)",
    )
    p.add_argument(
        "--temp-dir",
        default="temp",
        help="diretório onde SQL/planos são salvos (default: temp)",
    )
    p.add_argument("--dsn", help="DSN Oracle (host:porta/serviço)")
    p.add_argument("--user", help="usuário Oracle")
    p.add_argument("--password", help="senha (prefira ORACLE_PASSWORD no env)")
    p.add_argument("--db-config", help="caminho do YAML de conexão")
    p.add_argument("--allow", nargs="*", metavar="RULE_ID",
                   help="executar apenas estas regras")
    p.add_argument("--deny", nargs="*", metavar="RULE_ID",
                   help="desligar estas regras")
    p.add_argument("--format", choices=["text", "md"], default="text",
                   help="formato de saída (default: text)")
    p.add_argument("--diag", action="store_true",
                   help="diagnóstico de coleta por query (stderr)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="logging DEBUG")
    args = p.parse_args(argv)

    if args.source == "fixture":
        p.error("O modo batch requer --source <banco> (ex.: rawdb). "
                "Fixture não é suportada.")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    env = load_env_profile(args.env)
    cfg = resolve_db_config(args.dsn, args.user, args.password, _db_config_path(args))
    conn = connect(cfg)

    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(exist_ok=True)

    engine = RuleEngine(allowlist=args.allow, denylist=args.deny)
    analyzer = BatchAnalyzer(
        conn=conn,
        env=env,
        temp_dir=temp_dir,
        engine=engine,
        diag=args.diag,
    )

    report = analyzer.analyze(limit=args.limit)

    if args.format == "md":
        print(batch_to_markdown(report))
    else:
        print(batch_to_text(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
