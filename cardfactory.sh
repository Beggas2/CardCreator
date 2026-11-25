#!/usr/bin/env sh
# Inicializador para Linux/macOS. No Windows, use cardfactory.cmd.
set -e
cd "$(dirname "$0")"
command -v uv >/dev/null 2>&1 || { echo "Instale o uv: https://docs.astral.sh/uv/"; exit 1; }
[ -f .env ] || cp .env.example .env
exec uv run --project backend cardfactory serve --open "$@"
