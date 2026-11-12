#!/usr/bin/env python3
"""The vault, offline: names, links, redaction, the reading gate, and a whole sync against throwaway sources,
including the safety rules (a missing source, a folder that halves, removal only of files the sync wrote)."""
import contextlib, datetime, io, json, os, re, subprocess, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402
V.lane_lines = lambda: {"qa-cn3": "2.1", "daily-wed": "2.1", "prod-3": "2.1"}   # the release map, fixed for the test

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

CJK = chr(0x53C2) + chr(0x6570)
SAVE = "comm" + "it"
check("a slug is lowercase with hyphens", V.slug("The remote host retires; everything runs") == "the-remote-host-retires-everything-runs")
check("an apostrophe joins its word", V.slug("Evan's Work System") == "evans-work-system")
check("CJK is kept", V.slug("Profile " + CJK) == "profile-" + CJK)
check("a slug is cut at a word", not V.slug("word " * 40).endswith("-") and len(V.slug("word " * 40)) <= 80)

lk = V.Linker({}, {}, "https://jira.example", {"MH", "AC"})
out = lk("Fixed by MH-12, see [MH-12](https://jira.example/browse/MH-12) and `code MH-12`.")
check("a bare key is a direct Jira link", out.startswith("Fixed by [MH-12](https://jira.example/browse/MH-12),"))
check("an existing link is left alone", out.count("](https://jira.example/browse/MH-12)") == 2)
check("a key inside code stays code", "`code MH-12`" in out)
check("codec names are not tickets, even when a project shares the prefix", lk("AC-3, MPEG-2 and SMPTE-2110") == "AC-3, MPEG-2 and SMPTE-2110")
check("a project the owner does not work in is not linked", lk("XYZ-9") == "XYZ-9")
check("no Jira base, no links", V.Linker({}, {}, "", {"MH"})("MH-1") == "MH-1")
SRC = ("the release thread https://tvunetworks.slack.com/archives/C0C16LK4KT9/p1794389824737829 (andyBot) and "
       "<https://example.slack.com/archives/C1/p1|the thread>")
check("a Slack permalink in a page stays whole; Slack's <url|text> becomes a Markdown link",
      lk(SRC) == "the release thread https://tvunetworks.slack.com/archives/C0C16LK4KT9/p1794389824737829 (andyBot) and "
                 "[the thread](https://example.slack.com/archives/C1/p1)")
import ast, collections  # noqa: E402
_named = collections.Counter(t.id for n in ast.parse(open(V.__file__, encoding="utf-8").read()).body if isinstance(n, ast.Assign)
                             for t in n.targets if isinstance(t, ast.Name) and t.id.isupper())
_vrow = next(r for r in V.parts_rows("1 skill") if r.startswith("| the vault |"))
check("the overview's vault row names today.md, project pages, release lines and meetings, not Home or the morning page",
      all(w in _vrow for w in ("today.md", "projects/", "release line", "meetings/")) and "Home" not in _vrow and "morning page" not in _vrow)
check("no module constant in vault.py is assigned twice (a second SLACK_LINK broke every permalink)",
      [k for k, v in _named.items() if v > 1] == [])

addr = ".".join(["10", "0", "0", "7"])
check("an address is redacted", "<address>" in V.redact("box " + addr + ":8080 down"))
check("a version is not an address", V.redact("v1.0.622.2") == "v1.0.622.2")
check("api_token= is redacted", "<redacted>" in V.redact("api_token=abcdefghijklmnop"))
check("a JWT is redacted", "<token>" in V.redact("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"))

check("a day page well over budget is flagged", any("budget" in p for p in V.reading_gate(V.Note("x", "x", "# B\n\n" + "word " * 1400, {"type": "day"}))))
check("a page 5% over is within tolerance", V.reading_gate(V.Note("x", "x", "# B\n\n" + "word " * 1260, {"type": "day"})) == [])
check("link targets are not words", V.reading_units("[a](https://x.example/one/two/three)") == 1)
check("a placeholder root is not a machine path", V.reading_gate(V.Note("x", "x", "# P\n\n<runtime>/a <runtime>/b <runtime>/c", {"type": "plan"})) == [])
u = V.unwrap("# T\n\nOne line\nwrapped.\n\n- item\n  continues\n- next\n\n| a |\n|---|\n\n```\ncode\nstays\n```")
check("a wrapped paragraph becomes one line", "One line wrapped." in u)
check("a wrapped list item joins, the next item stays", "- item continues\n- next" in u)
check("tables and code keep their lines", "| a |\n|---|" in u and "code\nstays" in u)
CASE = '---\ntitle: "Fox · black frames"\ntype: "case"\ndate: "2026-11-05"\n{}status: "open"\n---\n# Fox · black frames\n'
check("a case without a Jira key is not a lint line for it; its customer still is",
      not any("keys" in x for x in V.spec_lint("cases/2026-11-05-fox-black-frames.md", CASE.format('customer: "Fox"\n')))
      and "missing customer" in V.spec_lint("cases/2026-11-05-fox-black-frames.md", CASE.format("")))
check("an empty ela: property is not read as the next line", [m.group(1) for m in V.GUIDE.finditer("ela:\n---\nela: go\n")] == ["go"])
# ela's own lines are never his word (2026-11-09: five runner jobs fired on ela's stubs and a dated ela property)
own = '---\nela: "2026-11-09: the asks carried no ruling"\n---\n- ela: keep / revert / commit —\n- ela: R1–R9 ...\nela: S1 map —\nela: keep / revert — revert\n- ela: 2026-11-09: in the body, his\n'
check("a stub ela leaves and a dated ela property are skipped; words after the dash are his",
      [m.group(1) for m in V.his_lines(own)] == ["keep / revert — revert", "2026-11-09: in the body, his"])
check("each of ela's own lines is a lint line", len(V.own_lines_lint(own)) == 4 and "progress" in V.own_lines_lint(own)[0])
check("a stub under a box does not answer it", V.open_asks("## Waiting for your word\n\n- [ ] keep it\n  ela: keep / drop —\n") == (1, 1)
      and V.open_asks("## Waiting for your word\n\n- [ ] keep it\n  ela: keep / drop — keep\n") == (0, 1))
check("a bold ela: label is not an ela: line; list and quote markers still are",
      [m.group(1) for m in V.GUIDE.finditer("- **ela:** 3 commits\n**ela:** x\n- ela: a\n* ela: b\n> ela: c\n- **the ela repo:** 3\n")] == ["a", "b", "c"])
check("a status run under the title becomes a subtitle", V.tidy_title("# brief · Fri            9 items\n\nText.") == "# Brief · Fri\n\n*9 items*\n\nText.")
check("a lowercase title is raised, ela is not", V.tidy_title("# code layout\n") == "# Code layout\n" and V.tidy_title("# ela review\n") == "# ela review\n")
check("a ::: block becomes a collapsed callout", V.callouts("::: ref Sources\na\n:::") == "> [!quote]- Sources\n> a")
check("a colon in a mermaid timeline period is caught", V.mermaid_problems("```mermaid\ntimeline\n  01:00 : Night\n```") != []
      and V.mermaid_problems("```mermaid\ntimeline\n  1 am : Night\n```\n```mermaid\nflowchart LR\n  a[\"01:00\"] --> b\n```") == [])
check("the warning sits under the title", V.with_warning("# T\n\nbody", ["too long"]).startswith("# T\n\n> [!warning]"))
sent = {"n": 1, "rule": "qa-today", "scope": ["--lane", "qa-cn3"], "command": "ela slack post x --team-thread", "applied": "2026-11-02T08:59:56+0800"}
check("Home's Done line says what made the post leave, and never 'on your tick' without the stamp",
      V.done_line(dict(sent, by="tick")) == "1 — QA today on qa-cn3 sent 08:59 on your tick"
      and V.done_line(dict(sent, by="slack-word")).endswith("sent 08:59 on your word in Slack")
      and V.done_line(dict(sent, by="rule:thread-reply", command="ela slack post y --team-thread")).endswith("sent 08:59 under rule thread-reply")
      and V.done_line(dict(sent, by="harness")).endswith("sent 08:59 by the test harness")
      and V.done_line(dict(sent, sent_by="a session's test run")) == "1 — QA today on qa-cn3 applied 08:59 (trigger not recorded)"
      and V.done_line({"n": 2, "text": "label MH-1", "command": "ela jira label MH-1 x", "applied": "2026-11-02T10:00:00+0800", "by": "rule:label"}) == "2 — label MH-1 done 10:00 under rule label")
import tempfile as _tf
with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh:
    json.dump([dict(sent, send_box=True), {"n": 2, "applied": "2026-11-02T10:00:00+0800", "by": "rule:label"}, {"n": 3, "applied": "2026-11-02T10:18:00+0800", "by": "tick"}], _fh)
_page = V.action_states("- [ ] send 1 — QA today on qa-cn3\n- done 2 — label MH-1 · evidence: x\n- [ ] apply 3 — comment\n", _fh.name)
os.unlink(_fh.name)
check("the page's lines carry the trigger the same way",
      "- [x] send 1 — QA today on qa-cn3 · applied 08:59 (trigger not recorded)" in _page
      and "- done 2 — label MH-1 · evidence: x · done 10:00 under rule label" in _page
      and "- [x] apply 3 — comment · applied 10:18 on your tick" in _page)


def git(*args):
    subprocess.run(["git", "-C", ELAK, "-c", "user.name=t", "-c", "user.email=t@t", *args], capture_output=True)


with tempfile.TemporaryDirectory() as tmp:
    ELAK, reports, vault, runtime = (os.path.join(tmp, d) for d in ("elak", "reports", "vault", "runtime"))
    for d in (ELAK + "/blueprint/decisions", reports + "/runner", reports + "/ela", vault, runtime):
        os.makedirs(d)
    today = datetime.date.today().isoformat()
    for i in range(6):
        open(f"{ELAK}/blueprint/decisions/{today[:4]}-0{i + 1}-01-decision-{i}.md", "w").write(
            f"---\nreader: owner\nstatus: proposed\n---\n# Decision {i}\n\nText.\n")
    open(f"{ELAK}/blueprint/decisions/{today[:4]}-01-02-internal.md", "w").write("---\nstatus: proposed\n---\n# How a script is built\n\nText.\n")
    open(f"{ELAK}/blueprint/decisions/{today[:4]}-01-03-ruled.md", "w").write("---\nreader: owner\nstatus: decided\n---\n# Ruled\n\nText.\n")
    git("init", "-q"); git("add", "."); git(SAVE, "-qm", "x")
    open(f"{reports}/runner/{today}-brief.md", "w").write("# Brief\n\n## Needs you\n\n### 1. A thing\n\n- [ ] apply 2 — ask QA\n- [ ] probe MH-1 from the replay\n- [x] already done upstream\n\n## New tickets\n\nMH-5 new, read.\n")
    os.makedirs(f"{reports}/recent")
    json.dump({"at": f"{today}T09:00", "days": 7, "since": today, "count": 1, "counts": {"2.1": 1, "no line": 0},
               "lines": [{"line": "2.1", "label": "release:mh-2.1", "lanes": {"qa": "qa-cn3"}, "train": [], "by_lane": [],
                          "tickets": [{"key": "MH-5", "summary": "a thing", "type": "Bug", "status": "Review", "assignee": "Dev", "priority": "High",
                                       "due": None, "seen_on": [], "stands": {"text": "dev"}, "qa": None, "last": f"created {today[5:]}"}]}],
               "no_line": [], "sources": {"lane_read": True, "test_lists": ["qa-cn3"]}}, open(f"{reports}/recent/{today}.json", "w"))
    open(f"{reports}/runner/{today}-changes.md", "w").write("# What changed\n\n## Code\n\nOne commit.\n")
    os.makedirs(f"{reports}/lanes", exist_ok=True)
    open(f"{reports}/lanes/train-2.1.md", "w").write(f"# Train · 2.1\n\n*{today} 09:00 · line 2.1 · qa-cn3 → daily-wed → prod-3 · 1 rows*\n\n*QA 1 open · 0 P1*\n\n"
                                                    "| P | ticket | title | owner | qa-cn3 | position |\n|---|---|---|---|---|---|\n| P3 | MH-5 | a thing | — | · 80 | qa |\n")
    open(f"{reports}/ela/{today}-long.md", "w").write("# Long review\n\n" + "word " * 3000)
    open(f"{reports}/ela/{today}-ghost.md", "w").write("---\nproject: ghost\n---\n# Ghost reading\n\nText.\n")
    for i in range(20):
        open(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md", "w").write(f"# Review {i}\n\nText.\n")
    BATCH = [f"{today[:4]}-08-{i + 10}-batch-{i}.md" for i in range(15)]   # bulk, for the halving and mass checks
    for f in BATCH:
        open(f"{reports}/{f}", "w").write("# Batch\n\nText.\n")
    open(f"{vault}/mine.md", "w").write("the owner's own file")
    os.makedirs(f"{vault}/projects/sb")
    SB_DEADLINE = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    open(f"{vault}/projects/sb/sb.md", "w").write(f'---\ntitle: "Super Bowl"\ntype: "project"\ndeadline: "{SB_DEADLINE}"\nkeys: "MH-5"\n'
                                                   'customer: "Hearst"\nsource: "vault"\n---\n# Super Bowl\n\n## Goal\n\nProve the chain.\n\n'
                                                   '## Next step\n\n- [ ] wire the decoder by 2026-01-05\n\nela: keep the head\n')
    open(f"{vault}/projects/sb/glossary.md", "w").write('---\ntitle: "Glossary"\ntype: "review"\ndate: "2026-11-01"\nsource: "vault"\n---\n# Glossary\n')
    open(f"{reports}/ela/{today}-sb-read.md", "w").write("---\nkeys: MH-5\n---\n# A read for the project\n\nText.\n")
    site = os.path.join(tmp, "site.json")
    json.dump({"vault": vault, "elak": ELAK, "reports": reports, "runtime": runtime}, open(site, "w"))
    V.SITE = site
    log = f"{reports}/ela/vault-removed.jsonl"

    def sync(force=False):
        a = types.SimpleNamespace(env_file=os.path.join(tmp, "none.env"), dry_run=False, force=force, json=True)
        try:
            V.cmd_sync(a); return 0
        except SystemExit as e:
            return e.code or 0
    def rows():
        try:
            return [json.loads(l) for l in open(log)]
        except OSError:
            return []
    check("a first sync succeeds", sync() == 0)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_sync(types.SimpleNamespace(env_file=os.path.join(tmp, "none.env"), dry_run=True, force=False, json=False))
    check("the sync's line says what it counts", re.search(r"vault: \d+ generated · \d+ in place · \d+ archived \(", buf.getvalue()) is not None)
    bufj = io.StringIO()
    with contextlib.redirect_stdout(bufj):
        V.cmd_sync(types.SimpleNamespace(env_file=os.path.join(tmp, "none.env"), dry_run=True, force=False, json=True))
    sbp = open(f"{vault}/projects/sb/sb.md").read()
    sbf, sbb = V.split_front(sbp)
    check("a project page is written in place: its properties settled, the desk's lines kept, watch from the deadline",
          'type: "project"' in sbp and f'deadline: "{SB_DEADLINE}"' in sbp and 'customer: "Hearst"' in sbp and 'aliases: ["Super Bowl"]' in sbp
          and f'watch: "{(datetime.date.today() + datetime.timedelta(days=44)).isoformat()}"' in sbp and f'date: "{today}"' in sbp)
    check("its head stands as written above the tail's first heading, the tail's headings in the runner's order",
          sbb.startswith("# Super Bowl\n\n## Goal\n\nProve the chain.\n\n## Next step\n\n- [ ] wire the decoder by 2026-01-05\n\nela: keep the head\n\n## Notes\n")
          and [h for h in re.findall(r"(?m)^## (.+)$", sbb) if h in V.TAIL_HEADS] == ["Notes", "Keys and threads", "Deadline"]
          and "## Waiting for your word" not in sbb)
    check("the tail says the days left and the overdue step, the keys watched, and lists the folder's reading and the inferred one",
          f"## Deadline\n\n*{SB_DEADLINE} · 30 days left*" in sbb and sbb.count("wire the decoder") == 1
          and "## Keys and threads\n\n*keys MH-5 · watched until" in sbb
          and "**in this folder**\n" in sbb and "- [[projects/sb/glossary|Glossary]] · review · 2026-11-01" in sbb
          and f"- [[projects/sb/{today}-review-sb-read|A read for the project]] · review · {today} · live" in sbb
          and "Nothing yet" not in sbb and "Afterwards" not in sbb)
    check("the read with the project's key goes beside its page, carries the inferred property, and the sync says so",
          'project: "sb"' in open(f"{vault}/projects/sb/{today}-review-sb-read.md").read()
          and {"note": f"readings/{today}-sb-read.md", "project": "sb"} in json.loads(bufj.getvalue())["projects"])
    check("a reading's own project: line is carried into the vault, and a project with no folder is a lint line",
          'project: "ghost"' in open(f"{vault}/reference/{today}-review-ghost.md").read()
          and any("project 'ghost' has no folder projects/ghost/" in w for w in json.loads(bufj.getvalue())["warnings"]))
    check("the retired angles are not written: no constraints page, no board, no recent (ADR 0015)",
          not any(os.path.exists(f"{vault}/{x}") for x in ("constraints.md", "board.md", "recent.md", "reference/recent.md")))
    check("the root holds only layout 5's entries", set(x for x in os.listdir(vault) if not x.startswith(".")) <= set(V.ROOTS5) | {"home.md", "mine.md"})
    stamp = {f: os.path.getmtime(os.path.join(dp, f)) for dp, _, fs in os.walk(vault) for f in fs if f.endswith(".md")}
    check("a second sync with nothing new writes nothing", sync() == 0 and
          all(os.path.getmtime(os.path.join(dp, f)) == stamp.get(f) for dp, _, fs in os.walk(vault) for f in fs if f.endswith(".md")))
    q = f"{vault}/reference/quiet.md"
    first, again = V.atomic_write(q, "x\n"), None
    t0 = os.path.getmtime(q)
    os.utime(q, (t0 - 100, t0 - 100))
    again = V.atomic_write(q, "x\n")
    check("a note is written only when its bytes change; the temporary file is dot-prefixed, never left",
          first and not again and os.path.getmtime(q) == t0 - 100 and V.tmp_path(q).endswith("/reference/.quiet.md.ela-tmp")
          and not [f for _, _, fs in os.walk(vault) for f in fs if f.endswith(".ela-tmp")])
    os.remove(q)
    dec0 = f"{vault}/reference/{today[:4]}-01-01-decision-0.md"
    check("a decision waiting for his ruling is live in its thing's home (reference/ when it serves none)",
          os.path.exists(dec0) and 'status: "live"' in open(dec0).read())
    check("one not written for him stays out", not os.path.exists(f"{vault}/reference/{today[:4]}-01-02-decision-internal.md"))
    check("one already ruled on stays out", not os.path.exists(f"{vault}/reference/{today[:4]}-01-03-decision-ruled.md"))
    check("a long review is written, under a warning", "[!warning]" in open(f"{vault}/reference/{today}-review-long.md").read())
    r0 = open(f"{vault}/reference/{today[:4]}-09-10-review-0.md").read()
    check("a report is a work note: live, with its next and moves, until marked done", 'status: "live"' in r0 and "next:" in r0
          and "moves:" in r0 and V.MOVES_HEAD in r0)
    home = open(f"{vault}/{V.TODAY}").read()
    above = home.split("---\n", 2)[2].split("\n---\n")[0]
    check("today.md is the one page: facts, needs you, today, then one line of links; Home points to it",
          all(f"## {x}" in above for x in ("Facts", "Needs you", "Today")) and f"[[reference/days/{today[:4]}/{today}-brief|morning page]]" in home
          and "[[reference/dropped|dropped asks]]" in home and not V.GUIDE.search(home) and len(V.plain(above).split()) <= V.TODAY_WORDS
          and "[[today]]" in open(f"{vault}/home.md").read() and os.path.exists(f"{vault}/{V.DROPPED}"))
    check("the changes page is a day page in reference/days/, linked from today.md", os.path.exists(f"{vault}/reference/days/{today[:4]}/{today}-changes.md")
          and f"[[reference/days/{today[:4]}/{today}-changes|what changed]]" in home)
    check("today.md's footer links neither the board nor recent, retired angles", "[[recent" not in home and "[[board" not in home)
    tr = open(f"{vault}/releases/2.1/train-2.1.md").read()
    check("a line's train page lands in its line's folder as a generated page of its type", 'type: "train"' in tr and "# Train · 2.1" in tr and f'date: "{today}"' in tr)
    check("the morning page points at no recent page", V.RECENT_POINTER not in open(f"{vault}/reference/days/{today[:4]}/{today}-brief.md").read())
    check("a decision carries its title as an alias and a meta line", 'aliases: ["Decision 0"]' in open(dec0).read() and "*decision · " in open(dec0).read())
    os.remove(dec0)
    check("a note the owner deleted is not written again", sync() == 0 and not os.path.exists(dec0))
    check("and it is recorded as deleted by him", any(r.get("fate") == "deleted" and r.get("by") == "owner" and r["path"].endswith("decision-0.md") for r in rows()))
    os.makedirs(f"{vault}/archive", exist_ok=True)
    os.rename(f"{vault}/reference/{today[:4]}-09-10-review-0.md", f"{vault}/archive/{today[:4]}-09-10-review-0.md")
    check("a note he dragged into the archive is not written again", sync() == 0 and not os.path.exists(f"{vault}/reference/{today[:4]}-09-10-review-0.md"))
    check("and stays in the archive, recorded as archived", os.path.exists(f"{vault}/archive/{today[:4]}-09-10-review-0.md")
          and any(r.get("fate") == "archived" and r["path"].endswith("review-0.md") for r in rows()))
    rv = f"{vault}/reference/{today[:4]}-09-12-review-2.md"
    with open(rv, "a") as fh:
        fh.write("\nela: post this to Jira\n")
    check("his ela: line in a generated note survives its rewrite", sync() == 0 and "ela: post this to Jira" in open(rv).read())
    check("and a sync after that writes nothing more", (lambda m: sync() == 0 and os.path.getmtime(rv) == m)(os.path.getmtime(rv)))
    os.makedirs(f"{vault}/.obsidian", exist_ok=True)
    def tab(f):                                            # Obsidian's workspace file, one tab open on f
        json.dump({"main": {"type": "split", "children": [{"type": "leaf", "state": {"type": "markdown", "state": {"file": f}}}]}},
                  open(f"{vault}/.obsidian/workspace.json", "w"))
    tab("home.md"); sync(); tab(f"readings/{today[:4]}-09-12-review-2.md"); sync()
    m = json.load(open(f"{vault}/{V.MANIFEST}"))           # he last opened Home an hour ago; ela wrote 30 minutes ago
    looked = datetime.datetime.fromisoformat(m["home"]["looked"]) - datetime.timedelta(hours=1)
    m["home"]["looked"] = looked.isoformat(timespec="seconds")
    json.dump(m, open(f"{vault}/{V.MANIFEST}", "w"))
    soon = (looked + datetime.timedelta(minutes=30)).isoformat(timespec="seconds")
    json.dump([{"n": 1, "tier": 1, "rule": "label", "text": "label MH-1", "applied": soon},
               {"n": 2, "tier": 2, "rule": "thread-reply", "text": "reply in the release thread"},
               {"n": 3, "tier": 3, "text": "close MH-3"}, {"n": 4, "text": "comment MH-4", "applied": soon}],
              open(f"{reports}/runner/{today}-actions.json", "w"))
    hm = (sync(), open(f"{vault}/{V.TODAY}").read())[1]
    check("today.md lists his own drafted action with its box and the 10:00 ones with don't; nothing applied",
          "- [ ] don't 2 — reply in the release thread" in hm and "1. close MH-3." in hm and "- [ ] A (recommended): apply as drafted" in hm
          and "MH-4" not in hm.split("## Needs you")[1].split("## Today")[0] and "*no answer: nothing happens; gone " in hm)
    check("the ask is remembered with the day it was first asked", json.load(open(f"{reports}/ela/asks.json"))["keys:MH-3"]["first"] == today)
    tab(V.TODAY)
    check("opening today.md counts as looking", sync() == 0 and json.load(open(f"{vault}/{V.MANIFEST}"))["home"]["open"] is True)
    tab(f"reference/{today[:4]}-09-12-review-2.md")
    check("and closing it as not", sync() == 0 and json.load(open(f"{vault}/{V.MANIFEST}"))["home"]["open"] is False)
    os.remove(f"{reports}/runner/{today}-actions.json"); sync()
    m = json.load(open(f"{vault}/{V.MANIFEST}"))
    m["seen"][f"reference/{today[:4]}-09-13-review-3.md"] = "2000-01-01"
    json.dump(m, open(f"{vault}/{V.MANIFEST}", "w"))
    check("a reading untouched for months stays where it is", sync() == 0
          and os.path.exists(f"{vault}/reference/{today[:4]}-09-13-review-3.md") and not os.path.exists(f"{vault}/archive/{today[:4]}-09-13-review-3.md"))
    # a generated note found where an earlier placement put it moves to its thing's home, his lines with it
    r3 = f"{today[:4]}-09-13-review-3.md"
    os.makedirs(f"{vault}/cases", exist_ok=True)
    os.rename(f"{vault}/reference/{r3}", f"{vault}/cases/{r3}")
    with open(f"{vault}/cases/{r3}", "a") as fh:
        fh.write("\nela: keep an eye on this\n")
    m = json.load(open(f"{vault}/{V.MANIFEST}"))
    m["files"] = [f"cases/{r3}" if f == f"reference/{r3}" else f for f in m["files"]]
    m["sources"][f"cases/{r3}"] = m["sources"].pop(f"reference/{r3}")
    json.dump(m, open(f"{vault}/{V.MANIFEST}", "w"))
    dry = types.SimpleNamespace(env_file=os.path.join(tmp, "none.env"), dry_run=True, force=False, json=True)
    buf0 = __import__("io").StringIO()
    with __import__("contextlib").redirect_stdout(buf0):
        V.cmd_sync(dry)
    check("a dry run shows the move and makes none", {"from": f"cases/{r3}", "to": f"reference/{r3}"} in json.loads(buf0.getvalue())["moved"]
          and os.path.exists(f"{vault}/cases/{r3}"))
    check("a sync moves a note placed elsewhere to its home, his line with it", sync() == 0
          and not os.path.exists(f"{vault}/cases/{r3}") and "ela: keep an eye on this" in open(f"{vault}/reference/{r3}").read()
          and not any(r["path"] == f"cases/{r3}" for r in rows()))
    r4 = f"{vault}/reference/{today[:4]}-09-14-review-4.md"
    V.cmd_finish(types.SimpleNamespace(path=f"reference/{today[:4]}-09-14-review-4.md", to="archive"))
    check("finish marks a note done where it is on his word, logged as his; the sync keeps it and never rewrites it",
          'status: "done"' in open(r4).read() and (lambda m: sync() == 0 and os.path.exists(r4) and os.path.getmtime(r4) == m)(os.path.getmtime(r4))
          and any(r.get("by") == "owner" and r.get("fate") == "archived" and r["path"].endswith("review-4.md") for r in rows()))
    try:
        V.cmd_finish(types.SimpleNamespace(path="home.md", to="delete")); refused = False
    except SystemExit:
        refused = True
    check("finish refuses a living page", refused and os.path.exists(f"{vault}/home.md"))
    r6 = f"{vault}/reference/{today[:4]}-03-01-decision-2.md"
    check("a live note carries an empty next field", 'next: ""' in open(r6).read() and "done:" not in open(r6).read())
    txt = open(r6).read(); open(r6, "w").write(txt.replace('next: ""', 'next: "done"'))
    check("next: done makes the note done where it is at the next sync, the move kept in next", sync() == 0
          and os.path.exists(r6) and not os.path.exists(f"{vault}/archive/{today[:4]}-03-01-decision-2.md")
          and 'next: "done"' in open(r6).read() and 'status: "done"' in open(r6).read() and 'moves: "closed"' in open(r6).read())
    r9 = f"{vault}/reference/{today[:4]}-04-01-decision-3.md"
    check("a note to read carries no ela property for the tables", "\nela:" not in open(r9).read().split("\n---", 1)[0])
    txt = open(r9).read(); open(r9, "w").write(txt.replace('next: ""', 'next: ""\nela: "1A, post it"'))
    check("a word typed in the old ela property stays, as a line in the note", sync() == 0
          and 'ela: "1A, post it"' in open(r9).read().split("\n---", 1)[1] and open(r9).read().count("1A, post it") == 1)
    txt = open(r9).read(); open(r9, "w").write(re.sub(r'^next: .*$', 'next: "confirm"', txt, count=1, flags=re.M))
    check("the move he chose survives a sync before the watcher acts on it", sync() == 0 and 'next: "confirm"' in open(r9).read())
    txt = open(r9).read(); open(r9, "w").write(txt.replace('next: "confirm"', 'next: "agree"'))
    check("a value the note does not offer is not kept by the rewrite", sync() == 0 and 'next: "agree"' not in open(r9).read().split("\n---", 1)[0])
    bp = f"{vault}/reference/days/{today[:4]}/{today}-brief.md"
    txt = open(bp).read(); open(bp, "w").write(txt.replace("- [ ] probe MH-1", "- [x] probe MH-1"))
    check("a choice he ticks stays ticked through the rewrite", sync() == 0 and "- [x] probe MH-1 from the replay" in open(bp).read()
          and "- [ ] apply 2" in open(bp).read())
    r7 = f"{vault}/reference/{today[:4]}-05-01-decision-4.md"
    txt = open(r7).read(); open(r7, "w").write(txt.replace('next: ""', "next: drop"))
    check("next: drop makes it done where it is, kept, next drop, logged as his", [x[1] for x in V.apply_marks(vault, reports)] == ["drop"]
          and os.path.exists(r7) and 'next: "drop"' in open(r7).read() and 'status: "done"' in open(r7).read()
          and any(r.get("fate") == "archived" and r["path"].endswith("decision-4.md") for r in rows()))
    with open(f"{vault}/reference/{today[:4]}-09-11-review-1.md", "a") as fh:
        fh.write("\n- ela: write this to the KB\n")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_guidance(types.SimpleNamespace(all=False, json=True))
    g = json.loads(buf.getvalue())
    check("ela: lines anywhere in the vault are read as his guidance", sorted(x["says"] for x in g["guidance"])
          == ["1A, post it", "keep an eye on this", "keep the head", "post this to Jira", "probe MH-1 from the replay", "write this to the KB"]
          and "to_learn" not in g)
    with open(f"{vault}/reference/{today[:4]}-09-11-review-1.md", "a") as fh:
        fh.write("\n- [x] apply 7, 8 — MH-9: hand it over and assign\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_guidance(types.SimpleNamespace(all=False, json=True))
    g2 = [x for x in json.loads(buf.getvalue())["guidance"] if x["says"].startswith("apply")]
    check("one tick on an ask of two writes is his word on each, each with its own id",
          [x["says"] for x in g2] == ["apply 7 — MH-9: hand it over and assign", "apply 8 — MH-9: hand it over and assign"]
          and len({x["id"] for x in g2}) == 2)
    p1 = f"{ELAK}/blueprint/decisions/{today[:4]}-02-01-decision-1.md"
    open(p1, "w").write(open(p1).read().replace("status: proposed", "status: decided"))
    git("add", "-A"); git(SAVE, "-qm", "ruled")
    d1 = f"{vault}/reference/{today[:4]}-02-01-decision-1.md"
    check("a decision he ruled on is done by ela where it is, kept", sync() == 0 and os.path.exists(d1)
          and 'status: "done"' in open(d1).read() and 'closed-by: "ela"' in open(d1).read()
          and any(r.get("by") == "ela" and r.get("fate") == "archived" for r in rows()))
    V.cmd_restore(types.SimpleNamespace(path=os.path.relpath(dec0, vault)))
    check("restore brings a deleted note back on the next sync", sync() == 0 and os.path.exists(dec0))
    os.rename(reports, reports + ".gone")
    check("a missing reports root stops the sync", sync() == 3)
    check("and nothing was removed", os.path.exists(dec0))
    os.rename(reports + ".gone", reports)
    for f in BATCH:
        os.remove(f"{reports}/{f}")
    for i in range(10, 20):
        os.remove(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md")
    check("the notes halving at once stops the sync", sync() == 3)
    check("--force applies a deliberate removal", sync(force=True) == 0 and not os.path.exists(f"{vault}/reference/{today[:4]}-09-28-review-18.md"))
    for i in range(10, 20):
        open(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md", "w").write(f"# Review {i}\n\nText.\n")
    for f in BATCH:
        open(f"{reports}/{f}", "w").write("# Batch\n\nText.\n")
    sync(force=True)
    before = len(rows())
    for i in range(10, 20):
        os.remove(f"{vault}/reference/{today[:4]}-09-{i + 10}-review-{i}.md")
    check("a mass disappearance is written again, not recorded as read", sync() == 0
          and os.path.exists(f"{vault}/reference/{today[:4]}-09-25-review-15.md") and len(rows()) == before)
    check("a file the sync never wrote is never removed", os.path.exists(f"{vault}/mine.md"))
    native = f"{vault}/ela/workflow.md"
    open(native, "w").write('---\ntitle: "Workflow"\ntype: "guide"\nsource: "vault"\n---\n\n# Workflow\n\nIt stands well.\n')
    check("a sync with a native page succeeds", sync(force=True) == 0)
    check("a native note is never overwritten", "It stands well." in open(native).read())
    check("a native note stays out of the manifest's files (it is only listed as seen)",
          "ela/workflow.md" not in json.load(open(f"{vault}/{V.MANIFEST}"))["files"]
          and "ela/workflow.md" in json.load(open(f"{vault}/{V.MANIFEST}"))["native"])
    os.makedirs(f"{vault}/ela/bot", exist_ok=True)
    rpt = f"{vault}/ela/bot/r.md"
    def report_warnings(words):
        open(rpt, "w").write('---\ntitle: "R"\ntype: "report"\nsource: "vault"\nstatus: "proposed"\n---\n\n# R\n\n' + "word " * words
                             + "\n\n> [!note]- Evidence\n> " + "more " * 3000 + "\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sync(force=True)
        return [w for w in json.loads(buf.getvalue().strip().splitlines()[-1])["warnings"] if "ela/bot/r.md" in w]
    check("a report outside the lifecycle folders, its evidence folded, is no lint line", report_warnings(300) == [])
    check("a report over 1,200 words outside its folds is a warning",
          any("words, budget 1,200 (folded callouts not counted)" in w for w in report_warnings(1500)))
    os.remove(rpt)
    ov = f"{vault}/ela/overview.md"
    open(ov, "w").write('---\ntitle: "ela"\ntype: "guide"\nsource: "vault"\n---\n\n# ela\n\nIntro by hand.\n\n## The parts\n\nstale table\n\n'
                        '## Waiting for your word\n\n- [ ] **Rule on the cadence** note\n\n## Known limits\n\n- One machine.\n\n## Extra\n\nKept.\n')
    os.makedirs(f"{vault}/mh", exist_ok=True)
    open(f"{vault}/mh/engineering-management.md", "w").write("# P\n\n## Plan\n\n| # | change | owner | by | done | state |\n|---|---|---|---|---|---|\n"
                                                            "| 1 | a | me | 01-01 | x | open |\n| 2 | b | me | 12-31 | y | open |\n\n## Next\n\n1. Plan 4: ask for the fallback.\n")
    o = (sync(force=True), open(ov).read())[1]
    check("the ela page is generated: measures, parts, schedule, the week's commits; the stale parts replaced",
          all(f"## {h}" in o for h in V.GENERATED_SECTIONS) and "stale table" not in o and "Intro by hand" not in o
          and "1 of 2 program items on time" in o and "## This week in ela" in o)
    check("its hand sections are kept as written, a missing one added, the desk's own kept",
          "- [ ] **Rule on the cadence** note" in o and "- One machine." in o and "## What changed for MediaHub this week\n\nNothing yet." in o
          and "## Extra\n\nKept." in o and "source:" not in o)
    hm = open(f"{vault}/{V.TODAY}").read()
    check("today.md carries no program or ela line: they are a link away", "**MediaHub:**" not in hm and "[[ela/overview|ela]]" in hm)
    check("and a sync after that writes the ela page no more", (lambda m: sync() == 0 and os.path.getmtime(ov) == m)(os.path.getmtime(ov)))
    os.makedirs(f"{vault}/library", exist_ok=True)
    topic = f"{vault}/library/topic-a.md"
    open(topic, "w").write('---\ntitle: "Topic A"\ntype: "topic"\nstatus: "decided"\nsource: "vault"\n---\n\n# Topic A\n')
    open(f"{vault}/library/library.md", "w").write("# Library\n")
    m = json.load(open(f"{vault}/{V.MANIFEST}"))
    m["files"].append("library/library.md")
    json.dump(m, open(f"{vault}/{V.MANIFEST}", "w"))
    check("a retired folder is neither written nor emptied: its pages are left for the owner", sync() == 0
          and open(f"{vault}/library/library.md").read() == "# Library\n" and 'status: "decided"' in open(topic).read()
          and "library/" not in open(f"{vault}/{V.MANIFEST}").read())
    open(f"{vault}/{V.MANIFEST}", "w").write("{broken")
    check("an unreadable manifest stops the sync", sync() == 3)
old = ("10-days", "20-reviews", "25-board", "30-verify", "40-decisions", "50-plans", "70-library", "80-views", "85-assistant", "90-attachments")
src = open(os.path.join(ROOT, "skills", "vault", "vault.py")).read() + open(os.path.join(ROOT, "skills", "reports", "SKILL.md")).read()
check("no folder of the first layout is named in the code", not any(o in src for o in old))
with tempfile.TemporaryDirectory() as t:
    ap = os.path.join(t, "actions.json")
    json.dump([{"n": 1, "applied": "2026-10-26T09:15:10+0800"}, {"n": 2},
               {"n": 3, "by_owner": {"at": "2026-10-26T11:09:48+0800", "comment": "9"}}], open(ap, "w"))
    page = V.action_states("- [ ] apply 1 — a\n- [ ] apply 2 — b\n- [ ] apply 3 — c\n- [ ] probe MH-1", ap)
    check("an applied write shows ticked with its time", "- [x] apply 1 — a · applied 09:15" in page)
    check("an open write gets a handled-myself box", "- [ ] apply 2 — b\n- [ ] I handled it myself — not apply 2" in page)
    check("a write he made in Jira shows as handled, its apply left unticked",
          "- [ ] apply 3 — c\n- [x] I handled it myself — not apply 3 · you commented in Jira 11:09" in page)
    check("a session choice is left as written", page.endswith("- [ ] probe MH-1"))
    check("no actions file leaves the page as written", V.action_states("- [ ] apply 1 — a", os.path.join(t, "none")) == "- [ ] apply 1 — a")
row = {"note": "days/x.md", "lines": ["what about apply 5?"], "at": "2026-10-26T11:50:00+0800", "status": "done",
       "job": "J1", "answer": "Leave it.\nela: not an ask\n- [ ] not a box"}
page = V.with_answers("# Day\n\nela: what about apply 5?\n", "days/x.md", [row])
check("an answer sits under the line it answers", "ela: what about apply 5?\n\n> [!note]- ela answered · 11:50 · job J1\n> Leave it." in page)
check("an answer's own ela: line is defused", "> ela — not an ask" in page and not any(
    m.group(1).strip() == "not an ask" for m in V.GUIDE.finditer(page)))
check("an answer is placed once", V.with_answers(page, "days/x.md", [row]) == page)
check("an answer whose line is gone is not placed", V.with_answers("# Day\n", "days/x.md", [row]) == "# Day\n")
native = '---\ntitle: "Day"\nela: "what about apply 5?"\nsource: "vault"\n---\n\n# Day\n\nela: what about apply 5?\n'
page = V.with_answers(native, "days/x.md", [row])
check("an answer never lands in the front matter", V.split_front(page)[0] == V.split_front(native)[0]
      and "ela: what about apply 5?\n\n> [!note]- ela answered" in page and V.front_breaks(V.split_front(page)[0]) == [])
check("an ask only in the front matter draws no answer", V.with_answers(native.replace("\nela: what about apply 5?\n", "\n"), "days/x.md", [row])
      == native.replace("\nela: what about apply 5?\n", "\n"))
check("front matter broken by a fold is a lint line", V.front_breaks(['title: "Day"', 'ela: "x"', '', '> [!note]- ela answered · 11:50 · job J1', '> Leave it.'])
      and V.front_breaks(['title: "Day', 'aliases:', '  - "Day"', 'keys: ["MH-1"]']) == ["front matter line 2: title does not parse"])
page = V.with_moves("# Plan\n\nbody\n", "projects/x/p.md", "plan")
check("a plan ends in what each of its boxes does", "- **agree**: ela builds it" in page and "- **reject**: done, as rejected" in page
      and "- **drop**: done and kept where it is" in page and "- [ ]" not in page and page.rstrip().endswith("`projects/x/p.md`.*"))
check("next moves are replaced, not repeated", V.with_moves(page, "projects/x/p.md", "plan").count(V.MOVES_HEAD) == 1)
built = V.with_moves(page, "projects/x/p.md", "built", "10-26 15:20")
check("a built note explains accept and not-done, not the ask's boxes", "- **accept**" in built and "- **not-done**" in built and "**drop**" not in built)
check("a kind without moves gets none", V.MOVES_HEAD not in V.with_moves(page, "x.md", "day"))
prog = V.progress_line(page, "step one")
check("progress goes above the next moves", prog.index("## Progress") < prog.index(V.MOVES_HEAD) and "· step one" in prog)
check("a second progress line joins the first", V.progress_line(prog, "step two").count("## Progress") == 1)
check("front matter keys are set and removed", V.set_front('---\ntype: "plan"\nclaimed: "x"\n---\nbody', status="built", claimed=None)
      == '---\ntype: "plan"\nstatus: "built"\n---\nbody')
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "projects", "x")); os.makedirs(rep)
    open(os.path.join(vlt, "projects", "x", "p.md"), "w").write('---\ntype: "plan"\nstatus: "live"\ndone: false\n---\n' + page)
    to = V.move_note(vlt, rep, "projects/x/p.md", "in-progress", "in progress")
    moved = open(os.path.join(vlt, to)).read()
    check("an agreed note stays where it is, live and building, the vault's own page (in-progress read as building)",
          to == "projects/x/p.md" and 'source: "vault"' in moved and 'status: "live"' in moved and 'moves: "built"' in moved
          and "done:" not in moved and "- **accept**" in moved and not os.path.exists(os.path.join(vlt, "in-progress")))
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "reference")); os.makedirs(rep)
    open(os.path.join(vlt, "reference", "a.md"), "w").write('---\ntype: "plan"\nstatus: "live"\nagree: true\ndone: false\n---\n# A\n')
    got = V.apply_marks(vlt, rep)
    check("a ticked agree box is reported for the runner and left in place", got == [("reference/a.md", "agree")]
          and os.path.exists(os.path.join(vlt, "reference", "a.md")))
    open(os.path.join(vlt, "reference", "b.md"), "w").write('---\ntype: "plan"\nstatus: "live"\nmoves: "built"\naccept: true\n---\n# B\n')
    check("a ticked accept box on a built note is reported too", ("reference/b.md", "accept") in V.apply_marks(vlt, rep, dry_run=True))
    open(os.path.join(vlt, "reference", "n.md"), "w").write('---\ntype: "plan"\nsource: "vault"\nstatus: "live"\n---\n# N\n\n## Next moves\n\n- [ ] Agree, build it\n')
    V.ensure_native_moves(vlt)
    n = open(os.path.join(vlt, "reference", "n.md")).read()
    check("a plan written in the vault gains its next field, its section kept once", 'next: ""' in n and n.count(V.MOVES_HEAD) == 1)
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "reference")); os.makedirs(rep)
    two = os.path.join(vlt, "reference", "two.md")
    open(two, "w").write('---\ntype: "review"\nstatus: "live"\nnext: "agree"\n---\n# Two\n\nbody\n')
    check("a move the note does not offer runs nothing", V.apply_marks(vlt, rep) == [] and os.path.exists(two))
    w = open(two).read()
    check("the note names the value and its choices, once", w.count(V.MOVE_WARN) == 1 and "`agree`" in w and "make-plan" in w)
    V.apply_marks(vlt, rep)
    check("the warning is not repeated", open(two).read().count(V.MOVE_WARN) == 1)
    open(two, "w").write(w.replace('next: "agree"', 'next: "make-plan"'))
    check("a move it offers runs", V.apply_marks(vlt, rep, dry_run=True) == [("reference/two.md", "make-plan")])
    open(two, "w").write(open(two).read().replace('next: "make-plan"', 'next: "noted"'))

with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "projects", "x")); os.makedirs(rep)
    open(os.path.join(vlt, "projects", "x", "q.md"), "w").write('---\ntype: "plan"\nstatus: "live"\nmoves: "plan"\nnext: "park"\n---\n# Q\n\nbody\n\n## Next moves\n\n- **agree**: x\n')
    check("a plan offers park, and park is the runner's", V.apply_marks(vlt, rep, dry_run=True) == [("projects/x/q.md", "park")])
    to = V.move_note(vlt, rep, "projects/x/q.md", "parked", waits_on="the Pack team, in its thread", wake="FB-1 moving")
    q = open(os.path.join(vlt, to)).read()
    check("a parked note stays where it is, live, saying who it waits on, since when and what wakes it, offering resume and drop only",
          to == "projects/x/q.md" and 'status: "live"' in q and 'waits-on: "the Pack team, in its thread"' in q and 'wake: "FB-1 moving"' in q
          and 'parked: "' in q and 'moves: "parked"' in q and "**resume**" in q and "**drop**" in q and "**agree**" not in q
          and "**done**" not in q)
    open(os.path.join(vlt, "projects", "x", "h.md"), "w").write('---\ntype: "plan"\nstatus: "live"\nsource: "vault"\nwaits-on: "QA"\nmoves: "parked"\n---\n# H\n\nhis body\n')
    V.ensure_native_moves(vlt)
    h = open(os.path.join(vlt, "projects", "x", "h.md")).read()
    check("a note parked by hand gains its chooser fields, its body untouched", 'moves: "parked"' in h and 'next: ""' in h and h.endswith("# H\n\nhis body\n"))
    open(os.path.join(vlt, "projects", "x", "h.md"), "w").write(h.replace('next: ""', 'next: "agree"'))
    check("a parked note runs only resume or drop", ("projects/x/h.md", "agree") not in V.apply_marks(vlt, rep))
    open(os.path.join(vlt, "projects", "x", "q.md"), "w").write(q.replace('next: ""', 'next: "resume"'))
    V.apply_marks(vlt, rep)
    r = open(os.path.join(vlt, "projects", "x", "q.md")).read()
    check("resume makes it live for his word again, its parked fields gone",
          'status: "live"' in V.split_front(r)[0] and not any(l.startswith(("wake:", "waits-on:", "parked:")) for l in V.split_front(r)[0])
          and "**agree**" in r)
    check("the parked moves are a set of their own", V.move_props("parked", in_to_read=False) == ["resume", "drop"] and V.move_set("parked") == "parked")

S = V.settled_status
check("a work note settles to live or done, layout 4's statuses read as the state they meant",
      S("projects", "in progress", "plan") == ("live", None, None) and S("reference", "waiting", "plan") == ("live", None, None)
      and S("reference", "parked", "decision") == ("live", None, None) and S("reference", "proposed", "review") == ("live", None, None)
      and S("releases", "closed", "review") == ("done", None, None) and S("reference", None, "review") == ("live", None, None))
check("an old outcome moves to next, and archive/ is done", S("archive", "accepted", "plan") == ("done", None, "accept")
      and S("reference", "planned", "review") == ("done", None, "make-plan") and S("archive", "not now", "plan") == ("done", None, "not-now"))
check("a verdict is a result", S("releases", "fail", "verify") == ("live", "fail", None)
      and S("archive", "pass", "verify") == ("done", "pass", None))
check("a case keeps its own states, closed in the archive; a page keeps what it had",
      S("cases", "answered", "case") == ("answered", None, None) and S("archive", "open", "case") == ("closed", None, None)
      and S("ela", "whatever", "guide") == ("whatever", None, None))
asks = "# R\n\n## Waiting for your word\n\n- [x] one\n- [ ] two\n  ela: no, keep it\n- [ ] three\n\n## Next\n\n- [ ] not an ask\n"
check("an ask is open until ticked or answered by an ela: line under it", V.open_asks(asks) == (1, 3)
      and V.open_asks(asks.replace("- [ ] three", "- [x] three")) == (0, 3) and V.open_asks("# R\n\n- [ ] x\n") == (0, 0))
check("an open ask on a done note is a lint line; on a live one it is not",
      "on a done note" in (V.asks_lint(V.Note("reference/r.md", "r", asks, {"type": "review", "status": "done"})) or "")
      and V.asks_lint(V.Note("reference/r.md", "r", asks, {"type": "review", "status": "live"})) is None
      and V.asks_lint(V.Note("ela/r.md", "r", asks, {"type": "report"})) is None
      and V.asks_lint(V.Note("ela/history/p.md", "p", asks, {"type": "plan", "status": "done"})) is None
      and V.asks_lint(V.Note("archive/p.md", "p", asks, {"type": "plan", "status": "done"})) is None)
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "v", "reference")); os.makedirs(os.path.join(t, "r", "ela"))
    fm = '---\ntype: "{}"\nsource: "vault"\nstatus: "live"\nnext: ""\nmoves: "{}"\n---\n'
    open(os.path.join(t, "v", "reference", "a.md"), "w").write(fm.format("review", "review") + asks.replace("- [ ] three", "- [x] three"))
    open(os.path.join(t, "v", "reference", "b.md"), "w").write(fm.format("review", "review") + asks)
    open(os.path.join(t, "v", "reference", "p.md"), "w").write(fm.format("plan", "plan") + asks.replace("- [ ] three", "- [x] three"))
    check("a dry run names the answered reading and changes nothing",
          V.answered_readings(os.path.join(t, "v"), os.path.join(t, "r"), dry_run=True) == [("reference/a.md", None)]
          and 'status: "live"' in open(os.path.join(t, "v", "reference", "a.md")).read())
    moved = V.answered_readings(os.path.join(t, "v"), os.path.join(t, "r"))
    ra = open(os.path.join(t, "v", "reference", "a.md")).read()
    check("a reading whose every ask is answered is done where it is; one with an open ask and a plan stay live",
          moved == [("reference/a.md", "reference/a.md")] and 'status: "done"' in ra and V.MOVES_HEAD not in ra
          and 'status: "live"' in open(os.path.join(t, "v", "reference", "b.md")).read()
          and 'status: "live"' in open(os.path.join(t, "v", "reference", "p.md")).read())
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "runner", "jobs"))
    def job(jid, status, kind="vault", note="readings/n.md"):
        json.dump({"id": jid, "kind": kind, "status": status, "created": "2026-10-30T15:32:00+0800", "started": "2026-10-30T15:33:00+0800",
                   "origin": {"note": note, "lines": ["do this"]}}, open(os.path.join(t, "runner", "jobs", jid + ".json"), "w"))
    job("j1", "queued"); job("j2", "running"); job("j3", "done"); job("j4", "queued", kind="owner")
    pend = V.load_pending(t)
    check("the vault's pending jobs are read from the runner's job files, nothing else", [r["job"] for r in pend] == ["j1", "j2"])
    nt = "# N\n\nela: do this\n\n## After\n\nx\n"
    on = V.with_answers(nt, "readings/n.md", pend[:1])
    check("a queued line shows at once as an on-it fold under it, and renders the same again",
          "ela: do this\n\n> [!note]- on it · queued 15:32 · job j1\n> waiting its turn" in on
          and V.with_answers(on, "readings/n.md", pend[:1]) == on and V.PENDING_FOLD.sub("", on) == nt)
    ans = V.with_answers(on, "readings/n.md", pend[:1] + [{"note": "readings/n.md", "lines": ["do this"], "at": "2026-10-30T15:40:00+0800",
                                                           "status": "done", "job": "j1", "answer": "Yes."}])
    check("the answer replaces the on-it fold", "on it" not in ans and "ela answered · 15:40 · job j1\n> Yes." in ans)
    check("a running job says since when", "running since 15:33" in V.pending_block(pend[1]))
with tempfile.TemporaryDirectory() as t:
    v, r = os.path.join(t, "v"), os.path.join(t, "r")
    for d in ("reference", "reference/days/2026"):
        os.makedirs(os.path.join(v, d))
    os.makedirs(os.path.join(r, "ela"))
    fm = '---\ntype: "{}"\nsource: "vault"\nstatus: "live"\nnext: "drop"\nmoves: "review"\n---\n# {}\n\nText.\n'
    for n, k in (("deep-1", "review"), ("deep-2", "review"), ("plan-3", "plan")):
        open(os.path.join(v, "reference", n + ".md"), "w").write(fm.format(k, n))
    open(os.path.join(v, "reference/days/2026", "2026-10-29-brief.md"), "w").write("see [[deep-1|the deep read]] and [[reference/plan-3]]\n")
    open(os.path.join(v, "home.md"), "w").write("[[deep-2]]\n")
    check("what links a note: day pages and notes, never Home", V.linked_from(v, "reference/deep-1.md") == ["reference/days/2026/2026-10-29-brief.md"]
          and V.linked_from(v, "reference/deep-2.md") == [])
    V.apply_marks(v, r)
    a1 = os.path.join(v, "reference", "deep-1.md")
    check("drop makes a reading done where it is, its text as it was, next drop",
          "# deep-1\n\nText." in open(a1).read() and 'status: "done"' in open(a1).read() and 'next: "drop"' in open(a1).read())
    check("drop deletes nothing and moves nothing, linked or not, reading or plan",
          all('status: "done"' in open(os.path.join(v, "reference", n + ".md")).read() for n in ("deep-1", "deep-2", "plan-3"))
          and not os.path.exists(os.path.join(v, "archive")))
past = V.Note("days/2026/2026-10-28-brief.md", "b", "# B", {"type": "day", "kind": "brief", "date": "2026-10-28"}); past.held = ["too long"]
now_ = V.Note("days/2026/2026-10-30-brief.md", "b", "# B", {"type": "day", "kind": "brief", "date": "2026-10-30"}); now_.held = ["too long"]
rev = V.Note("readings/2026-10-28-r.md", "r", "# R", {"type": "review", "date": "2026-10-28"}); rev.held = ["too long"]
hm = V.home(datetime.date(2026, 10, 30), datetime.datetime(2026, 10, 30, 9), [past, now_, rev])
check("Home owes no rewrite of a past day page; today's and a review stay listed",
      "owes a shorter version of 2" in hm and "2026-10-28-brief" not in hm and "2026-10-30-brief|" in hm)
check("a watch window: an explicit date, a type's default, a cleared watch stops it",
      V.watch_until({"watch": "until 2026-11-13"}) == datetime.date(2026, 11, 13)
      and V.watch_until({"type": "review", "date": "2026-10-30"}) == datetime.date(2026, 11, 13)
      and V.watch_until({"type": "meeting", "date": "2026-10-30"}) == datetime.date(2026, 11, 13)
      and V.watch_until({"type": "report", "date": "2026-10-30"}) == datetime.date(2026, 11, 13)   # 10 working days
      and V.watch_until({"type": "review", "date": "2026-10-30", "watch": ""}) is None)
with tempfile.TemporaryDirectory() as t:
    v, r = os.path.join(t, "v"), os.path.join(t, "r")
    for d in ("archive", "in-progress", "readings"):
        os.makedirs(os.path.join(v, d))
    os.makedirs(os.path.join(r, "ela"))
    link = "https://x.slack.com/archives/C1/p1793000000000001"
    td = datetime.date.today()
    open(os.path.join(v, "archive", "promote.md"), "w").write(
        f'---\ntype: "review"\ndate: "{td}"\nstatus: "closed"\nposted: ["{link}"]\nkeys: "MH-3855"\n---\n# Promote\n\nHis text.\n')
    open(os.path.join(v, "in-progress", "plan.md"), "w").write(
        f'---\ntype: "plan"\ndate: "{td}"\nkeys: "MH-1"\nwatch: ""\n---\n# Plan\n\n## Next moves\n\n- x\n')
    open(os.path.join(v, "archive", "old.md"), "w").write('---\ntype: "review"\ndate: "2026-01-01"\nkeys: "MH-2"\n---\n# Old\n')
    open(os.path.join(v, "readings", "r.md"), "w").write(f'---\ntype: "review"\ndate: "{td}"\nkeys: "MH-3"\n---\n# R\n')
    check("only archive and in-progress notes with posted or keys, in their window, are watched",
          [w["note"] for w in V.watched_notes(v, td)] == ["archive/promote.md"])
    tz = datetime.datetime.now().astimezone().strftime("%z")
    at = f"{td}T10:00:00.000{tz}"
    ts = str(datetime.datetime.combine(td, datetime.time(11)).timestamp())
    jira = {"issues": [{"key": "MH-3855", "events": [{"field": "status", "at": at, "by": "Andy Zhao", "from": "In Progress", "to": "Done"}],
                        "comments": [{"at": at, "by": "Erin Zhang", "text": "secret words of a colleague"},
                                     {"at": at, "by": "Owner", "text": "mine"}]}]}
    thread = {"messages": [{"ts": "1"}, {"ts": ts, "user": "Andy Zhao", "text": "deployed, verbatim"},
                           {"ts": ts, "user": "Helm Lookout", "text": "bot"}]}
    sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
    import brief as B
    calls = []
    def fake(cmd, timeout=600):
        calls.append(cmd)
        return jira if "changes" in cmd else thread
    B.run_json, B.owner_jira_name = fake, lambda e: "Owner"
    json.dump({"vault": v, "reports": r}, open(os.path.join(t, "site.json"), "w"))
    V.SITE = os.path.join(t, "site.json")
    def after(**kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            V.cmd_afterwards(types.SimpleNamespace(env_file=None, since=None, dry_run=kw.get("dry", False), json=True))
        return json.loads(buf.getvalue())
    out = after(dry=True)
    check("a dry run reads, reports and writes nothing", out["appended"] == 2 and "Afterwards" not in open(os.path.join(v, "archive", "promote.md")).read())
    out = after()
    txt = open(os.path.join(v, "archive", "promote.md")).read()
    check("the JSON carries since, notes, lines, appended and watched", set(out) >= {"since", "notes", "lines", "appended", "watched"}
          and out["watched"] == 1 and out["appended"] == 2)
    check("one line per source per day, in ela's words: who moved the key, who commented, who replied, and the link",
          f"- {td.isoformat()[5:]} · MH-3855: In Progress → Done (Andy Zhao); a comment from Erin Zhang" in txt
          and f"- {td.isoformat()[5:]} · thread: a reply from Andy Zhao → [thread]({link})" in txt)
    check("never a colleague's words, never the owner's own or a machine's", "secret" not in txt and "verbatim" not in txt
          and "Owner" not in txt.split("## Afterwards")[1] and "Helm Lookout" not in txt)
    check("his text is kept, watched and last are stamped", "His text." in txt and "watched:" in txt and f'last: "{td}"' in txt)
    log = [json.loads(l) for l in open(os.path.join(r, "ela", "afterwards.jsonl"))]
    check("one log row per new line", len(log) == 2 and {x["ref"] for x in log} == {"MH-3855", link})
    again = after()
    check("a second pass the same day is idempotent: no new line, no new row", again["appended"] == 0
          and open(os.path.join(v, "archive", "promote.md")).read().replace(V.props_of(V.split_front(txt)[0])["watched"], "") .count("· MH-3855") == 1
          and len(open(os.path.join(r, "ela", "afterwards.jsonl")).readlines()) == 2)
td = datetime.date.today()
st = V.archive_stamp('---\ntype: "review"\ndate: "2026-10-01"\ntitle: "Promote MH-10"\n---\n# Promote [MH-10](x)\n\n'
                     '> Status: [MH-11](x) open, see https://t.slack.com/archives/C1/p1793000000000002.\n\n'
                     '## Detail\n\nMH-12 and UR-457 cited; https://t.slack.com/archives/C1/p1793000000000003\n', td)
check("an archived note is stamped with its subject keys, every thread it links, and the day its window counts from",
      st == {"archived": td.isoformat(), "keys": "MH-10 MH-11",
             "posted": "https://t.slack.com/archives/C1/p1793000000000002 https://t.slack.com/archives/C1/p1793000000000003"})
check("a note that already carries keys, posted or archived is never re-stamped",
      all(V.archive_stamp(f'---\n{k}: "x"\n---\n# MH-1\n', td) is None for k in ("keys", "posted", "archived")))
check("the window counts from archived when present",
      V.watch_until({"type": "review", "date": "2026-01-01", "archived": "2026-10-30"}) == datetime.date(2026, 11, 13))
with tempfile.TemporaryDirectory() as t2:
    v = os.path.join(t2, "v"); os.makedirs(os.path.join(v, "archive"))
    a = os.path.join(v, "archive", "old-review.md")
    open(a, "w").write('---\ntype: "review"\ndate: "2026-01-01"\n---\n# Review of [MH-7](x)\n\nHis text.\n')
    dry = V.stamp_archive(v, td, dry_run=True)
    check("a dry run stamps nothing on disk but watches as if it had",
          "archived:" not in open(a).read() and [w["note"] for w in V.watched_notes(v, td, dry)] == ["archive/old-review.md"])
    V.stamp_archive(v, td)
    check("an old note dragged into archive is watched from the day it was stamped, its text kept",
          [w["note"] for w in V.watched_notes(v, td)] == ["archive/old-review.md"] and "His text." in open(a).read()
          and V.stamp_archive(v, td) == {})
body = "---\ntype: \"plan\"\n---\n# P\n\ntext\n\n## Next moves\n\n- **accept**\n"
nt, new = V.with_afterwards(body, [("MH-1", "2026-10-31", "- 10-31 · MH-1: A → B (x)")])
check("Afterwards sits above the next moves, so a move keeps it", nt.index("## Afterwards") < nt.index("## Next moves") and len(new) == 1)
nt2, new2 = V.with_afterwards(nt, [("MH-1", "2026-10-31", "- 10-31 · MH-1: A → C (x)")])
check("a day's line is brought up to date in place", new2 == [] and "A → C" in nt2 and "A → B" not in nt2)
full = V.with_afterwards("# N\n", [(f"MH-{i}", "2026-10-31", f"- 10-31 · MH-{i}: x") for i in range(45)])[0]
check("at most 40 lines a note", full.count("\n- 10-31") == 40)
check("the all-notes base has Live and Done views, and Home links Done", "name: Done" in V.VIEWS["all-notes"] and "name: Live" in V.VIEWS["all-notes"]
      and "[[ela/all-notes.base#Done|done]]" in V.home(datetime.date(2026, 10, 30), datetime.datetime(2026, 10, 30, 9), []))
one = V.Note("one-thing.md", "One Thing · 2026-11", "# One Thing · 2026-11\n", {"type": "one-thing", "date": "2026-11-03"})
one.count = 14
hm1 = V.home(datetime.date(2026, 11, 3), datetime.datetime(2026, 11, 3, 9), [one])
check("Home links the One Thing page with the rows still to paste, once, below the divider",
      "[[one-thing|One Thing]] (14 to paste)" in hm1.split("\n---\n", 1)[1] and hm1.count("|One Thing]]") == 1)
one.count = 0
check("Home links the One Thing page without a count when every row is pasted",
      "[[one-thing|One Thing]]" in V.home(datetime.date(2026, 11, 3), datetime.datetime(2026, 11, 3, 9), [one])
      and "to paste" not in V.home(datetime.date(2026, 11, 3), datetime.datetime(2026, 11, 3, 9), [one]))
check("Home has no One Thing link when the vault has no One Thing page",
      "One Thing" not in V.home(datetime.date(2026, 11, 2), datetime.datetime(2026, 11, 2, 9), []))
check("the One Thing page is a living page of the page family", V.TYPE_FAMILY.get("one-thing") == "page" and "one-thing" in V.BUDGET)
check("a sprint is a work note, live until done; a reading too", S("reference", "active", "sprint") == ("live", None, None)
      and S("reference", "decided", "review") == ("live", None, None))
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "reference")); os.makedirs(rep)
    open(os.path.join(vlt, "reference", "r.md"), "w").write('---\ntype: "review"\nstatus: "live"\n---\n# R\n')
    to = V.move_note(vlt, rep, "reference/r.md", "archive", "in a session", next_="make-plan")
    r = open(os.path.join(vlt, to)).read()
    check("a move to done with --next keeps that word as next, status done, where it is",
          to == "reference/r.md" and 'next: "make-plan"' in r and 'status: "done"' in r)
check("the statuses: live and done, a case's, a project's parked, layout 4's read as input; never a report's ruling",
      V.STATUSES[:5] == ("live", "done", "open", "answered", "closed") and "parked" in V.STATUSES and "decided" not in V.STATUSES)
with tempfile.TemporaryDirectory() as t:
    for d in ("archive", "projects/x", "reference"):
        os.makedirs(os.path.join(t, d))
    open(os.path.join(t, "archive", "a.md"), "w").write('---\ntype: "plan"\nstatus: "accepted"\n---\n# A\n\nhis body\n')
    open(os.path.join(t, "archive", "v.md"), "w").write('---\ntype: verify\nstatus: pass\n---\n# V\n')
    open(os.path.join(t, "projects", "x", "b.md"), "w").write('---\ntype: "plan"\nstatus: "in-progress"\n---\n# B\n')
    open(os.path.join(t, "reference", "s.md"), "w").write('---\ntype: "sprint"\nstatus: "active"\n---\n# S\n')
    fixes = V.settle_statuses(t)
    a = open(os.path.join(t, "archive", "a.md")).read()
    check("sync settles a native note's front matter, one line per fix, its body untouched", len(fixes) == 4
          and 'status: "done"' in a and 'next: "accept"' in a and 'moves: "closed"' in a and a.endswith("# A\n\nhis body\n")
          and 'result: "pass"' in open(os.path.join(t, "archive", "v.md")).read()
          and 'status: "live"' in open(os.path.join(t, "projects", "x", "b.md")).read()
          and 'status: "live"' in open(os.path.join(t, "reference", "s.md")).read())
    check("a second pass has nothing to fix", V.settle_statuses(t) == [])
    V.write_move_sets(t)
    ms = {n: open(os.path.join(t, "ela", "moves", n + ".md")).read() for n in ("plan", "built", "parked", "closed", "case")}
    check("each move set lists its moves and its type's states", "live" in ms["plan"] and "done" in ms["plan"] and "proposed" not in ms["plan"]
          and "accept" in ms["built"] and "name: next" not in ms["closed"] and "done" in ms["closed"]
          and "- name: status" in ms["parked"] and "answered" in ms["case"] and "live" not in ms["case"])

with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "verify", "plans"))
    open(os.path.join(t, "verify", "plans", "2026-10-27-MH-5.md"), "w").write('---\ntype: "verify-plan"\nkey: "MH-5"\n---\n# MH-5 · verify plan\n\n| # | goal |\n')
    open(os.path.join(t, "verify", "plans", "2026-10-26-MH-6.md"), "w").write('---\ntype: "verify-plan"\n---\n# MH-6 · verify plan\n')
    done6 = V.Note("to-read/2026-10-27-verify-mh-6.md", "MH-6 · PASS", "# x", {"type": "verify", "date": "2026-10-27"})
    vp = V.verify_plan_notes(t, [done6])
    check("a verification plan is a reading now, no status: nothing waits on it", [n.path for n in vp] == ["readings/2026-10-27-verify-plan-mh-5.md"]
          and vp[0].props == {"type": "verify-plan", "date": "2026-10-27"})
    check("a result on or after the plan's date replaces it", all("mh-6" not in n.path for n in vp))
check("a plan offers no moves of its own any more", "verify-plan" not in V.MOVE_PROPS and "run" not in V.MOVE_MEANING)

with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "blueprint", "decisions"))
    open(os.path.join(t, "blueprint", "decisions", "a.md"), "w").write('---\nstatus: proposed\n---\n# A\n')
    open(os.path.join(t, "blueprint", "decisions", "b.md"), "w").write('---\nstatus: accepted\n---\n# B\n')
    check("only a decision that exists and is no longer proposed counts as ruled",
          not V.ruled(t, "blueprint/decisions/a.md") and V.ruled(t, "blueprint/decisions/b.md") and not V.ruled(t, "blueprint/decisions/gone.md"))
    log = os.path.join(t, "removed.jsonl")
    open(log, "w").write("\n".join(json.dumps(r) for r in (
        {"path": "to-read/x.md", "src": "blueprint/decisions/x.md", "by": "ela", "fate": "archived"},
        {"path": "to-read/y.md", "src": "reviews/y.md", "by": "ela", "fate": "archived"},
        {"path": "to-read/z.md", "src": "blueprint/decisions/z.md", "by": "owner", "fate": "deleted"})) + "\n")
    paths, _ = V.load_removed(log)
    check("ela archiving a ruled decision does not keep it out if it is proposed again; his own deletion and ela's 30-day "
          "archive still do", paths == {"to-read/y.md", "to-read/z.md"})

import fcntl  # noqa: E402
with tempfile.TemporaryDirectory() as t:
    site_was = V.SITE
    V.SITE = os.path.join(t, "site.json"); json.dump({"runtime": t}, open(V.SITE, "w"))
    held = V.vault_lock()
    other = open(os.path.join(t, "vault-sync.lock"), "w")
    try:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB); blocked = False
    except BlockingIOError:
        blocked = True
    held.close()
    V.SITE = site_was
    check("every vault writer takes the sync's lock, so a note moved during a sync waits",
          blocked and {"sync", "marks", "finish", "note", "restore"} <= set(V.WRITERS) and "guidance" not in V.WRITERS)

with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "reference")); os.makedirs(os.path.join(vlt, "archive")); os.makedirs(rep)
    open(os.path.join(vlt, "archive", "same.md"), "w").write("# kept\n")
    open(os.path.join(vlt, "reference", "same.md"), "w").write('---\ntype: "plan"\nstatus: "live"\n---\n# new\n')
    to = V.move_note(vlt, rep, "reference/same.md", "archive", "rejected")
    check("a move to done stays where it is and touches no namesake", to == "reference/same.md"
          and open(os.path.join(vlt, "archive", "same.md")).read() == "# kept\n" and 'status: "done"' in open(os.path.join(vlt, to)).read()
          and 'next: "reject"' in open(os.path.join(vlt, to)).read())
    check("a note kept in its own folder keeps its name", V.free_path(os.path.join(vlt, "archive"), "same.md", own=os.path.join(vlt, "archive", "same.md"))
          == os.path.join(vlt, "archive", "same.md"))

import hashlib  # noqa: E402
check("an ela: line keeps the id it always had; the same words again get their own", V.guidance_id("n.md", "post it")
      == hashlib.sha256("n.md\0post it".encode()).hexdigest()[:12] and V.guidance_id("n.md", "post it", 2) != V.guidance_id("n.md", "post it"))

with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "days", "2026")); os.makedirs(rep)
    lp = os.path.join(vlt, "days", "2026", "2026-10-27-learned.md")
    open(lp, "w").write('---\ntype: "day"\nkind: "learned"\nmoves: "learned"\nnext: "learn"\n---\n# What the day taught\n')
    check("the evening's learned page is a day page: no moves, nothing taken from it",
          "learned" not in V.MOVE_PROPS and V.apply_marks(vlt, rep) == [] and os.path.exists(lp) and not os.path.exists(os.path.join(vlt, "to-learn")))
    os.makedirs(os.path.join(vlt, "reference"))
    open(os.path.join(vlt, "reference", "r.md"), "w").write('---\ntype: "review"\nsource: "vault"\nstatus: "live"\nmoves: "review"\nnext: ""\n---\n# R\n')
    to = V.move_note(vlt, rep, "reference/r.md", "readings")
    r = open(os.path.join(vlt, to)).read()
    check("a review written in place is done on his word (readings read as done), where it is", to == "reference/r.md"
          and 'status: "done"' in r and 'moves: "closed"' in r and 'source: "vault"' in r and V.MOVES_HEAD not in r)

day = datetime.date(2026, 10, 26)
cons = {"exists": True, "error": None, "today": day.isoformat(), "gaps": [{"kind": "host_unreadable", "host": "qa", "detail": "qa login failed"}],
        "counts": {"active": 1, "expired": 1, "over": 1},
        "active": [{"id": "held", "says": "The new input stays off prod 3.", "until": "2026-11-09", "days_left": 14,
                    "lift_when": "QA passes the chain", "source": "archive/2026-10-26-risk.md", "checks": [{"lanes": ["prod-3"], "what": "the topic list is empty"}],
                    "pins": [{"service": "mediahub-frontend", "lane": "prod-3", "max": "2.2.118", "version": "2.2.120", "state": "over"}]}],
        "expired": [{"id": "old", "says": "An old hold.", "until": "2026-10-24", "days_since_expiry": 2, "pins": [], "checks": []}]}
cn = V.constraints_note(cons, day)
check("a constraint shows what it says, each pin running and over, until, lift and its note",
      "## The new input stays off prod 3." in cn.body and "| 2.2.120 | **over** |" in cn.body and "until 2026-11-09 (14 days)" in cn.body
      and "Lifts when: QA passes the chain" in cn.body and "[[archive/2026-10-26-risk|its note]]" in cn.body and "by hand on prod-3" in cn.body)
check("an expired one is listed, marked expired", "## Expired" in cn.body and "**expired** 2 day(s) ago" in cn.body)
check("a lane not read is named", "Not read: 1" in cn.body)
hm = V.home(day, datetime.datetime(2026, 10, 26, 9), [cn])
check("Home says how many there are and how many are over, linking the page", "[[constraints|1 standing constraint]] · 1 over · 1 expired" in hm)
check("an unreadable read says so", "could not be read" in V.constraints_note(None, day).body)
day = datetime.date(2026, 10, 28)
acts = [{"n": i, "tier": 3, "text": f"t{i}", "day": "2026-10-28"} for i in range(1, 6)]
hm = V.home(day, datetime.datetime(2026, 10, 28, 9), [], {"actions": acts})
check("Home shows at most three of his own, and says how many more", hm.count("- [ ] apply") == 3 and "+2 more on the morning page" in hm)
t2 = [{"n": 7, "tier": 2, "text": "reply", "day": "2026-10-28"}, {"n": 8, "tier": 2, "text": "test list", "day": "2026-10-28", "send_at": "19:00"}]
hm = V.home(day, datetime.datetime(2026, 10, 28, 9), [], {"actions": t2})
check("Home groups the don't boxes by send time, 10:00 first, an action without one at 10:00",
      hm.index("**At 10:00 unless you tick:**") < hm.index("don't 7") < hm.index("**At 19:00 unless you tick:**") < hm.index("don't 8"))
sent = [{"n": 1, "tier": 1, "text": "label MH-1", "day": "2026-10-28", "applied": "2026-10-28T08:50:00+0800"},
        {"n": 2, "tier": 2, "rule": "qa-today", "scope": ["--lane", "qa-cn3"], "kind": "slack", "day": "2026-10-28",
         "applied": "2026-10-28T09:30:31+0800", "permalink": "https://x/p1"},
        {"n": 3, "tier": 3, "text": "his own", "command": "ela jira fixed-in MH-1 --add x", "day": "2026-10-28", "applied": "2026-10-28T10:56:00+0800", "by": "tick"},
        {"n": 4, "tier": 3, "text": "to the desk", "command": "ela jira fixed-in MH-2 --remove y", "day": "2026-10-28", "applied": "2026-10-28T14:08:00+0800", "by": "desk-word"},
        {"n": 5, "tier": 3, "text": "not yet", "day": "2026-10-28"}]
hm = V.home(day, datetime.datetime(2026, 10, 28, 9), [], {"actions": sent})
check("Home's Done line lists every applied action, tier 3 included, with its time and trigger, a post with its link",
      "- 1 — label MH-1 applied 08:50 (trigger not recorded)" in hm and "- 2 — QA today on qa-cn3 applied 09:30 (trigger not recorded) · [link](https://x/p1)" in hm
      and "- 3 — his own done 10:56 on your tick" in hm and "- 4 — to the desk done 14:08 on your word to the desk" in hm and "not yet" not in hm.split("**At")[0])
held = [{"n": 7, "tier": 2, "text": "reply", "day": "2026-10-28"},
        {"n": 8, "tier": 2, "text": "at 09:30: post", "day": "2026-10-28", "send_at": "09:30",
         "dry_run": {"at": "2026-10-28T09:30:05+0800", "line": "8 — dry run: would have posted at 09:30 in #c · text in f"}}]
hm = V.home(day, datetime.datetime(2026, 10, 28, 9), [], {"actions": held, "hold": {"until": "2026-11-05"}})
check("under a tier-2 hold Home's block has no boxes and says until when",
      "**At 10:00, held until 2026-11-05 (dry run):**\n- 7 — reply" in hm and "don't" not in hm and "unless you tick" not in hm)
check("and a dry run shows its own line, in the Done line too, never as sent",
      "**At 09:30, held until 2026-11-05 (dry run):**\n- 8 — dry run: would have posted at 09:30" in hm
      and "**Done since you last looked:**\n- 8 — dry run:" in hm and "sent" not in hm)
sb = {"tier": 3, "send_box": True, "rule": "qa-today", "scope": ["--lane", "qa-cn3"], "kind": "slack",
      "command": "ela slack post x", "text": "QA today on qa-cn3", "day": "2026-10-28"}
box = [dict(sb, n=4), dict(sb, n=5, scope=["--lane", "qa-us1"], send_ticked={"at": "2026-10-28T09:12:00+0800"}),
       dict(sb, n=6, scope=["--lane", "qa-eu1"], vetoed="2026-10-28T09:20:00+0800"), {"n": 7, "tier": 2, "text": "reply", "day": "2026-10-28"}]
hm = V.home(day, datetime.datetime(2026, 10, 28, 9), [], {"actions": box, "hold": {"until": "2026-11-05"}})
check("Home lists a send box between the tier-2 block and his own, in the form the runner reads, a ticked one with its time",
      hm.index("unless you tick" if "unless you tick" in hm else "held until") < hm.index("**Send when you tick:**") < hm.index("**Only you:**")
      and "- [ ] send 4 — QA today on qa-cn3 (your ela: lines applied first) · [[test-list-qa-cn3|the list]] · untouched: not sent" in hm
      and "- [x] send 5 — QA today on qa-us1 (your ela: lines applied first) · ticked 09:12" in hm
      and "send 6" not in hm and "apply 4" not in hm and "**Only you:** nothing today." in hm)
RUNNER_TICK = r"(?m)^[ \t]*(?:>[ \t]*)*[-*][ \t]+\[[xX]\][ \t]+send[ \t]+(\d+)\b"   # ela-runner's `ticked()` regex, as it stands
check("a send box ticked on Home is what the runner reads, the decorated open one is not", re.findall(RUNNER_TICK, hm) == ["5"]
      and re.findall(r"(?m)^[ \t]*[-*][ \t]+\[[ xX]\][ \t]+send[ \t]+(\d+) — ", hm) == ["4", "5"])
lists = {("qa-today", "qa-cn3"): "[[releases/2.1/test-list-qa-cn3|19 rows, 2 P1]]", ("dev-today", "2.1"): "[[releases/2.1/dev-list-2.1|78 rows, 19 with a gap]]"}
dev = dict(sb, n=9, rule="dev-today", scope=["--line", "2.1"], channel="prj_dev_mediahub", command="ela slack post #prj_dev_mediahub --file f --team-day-post")
hm = V.home(day, datetime.datetime(2026, 10, 28, 9), [], {"actions": [dict(sb, n=4, channel="mediahub-qa-release"), dev,
                                                                       dict(sb, n=8, scope=["--lane", "qa-us1"], unsent={"at": "x", "final": True})], "lists": lists})
check("an open send line links the list it would send with its counts, names the channel and ends untouched: not sent",
      "- [ ] send 4 — QA today on qa-cn3 (your ela: lines applied first) · [[releases/2.1/test-list-qa-cn3|19 rows, 2 P1]] → #mediahub-qa-release · untouched: not sent" in hm
      and "- [ ] send 9 — Dev today on 2.1 (your ela: lines applied first) · [[releases/2.1/dev-list-2.1|78 rows, 19 with a gap]] → #prj_dev_mediahub · untouched: not sent" in hm)
check("one the runner gave up on at its last pass has no box and says so", "- send 8 — QA today on qa-us1 (your ela: lines applied first) · not sent: no tick · stays as apply 8" in hm
      and re.findall(RUNNER_TICK, hm) == [])
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "lanes"))
    open(os.path.join(t, "lanes", "test-list-qa-cn3.md"), "w").write("# Test list · QA-AWS3\n\n*now*\n\n19 open · P1 2 · P2 5 · P3 12 · 4 auto\n\n| P |\n")
    open(os.path.join(t, "lanes", "dev-list-2.1.md"), "w").write("# Dev list · 2.1\n\n78 ticket(s) · 19 with a gap · 3 build change(s)\n")
    open(os.path.join(t, "lanes", "train-2.1.md"), "w").write("# Train\n")
    check("the lane lists' links are read from the pages' own count lines", V.list_links(t) == lists and V.list_links(os.path.join(t, "none")) == {})
hm = V.home(day, datetime.datetime(2026, 10, 28, 11), [], {"actions": [dict(sb, n=4, applied="2026-10-28T09:30:20+0800", permalink="https://x/p4")]})
check("after the send the Done line lists it, the block is gone",
      "- 4 — QA today on qa-cn3 applied 09:30 (trigger not recorded) · [link](https://x/p4)" in hm and "Send when you tick" not in hm)
check("no send box today, no block", "Send when you tick" not in V.home(day, datetime.datetime(2026, 10, 28, 9), [], {"actions": acts}))
with tempfile.TemporaryDirectory() as t:
    ap = os.path.join(t, "a.json")
    json.dump([dict(sb, n=4), dict(sb, n=5, send_ticked="2026-10-28T09:12:00+0800"),
               dict(sb, n=6, applied="2026-10-28T09:30:20+0800", permalink="https://x/p6"), dict(sb, n=7, failed={"error": "slack 500"})], open(ap, "w"))
    pg = "## QA today\n\n- [ ] send 4 — QA today on qa-cn3 (your ela: lines applied first) · unticked: stays as apply 4\n" \
         "- [ ] send 5 — b · unticked: stays as apply 5\n- [x] send 6 — c\n- [x] send 7 — d\n- [x] send 6 — c · sent 09:30 · [link](https://x/p6)"
    check("the morning page's send box under QA today: open with the list, channel and untouched: not sent; ticked, sent with its link, not sent",
          V.action_states(pg, ap, lists) == "## QA today\n\n- [ ] send 4 — QA today on qa-cn3 (your ela: lines applied first) · [[releases/2.1/test-list-qa-cn3|19 rows, 2 P1]] · untouched: not sent\n"
          "- [x] send 5 — b · ticked 09:12\n- [x] send 6 — c · applied 09:30 (trigger not recorded) · [link](https://x/p6)\n- [x] send 7 — d · not sent: slack 500\n"
          "- [x] send 6 — c · sent 09:30 · [link](https://x/p6)")
    check("a decorated line is decorated once", V.action_states(V.action_states(pg, ap, lists), ap, lists) == V.action_states(pg, ap, lists))
with tempfile.TemporaryDirectory() as t:
    os.makedirs(f"{t}/runner")
    check("no hold file, no hold", V.tier2_hold(t, "2026-10-30") is None)
    json.dump({"tier2": {"until": "2026-11-05", "since": "2026-10-30"}}, open(f"{t}/runner/hold.json", "w"))
    check("a hold stands through its until", V.tier2_hold(t, "2026-11-05") and V.tier2_hold(t, "2026-11-06") is None)
    json.dump({"tier2": {"until": "2026-11-05", "lifted": "2026-10-31"}}, open(f"{t}/runner/hold.json", "w"))
    check("a lifted hold ends it", V.tier2_hold(t, "2026-11-01") is None)
    ap = os.path.join(t, "a.json")
    json.dump([{"n": 14, "dry_run": {"line": "14 — dry run: would have posted at 09:30 in #c"}}], open(ap, "w"))
    check("the morning page shows a dry run's line in place of its box",
          V.action_states("x\n- [ ] don't 14 — at 09:30 unless you tick: QA today", ap) == "x\n- 14 — dry run: would have posted at 09:30 in #c")
disk = "# B\n\n## Needs you\n\n- x\n\n## Scrum with the PM at 10:00\n\n- Sprint\nela: PM rules 0x81004009 shows the notice too\n\n## FYI\n\n- y\nela: drop the FYI\n"
check("a line's section is the heading above it", V.section_at(disk, disk.index("ela: PM")) == "Scrum with the PM at 10:00")
new_page = "# B\n\n## Needs you\n\n- x2\n\n## Scrum with the PM at 10:00\n\n- Sprint 2\n\n## Lanes\n\n- z\n"
kept = [(V.section_at(disk, m.start()), m.group(0).strip()) for m in V.GUIDE.finditer(disk)]
out = V.place_lines(new_page, kept)
check("a rewrite keeps his line under its meeting, and one whose section is gone at the end",
      out.index("ela: PM rules") < out.index("## Lanes") and out.index("- Sprint 2") < out.index("ela: PM rules") and out.rstrip().endswith("ela: drop the FYI"))
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "review"))
    for d in ("2026-10-28", "2026-09-20"):
        open(os.path.join(t, "review", f"{d}-reader.md"), "w").write("| item | verdict | line |\n|---|---|---|\n| 1. x | tickable | y |\n")
    open(os.path.join(t, "review", "2026-10-28-replay.json"), "w").write("{}")
    rn = [n for n in V.report_notes(t, datetime.date(2026, 10, 28)) if n.props.get("type") == "reader"]
    check("a reader page is not carried into the vault any more (ADR 0015: nothing read it there)", rn == [])
big = "# A plan\n\n" + "word " * 700 + "\n\n> [!note]- Drafts\n> " + "more " * 3000 + "\n"
check("a plan's budget counts only outside its folds", V.reading_gate(V.Note("in-progress/p.md", "p", big, {"type": "plan"})) == [])
check("a plan over 800 open words is held",
      any("budget 800" in x for x in V.reading_gate(V.Note("in-progress/p.md", "p", "# A plan\n\n" + "word " * 1000, {"type": "plan"}))))
rd = "# The reader\n\n## Learned\n\n" + "".join(f"- a lesson {i} — origin\n" for i in range(7))
check("a reader page with more than five Learned lines is held", "7 Learned lines" in " ".join(V.reading_gate(V.Note("ela/review/r.md", "r", rd, {"type": "reader"}))))
with tempfile.TemporaryDirectory() as t:
    vault, reports = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vault, "projects", "x")); os.makedirs(os.path.join(reports, "ela"))
    open(os.path.join(vault, "projects", "x", "p.md"), "w").write('---\ntype: "plan"\nstatus: "live"\nmoves: "built"\n---\n# P\n')
    got = V.move_note(vault, reports, "projects/x/p.md", "archive", next_="reopen")
    fm = V.props_of(V.split_front(open(os.path.join(vault, got)).read())[0])
    check("done by ela after three working days, where it is, offering reopen", got == "projects/x/p.md" and fm.get("status") == "done"
          and fm.get("moves") == "reopen" and fm.get("closed-by") == "ela")
    check("the status pass leaves its reopen set alone", not any("moves" in x for x in V.settle_statuses(vault)))
    txt = open(os.path.join(vault, got)).read()
    open(os.path.join(vault, got), "w").write(txt.replace('next: ""', 'next: "reopen"'))
    check("his reopen is a move", V.apply_marks(vault, reports) == [("projects/x/p.md", "reopen")])
    fm = V.props_of(V.split_front(open(os.path.join(vault, "projects", "x", "p.md")).read())[0])
    check("reopen makes it live again as built, for his accept", fm.get("status") == "live" and fm.get("moves") == "built" and not fm.get("closed-by"))
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "ela"))
    with open(os.path.join(t, "ela", "closed-by-ela.jsonl"), "w") as fh:
        fh.write('{"at": "2026-10-29T08:00:00+08:00", "note": "archive/p.md", "title": "A plan", "built": "10-24 18:00"}\n')
        fh.write('{"at": "2026-10-10T08:00:00+08:00", "note": "archive/old.md", "title": "Old"}\n')
    rows = V.closed_by_ela({"reports": t}, datetime.date(2026, 10, 29))
    check("the ela page lists the week's notes ela closed, each reopenable", rows == ["- [[archive/p|A plan]] — closed by ela 2026-10-29, built 10-24 18:00; reopen if wrong"])
check("nothing closed says so", V.closed_by_ela({"reports": "/nonexistent"}, datetime.date(2026, 10, 29))[0].startswith("Nothing"))
check("a type outside the closed set is a lint line", "not in the closed set" in V.type_lint("to-read/x.md", "memo"))
check("a decision outside its folders is a lint line", "belongs in" in V.type_lint("readings/x.md", "decision"))
check("a report is a page, in any folder", V.type_lint("ela/bot/x.md", "report") is None and V.type_lint("x.md", "report") is None)
check("a verification in its line's folder is in place; in to-read/ it is not", V.type_lint("releases/2.1/2026-10-29-verify-mh-1.md", "verify") is None
      and V.type_lint("to-read/2026-10-29-verify-mh-1.md", "verify") is not None)
check("a guide outside ela/ is a lint line", "belongs in ela/" in (V.type_lint("meetings/review-list.md", "guide") or ""))
check("the ela page is a guide in place", V.type_lint("ela/overview.md", "guide") is None)
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "ela", "bot"))
    open(os.path.join(t, "ela", "bot", "r.md"), "w").write('---\ntype: "report"\nsource: "vault"\nstatus: "proposed"\nmoves: "plan"\n---\n# R\n')
    open(os.path.join(t, "ela", "bot", "q.md"), "w").write('---\ntype: "report"\nsource: "vault"\nstatus: "proposed"\nmoves: ""\n---\n# Q\n')
    lint = {n.path: V.report_lint(n) for n in V.native_notes(t)}
    check("a report carrying moves is a lint line", any("offers no moves" in x for x in lint["ela/bot/r.md"]))
    check("a report with empty moves is quiet", lint["ela/bot/q.md"] == [])
with tempfile.TemporaryDirectory() as t:
    for d in ("to-read", "mh", "ela", "library", ".obsidian"):
        os.makedirs(os.path.join(t, d))
    open(os.path.join(t, "home.md"), "w").write("# H\n")
    check("the readme's layout names the eight entries", V.layout_folders() == set(V.ROOTS5))
    check("a top folder the readme does not name is a lint line, hidden ones and files are not",
          V.folder_lint(t) == [f"{d}/: a top folder the readme's layout does not name" for d in ("library", "mh", "to-read")])
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "archive"))
    open(os.path.join(t, "archive", "a.md"), "w").write("---\ntype: verify\nstatus: \"done\"\nmoves: \"closed\"\n---\n# A\n")
    fixes = V.settle_statuses(t)
    check("an unquoted type in archive is quoted, the body untouched", fixes == ["archive/a.md: type quoted"]
          and 'type: "verify"' in open(os.path.join(t, "archive", "a.md")).read())
check("a project is a living page with a budget, and a reading may live in its folder",
      V.TYPE_FAMILY.get("project") == "page" and V.BUDGET.get("project") == 1200 and "projects" in V.FAMILY_FOLDERS["reading"])
check("a project page is projects/<key>/<key>.md; a reading or a report beside it is in place",
      V.type_lint("projects/a/a.md", "project") is None and "projects/<key>/<key>.md" in (V.type_lint("projects/a/b.md", "project") or "")
      and "projects/<key>/<key>.md" in (V.type_lint("mh/a.md", "project") or "")
      and V.type_lint("projects/a/2026-11-04-glossary.md", "review") is None and V.type_lint("projects/a/r.md", "report") is None)
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "projects", "sb"))
    check("project: names a folder that exists, or it is a lint line",
          V.project_lint("readings/x.md", {"project": "sb"}, t) is None and V.project_lint("readings/x.md", {}, t) is None
          and "has no folder projects/nope/" in (V.project_lint("readings/x.md", {"project": "nope"}, t) or ""))
td = datetime.date(2026, 11, 4)
pf = V.project_facts("sb", '---\ntitle: "SB"\ndeadline: "2027-02-14"\nnext-step: "the PoC week, 11-10"\nkeys: "MH-1 MH-2 AC-4"\n'
                     'channels: "https://x.slack.com/archives/C1/p1"\n---\n# SB\n\n- [ ] first box\n\n## Notes\n\nold tail\n\n'
                     '## Afterwards\n\n- 11-03 · MH-1: A → B (x)\n', td)
check("a project's facts: the deadline and days, the next-step property before the first box, its date, keys without codecs, threads from channels, "
      "the Afterwards rows, the head without the tail",
      pf["days"] == 102 and pf["step"] == "the PoC week, 11-10" and pf["step_due"] == datetime.date(2026, 11, 10) and not pf["overdue"]
      and pf["keys"] == ["MH-1", "MH-2"] and pf["links"] == ["https://x.slack.com/archives/C1/p1"] and pf["afterwards"] == ["- 11-03 · MH-1: A → B (x)"]
      and pf["head"] == "# SB\n\n- [ ] first box\n")
pf2 = V.project_facts("sb", '---\ndeadline: "2026-11-10"\n---\n# SB\n\n- [x] done\n- [ ] ask Robin, since 10-28\n', td)
check("without next-step the first unticked box is the step; a past date makes it overdue",
      pf2["step"] == "ask Robin, since 10-28" and pf2["step_due"] == datetime.date(2026, 10, 28) and pf2["overdue"])
check("a step without a date is overdue only once the deadline has passed",
      not V.project_facts("sb", '---\ndeadline: "2026-11-10"\n---\n- [ ] ask\n', td)["overdue"]
      and V.project_facts("sb", '---\ndeadline: "2026-11-01"\n---\n- [ ] ask\n', td)["overdue"]
      and V.project_facts("sb", '---\ndeadline: "2026-11-01"\n---\n# nothing\n', td)["step"] is None)
check("a month-day step date lands in the nearest year", V.step_date("by 01-05", td) == datetime.date(2027, 1, 5)
      and V.step_date("since 10-28", td) == datetime.date(2026, 10, 28) and V.step_date("no date", td) is None)
check("a project page is watched until its deadline plus 14 days unless watch says otherwise",
      V.watch_until({"type": "project", "deadline": "2027-02-14"}) == datetime.date(2027, 2, 28)
      and V.watch_until({"type": "project", "deadline": "2027-02-14", "watch": ""}) is None)
with tempfile.TemporaryDirectory() as t:
    for d in ("projects/sb", "archive", "readings"):
        os.makedirs(os.path.join(t, d))
    open(os.path.join(t, "projects", "sb", "sb.md"), "w").write('---\ntype: "project"\ndeadline: "2027-02-14"\nkeys: "MH-1"\nchannels: "https://x.slack.com/archives/C1/p1"\n---\n# SB\n')
    open(os.path.join(t, "archive", "a.md"), "w").write('---\ntype: "review"\nkeys: "MH-1 MH-9"\n---\n# A\n')
    open(os.path.join(t, "archive", "b.md"), "w").write('---\ntype: "review"\nkeys: "MH-9"\nproject: "other"\n---\n# B\n')
    open(os.path.join(t, "readings", "c.md"), "w").write('---\ntype: "review"\n---\n# C\n')
    gen = V.Note("to-read/2026-11-04-verify-mh-1.md", "MH-1 · PASS", "# x", {"type": "verify"})
    got = V.infer_projects(t, {"sb": {"MH-1"}}, [gen], dry_run=True)
    check("a dry run infers and writes nothing", got == [("to-read/2026-11-04-verify-mh-1.md", "sb"), ("archive/a.md", "sb")]
          and "project:" not in open(os.path.join(t, "archive", "a.md")).read() and gen.props.get("project") == "sb")
    V.infer_projects(t, {"sb": {"MH-1"}}, [], dry_run=False)
    check("the sync writes the inferred project into a note's front matter, never onto one that names its own or the page",
          'project: "sb"' in open(os.path.join(t, "archive", "a.md")).read() and 'project: "other"' in open(os.path.join(t, "archive", "b.md")).read()
          and "project:" not in open(os.path.join(t, "projects", "sb", "sb.md")).read() and "project:" not in open(os.path.join(t, "readings", "c.md")).read())
    check("a project page and what its folder keeps are watched, its threads read from channels",
          [(w["note"], w["links"]) for w in V.watched_notes(t, td)] == [("projects/sb/sb.md", ["https://x.slack.com/archives/C1/p1"])])
    rows = V.project_rows(t, "sb")
    check("the project's rows are the notes naming it, newest first", [r["path"] for r in rows] == ["archive/a.md"])
def _proj(key, days, overdue, step="ask the customer"):
    n = V.Note(f"projects/{key}/{key}.md", key, "# x", {"type": "project"})
    n.facts = {"key": key, "path": n.path, "days": days, "deadline": td + datetime.timedelta(days=days), "overdue": overdue, "step": step}
    return n
hm = V.home(td, datetime.datetime(2026, 11, 4, 9), [_proj("sb", 102, True), _proj("poc", 3, False)], {"program": "Plan 4."})
check("Home lists each project with its days left beside the program, and keeps the program's step while none is near and late",
      "[[mh/engineering-management|program]] · projects: [[projects/sb/sb|sb]] 102 days left · [[projects/poc/poc|poc]] 3 days left · [[ela/overview|ela]]" in hm
      and "**MediaHub:** Plan 4." in hm and "**sb:**" not in hm)
hm = V.home(td, datetime.datetime(2026, 11, 4, 9), [_proj("sb", 102, True), _proj("poc", 3, True, "send the SRT listener")], {"program": "Plan 4."})
check("a project with its deadline under 14 days and its step overdue takes the fourth line",
      "**poc:** send the SRT listener · 3 days left to 2026-11-07, the step is overdue → [[projects/poc/poc|the project]]" in hm
      and "**MediaHub:**" not in hm)
check("no project, no projects link", "projects:" not in V.home(td, datetime.datetime(2026, 11, 4, 9), []))
check("the readme's layout names projects/, the base has a Projects view and a project column",
      "projects" in V.layout_folders() and "name: Projects" in V.VIEWS["all-notes"] and 'file.hasProperty("project")' in V.VIEWS["all-notes"]
      and "order: [project, date, formula.note, type, status, next]" in V.VIEWS["all-notes"] and "project" in V.PROPS)

# the service map: one living page from the published map (site.json `map`), its Review section the owner's
check("the service map is a living page of the page family with a 2,500-word budget, and lives only at ela/service-map.md",
      V.TYPE_FAMILY.get("services") == "page" and V.BUDGET.get("services") == 2500 and V.type_lint(V.SERVICES_PAGE, "services") is None
      and V.type_lint("to-read/service-map.md", "services") is not None)
with tempfile.TemporaryDirectory() as tmp:
    ELAK, reports, vault, runtime = (os.path.join(tmp, d) for d in ("elak", "reports", "vault", "runtime"))
    for d in (ELAK + "/blueprint/decisions", reports + "/runner", reports + "/ela", vault + "/ela", runtime):
        os.makedirs(d)
    open(f"{ELAK}/blueprint/decisions/2026-01-01-d.md", "w").write("---\nreader: owner\nstatus: proposed\n---\n# D\n\nText.\n")
    git("init", "-q"); git("add", "."); git(SAVE, "-qm", "x")
    fixtures = os.path.join(ROOT, "tests", "fixtures", "map")
    check("no published map, no page", V.services_note({"map": os.path.join(tmp, "none")}, vault, datetime.date.today()) is None)
    page = os.path.join(vault, "ela", "service-map.md")
    open(page, "w").write('---\ntitle: "The service map for review"\ntype: "report"\ndate: "2026-11-04"\nsource: "vault"\nstatus: "proposed"\nela: ""\n---\n'
                          "# The service map for review\n\n*Written by the desk.*\n\n## The Fixed In grammar\n\n- the old grammar text\n\n"
                          "## Docker images and their services\n\n| old |\n|---|\n| `copier` |\n\nela: the copier owner is wrong\n\n"
                          "## Review items from this week\n\n- [x] MH-1 carried a swapped slug.\n- [ ] MH-2 confirm the prod id.\n\nela: agree to the first rule\n\n"
                          "## What you should do\n\n- [ ] Read the tables.\n")
    V.SITE = os.path.join(tmp, "site.json")
    json.dump({"vault": vault, "elak": ELAK, "reports": reports, "runtime": runtime, "map": fixtures}, open(V.SITE, "w"))
    def sync():
        try:
            V.cmd_sync(types.SimpleNamespace(env_file=os.path.join(tmp, "none.env"), dry_run=False, force=False, json=True)); return 0
        except SystemExit as e:
            return e.code or 0
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = sync()
    text = open(page).read()
    check("the sync writes the page as a generated note: type services, the title an alias, no longer the desk's report",
          code == 0 and 'type: "services"' in text and 'aliases: ["The service map for review"]' in text and "source:" not in text and "status:" not in text)
    check("the Fixed In grammar is release.yaml's, not the desk's",
          "- Field `customfield_11252`; grammar `<slug>@<version>[; <slug>@<version> ...]`; canonical version `M.m.p+BUILD`." in text
          and "- Docker form: `mds-<slug>@<image>:<tag> — the image qualifier is mandatory`." in text
          and "- Grandfathered: bare build N — read as 0.0.0+N; legacy short slugs mh-*, um-*, ur-streaming on historical entries." in text
          and "the old grammar text" not in text)
    check("the app-layer table: repo, job, both ids shortened with their field, the grammar by rule, the Fixed In form; the gateway line",
          "| `mediahub-backend` | `web/tvu-media-hub` | `media-hub-v4` | `dc517f04…` · backendVersion | `09bda8fc…` · backendVersion | app_layer: `M.m.SUB[.PATCH][+BUILD]` | `mediahub-backend@M.m.p+BUILD` |" in text
          and "| `orchestration` | `web/orchestration` | `orchestration-docker` | — | — | semver_build (default): `M.m.p+SUFFIX` | `orchestration@M.m.p+BUILD` |" in text
          and "| `j2n` | — | — | `a9305b63…` · backendVersion | — | semver_build: `M.m.p+SUFFIX` | `j2n@M.m.p+BUILD` |" in text
          and "Orchestration publishes no lane version in userservice; its version is read through the API gateway at `/orchestration-{token}/base/version` per lane token (2 lanes)." in text)
    check("the docker table is folded under the counts, one row per GM service, the image, class, repos and owner on the first row only",
          "> [!note]- 2 images · 3 services\n> | image (class) | slug | GM name | process type | MQTT topic | service id | status | repo | owner |\n> |---|---|---|---|---|---|---|---|---|\n"
          "> | `copier` (mds-wrapped) | `mds-srt-copier` | Docker Srt Copier | `srt_copier` | `docker_srt_copier` | `04b1ff59…` | Deployed | `media/tvu264`<br>`media/mediaboxPlugins` | Owner A |\n"
          "> |  | `mds-udp-copier` | Docker Udp Copier | `udp_copier` | `docker_udp_copier` | `131519da…` | Deployed |  |  |\n"
          "> | `output` (?) | `mds-ai-sender` | Docker Sender | `Sender` | — | (no prod serviceId — 2.1 daily 23ffedf6…) | Deployed (2.1 daily + QA) | `media/AI/Output` |  |\n" in text
          and "\n2 images, 3 GM services.\n" in text and "| old |" not in text)
    check("the desk's sections become the Review section, kept as written one level down, ticks and ela: lines with them",
          "## Review\n\n### Review items from this week\n\n- [x] MH-1 carried a swapped slug.\n- [ ] MH-2 confirm the prod id.\n\nela: agree to the first rule\n\n### What you should do\n\n- [ ] Read the tables.\n" in text
          and text.count("\n## Review\n") == 1)
    check("an ela: line under a generated section is kept at the end of that section, and once",
          text.count("ela: the copier owner is wrong") == 1 and text.index("2 images, 3 GM services.") < text.index("ela: the copier owner is wrong") < text.index("## Review"))
    check("the page is within its budget: the fold is not counted", V.reading_gate(V.Note(V.SERVICES_PAGE, "x", V.split_front(text)[1], {"type": "services"})) == [])
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        sync()
    check("a second sync writes the same page", open(page).read() == text)
    open(page, "a").write("\nela: drop the second item\n\n### Later\n\nA note of mine.\n")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        sync()
    text3 = open(page).read()
    check("what he adds under Review is kept as written on the next sync", text3.endswith("ela: drop the second item\n\n### Later\n\nA note of mine.\n") and text3.count("### Later") == 1)

# closed notes by subject (vault in-progress/2026-11-09-kept-notes-by-subject-cases-and-archive.md)
H = V.home_for
check("a work note that serves no project has its thing's home by type, else reference",
      H("to-read/2026-11-05-x-timeline.md", {"type": "case"}) == "cases"
      and H("to-read/2026-10-21-verify-mh-1.md", {"type": "verify"}) == "releases"
      and H("to-read/2026-10-29-verify-plan-mh-2.md", {"type": "verify-plan"}) == "releases"
      and H("readings/2026-11-02-promote-2-1-daily-wed-to-prod-3.md", {"type": "review"}) == "releases/2.1"
      and H("readings/2026-11-03-promote-wed-to-prod-3-docker-check.md", {"type": "review"}) == "releases"
      and H("readings/2026-10-28-mh-2-0-region-hotfix-review.md", {"type": "review"}) == "releases/2.0"
      and H("in-progress/2026-10-27-a.md", {"type": "plan", "target": "ela-runner"}) == "ela"
      and H("in-progress/2026-11-04-b.md", {"type": "plan", "target": "the vault's layout and lint"}) == "ela"
      and H("to-read/2026-10-26-c.md", {"type": "review", "title": "System review: ela, the runner"}) == "ela"
      and H("to-read/2026-10-27-d.md", {"type": "plan", "target": "helm"}) == "reference"
      and H("readings/2026-09-21-audio-mixer-mediabox.md", {"type": "review"}) == "reference"
      and H("readings/2026-10-28-deep-mh-3829.md", {"type": "ticket"}) == "reference"
      and H("x/2026-10-01-elastic-plan.md", {"type": "plan", "target": "elastic search"}) == "reference")
check("a case is its own family, in cases/ or the archive; a plan may sit in ela/history, a verification in releases",
      V.type_lint("cases/2026-11-05-x.md", "case") is None and V.type_lint("reference/x.md", "case") is not None
      and V.type_lint("ela/history/x.md", "plan") is None and V.type_lint("releases/x.md", "verify") is None
      and V.type_lint("mh/x.md", "verify") is not None)
check("a work note settles to live or done wherever it lives; a case keeps open, answered or closed",
      S("releases", "accepted", "review") == ("done", None, "accept") and S("ela/history", "proposed", "plan")[0] == "live"
      and S("cases", "answered", "case") == ("answered", None, None) and S("cases", "weird", "case")[0] == "open")
with tempfile.TemporaryDirectory() as t:
    vlt, rep_ = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "releases")); os.makedirs(os.path.join(vlt, "cases")); os.makedirs(rep_)
    open(os.path.join(vlt, "releases", "2026-11-02-promote-x.md"), "w").write('---\ntype: "review"\nstatus: "live"\n---\n# P\n')
    open(os.path.join(vlt, "cases", "2026-11-05-case-x.md"), "w").write('---\ntype: "case"\nstatus: "answered"\n---\n# C\n')
    to1 = V.move_note(vlt, rep_, "releases/2026-11-02-promote-x.md", "archive", next_="done")
    with contextlib.redirect_stdout(io.StringIO()):
        f2 = V.finish(vlt, rep_, "cases/2026-11-05-case-x.md", "archive", "done")
    c = open(os.path.join(vlt, "cases", "2026-11-05-case-x.md")).read()
    check("closing marks a release review done and a case closed, each where it lives",
          to1 == "releases/2026-11-02-promote-x.md" and 'status: "done"' in open(os.path.join(vlt, to1)).read()
          and f2 == "cases" and 'status: "closed"' in c and 'moves: "case"' in c and not os.path.exists(os.path.join(vlt, "archive")))
    rows = [json.loads(l) for l in open(os.path.join(rep_, "ela", "vault-removed.jsonl"))]
    check("the log records a closed note as archived, naming the home it stays in",
          all(x["fate"] == "archived" for x in rows) and {x.get("home") for x in rows} == {"releases", "cases"})
with tempfile.TemporaryDirectory() as t:
    v = os.path.join(t, "v")
    for d in ("archive", "cases", "releases"):
        os.makedirs(os.path.join(v, d))
    td = datetime.date.today()
    open(os.path.join(v, "cases", "c.md"), "w").write(f'---\ntype: "case"\ndate: "{td}"\nstatus: "open"\nkeys: "MH-9"\n---\n# C\n')
    open(os.path.join(v, "releases", "p.md"), "w").write(f'---\ntype: "review"\ndate: "{td}"\nstatus: "done"\nkeys: "MH-8"\n---\n# P\n')
    open(os.path.join(v, "releases", "g.md"), "w").write(f'---\ntype: "review"\ndate: "{td}"\nstatus: "live"\nkeys: "MH-7"\n---\n# G\n')
    json.dump({"layout": 5, "files": ["releases/g.md"]}, open(os.path.join(v, V.MANIFEST), "w"))
    check("the afterwards watch covers a case and a done note anywhere, never a generated live one",
          sorted(w["note"] for w in V.watched_notes(v, td)) == ["cases/c.md", "releases/p.md"])
    open(os.path.join(v, "releases", "s.md"), "w").write('---\ntype: "review"\nstatus: "done"\n---\n# S\n\nSee MH-7 and https://x.slack.com/archives/C1/p1793000000000009\n')
    check("a done note is stamped like an archived one", "releases/s.md" in V.stamp_archive(v, td, dry_run=True))
with tempfile.TemporaryDirectory() as t:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_tidy(types.SimpleNamespace(apply=True, json=False))
    check("tidy is retired with layout 5 and points to migrate", "migrate" in buf.getvalue())
# release lines (mh/releases/<line>/): the line from the title, else the first key's release label, else the root
L = {"MH-1": "2.1", "MH-2": None, "MH-5": "2.0"}.get
check("a release note is filed by the line its title names first, else its first key's label, else the root",
      H("readings/2026-11-02-promote-2-1-daily-wed-to-prod-3.md", {"type": "review", "title": "Promote MH 2.1 Wednesday to prod 3"}, L) == "releases/2.1"
      and H("readings/x-deploy-approvals.md", {"type": "review", "title": "Deploy approvals: MH 2.1 to prod 3, MH 2.0 hotfix to prod 8"}, L) == "releases/2.1"
      and H("readings/2026-10-28-mh-2-0-region-hotfix-review.md", {"type": "review", "title": "MH 2.0 hotfix: region"}, L) == "releases/2.0"
      and H("readings/2026-11-09-mh2-1-daily-wed-to-prod-3.md", {"type": "review", "title": "MH 2.1 · daily-wed → prod-3 · release note"}, L) == "releases/2.1"
      and H("to-read/2026-10-21-verify-mh-1.md", {"type": "verify", "title": "MH-1 · FAIL on prod-3", "keys": "MH-1"}, L) == "releases/2.1"
      and H("to-read/v.md", {"type": "verify", "title": "MH-5 · PASS", "keys": ["MH-5", "MH-1"]}, L) == "releases/2.0"
      and H("to-read/2026-10-29-verify-plan-mh-2.md", {"type": "verify-plan", "keys": "MH-2 MH-1"}, L) == "releases"
      and H("readings/x-promote.md", {"type": "review", "title": "Promote MediaHub 2.1.15 to prod"}, L) == "releases"
      and H("readings/2026-09-21-audio-mixer-mediabox.md", {"type": "review", "title": "Audio mixer on MediaBox"}, L) == "reference")
check("a line folder counts as its home: status, lint, folder",
      V.subject_home("releases/2.1") == "releases" and V.folder_of("releases/2.1/x.md") == "releases"
      and V.folder_of("mh/x.md") == "mh" and V.kept_home("releases/2.1") == "releases" and V.kept_home("mh") is None
      and V.type_lint("releases/2.1/x.md", "verify") is None and V.type_lint("releases/2.1/p.md", "plan") is None
      and V.type_lint("mh/p.md", "review") is not None and V.type_lint("mh/v.md", "verify") is not None)
with tempfile.TemporaryDirectory() as t:
    v, rep = os.path.join(t, "v"), os.path.join(t, "r")
    for d in ("releases/2.1", "archive"):
        os.makedirs(os.path.join(v, d))
    os.makedirs(rep)
    open(os.path.join(v, "releases/2.1", "2026-11-06-promote-y.md"), "w").write('---\ntype: "review"\ntitle: "Promote MH 2.1 build 85"\nstatus: "live"\n---\n# P\n')
    to = V.move_note(v, rep, "releases/2.1/2026-11-06-promote-y.md", "archive", next_="done")
    c = open(os.path.join(v, to)).read()
    row = [json.loads(l) for l in open(os.path.join(rep, "ela", "vault-removed.jsonl"))][-1]
    check("closing a release review marks it done in its line's folder, logged under releases",
          to == "releases/2.1/2026-11-06-promote-y.md" and 'status: "done"' in c and 'moves: "closed"' in c and row["home"] == "releases")
    td = datetime.date.today()
    open(os.path.join(v, "releases/2.1", "s.md"), "w").write(f'---\ntype: "review"\ndate: "{td}"\nstatus: "closed"\n---\n# S\n\nSee MH-7.\n')
    check("a note in a line folder is settled like one anywhere: closed reads as done, and a done note is stamped",
          any(x.startswith("releases/2.1/s.md: status closed → done") for x in V.settle_statuses(v, dry_run=True)))
    open(os.path.join(v, "releases/2.1", "record.md"), "w").write('---\ntype: "report"\nstatus: "decided"\n---\n# R\n')
    open(os.path.join(v, "releases/2.1", "plan.md"), "w").write('---\ntype: "plan"\nstatus: "draft"\n---\n# P\n')
    fixes = V.settle_statuses(v, dry_run=True)
    check("a line's record keeps its ruling; its test plan is a work note, live",
          not any(x.startswith("releases/2.1/record.md") for x in fixes) and any(x.startswith("releases/2.1/plan.md: status draft → live") for x in fixes))
base = V.VIEWS["all-notes"]
check("the all-notes base has a subject column and a Cases view; Done lists the archive and every done note",
      "subject: 'file.folder'" in base and "name: Cases" in base
      and base.split("name: Done", 1)[1].count("file.inFolder(") == 1 and 'status == "done"' in base.split("name: Done", 1)[1]
      and "formula.subject" in base.split("name: Done", 1)[1])

# the note standards: one spec per type, printed in the readme, linted one line per deviation, never a failure
check("every type ela or a session authors has a spec, and the readme prints each one",
      all(k in V.SPECS for k in ("decision", "plan", "sprint", "review", "ticket", "verify", "verify-plan", "case", "report",
                                  "project", "meeting", "day", "reader", "draft"))
      and all(f"### {k}" in V.spec_text() for k in V.SPECS) and V.SPEC_MARK in V.README and V.TYPE_FAMILY.get("draft") == "draft")
good = ('---\ntitle: "MH-1 · fixed, on QA"\naliases: ["MH-1 · fixed, on QA"]\ntype: "ticket"\ndate: "2026-11-09"\nkeys: "MH-1"\n---\n'
        "# [MH-1](https://j/browse/MH-1) · fixed, on QA\n\n## Next\n\nText about [MH-2](https://j/browse/MH-2).\n\n**Do.** Ask QA.\n")
check("a note that meets its spec has no lint line", V.spec_lint("reference/2026-11-09-mh-1-fixed.md", good) == [])
bad = ('---\ntitle: [MH-1](https://j/browse/MH-1): build 85 fixed\naliases: ["old"]\ntype: "ticket"\ndate: "2026-11-08"\n---\n'
       "# Something else\n\nMH-2 is bare; MH-035 is a test id.\n")
lines = V.spec_lint("reference/2026-11-09-mh-1-build-84.md", bad)
check("each deviation is one line: quoting, a link in the title, aliases, heading, date, name, required, Do, bare keys",
      all(any(x in l for l in lines) for x in ("title not quoted", "title carries a link", "not among the aliases",
                                                "first heading", "file name says", "missing keys", "the file name says 84",
                                                "no **Do.** line", "1 Jira key not linked (MH-2)")))
check("a generated note's keys are its renderer's, not linted", not any("not linked" in l for l in V.spec_lint("reference/2026-11-09-mh-1-build-84.md", bad, True)))
cn = '---\ntitle: "MH 2.0 hotfix：区域收窄"\naliases: ["MH 2.0 hotfix：区域收窄"]\ntype: "review"\ndate: "2026-10-28"\n---\n# MH 2.0 hotfix：区域收窄\n\n' + "这是中文正文内容。" * 40 + "\n"
check("a Chinese title or body is a lint line", "title not in English" in V.spec_lint("releases/2.0/2026-10-28-x-review.md", cn)
      and any(l.startswith("body not in English") for l in V.spec_lint("releases/2.0/2026-10-28-x-review.md", cn)))
long_ = '---\ntitle: "MH 2.1 · a → b · checks"\naliases: ["MH 2.1 · a → b · checks"]\ntype: "review"\ndate: "2026-11-09"\n---\n# MH 2.1 · a → b · checks\n\n' + "word " * 3000 + "\n"
check("a review over its budget is linted, never cut, and a done one needs no closing now",
      V.spec_lint("releases/2.1/2026-11-09-review-x.md", long_.replace('type: "review"', 'type: "review"\nstatus: "done"'))
      == ["3,005 words, budget 2,500 (lint only: nothing is cut)"])
check("a live review without its closing is linted", "no ## What you should do" in V.spec_lint("reference/2026-11-09-x.md", long_))
check("a type outside the specs and the closed set is named", V.spec_lint("to-read/x.md", '---\ntype: "memo"\n---\n# x\n') == ["type 'memo' has no spec"])
new, fixes = V.normalise(bad)
fl = V.split_front(new)[0]
check("normalise quotes the title, takes its links out, keeps the old spelling as an alias, and leaves the body",
      'title: "MH-1: build 85 fixed"' in fl and json.loads(next(l for l in fl if l.startswith("aliases:"))[8:])
      == ["MH-1: build 85 fixed", "old", "[MH-1](https://j/browse/MH-1): build 85 fixed"]
      and V.split_front(new)[1] == V.split_front(bad)[1] and fixes and V.normalise(new)[1] == [] and V.normalise(good) == (good, []))
body = "MH-1 and [MH-2](https://j/browse/MH-2), `MH-3`, [[mh-4-page]], WF-5 and MH-035.\n```\nMH-6\n```\n> [!note]- Slack\n> ~~~~\n> MH-7 ready to paste\n> ~~~~\n"
new_b, n = V.link_keys(body, "https://j", {"MH"})
check("link_keys links each bare key of a known project; code, links, other projects and test ids stay",
      n == 1 and new_b.startswith("[MH-1](https://j/browse/MH-1) and [MH-2](https://j/browse/MH-2), `MH-3`")
      and "WF-5" in new_b and "[MH-035]" not in new_b and "```\nMH-6\n```" in new_b and "> MH-7 ready" in new_b and V.link_keys(new_b, "https://j", {"MH"})[1] == 0)
fixed_g, fx = V.normalise(good.replace("Text about [MH-2](https://j/browse/MH-2)", "Text about MH-2"), "https://j", {"MH"})
check("lint --fix links bare keys and touches nothing else", fixed_g == good and fx == ["1 Jira key linked"])
blk = '---\ntitle: MH-9 · PASS on qa\naliases:\n  - MH-9 · PASS on qa\ntype: "verify"\n---\n\n# MH-9 · PASS on qa\n\nMH-9 body.\n'
nb, fx = V.normalise(blk, "https://j", {"MH"})
check("normalise rewrites a block list of aliases whole and keeps the body's blank lines",
      nb == '---\ntitle: "MH-9 · PASS on qa"\naliases: ["MH-9 · PASS on qa"]\ntype: "verify"\n---\n\n# [MH-9](https://j/browse/MH-9) · PASS on qa\n\n[MH-9](https://j/browse/MH-9) body.\n'
      and "aliases written as one list" in fx)
half = '---\ntitle: "MH-9 · PASS on qa"\naliases: ["MH-9 · PASS on qa"]\n  - MH-9 · PASS on qa\ntype: "verify"\n---\n\n# MH-9 · PASS on qa\n'
check("a list left half-rewritten is repaired into one", V.normalise(half)[0] == '---\ntitle: "MH-9 · PASS on qa"\naliases: ["MH-9 · PASS on qa"]\ntype: "verify"\n---\n\n# MH-9 · PASS on qa\n')
check("a reader page is headed by its title; what the old heading said stays beneath",
      V.reader_heading("# Reader · morning page of Fri 2026-11-06\n\nx\n", "2026-11-06") == "# The reader · 2026-11-06\n\n*Morning page of Fri 2026-11-06*\n\nx\n"
      and V.reader_heading("# The reader · 2026-11-06\n", "2026-11-06") == "# The reader · 2026-11-06\n")
zh = cn.replace('date: "2026-10-28"\n', 'date: "2026-10-28"\nlanguage: "zh"\n')
check("a note for a Chinese-speaking audience keeps its body's language and still wants an English title",
      "title not in English" in V.spec_lint("mh/releases/2.0/2026-10-28-x-review.md", zh)
      and not any(l.startswith("body not in English") for l in V.spec_lint("mh/releases/2.0/2026-10-28-x-review.md", zh))
      and "language" in V.PROPS and 'language: \\"zh\\"' not in V.spec_text() and '`language: "zh"`' in V.spec_text())
# release filing by name: the real names of mh/releases/2.1, the lane hop and mh<line> shapes included
REAL_21 = ["2026-10-27-release-2-1-cannot-evaluate", "2026-10-30-promote-2-1-qa-cn3-to-daily-wed",
           "2026-11-02-deploy-approvals-prod-3-and-prod-8", "2026-11-02-promote-2-1-daily-wed-to-prod-3",
           "2026-11-02-promote-2-1-qa-cn3-to-daily-wed", "2026-11-03-promote-wed-to-prod-3-docker-check",
           "2026-11-06-promote-2-1-build-85-to-daily-wed", "2026-11-09-mh2-1-daily-wed-to-prod-3"]
check("every release review name in mh/releases/2.1 reads as a release review by its name alone",
      all(V.RELEASE_NAME.search(n[11:]) for n in REAL_21))
check("a lane hop and an mh<line> name match; a lane named in passing does not",
      V.RELEASE_NAME.search("mh2-1-notes") and V.RELEASE_NAME.search("daily-wed-to-prod-3")
      and V.RELEASE_NAME.search("qa-cn3-to-daily-wed") and not V.RELEASE_NAME.search("risk-html-input-on-prod3")
      and not V.RELEASE_NAME.search("steps-to-production") and not V.RELEASE_NAME.search("audio-mixer-mediabox"))
# the names the desk gave the line's notes on 2026-11-10: the rule <date>-<kind>-<what>, the line left to the folder
NEW_21 = ["2026-10-27-review-cannot-evaluate", "2026-10-30-promote-qa-cn3-to-daily-wed", "2026-11-02-deploy-approvals-prod-3-prod-8",
          "2026-11-02-promote-daily-wed-to-prod-3", "2026-11-02-promote-qa-cn3-to-daily-wed", "2026-11-03-docker-daily-wed-to-prod-3",
          "2026-11-04-promote-qa-cn3-to-daily-wed-with-overlay", "2026-11-06-promote-build-85-to-daily-wed",
          "2026-11-09-deploy-daily-wed-to-prod-3"]
rn = '---\ntitle: "MH 2.1 · a → b · checks"\naliases: ["MH 2.1 · a → b · checks"]\ntype: "review"\ndate: "{d}"\n---\n# MH 2.1 · a → b · checks\n'
check("the new real names in releases/2.1 pass spec_lint with no name line",
      not [n for n in NEW_21 if any(l.startswith("file name") for l in V.spec_lint(f"releases/2.1/{n}.md", rn.format(d=n[:10])))])
check("an old real name writing the line (2-1, mh2-1) breaks the name rule in releases/2.1; in reference/ it does not",
      all(any(l.startswith("file name") for l in V.spec_lint(f"releases/2.1/{n}.md", rn.format(d=n[:10]))) for n in REAL_21
          if re.search(r"(?:^|-)(?:mh)?2-1-", n[11:]))
      and not any(l.startswith("file name") for l in V.spec_lint(f"reference/{REAL_21[-1]}.md", rn.format(d=REAL_21[-1][:10]))))
check("a release review's name is mended to the rule (migrate uses it); a name under it is left",
      V.release_review_name("2026-11-09-mh2-1-daily-wed-to-prod-3.md") == "2026-11-09-review-daily-wed-to-prod-3.md"
      and V.release_review_name("2026-11-02-promote-2-1-daily-wed-to-prod-3.md") == "2026-11-02-promote-daily-wed-to-prod-3.md"
      and V.release_review_name("2026-10-27-release-2-1-cannot-evaluate.md") == "2026-10-27-review-cannot-evaluate.md"
      and V.release_review_name("2026-11-09-deploy-daily-wed-to-prod-3.md") == "2026-11-09-deploy-daily-wed-to-prod-3.md")
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "releases/2.1")); os.makedirs(os.path.join(rep, "ela"))
    old = "2026-11-02-promote-daily-wed-to-prod-3"
    open(os.path.join(vlt, "releases/2.1", old + ".md"), "w").write('---\ntype: "review"\nstatus: "live"\n---\n# R\n')
    V.finish(vlt, rep, f"releases/2.1/{old}.md", "done")
    check("finish closes a release review where it is, under its own name", os.path.isfile(os.path.join(vlt, "releases/2.1", old + ".md"))
          and 'status: "done"' in open(os.path.join(vlt, "releases/2.1", old + ".md")).read())
check("a ticket number in a name is not a line", V.release_line({}, lambda k: None, "2026-10-29-verify-mh-1084-2") is None)
check("a review named mh2-1-…, untitled, is placed in releases/2.1 by the line its name writes",
      V.home_for("archive/2026-11-09-mh2-1-daily-wed-to-prod-3.md", {"type": "review"}, lambda k: None) == "releases/2.1"
      and V.home_for("archive/2026-11-02-promote-2-1-daily-wed-to-prod-3.md", {"type": "review"}, lambda k: None)
      == "releases/2.1")

# a kept note is the record: the sync never writes it, a later source change is an Afterwards line and a lint line
with tempfile.TemporaryDirectory() as t:
    vlt = os.path.join(t, "v"); os.makedirs(os.path.join(vlt, "releases/2.1"))
    open(os.path.join(vlt, "releases/2.1/d.md"), "w").write('---\ntype: "review"\nstatus: "done"\n---\n# D\n')
    open(os.path.join(vlt, "releases/2.1/l.md"), "w").write('---\ntype: "review"\nstatus: "live"\n---\n# L\n')
    check("kept is archive/, and a done note wherever it lives",
          V.is_kept("archive/x.md") and V.is_kept("releases/2.1/d.md", vlt) and not V.is_kept("releases/2.1/l.md", vlt)
          and not V.is_kept("releases/2.1/d.md") and V.kept_notes(vlt) == ["releases/2.1/d.md"])
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "releases/2.1")); os.makedirs(os.path.join(rep, "ela"))
    note = "releases/2.1/2026-11-09-mh2-1-x.md"
    body = '---\ntype: "review"\nstatus: "closed"\n---\n# X\n\n- [x] checked by him\n'
    open(os.path.join(vlt, note), "w").write(body)
    open(os.path.join(vlt, "releases/2.1/2026-11-08-y.md"), "w").write(body)
    src, src2 = os.path.join(rep, "ela", "2026-11-09-mh2.1-x.md"), os.path.join(rep, "ela", "2026-11-08-y.md")
    open(src, "w").write("# X, rewritten\n"); open(src2, "w").write("# Y\n")
    closed = datetime.datetime(2026, 11, 9, 14, 13, 32)
    os.utime(src, (closed.timestamp() + 98, closed.timestamp() + 98))          # written after the close
    os.utime(src2, (closed.timestamp() - 600, closed.timestamp() - 600))       # written before it
    with open(os.path.join(rep, "ela", "vault-removed.jsonl"), "w") as fh:
        for path, s_ in (("readings/2026-11-09-mh2-1-x.md", "ela/2026-11-09-mh2.1-x.md"),
                         ("readings/2026-11-08-y.md", "ela/2026-11-08-y.md")):
            fh.write(json.dumps({"at": closed.isoformat(timespec="seconds"), "path": path, "fate": "archived",
                                 "by": "owner", "src": s_}) + "\n")
    ch = V.source_changes(vlt, rep)
    check("a source written after its note closed is found; one written before is not",
          [c["note"] for c in ch] == [note] and ch[0]["src"] == "ela/2026-11-09-mh2.1-x.md")
    V.append_source_changes(vlt, rep, dry_run=True)
    check("a dry run leaves the kept note untouched", open(os.path.join(vlt, note)).read() == body)
    V.append_source_changes(vlt, rep)
    once = open(os.path.join(vlt, note)).read()
    V.append_source_changes(vlt, rep)
    twice = open(os.path.join(vlt, note)).read()
    check("the change is one dated line under Afterwards, his text and ticks kept, a second pass adds nothing",
          once.startswith(body.rstrip("\n")) and "## Afterwards" in once and once.count("ela/2026-11-09-mh2.1-x.md") == 1
          and "- [x] checked by him" in once and once == twice)
    check("the note closed before its source last changed is the only one touched",
          open(os.path.join(vlt, "releases/2.1/2026-11-08-y.md")).read() == body)
    inplace = '---\ntype: "review"\nstatus: "closed"\nsource: "vault"\n---\n# X\n\n- [x] checked by him\n'
    open(os.path.join(vlt, note), "w").write(inplace)
    check("a note written in place (source vault) reports no source change and gains no Afterwards line",
          V.source_changes(vlt, rep) == [] and V.append_source_changes(vlt, rep) == []
          and open(os.path.join(vlt, note)).read() == inplace)
# ela's own notes pass ela's lint (the record of 2026-11-11: 17 lint lines, several on notes ela wrote)
rec = '---\ntitle: "MediaHub 2.1 build 90 → QA-AWS3 · what changed"\naliases: ["MediaHub 2.1 build 90 → QA-AWS3 · what changed"]\ntype: "report"\n' \
      'date: "2026-11-10"\nsource: "vault"\nstatus: "decided"\n---\n# MediaHub 2.1 build 90 → QA-AWS3 · what changed\n\n| a | b |\n'
check("a release line's record and a build's release note owe no What you should do",
      not any("What you should do" in x for x in V.spec_lint("releases/2.1/2026-11-10-build-90-to-qa-aws3.md", rec))
      and not any("What you should do" in x for x in V.spec_lint("releases/2.1/release-2-1-record.md", rec.replace("2026-11-10", "2026-11-04"))))
check("a page's links to layout 4's lanes/ go to where layout 5 keeps the page",
      V.layout5_links("see [[lanes/docker|Docker candidates]] and [[lanes/test-list-qa-cn3|QA]]", {"qa-cn3": "2.1"})
      == "see [[releases/docker|Docker candidates]] and [[releases/2.1/test-list-qa-cn3|QA]]")
with tempfile.TemporaryDirectory() as rt:
    os.makedirs(os.path.join(rt, "ela")); os.makedirs(os.path.join(rt, "lanes"))
    open(os.path.join(rt, "ela", "2026-11-11-deep-MH-3993.md"), "w").write(
        "# [MH-3993](https://j/browse/MH-3993) · Graphics Insertion missing at 4K — no fix exists\n\n**Do.** hand it over.\n")
    open(os.path.join(rt, "lanes", "docker.md"), "w").write("# Docker candidates\n\n*2026-11-11*\n")
    got = {n.path: n for n in V.report_notes(rt, datetime.date(2026, 11, 11))}
    deep = next((n for p_, n in got.items() if p_.endswith("2026-11-11-deep-mh-3993.md")), None)
    page = V.front([], dict(deep.props, title=deep.title)) + deep.body if deep else ""
    check("the deep reading: a plain title among its aliases, its key set; the docker page placed in releases/",
          deep is not None and deep.title.startswith("MH-3993 · Graphics") and deep.props["keys"] == ["MH-3993"]
          and V.spec_lint("reference/2026-11-11-deep-mh-3993.md", page) == []
          and "releases/docker.md" in got and not V.type_lint("releases/docker.md", "docker"))

# a note of the vault's own gone without a verb keeps a trace: a row in the deletion log, with its backup copy
with tempfile.TemporaryDirectory() as t:
    vault, backup = os.path.join(t, "vault"), os.path.join(t, "backup", "vault")
    for root in (vault, backup):
        os.makedirs(os.path.join(root, "meetings")); os.makedirs(os.path.join(root, "archive"))
    note = '---\ntitle: "Scrum with the PM · Fri 2026-11-13"\ntype: "meeting"\nsource: "vault"\n---\n\n# Scrum with the PM\n'
    for f in ("scrum-pm.md", "moved.md", "logged.md"):
        open(os.path.join(backup, "meetings", f), "w").write(note)
    open(os.path.join(vault, "archive", "moved.md"), "w").write(note)    # moved by hand: a note of that name is still there
    gone = V.gone_by_hand(vault, None, set(), {"meetings/logged.md"}, backup)
    check("gone by hand: only the note gone without a verb, found against the backup on the first pass", gone == ["meetings/scrum-pm.md"])
    log = os.path.join(t, "removed.jsonl")
    V.record_gone(log, gone, datetime.datetime(2026, 11, 12, 10, 0))
    row = json.loads(open(log).read())
    check("its row says gone by hand and where the last copy is",
          row["fate"] == "gone by hand" and row["backup"] == "backup/reports:vault/meetings/scrum-pm.md" and "meetings/scrum-pm.md" in V.load_removed(log)[0])
    check("from then on the manifest's list is the record", V.gone_by_hand(vault, [], set(), set(), backup) == [])

# Afterwards names the ticket by key and title; one person's consecutive moves read first → last (desk, 2026-11-12)
woke = [{"ref": "MH-3873", "source": "jira", "kind": "status", "from": "Backlog", "to": "In Progress", "who": "Andyzhao", "at": "2026-11-11T10:00:00+08:00"},
        {"ref": "MH-3873", "source": "jira", "kind": "status", "from": "In Progress", "to": "Review", "who": "Andyzhao", "at": "2026-11-11T11:00:00+08:00"},
        {"ref": "MH-3873", "source": "jira", "kind": "comment", "who": "Andyzhao", "at": "2026-11-11T11:05:00+08:00"},
        {"ref": "MH-3891", "source": "jira", "kind": "status", "from": "Review", "to": "Done", "who": "Erin Zhang", "at": "2026-11-11T12:00:00+08:00"},
        {"ref": "MH-3891", "source": "jira", "kind": "status", "from": "Done", "to": "Reopened", "who": "Andyzhao", "at": "2026-11-11T13:00:00+08:00"}]
al = {ref: l for ref, _, l in V.afterwards_lines(woke, "https://j", {"MH-3873": {"summary": "BE: keep YouTube source LOADING until ready"}})}
check("an Afterwards line: the ticket with its title, one person's run collapsed",
      al["MH-3873"] == "- 11-11 · [MH-3873](https://j/browse/MH-3873) BE: keep YouTube source LOADING until ready: Backlog → Review (Andyzhao); a comment from Andyzhao")
check("moves by two people stay two; a ticket the store lacks keeps its key alone",
      al["MH-3891"] == "- 11-11 · [MH-3891](https://j/browse/MH-3891): Review → Done (Erin Zhang); Done → Reopened (Andyzhao)")

check("three keys with no words between them are a lint line, linked or not; two, or keys with words, are not",
      len(V.key_cluster_lint("x\n\nUR Caller: purpose ([MH-3998](u) [MH-3926](u) MH-3993)\n")) == 1
      and V.key_cluster_lint("MH-1 and MH-2\n- MH-3 title · Review\n- MH-4 title · Done\n- MH-5 x\n") == []
      and V.key_cluster_lint("MPEG-2 AC-3 H-264 codecs\n") == [])
check("the note standards carry the rule", "A key never stands alone" in V.spec_text())

lk = V.Linker({}, {}, "https://j", ["MH"])
check("a key with a leading zero is a customer's id, not a ticket: left unlinked inside a title",
      lk("MH-3891 [FloSports MH-030] Share profiles") == "[MH-3891](https://j/browse/MH-3891) [FloSports MH-030] Share profiles")

sys.exit(1 if failures else 0)
