#!/usr/bin/env python3
"""A build reconciled against Jira, offline: builds 90 and 91 to QA-AWS3 as recorded, their tickets as Jira held them on
2026-11-12 and the two release threads. Every miss the record of those threads names is found and nothing for the
tickets in order (bare Fixed In included); a revert folded into another ticket is an open question, never in the batch;
the release note carries the gaps table; the batch appends and never rewrites; three builds of one agent's miss raise
one question with a drafted message. Nothing here reads or writes Jira or Slack."""
import copy, datetime, json, os, re, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import release as R  # noqa: E402
import reconcile as RC  # noqa: E402
import questions as Q  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

FIX = os.path.join(ROOT, "tests", "fixtures")
ISSUES = json.load(open(os.path.join(FIX, "reconcile", "issues.json"), encoding="utf-8"))


def thread(build):
    """The fixture thread as slack read --json gives it: [{user, ts, text}]."""
    msgs = []
    for line in open(os.path.join(FIX, "reconcile", f"thread-build-{build}.txt"), encoding="utf-8").read().split("\n"):
        m = re.match(r"^--- (.+?)  ts=(\S+)$", line)
        if m:
            msgs.append({"user": m.group(1), "ts": m.group(2), "text": ""})
        elif msgs:
            msgs[-1]["text"] += (("\n" if msgs[-1]["text"] else "") + line)
    return msgs


def record(build):
    name = {"90": "2026-11-10-build-90-to-qa-aws3", "91": "2026-11-11-build-91-to-qa-aws3"}[build]
    where = os.path.join(FIX, "releases", "2.1") if build == "90" else os.path.join(FIX, "reconcile")   # build 90 is release changes' too
    rec = json.load(open(os.path.join(where, name + ".json"), encoding="utf-8"))
    return dict(rec, name=name)


def misses(res):
    return {(r["key"], m["kind"], m.get("entry")) for r in res["rows"] for m in r["misses"]}


# ── the thread ────────────────────────────────────────────────────────────────────────────────────────
t91 = RC.thread_reading(thread("91"), RC.record_keys(record("91")))
check("build 91's thread: the Jenkins numbers per job and version",
      t91["builds"]["ur-caller"] == {"2.1.91": 382} and t91["builds"]["mx-service-front-docker"] == {"3.0.44": 201})
check("the fold: MH-3927 reverted into MH-3926, and it is not announced for Review",
      [(f["key"], f["into"]) for f in t91["folds"]] == [("MH-3927", "MH-3926")] and "MH-3927" not in t91["announced"])
check("the assignee lists: Alice for MH-3992, Erin for the rest, asked of Summer's agent",
      t91["announced"]["MH-3992"]["assignee"] == "Alice" and t91["announced"]["MH-4001"]["assignee"] == "Erin"
      and t91["announced"]["MH-3926"]["agent"] == "Summer Slack Bot")
check("MH-3998 handled by andyBot itself: Review, held by Erin",
      t91["announced"]["MH-3998"] == dict(t91["announced"]["MH-3998"], status="Review", assignee="Erin", agent="andyBot"))
t90 = RC.thread_reading(thread("90"), RC.record_keys(record("90")))
check("build 90: two builds of one job keep their own numbers",
      t90["builds"]["mx-service-front-docker"] == {"3.0.42": 199, "3.0.43": 200})
check("build 90: andyBot moved the backend six itself, to Erin; the frontend seven were asked of Summer's agent",
      t90["announced"]["MH-3795"]["agent"] == "andyBot" and t90["announced"]["MH-3795"]["assignee"] == "Erin"
      and t90["announced"]["MH-1860"]["agent"] == "Summer Slack Bot" and t90["announced"]["MH-1860"]["assignee"] is None)
check("an agent's owner is the person whose name it starts with",
      RC.agent_owner("Summer Slack Bot", ["Sunny Yin", "Summer Chen", "andyzhao"]) == "Summer Chen"
      and RC.agent_owner("andyBot", ["Summer Chen", "andyzhao"]) == "andyzhao")

# ── the two builds ────────────────────────────────────────────────────────────────────────────────────
r90 = RC.reconcile(record("90"), ISSUES, t90)
r91 = RC.reconcile(record("91"), ISSUES, t91)
want91 = {("MH-3998", "fixed-in", "unified-streaming@2.1.91+382"), ("MH-3998", "fixed-in", "unified-media-frontend@3.0.44+201"),
          ("MH-3998", "label", None), ("MH-3987", "fixed-in", "unified-streaming@2.1.91+382"), ("MH-3987", "label", None),
          ("MH-3988", "fixed-in", "mediahub-frontend@2.2.130+187"), ("MH-3988", "label", None),
          ("MH-3891", "rework", "unified-streaming@2.1.91+382"), ("MH-3887", "rework", "unified-streaming@2.1.91+382")}
check("build 91: the owner's two skipped tickets, MH-3988 moved bare, the rework not appended — and nothing else",
      misses(r91) == want91)
# the record of the threads named MH-1860, MH-3883 and MH-3941 for build 90; read against the same rule, the backend
# changelog of 2.1.43 also names MH-3887 (no backend entry) and MH-3795 (Fixed In 2.1.40): rework not appended
want90 = {("MH-1860", "fixed-in", "mediahub-frontend@2.2.129+186"), ("MH-1860", "label", None),
          ("MH-3883", "fixed-in", "mediahub-backend@2.1.43+275"), ("MH-3941", "rework", "mediahub-frontend@2.2.129+186"),
          ("MH-3887", "fixed-in", "mediahub-backend@2.1.43+275"), ("MH-3795", "rework", "mediahub-backend@2.1.43+275")}
check("build 90: MH-1860 without Fixed In or label, MH-3883 Done without one, MH-3941 one build behind, and the rule's two more",
      misses(r90) == want90)
check("the tickets in order owe nothing, MH-3926's bare entry included",
      "MH-3926" in r91["ok"] and "MH-3881" in r90["ok"] and len(r91["ok"]) == 14 and len(r90["ok"]) == 9)
check("no status or assignee miss: what the threads announced is what Jira holds",
      not any(k in ("status", "assignee") for _, k, _ in misses(r90) | misses(r91)))
check("MH-3927 is an open question to its holder, not a row",
      [(q["key"], q["holder"]) for q in r91["questions"]] == [("MH-3927", "Summer Chen")] and "MH-3927" not in {r["key"] for r in r91["rows"]})

# ── the rules on made-up tickets ──────────────────────────────────────────────────────────────────────
iss = copy.deepcopy(ISSUES)
iss["MH-3926"]["fields"]["customfield_11252"] = "unified-streaming@2.1.91+382"
iss["MH-3958"]["fields"]["status"] = {"name": "In Progress"}
iss["MH-4001"]["fields"]["assignee"] = {"displayName": "Alice Wang"}
iss["MH-3873"]["fields"]["labels"] = ["release:mh-2.1", "flag:no-version"]
iss["MH-3873"]["fields"]["customfield_11252"] = None
iss["MH-3993"]["fields"]["customfield_11252"] = "unified-streaming@2.1.92"
iss["MH-3933"]["fields"]["customfield_11252"] = "mediahub-backend@2.0.44"
r = RC.reconcile(record("91"), iss, t91)
m = misses(r)
check("a canonical +BUILD entry covers the build as the bare one does", not any(k == "MH-3926" for k, _, _ in m))
check("a status behind the announced Review is named", ("MH-3958", "status", None) in m)
check("an assignee other than the announced one is named on an open ticket", ("MH-4001", "assignee", None) in m)
check("flag:no-version owes no Fixed In", not any(k == "MH-3873" for k, _, _ in m))
check("a later build in the series covers this one", not any(k == "MH-3993" for k, _, _ in m))
check("an entry in another series does not", ("MH-3933", "fixed-in", "mediahub-backend@2.1.44+276") in m)
blind = RC.reconcile(record("91"), ISSUES, None)
check("no thread: status and assignee are not judged, said once; Fixed In and label still are; entries bare",
      blind["gaps"] == ["release thread not read: status and assignee not judged"] and blind["questions"] == []
      and ("MH-3987", "fixed-in", "unified-streaming@2.1.91") in misses(blind))
check("a ticket Jira did not return is a gap, never in order",
      "MH-3998: not read in Jira" in RC.reconcile(record("91"), {k: v for k, v in ISSUES.items() if k != "MH-3998"}, t91)["gaps"])

# ── where it shows ────────────────────────────────────────────────────────────────────────────────────
note = R.build_note(record("91"), r91)
table = note.split("## Jira gaps")[1] if "## Jira gaps" in note else ""
check("the release note carries the Jira gaps table: ticket, what is missing, the proposed entry",
      "| ticket | what is missing | proposed |" in table and "| MH-3988 Pre-start permission request omits credentials, hits prod billing · Review | no mediahub-frontend entry for 2.2.130; no release:mh-2.1 | "
      "mediahub-frontend@2.2.130+187; label release:mh-2.1 |" in table and "| MH-3927 Graphics Insertion trusts destination attribute overlayAppId, allowing cross-tenant … · Review | reverted into MH-3926" in table)
check("nothing when there is none", "Jira gaps" not in R.build_note(record("91"), dict(r91, rows=[], questions=[]))
      and "Jira gaps" not in R.build_note(record("91")))
check("one ask for every build in the window",
      RC.ask_text([r90, r91]) == "QA-AWS3 builds 90, 91: 9 tickets lack Fixed In or the label.")
cmds = [t for res in (r90, r91) for _, t in RC.batch_commands(res)]
check("the batch: a Fixed In append and a label add per ticket, nothing else",
      ["fixed-in", "MH-3998", "--add", "unified-streaming@2.1.91+382; unified-media-frontend@3.0.44+201"] in cmds
      and ["label", "MH-3998", "--add", "release:mh-2.1"] in cmds
      and all(c[0] in ("fixed-in", "label") and c[2] == "--add" and "--remove" not in c and "--clear" not in c for c in cmds))
check("MH-3927 is not in the batch, nor a status or assignee", not any("MH-3927" in c for c in cmds))
merged = RC.merged_commands([r90, r91])
check("a ticket two builds carry is one append naming both entries",
      [c for _, c in merged if c[:2] == ["fixed-in", "MH-3887"]] == [["fixed-in", "MH-3887", "--add", "mediahub-backend@2.1.43+275; unified-streaming@2.1.91+382"]]
      and len([c for _, c in merged if c[0] == "fixed-in"]) == 9)
check("a key carried by two services of one build is one write", sum(1 for c in cmds if c[:2] == ["fixed-in", "MH-3998"]) == 1)

with tempfile.TemporaryDirectory() as tmp:
    # the release note in the vault reads the reading kept beside the record
    os.makedirs(os.path.join(tmp, "releases", "2.1"))
    for b in ("90", "91"):
        rec = record(b)
        json.dump({k: v for k, v in rec.items() if k != "name"}, open(os.path.join(tmp, "releases", "2.1", rec["name"] + ".json"), "w"))
    json.dump(dict(r91, at="2026-11-12T07:30:00+08:00"), open(RC.reading_path(tmp, r91), "w"))
    check("the kept reading is found by its record, and only for it",
          RC.saved_reading(tmp, record("91"))["build"] == "91" and RC.saved_reading(tmp, record("90")) is None)
    check("a kept reading is not taken for a build record", [x["name"] for x in R.build_records(tmp)] ==
          ["2026-11-11-build-91-to-qa-aws3", "2026-11-10-build-90-to-qa-aws3"])

    # questions: the fold once, with its ticket's state as its base; a pattern on three builds of one agent
    state = {"questions": {}, "built": {}}
    today = datetime.date(2026, 11, 12)
    added = RC.raise_questions(state, [r90, r91], [r90, r91], today, "2026-11-12T07:30:00+08:00")
    fold = state["questions"][added[0]] if added else {}
    check("two builds are not a pattern: only the fold is raised from builds 90 and 91", len(added) == 1)
    check("the fold is one open question to Summer Chen on MH-3927, its base the ticket now",
          len(added) == 1 and fold.get("who") == "Summer Chen" and fold.get("lead") == ["MH-3927"]
          and fold["base"]["tickets"]["MH-3927"]["status"] == "Review" and fold.get("audience") == RC.AUDIENCE)
    check("raised again, it is not raised twice", RC.raise_questions(state, [r91], [r90, r91], today, "x") == [])
    r92 = dict(copy.deepcopy(r90), build="92", name="2026-11-12-build-92-to-qa-aws3", date="2026-11-12", questions=[])
    written = {}
    added = RC.raise_questions(state, [], [r90, r91, r92], today, "x", drafts_dir=os.path.join(tmp, "drafts"),
                               write=lambda p, t: written.__setitem__(p, t))
    pats = [state["questions"][i] for i in added]
    check("andyBot's missing Fixed In on three builds is one question to its owner, with a drafted message",
          any(p["who"] == "andyzhao" and "andyBot" in p["text"] and "no Fixed In" in p["text"] and p.get("message")
              and p["draft"]["file"] in written for p in pats))
    check("the question's own message is its draft, never the meeting wording",
          all(Q.draft(p)["text"] == p["message"] for p in pats))

# ── the note in the vault: written once, then the owner's; ela's part is rewritten, his sections stay ───
held = ("---\nsource: \"vault\"\n---\n# build 91\n\n| UR Caller | 2.1.90 → 2.1.91 | (MH-3998 MH-3926 MH-3993) |\n\n"
        "## Afterwards\n\n- 11-11 · MH-3873: Backlog → Review\n\n## Extra\n\nAn extra section.\n")
fresh = "# build 91\n\n## UR Caller\n\n2.1.90 → 2.1.91 · SCTE\n\n- MH-3998 SCTE-35 include option · Review\n\n## Jira gaps\n\n| a |\n"
merged = V.release_note_merge(held, fresh, ["UR Caller"])
check("a held note: ela's part rewritten from the record, Afterwards and his own section kept in order, front kept",
      merged.startswith("---\nsource: \"vault\"\n---\n# build 91\n\n## UR Caller") and "(MH-3998 MH-3926" not in merged
      and merged.index("## Jira gaps") < merged.index("## Afterwards") < merged.index("## Extra") and merged.endswith("An extra section.\n"))
check("a second pass changes nothing", V.release_note_merge(merged, fresh, ["UR Caller"]) == merged)
check("nothing missing any more: the gaps section leaves with the rewrite",
      "Jira gaps" not in V.release_note_merge(merged, fresh.split("\n## Jira gaps")[0] + "\n", ["UR Caller"]))
check("his words in ela's part: the note is left alone",
      V.release_note_merge(held.replace("# build 91\n", "# build 91\n\n- [ ] check this\n"), fresh, ["UR Caller"]) is None)

with tempfile.TemporaryDirectory() as tmp:                 # a held note he marked done is the record: left as it is
    rel = os.path.join(tmp, "vault", "releases", "2.1")
    os.makedirs(rel); os.makedirs(os.path.join(tmp, "reports", "releases", "2.1"))
    json.dump({k: v for k, v in record("91").items() if k != "name"}, open(os.path.join(tmp, "reports", "releases", "2.1", "2026-11-11-build-91-to-qa-aws3.json"), "w"))
    done = held.replace('source: "vault"', 'source: "vault"\nstatus: "done"')
    open(os.path.join(rel, "2026-11-11-build-91-to-qa-aws3.md"), "w").write(done)
    check("a held note marked done is never rewritten", V.release_notes_native(os.path.join(tmp, "vault"), os.path.join(tmp, "reports"), tmp) == []
          and open(os.path.join(rel, "2026-11-11-build-91-to-qa-aws3.md")).read() == done)
    open(os.path.join(rel, "2026-11-11-build-91-to-qa-aws3.md"), "w").write(held)
    check("a held note not done is brought up to date", V.release_notes_native(os.path.join(tmp, "vault"), os.path.join(tmp, "reports"), tmp)
          == ["releases/2.1/2026-11-11-build-91-to-qa-aws3.md"])

# ── Helm's deep links: a compare per service row, a live view per lane (the site's Helm URL, never in a tracked file) ──
with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, "facts", "builds"))
    json.dump({"builds": [{"number": 382, "version": "2.1.91", "result": "SUCCESS"}, {"number": 381, "version": "2.1.90", "result": "SUCCESS"},
                          {"number": 383, "version": "2.1.91", "result": "FAILURE"}]},
              open(os.path.join(tmp, "facts", "builds", "ur-caller.json"), "w"))
    links = R.helm_compare(record("91"), tmp, "https://helm.test/")
    check("UR Caller's row compares its job's build of the old version with the new one; no number, no link",
          links == {"UR Caller": "https://helm.test/builds/compare?from=ur-caller-381&to=ur-caller-382"})
    note = R.build_note(record("91"), compare=links)
    check("the link is short and at the end of the service's line",
          "\n2.1.90 → 2.1.91 · SCTE off switch, overlay cleanup and 4K buffering, operator logging, YouTube readiness, CSC via MQTT"
          " · [compare](https://helm.test/builds/compare?from=ur-caller-381&to=ur-caller-382)\n" in note
          and "[compare]" not in note.split("## MediaHub frontend")[1])
    check("no Helm URL, no link", R.helm_compare(record("91"), tmp, None) == {})
page = "# The lanes\n\n## Line 2.1 · prod-3 ← daily-wed ← QA-AWS3\n\n| table |\n\n## Differences\n"
check("each line's heading gets its lanes' live views, in the heading's order",
      "## Line 2.1 · prod-3 ← daily-wed ← QA-AWS3\n\nlive: [prod-3](https://h/lanes/prod-3) · [daily-wed](https://h/lanes/daily-wed) · "
      "[qa-cn3](https://h/lanes/qa-cn3)\n" in V.lanes_live(page, "https://h") and V.lanes_live(page, None) == page)

# ── today.md's build block: service lines without key clusters; the owner's tickets inline ───────────────
TK = {k: R.ticket_facts(v) for k, v in ISSUES.items()}
rec91 = dict(record("91"), name="2026-11-11-build-91-to-qa-aws3")
block = V.build_block([], [rec91], datetime.date(2026, 11, 12), TK, "Evan Li")
lines = block.split("\n")
ur = next(i for i, l in enumerate(lines) if l.startswith("  - UR Caller"))
check("build 91: MH-3998 and MH-3987 inline under UR Caller, the rest a count linking its section",
      lines[ur].endswith("· [[releases/2.1/2026-11-11-build-91-to-qa-aws3#UR Caller|6 more tickets]]")
      and lines[ur + 1] == "    - MH-3998 SCTE-35 include option on SRT, UDP and RTP destinations · Review · also Unified Media frontend"
      and lines[ur + 2] == "    - MH-3987 [App] Drive CSC sessions through mqtt-gateway instead of direct HTTP · Review")
check("no service line carries a cluster of keys", not re.search(r"\(MH-\d+ MH-", block))
check("a ticket two services carry shows once, under the first; the second's line has nothing more to count",
      block.count("MH-3998") == 1 and next(l for l in lines if l.startswith("  - Unified Media frontend")).endswith("destinations"))
um = next(l for l in lines if l.startswith("  - Unified Media frontend"))
check("a service with three tickets or fewer shows them, within the cap of five in all",
      sum(1 for l in lines if l.startswith("    - ")) <= V.INLINE_MAX and not um.endswith("tickets]]"))
TK2 = dict(TK, **{"MH-4000": dict(TK["MH-4000"], status="Reopened")})
check("a ticket reopened in QA is inline too", "    - MH-4000 " in V.build_block([], [rec91], datetime.date(2026, 11, 12), TK2, "Evan Li"))

# ── today.md: the ask comes from the drafted action, one line, its apply the batch ───────────────────────
iso = "2026-11-12"
act = {"n": 1, "day": iso, "tier": 3, "rule": "release-reconcile", "kind": "fixed-in",
       "text": RC.ask_text([r90, r91]), "command": "ela release reconcile qa-aws3 --build 90 --build 91 --batch",
       "evidence": "QA-AWS3 builds 90, 91 against Jira, read 2026-11-12 07:30"}
cands = V.ask_candidates(datetime.date(2026, 11, 12), [act], [])
shown, more, _, _ = V.settle_asks({}, cands, datetime.date(2026, 11, 12))
page = V.today_page(datetime.date(2026, 11, 12), [], {}, shown)
needs = page.split("## Needs you")[1].split("##")[0] if "## Needs you" in page else ""
check("today.md: one ask, its A the batch", needs.count("- [ ] A (recommended): apply as drafted") == 1
      and "1. QA-AWS3 builds 90, 91: 9 tickets lack Fixed In or the label." in needs)

# the action carries its own letters: A apply the batch · B show me each · C skip this build
act3 = dict(act, options=RC.ask_options(1, act["command"]))
cands = V.ask_candidates(datetime.date(2026, 11, 12), [act3], [])
check("ask_candidates passes the action's options through", cands[0].get("options") == act3["options"])
shown, _, _, _ = V.settle_asks({}, cands, datetime.date(2026, 11, 12))
needs = V.today_page(datetime.date(2026, 11, 12), [], {}, shown).split("## Needs you")[1].split("##")[0]
check("today.md: A apply the batch · B show me each · C skip this build",
      "- [ ] A (recommended): apply the batch" in needs and "- [ ] B: show me each" in needs and "- [ ] C: skip this build" in needs
      and "apply as drafted" not in needs)
opts = {o["letter"]: o["does"] for o in act3["options"]}
check("A is `apply N`, B the batch's dry run (no --apply), C a drop",
      opts == {"A": "apply 1", "B": "ela release reconcile qa-aws3 --build 90 --build 91 --batch", "C": "drop"}
      and not V.sync_handles(opts["A"]) and V.sync_handles(opts["C"]))

print(f"{len(failures)} failures" if failures else "release reconcile: all offline checks passed")
sys.exit(1 if failures else 0)
