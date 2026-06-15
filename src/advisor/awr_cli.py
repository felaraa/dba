#!/usr/bin/env python3
"""
awr_cli.py — Cria ou atualiza um env_profile a partir de AWR report(s) HTML.

Fluxo:
  AWR(s) HTML --> awr_parser.parse_awr --> [AwrMetrics]
              --> awr_parser.aggregate_metrics --> AwrMetrics
              --> profile_builder.build_profile (+ perfil existente no --update)
              --> profile_builder.emit_yaml --> env_profile_*.yaml comentado

Modos:
  CREATE  (default): gera um perfil novo. Campos humanos (scoring/index_ddl/
          exadata) recebem defaults.
  UPDATE  (--update): lê o YAML em --out, REFRESCA os campos derivados do AWR e
          PRESERVA os campos humanos. (Comentários nunca se perdem: o arquivo é
          re-emitido inteiro pelo template comentado.)

Exemplos:
  # criar um perfil novo a partir de um AWR
  python -m advisor.awr_cli --awr awr_prod.html --out config/env_profile_prod.yaml

  # RAC: agregar um AWR por nó
  python -m advisor.awr_cli --awr awr_inst1.html awr_inst2.html \\
      --name PRODDB --rac-nodes 2 --out config/env_profile_prod.yaml

  # atualizar um perfil existente com um AWR mais recente (preserva scoring)
  python -m advisor.awr_cli --awr awr_novo.html \\
      --out config/env_profile_prod.yaml --update --diag

  # só inspecionar o que o AWR rende, sem gravar
  python -m advisor.awr_cli --awr awr.html --stdout --diag
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from .awr_parser import aggregate_metrics, parse_awr
from .profile_builder import build_profile, emit_yaml


def _read(path: str) -> str:
    # AWR HTML às vezes vem latin-1 / com BOM; toleramos a decodificação
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _load_existing(path: str) -> Optional[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _diag(metrics, profile, out_path, mode):
    e = sys.stderr
    print(f"[awr] modo: {mode}", file=e)
    print(f"[awr] arquivos lidos: {', '.join(metrics.source_files) or '(nenhum)'}", file=e)
    print(f"[awr] CAMPOS ENCONTRADOS ({len(metrics.found)}): "
          f"{', '.join(metrics.found) or '(nenhum)'}", file=e)
    if metrics.missing:
        print(f"[awr] AVISO — NÃO encontrados no AWR ({len(metrics.missing)}): "
              f"{', '.join(metrics.missing)}", file=e)
        print("[awr]   (esses campos ficam com default no CREATE, ou são "
              "preservados do perfil existente no UPDATE)", file=e)
    segs = profile["rac_contention"].get("hot_segments", [])
    print(f"[awr] segmentos quentes capturados: {len(segs)}", file=e)
    for s in segs[:15]:
        print(f"    {s['owner']}.{s['name']} ({s['type']})", file=e)
    if len(segs) > 15:
        print(f"    ... (+{len(segs) - 15})", file=e)
    print(f"[awr] cpu_bound={profile['workload']['cpu_bound']} "
          f"db_cpu%={profile['workload']['db_cpu_pct_of_dbtime']} "
          f"cache_hit_very_high={profile['workload']['cache_hit_very_high']}", file=e)
    print(f"[awr] destino: {out_path or '(stdout)'}", file=e)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Cria/atualiza um env_profile a partir de AWR(s) HTML")
    p.add_argument("--awr", required=True, nargs="+",
                   help="um ou mais AWR reports HTML (RAC: um por nó)")
    p.add_argument("--out", help="caminho do env_profile YAML a gravar/atualizar")
    p.add_argument("--update", action="store_true",
                   help="atualiza o YAML em --out preservando campos humanos "
                        "(scoring, index_ddl, exadata)")
    p.add_argument("--name", help="sobrescreve identity.name (senão usa o DB Name do AWR)")
    p.add_argument("--rac-nodes", type=int, help="sobrescreve identity.rac_nodes")
    p.add_argument("--exadata", dest="exadata", action="store_true", default=None,
                   help="marca identity.exadata=true (AWR não detecta sozinho)")
    p.add_argument("--stdout", action="store_true",
                   help="imprime o YAML em vez de gravar (ou além de --out)")
    p.add_argument("--diag", action="store_true",
                   help="mostra o que foi extraído e o que faltou no AWR")
    args = p.parse_args(argv)

    if not args.out and not args.stdout:
        p.error("informe --out (arquivo de destino) e/ou --stdout")
    if args.update and not args.out:
        p.error("--update requer --out (o YAML a ser atualizado)")

    # 1. parse + agregação
    metrics_list = []
    for path in args.awr:
        if not Path(path).exists():
            print(f"[awr] ERRO: arquivo não encontrado: {path}", file=sys.stderr)
            return 2
        metrics_list.append(parse_awr(_read(path), source_name=Path(path).name))
    metrics = aggregate_metrics(metrics_list)

    # 2. perfil existente (modo update)
    existing = None
    mode = "CREATE"
    if args.update:
        existing = _load_existing(args.out)
        if existing is None:
            print(f"[awr] ERRO: --update mas {args.out} não existe (use CREATE).",
                  file=sys.stderr)
            return 2
        mode = "UPDATE"
    elif args.out and Path(args.out).exists():
        print(f"[awr] AVISO: {args.out} já existe e será SOBRESCRITO "
              f"(use --update para preservar scoring/index_ddl).", file=sys.stderr)

    # 3. montar + emitir
    profile = build_profile(
        metrics, existing=existing, name=args.name,
        rac_nodes=args.rac_nodes, exadata=args.exadata)
    window = (f"{mode.lower()} de {len(metrics.source_files)} AWR(s) em "
              f"{date.today().isoformat()}")
    text = emit_yaml(profile, awr_window_note=window)

    if args.diag:
        _diag(metrics, profile, args.out, mode)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[awr] {mode}: env_profile gravado em {args.out}", file=sys.stderr)
    if args.stdout:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
