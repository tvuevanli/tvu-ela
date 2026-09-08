#!/usr/bin/env bash
# ela verification: every script compiles, every capability answers --help, the guard's cases pass.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"; fail=0
python3 -m py_compile bin/ela $(find skills -name '*.py') || fail=1
for s in skills/*/*.py; do
  case "$s" in */deps.py) continue;; esac
  python3 "$s" --help >/dev/null 2>&1 || { echo "help failed: $s"; fail=1; }
done
for h in hooks/*.sh; do bash -n "$h" || fail=1; done
tests/test_content_guard.sh || fail=1
python3 tests/test_manual_coverage.py || fail=1
[ $fail -eq 0 ] && echo "ela: verification passed" || echo "ela: verification FAILED"
exit $fail
