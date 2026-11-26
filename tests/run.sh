#!/usr/bin/env bash
# ela verification: every script compiles, every capability answers --help, the guard's cases pass.
set -u
export ELA_TEST=1   # a live verb refuses unless the tool it would reach is a stub under the temp directory
export ELA_PUBLISH_MIRROR=""   # no test refreshes the owner's read-only mirror; the mirror test names its own tmp target
export ELA_FACTS_CALLS=0   # a test's stubbed call is not a live call: the day's calls log stays the machine's
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"; fail=0
# Tripwire: nothing a test starts reaches a live system. The tools that would leave the machine or start a session
# are stubs first on PATH, and every Python refuses a non-loopback connect (tests/tripwire/sitecustomize.py); each
# hit is logged with the test that made it, and any hit fails the run.
export ELA_TRIPWIRE="$(mktemp -d)"; trap 'rm -rf "$ELA_TRIPWIRE"' EXIT
mkdir "$ELA_TRIPWIRE/bin"
for t in claude zellij ssh scp curl wget; do
  printf '#!/bin/sh\necho "${ELA_TEST_NAME:-?}: %s $*" >> "%s/hits"\necho "tripwire: %s is a stub under tests/run.sh" >&2\nexit 97\n' \
    "$t" "$ELA_TRIPWIRE" "$t" > "$ELA_TRIPWIRE/bin/$t"
  chmod +x "$ELA_TRIPWIRE/bin/$t"
done
# A credential in the caller's environment outranks every env file a test writes ($SLACK_BOT_TOKEN before --env-file):
# none is inherited.
for v in $(env | sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | grep -E '(_TOKEN|_KEY|_SECRET|_PASSWORD|_PASS|_ENV_FILE)$'); do
  unset "$v"
done
export PATH="$ELA_TRIPWIRE/bin:$PATH" PYTHONPATH="$ROOT/tests/tripwire${PYTHONPATH:+:$PYTHONPATH}"
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
python3 tests/test_publish_mirror_offline.py >/dev/null 2>&1 || { echo "publish mirror offline failed"; fail=1; }
python3 tests/test_configserver_redact_offline.py || fail=1
python3 tests/test_apifox_public_offline.py >/dev/null 2>&1 || { echo "apifox public offline failed"; fail=1; }
python3 tests/test_redact_push_offline.py || fail=1
python3 tests/test_tiers_offline.py || fail=1
python3 tests/test_team_find_offline.py >/dev/null 2>&1 || { echo "team find offline failed"; fail=1; }
python3 tests/test_setup_secret_offline.py || fail=1
python3 tests/test_mr_dryrun.py || fail=1
python3 tests/test_fixedin_offline.py || fail=1
python3 tests/test_fixedin_declared_offline.py || fail=1
python3 tests/test_browser_offline.py || fail=1
python3 tests/test_stream_audio_offline.py || fail=1
python3 tests/test_stage_offline.py || fail=1
python3 tests/test_testlist_offline.py || fail=1
python3 tests/test_report_verdicts_offline.py >/dev/null 2>&1 || { echo "report verdicts offline failed"; fail=1; }
python3 tests/test_testlist_slack_offline.py || fail=1
python3 tests/test_slack_mrkdwn_offline.py || fail=1
python3 tests/test_slack_table_offline.py || fail=1
python3 tests/test_slack_mentions_offline.py || fail=1
python3 tests/test_lists_sheet_offline.py || fail=1
python3 tests/test_verify_report_offline.py || fail=1
python3 tests/test_jira_fixedin_offline.py || fail=1
python3 tests/test_jira_close_offline.py || fail=1
python3 tests/test_jira_description_offline.py || fail=1
python3 tests/test_jira_standard_offline.py || fail=1
python3 tests/test_jira_labels_offline.py || fail=1
python3 tests/test_jira_link_offline.py || fail=1
python3 tests/test_jira_signed_offline.py || fail=1
python3 tests/test_cited_sections.py || fail=1
python3 tests/test_brief_yesterday_offline.py || fail=1
python3 tests/test_ticket_refresh_offline.py || fail=1
python3 tests/test_review_lint_offline.py || fail=1
python3 tests/test_review_replay_offline.py || fail=1
python3 tests/test_review_reader_offline.py || fail=1
python3 tests/test_brief_day_offline.py || fail=1
python3 tests/test_meeting_offline.py || fail=1
python3 tests/test_questions_offline.py || fail=1
python3 tests/test_vault_rename_offline.py || fail=1
python3 tests/test_vault_tidy_offline.py || fail=1
python3 tests/test_vault_links_offline.py || fail=1
python3 tests/test_vault_stem_offline.py || fail=1
python3 tests/test_vault_front_closed_offline.py || fail=1
python3 tests/test_brief_sprint_offline.py || fail=1
python3 tests/test_brief_changes_offline.py || fail=1
python3 tests/test_brief_china_offline.py || fail=1
python3 tests/test_vault_offline.py || fail=1
python3 tests/test_vault_line_folder_offline.py || fail=1
python3 tests/test_vault_watch_offline.py || fail=1
python3 tests/test_vault_manual_offline.py || fail=1
python3 tests/test_vault_migrate_offline.py || fail=1
python3 tests/test_today_offline.py || fail=1
python3 tests/test_today_head_offline.py || fail=1
python3 tests/test_dry_offline.py || fail=1
python3 tests/test_logs_window_offline.py >/dev/null || { echo "logs window offline failed"; fail=1; }
python3 tests/test_logs_observer_offline.py >/dev/null || { echo "logs observer offline failed"; fail=1; }
python3 tests/test_dry_corpus_offline.py || fail=1
python3 tests/test_focus_offline.py || fail=1
python3 tests/test_watch_offline.py || fail=1
python3 tests/test_watch_disputes_offline.py || fail=1
python3 tests/test_dry_undo_offline.py || fail=1
python3 tests/test_mention_offline.py || fail=1
python3 tests/test_mention_post_offline.py || fail=1
python3 tests/test_improve_offline.py || fail=1
python3 tests/test_review_loop_offline.py || fail=1
python3 tests/test_release_changes_offline.py || fail=1
python3 tests/test_line_page_offline.py || fail=1
python3 tests/test_release_reconcile_offline.py || fail=1
python3 tests/test_release_cn_offline.py || fail=1
python3 tests/test_page_fold_offline.py || fail=1
python3 tests/test_recent_offline.py || fail=1
python3 tests/test_teamreport_offline.py >/dev/null 2>&1 || { echo "teamreport offline failed"; fail=1; }
python3 tests/test_train_offline.py || fail=1
python3 tests/test_onething_offline.py || fail=1
python3 tests/test_promote_constraints_offline.py || fail=1
python3 tests/test_promote_pending_offline.py || fail=1
python3 tests/test_brief_pending_offline.py || fail=1
python3 tests/test_brief_lanes_offline.py || fail=1
python3 tests/test_brief_release_due_offline.py || fail=1
python3 tests/test_release_pins_offline.py || fail=1
python3 tests/test_release_next_offline.py >/dev/null || { echo "release next offline failed"; fail=1; }
python3 tests/test_release_next_facts_offline.py >/dev/null 2>&1 || { echo "release next facts-only offline failed"; fail=1; }
python3 tests/test_release_must_clear_offline.py >/dev/null 2>&1 || { echo "release must clear offline failed"; fail=1; }
python3 tests/test_release_train_alias_offline.py || fail=1
python3 tests/test_release_gateway_offline.py || fail=1
python3 tests/test_release_create_offline.py || fail=1
python3 tests/test_publish_pins_offline.py || fail=1
python3 tests/test_publish_head_offline.py || fail=1
python3 tests/test_publish_release_guard_offline.py || fail=1
python3 tests/test_publish_versions_offline.py >/dev/null || { echo "publish versions offline failed"; fail=1; }
python3 tests/test_publish_lane_labels_offline.py >/dev/null || { echo "publish lane labels offline failed"; fail=1; }
python3 tests/test_tiers_offline.py || fail=1
python3 tests/test_sessions_offline.py || fail=1
python3 tests/test_sessions_reap_offline.py || fail=1
python3 tests/test_sessions_mark_offline.py || fail=1
python3 tests/test_description_budget.py || fail=1
python3 tests/test_graph_envs_offline.py || fail=1
python3 tests/test_graph_usage_offline.py || fail=1
python3 tests/test_graph_candidates_offline.py || fail=1
python3 tests/test_brief_qa_lanes_offline.py || fail=1
python3 tests/test_promote_mail_lanes_offline.py || fail=1
python3 tests/test_facts_offline.py || fail=1
python3 tests/test_proposals_offline.py || fail=1
python3 tests/test_tvukb_offline.py || fail=1
python3 tests/test_links_offline.py || fail=1
python3 tests/test_runtime_chain_offline.py || fail=1
python3 tests/test_promote_envproof_offline.py || fail=1
python3 tests/test_promote_qajira_offline.py || fail=1
python3 tests/test_promote_placement_offline.py || fail=1
python3 tests/test_promote_prereqs_offline.py || fail=1
python3 tests/test_doctor_offline.py || fail=1
python3 tests/test_promote_plan_offline.py || fail=1
python3 tests/test_promote_livedeps_offline.py || fail=1
python3 tests/test_promote_ship_offline.py || fail=1
python3 tests/test_promote_note_offline.py || fail=1
python3 tests/test_project_offline.py || fail=1
python3 tests/test_project_jira_offline.py || fail=1
python3 tests/test_docker_offline.py || fail=1
python3 tests/test_j2n_offline.py || fail=1
python3 tests/test_pick_offline.py || fail=1
python3 tests/test_siteguard_offline.py || fail=1
python3 tests/test_env_fallback_offline.py || fail=1
python3 tests/test_lang_tag_offline.py || fail=1
python3 tests/test_vault_name_offline.py || fail=1
python3 tests/test_session_start_offline.py || fail=1
if [ -s "$ELA_TRIPWIRE/hits" ]; then
  echo "tripwire: a test reached for a live system:"; sort -u "$ELA_TRIPWIRE/hits" | sed 's/^/  /'; fail=1
fi
[ $fail -eq 0 ] && echo "ela: verification passed" || echo "ela: verification FAILED"
exit $fail
