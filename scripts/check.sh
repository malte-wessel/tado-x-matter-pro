#!/bin/sh
# Everything CI's python job runs: lint, format check, type check, tests.
#   scripts/check.sh            the whole suite
#   scripts/check.sh --fix      format and autofix first, then check
set -e
cd "$(dirname "$0")/.."
if [ "$1" = "--fix" ]; then
  uv run ruff format .
  uv run ruff check --fix .
fi
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components tests/python
uv run pytest
