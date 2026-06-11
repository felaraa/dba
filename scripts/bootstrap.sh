#!/usr/bin/env bash
# Setup do ambiente de desenvolvimento.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[db,dev]"

echo
echo "Ambiente pronto. Ative com: source .venv/bin/activate"
echo "Rode os testes com:        pytest -q"
echo "Para conexão real, copie:  cp config/db.yaml.example config/db.yaml  (e edite)"
