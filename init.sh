#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mode="${1:-docs}"
case "$mode" in
  docs|python|dashboard) ;;
  *) echo 'Usage: bash init.sh [docs|python|dashboard]' >&2; exit 2 ;;
esac
python scripts/check_docs.py
git diff --check
case "$mode" in
  python)
    python -m ruff check .
    python -m pytest tests -q
    ;;
  dashboard)
    pnpm --dir dashboard test
    pnpm --dir dashboard build
    ;;
esac
echo "Verification passed for mode: $mode. Apply additional task gates from docs/agent/verification.md."
