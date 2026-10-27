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
python3 tests/test_publish_stale.py || fail=1
python3 tests/test_publish_redact.py || fail=1
python3 tests/test_mr_dryrun.py || fail=1
python3 tests/test_fixedin_offline.py || fail=1
python3 tests/test_fixedin_declared_offline.py || fail=1
python3 tests/test_browser_offline.py || fail=1
python3 tests/test_stage_offline.py || fail=1
python3 tests/test_verify_report_offline.py || fail=1
python3 tests/test_jira_fixedin_offline.py || fail=1
python3 tests/test_jira_close_offline.py || fail=1
python3 tests/test_jira_description_offline.py || fail=1
python3 tests/test_jira_standard_offline.py || fail=1
python3 tests/test_jira_labels_offline.py || fail=1
python3 tests/test_brief_yesterday_offline.py || fail=1
python3 tests/test_ticket_refresh_offline.py || fail=1
python3 tests/test_review_lint_offline.py || fail=1
python3 tests/test_review_replay_offline.py || fail=1
python3 tests/test_review_reader_offline.py || fail=1
python3 tests/test_brief_sprint_offline.py || fail=1
python3 tests/test_brief_changes_offline.py || fail=1
python3 tests/test_vault_offline.py || fail=1
python3 tests/test_promote_constraints_offline.py || fail=1
python3 tests/test_promote_pending_offline.py || fail=1
python3 tests/test_release_pins_offline.py || fail=1
python3 tests/test_release_create_offline.py || fail=1
python3 tests/test_publish_pins_offline.py || fail=1
python3 tests/test_publish_head_offline.py || fail=1
python3 tests/test_description_budget.py || fail=1
[ $fail -eq 0 ] && echo "ela: verification passed" || echo "ela: verification FAILED"
exit $fail
