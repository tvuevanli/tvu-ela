---
name: mail
description: Read Evan's Gmail first-hand — search with Gmail query syntax, read one message as text, read a whole thread. The QA test reports (Erin's release/daily reports, Alice's daily reports), the deploy notices and the PM's release approvals are emails; a Jira comment is at most a summary of one. Use for "QA 报告说什么", "邮件里有没有", "Erin 验了没", "who approved the release", or whenever a question of what QA verified needs the full report.
user-invocable: true
---

# /ela:mail — a sense that reads Evan's mailbox, read-only

```bash
MAIL="python3 ${CLAUDE_PLUGIN_ROOT}/skills/mail/mail.py --env-file <env>"
$MAIL search 'from:erinzhang after:2026/08/27 subject:(MediaHub)' --limit 20   # Gmail query syntax, newest first
$MAIL read <message id>            # headers + body as text
$MAIL thread <thread id>           # every message, oldest first
```
Every subcommand takes `--json`. Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
Credentials: the read-only Google token the gdoc capability uses (`GOOGLE_TOKEN_FILE` in the env file); the
token must carry `gmail.readonly`. Nothing here sends, labels or deletes.

## Invariants
- **A report email is evidence; a Jira comment about it is a summary.** When both exist, cite the email.
- **Quote the report's own verdict words** — `PASS`, `FAIL`, `N/A`, `未修复`, `已修复`, `未排期` — with the
  date and the build named in the report; never re-derive a pass rate.
- **N/A is a conclusion.** "QA declared it not applicable" is different from "no QA round"; keep them apart.
- **Search by sender and window, then by subject.** The report subjects vary (`Summary Test Report for
  [Release MediaHub QA-AWS3] …`, `Daily Test Report for TVU MediaHub on aws-cn3-env on …`); the senders
  and the date window are the stable handles.
- Read-only. Nothing in a mailbox is ever copied into the knowledge base; cite the message id.
