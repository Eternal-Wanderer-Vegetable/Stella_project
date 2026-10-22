#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
elif command -v python >/dev/null 2>&1; then
  python_bin="python"
else
  printf '%s\n' 'Python 3 is required to sync this test checkout.' >&2
  exit 127
fi

exec "$python_bin" "$script_dir/sync_test_repo.py"
