# The Slack body's layout

Part of ela's promote skill (`SKILL.md` beside this file), read before the Slack body is written (§2, output 2).

The rules of the post (a dry run and `--preview` before any send, two sends and two confirms, no verdict and no decision
of the owner's) are in `SKILL.md`. The layout, at most about forty lines:

- *Versions* — one ``` block, a padded column per lane and per candidate build, a row per service.
- *<candidate build> — QA results* — one line per ticket: marker · key link · a few words · QA's verdict and date.
  *New bugs from that round* under it, one line each, with severity.
- *Carried along from <earlier builds>* — what the target lane also gains: the unverified tickets one per line,
  the verified ones as a single ✅ line of keys, ticketless commits as one counted line.
- *<next build> — not yet tested* — one line of keys, when a newer build is on the from-lane.
- *Open points* — numbered questions, one line each.
