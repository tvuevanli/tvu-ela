#!/usr/bin/env python3
"""The vault, offline: names, links, redaction, the reading gate, and a whole sync against throwaway sources,
including the safety rules (a missing source, a folder that halves, removal only of files the sync wrote)."""
import datetime, json, os, subprocess, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

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
check("an empty ela: property is not read as the next line", [m.group(1) for m in V.GUIDE.finditer("ela:\n---\nela: go\n")] == ["go"])
check("a status run under the title becomes a subtitle", V.tidy_title("# brief · Fri            9 items\n\nText.") == "# Brief · Fri\n\n*9 items*\n\nText.")
check("a lowercase title is raised, ela is not", V.tidy_title("# code layout\n") == "# Code layout\n" and V.tidy_title("# ela review\n") == "# ela review\n")
check("a ::: block becomes a collapsed callout", V.callouts("::: ref Sources\na\n:::") == "> [!quote]- Sources\n> a")
check("a colon in a mermaid timeline period is caught", V.mermaid_problems("```mermaid\ntimeline\n  01:00 : Night\n```") != []
      and V.mermaid_problems("```mermaid\ntimeline\n  1 am : Night\n```\n```mermaid\nflowchart LR\n  a[\"01:00\"] --> b\n```") == [])
check("the warning sits under the title", V.with_warning("# T\n\nbody", ["too long"]).startswith("# T\n\n> [!warning]"))


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
    open(f"{reports}/runner/{today}-brief.md", "w").write("# Brief\n\n## Needs you\n\n### 1. A thing\n\n- [ ] apply 2 — ask QA\n- [ ] probe MH-1 from the replay\n- [x] already done upstream\n")
    open(f"{reports}/runner/{today}-changes.md", "w").write("# What changed\n\n## Code\n\nOne commit.\n")
    open(f"{reports}/ela/{today}-long.md", "w").write("# Long review\n\n" + "word " * 3000)
    for i in range(20):
        open(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md", "w").write(f"# Review {i}\n\nText.\n")
    BATCH = [f"{today[:4]}-08-{i + 10}-batch-{i}.md" for i in range(15)]   # bulk, for the halving and mass checks
    for f in BATCH:
        open(f"{reports}/{f}", "w").write("# Batch\n\nText.\n")
    open(f"{vault}/mine.md", "w").write("the owner's own file")
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
    check("with no constraints file the page says none is confirmed, and Home is silent",
          "No standing constraint has been confirmed yet" in open(f"{vault}/constraints.md").read()
          and "standing constraint" not in open(f"{vault}/home.md").read())
    stamp = {f: os.path.getmtime(os.path.join(dp, f)) for dp, _, fs in os.walk(vault) for f in fs if f.endswith(".md")}
    check("a second sync with nothing new writes nothing", sync() == 0 and
          all(os.path.getmtime(os.path.join(dp, f)) == stamp.get(f) for dp, _, fs in os.walk(vault) for f in fs if f.endswith(".md")))
    dec0 = f"{vault}/to-read/{today[:4]}-01-01-decision-0.md"
    check("a decision waiting for his ruling is in to-read", os.path.exists(dec0))
    check("one not written for him stays out", not os.path.exists(f"{vault}/to-read/{today[:4]}-01-02-internal.md"))
    check("one already ruled on stays out", not os.path.exists(f"{vault}/to-read/{today[:4]}-01-03-ruled.md"))
    check("a long review is written, under a warning", "[!warning]" in open(f"{vault}/to-read/{today}-long.md").read())
    home = open(f"{vault}/home.md").read()
    check("Home embeds today's page, the waiting and to-read views, and what ela owes", "![[days/" in home and "all-notes.base#To read" in home
          and "#Waiting for your word" in home and "ela owes a shorter version" in home)
    check("the changes page is a day page, linked from Home's Today", os.path.exists(f"{vault}/days/{today[:4]}/{today}-changes.md")
          and "→ What changed yesterday" in home)
    check("a decision carries its title as an alias and a meta line", 'aliases: ["Decision 0"]' in open(dec0).read() and "*decision · " in open(dec0).read())
    os.remove(dec0)
    check("a note the owner deleted is not written again", sync() == 0 and not os.path.exists(dec0))
    check("and it is recorded as deleted by him", any(r.get("fate") == "deleted" and r.get("by") == "owner" and r["path"].endswith("decision-0.md") for r in rows()))
    os.makedirs(f"{vault}/archive", exist_ok=True)
    os.rename(f"{vault}/to-read/{today[:4]}-09-10-review-0.md", f"{vault}/archive/{today[:4]}-09-10-review-0.md")
    check("a note he dragged into the archive is not written again", sync() == 0 and not os.path.exists(f"{vault}/to-read/{today[:4]}-09-10-review-0.md"))
    check("and stays in the archive, recorded as archived", os.path.exists(f"{vault}/archive/{today[:4]}-09-10-review-0.md")
          and any(r.get("fate") == "archived" and r["path"].endswith("review-0.md") for r in rows()))
    rv = f"{vault}/to-read/{today[:4]}-09-12-review-2.md"
    with open(rv, "a") as fh:
        fh.write("\nela: post this to Jira\n")
    check("his ela: line in a generated note survives its rewrite", sync() == 0 and "ela: post this to Jira" in open(rv).read())
    check("and a sync after that writes nothing more", (lambda m: sync() == 0 and os.path.getmtime(rv) == m)(os.path.getmtime(rv)))
    m = json.load(open(f"{vault}/{V.MANIFEST}"))
    m["seen"][f"to-read/{today[:4]}-09-13-review-3.md"] = "2000-01-01"
    json.dump(m, open(f"{vault}/{V.MANIFEST}", "w"))
    check("a review untouched for 30 days in the vault is archived by ela", sync() == 0
          and os.path.exists(f"{vault}/archive/{today[:4]}-09-13-review-3.md") and not os.path.exists(f"{vault}/to-read/{today[:4]}-09-13-review-3.md"))
    check("but one whose source is old and that just arrived stays", os.path.exists(f"{vault}/to-read/{today[:4]}-09-14-review-4.md"))
    V.cmd_finish(types.SimpleNamespace(path=f"to-read/{today[:4]}-09-14-review-4.md", to="archive"))
    check("finish moves a note into the archive on his word, logged as his", os.path.exists(f"{vault}/archive/{today[:4]}-09-14-review-4.md")
          and sync() == 0 and not os.path.exists(f"{vault}/to-read/{today[:4]}-09-14-review-4.md")
          and any(r.get("by") == "owner" and r.get("fate") == "archived" and r["path"].endswith("review-4.md") for r in rows()))
    try:
        V.cmd_finish(types.SimpleNamespace(path="home.md", to="delete")); refused = False
    except SystemExit:
        refused = True
    check("finish refuses a living page", refused and os.path.exists(f"{vault}/home.md"))
    r6 = f"{vault}/to-read/{today[:4]}-09-16-review-6.md"
    check("a to-read note carries an empty next field", 'next: ""' in open(r6).read() and "done:" not in open(r6).read())
    txt = open(r6).read(); open(r6, "w").write(txt.replace('next: ""', 'next: "done"'))
    a6 = f"{vault}/archive/{today[:4]}-09-16-review-6.md"
    check("next: done archives the note at the next sync, closed, the move kept in next", sync() == 0
          and os.path.exists(a6) and not os.path.exists(r6)
          and 'next: "done"' in open(a6).read() and 'status: "closed"' in open(a6).read() and 'moves: "closed"' in open(a6).read())
    r9 = f"{vault}/to-read/{today[:4]}-09-19-review-9.md"
    check("a note to read carries no ela property for the tables", "\nela:" not in open(r9).read().split("\n---", 1)[0])
    txt = open(r9).read(); open(r9, "w").write(txt.replace('next: ""', 'next: ""\nela: "1A, post it"'))
    check("a word typed in the old ela property stays, as a line in the note", sync() == 0
          and 'ela: "1A, post it"' in open(r9).read().split("\n---", 1)[1] and open(r9).read().count("1A, post it") == 1)
    bp = f"{vault}/days/{today[:4]}/{today}-brief.md"
    txt = open(bp).read(); open(bp, "w").write(txt.replace("- [ ] probe MH-1", "- [x] probe MH-1"))
    check("a choice he ticks stays ticked through the rewrite", sync() == 0 and "- [x] probe MH-1 from the replay" in open(bp).read()
          and "- [ ] apply 2" in open(bp).read())
    r7 = f"{vault}/to-read/{today[:4]}-09-17-review-7.md"
    txt = open(r7).read(); open(r7, "w").write(txt.replace('next: ""', "next: drop"))
    check("next: drop deletes it, logged as his", [x[1] for x in V.apply_marks(vault, reports)] == ["drop"] and not os.path.exists(r7)
          and any(r.get("fate") == "deleted" and r["path"].endswith("review-7.md") for r in rows()))
    os.makedirs(f"{vault}/to-learn", exist_ok=True)
    os.rename(f"{vault}/to-read/{today[:4]}-09-11-review-1.md", f"{vault}/to-learn/{today[:4]}-09-11-review-1.md")
    with open(f"{vault}/to-learn/{today[:4]}-09-11-review-1.md", "a") as fh:
        fh.write("\n- ela: write this to the KB\n")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_guidance(types.SimpleNamespace(all=False, json=True))
    g = json.loads(buf.getvalue())
    check("ela: lines anywhere in the vault are read as his guidance", sorted(x["says"] for x in g["guidance"]) == ["1A, post it", "post this to Jira", "probe MH-1 from the replay", "write this to the KB"]
          and len(g["to_learn"]) == 1)
    check("a note he dragged into to-learn is recorded so and left there", sync() == 0
          and os.path.exists(f"{vault}/to-learn/{today[:4]}-09-11-review-1.md") and not os.path.exists(f"{vault}/to-read/{today[:4]}-09-11-review-1.md")
          and any(r.get("fate") == "to-learn" and r["path"].endswith("review-1.md") for r in rows()))
    p1 = f"{ELAK}/blueprint/decisions/{today[:4]}-02-01-decision-1.md"
    open(p1, "w").write(open(p1).read().replace("status: proposed", "status: decided"))
    git("add", "-A"); git(SAVE, "-qm", "ruled")
    check("a decision he ruled on is archived by ela", sync() == 0 and os.path.exists(f"{vault}/archive/{today[:4]}-02-01-decision-1.md")
          and not os.path.exists(f"{vault}/to-read/{today[:4]}-02-01-decision-1.md")
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
    check("--force applies a deliberate removal", sync(force=True) == 0 and not os.path.exists(f"{vault}/to-read/{today[:4]}-09-28-review-18.md"))
    for i in range(10, 20):
        open(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md", "w").write(f"# Review {i}\n\nText.\n")
    for f in BATCH:
        open(f"{reports}/{f}", "w").write("# Batch\n\nText.\n")
    sync(force=True)
    before = len(rows())
    for i in range(10, 20):
        os.remove(f"{vault}/to-read/{today[:4]}-09-{i + 10}-review-{i}.md")
    check("a mass disappearance is written again, not recorded as read", sync() == 0
          and os.path.exists(f"{vault}/to-read/{today[:4]}-09-25-review-15.md") and len(rows()) == before)
    check("a file the sync never wrote is never removed", os.path.exists(f"{vault}/mine.md"))
    os.makedirs(f"{vault}/library", exist_ok=True)
    native = f"{vault}/library/topic-a.md"
    open(native, "w").write('---\ntitle: "Topic A"\ntype: "topic"\nsource: "vault"\n---\n\n# Topic A\n\nIt stands well.\n')
    check("a sync with a native topic succeeds", sync(force=True) == 0)
    check("a native note is never overwritten", "It stands well." in open(native).read())
    check("the library index lists it", "Topic A" in open(f"{vault}/library/library.md").read())
    check("a native note stays out of the manifest", "library/topic-a.md" not in open(f"{vault}/{V.MANIFEST}").read())
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
page = V.with_moves("# Plan\n\nbody\n", "to-read/p.md", "plan")
check("a plan ends in what each of its boxes does", "- **agree**: ela builds it" in page and "- **reject**: archived as rejected" in page
      and "- **drop**: deleted" in page and "- [ ]" not in page and page.rstrip().endswith("`to-read/p.md`.*"))
check("next moves are replaced, not repeated", V.with_moves(page, "to-read/p.md", "plan").count(V.MOVES_HEAD) == 1)
built = V.with_moves(page, "in-progress/p.md", "built", "10-26 15:20")
check("a built note explains accept and not-done, not the to-read boxes", "- **accept**" in built and "- **not-done**" in built and "**drop**" not in built)
check("a kind without moves gets none", V.MOVES_HEAD not in V.with_moves(page, "x.md", "day"))
prog = V.progress_line(page, "step one")
check("progress goes above the next moves", prog.index("## Progress") < prog.index(V.MOVES_HEAD) and "· step one" in prog)
check("a second progress line joins the first", V.progress_line(prog, "step two").count("## Progress") == 1)
check("front matter keys are set and removed", V.set_front('---\ntype: "plan"\nclaimed: "x"\n---\nbody', status="built", claimed=None)
      == '---\ntype: "plan"\nstatus: "built"\n---\nbody')
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "to-read")); os.makedirs(rep)
    open(os.path.join(vlt, "to-read", "p.md"), "w").write('---\ntype: "plan"\nstatus: "proposed"\ndone: false\n---\n' + page)
    to = V.move_note(vlt, rep, "to-read/p.md", "in-progress", "in progress")
    moved = open(os.path.join(vlt, to)).read()
    check("an agreed note moves to in-progress as the vault's own page", to == "in-progress/p.md" and 'source: "vault"' in moved
          and 'status: "building"' in moved and 'moves: "built"' in moved and "done:" not in moved and V.MOVES_HEAD not in moved)
    check("the move is logged as his", '"fate": "in-progress"' in open(os.path.join(rep, "ela", "vault-removed.jsonl")).read())
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "to-read")); os.makedirs(rep)
    open(os.path.join(vlt, "to-read", "a.md"), "w").write('---\ntype: "plan"\nagree: true\ndone: false\n---\n# A\n')
    got = V.apply_marks(vlt, rep)
    check("a ticked agree box is reported for the runner and left in place", got == [("to-read/a.md", "agree")]
          and os.path.exists(os.path.join(vlt, "to-read", "a.md")))
    os.makedirs(os.path.join(vlt, "in-progress"))
    open(os.path.join(vlt, "in-progress", "b.md"), "w").write('---\ntype: "plan"\nstatus: "built"\naccept: true\n---\n# B\n')
    check("a ticked accept box on a built note is reported too", ("in-progress/b.md", "accept") in V.apply_marks(vlt, rep, dry_run=True))
    open(os.path.join(vlt, "to-read", "n.md"), "w").write('---\ntype: "plan"\nsource: "vault"\n---\n# N\n\n## Next moves\n\n- [ ] Agree, build it\n')
    V.ensure_native_moves(vlt)
    n = open(os.path.join(vlt, "to-read", "n.md")).read()
    check("a plan written in the vault gains its next field, its section kept once", 'next: ""' in n and n.count(V.MOVES_HEAD) == 1)
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "to-read")); os.makedirs(rep)
    two = os.path.join(vlt, "to-read", "two.md")
    open(two, "w").write('---\ntype: "review"\nnext: "agree"\n---\n# Two\n\nbody\n')
    check("a move the note does not offer runs nothing", V.apply_marks(vlt, rep) == [] and os.path.exists(two))
    w = open(two).read()
    check("the note names the value and its choices, once", w.count(V.MOVE_WARN) == 1 and "`agree`" in w and "make-plan" in w)
    V.apply_marks(vlt, rep)
    check("the warning is not repeated", open(two).read().count(V.MOVE_WARN) == 1)
    open(two, "w").write(w.replace('next: "agree"', 'next: "make-plan"'))
    check("a move it offers runs", V.apply_marks(vlt, rep, dry_run=True) == [("to-read/two.md", "make-plan")])
    open(two, "w").write(open(two).read().replace('next: "make-plan"', 'next: "noted"'))

with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "to-read")); os.makedirs(rep)
    open(os.path.join(vlt, "to-read", "q.md"), "w").write('---\ntype: "plan"\nmoves: "plan"\nnext: "park"\n---\n# Q\n\nbody\n\n## Next moves\n\n- **agree**: x\n')
    check("a plan offers park, and park is the runner's", V.apply_marks(vlt, rep, dry_run=True) == [("to-read/q.md", "park")])
    to = V.move_note(vlt, rep, "to-read/q.md", "parked", waits_on="the Pack team, in its thread", wake="FB-1 moving")
    q = open(os.path.join(vlt, to)).read()
    check("a parked note says who it waits on, since when and what wakes it, and offers resume and drop only",
          to == "parked/q.md" and 'status: "parked"' in q and 'waits-on: "the Pack team, in its thread"' in q and 'wake: "FB-1 moving"' in q
          and 'parked: "' in q and 'moves: "parked"' in q and "**resume**" in q and "**drop**" in q and "**agree**" not in q
          and "**done**" not in q)
    check("the move to parked is logged as his", '"fate": "parked"' in open(os.path.join(rep, "ela", "vault-removed.jsonl")).read())
    hm = V.home(datetime.date(2026, 10, 27), datetime.datetime(2026, 10, 27, 9), [V.Note("parked/q.md", "Q", "# Q", {"type": "plan", "date": "2026-10-27"})])
    check("Home shows the Parked view when a note is parked", "## Parked" in hm and "all-notes.base#Parked]]" in hm)
    check("and no Parked block without one", "## Parked" not in V.home(datetime.date(2026, 10, 27), datetime.datetime(2026, 10, 27, 9), []))
    open(os.path.join(vlt, "parked", "h.md"), "w").write('---\ntype: "plan"\nstatus: "parked"\nwake: "FB-2"\n---\n# H\n\nhis body\n')
    V.ensure_native_moves(vlt)
    h = open(os.path.join(vlt, "parked", "h.md")).read()
    check("a note parked by hand gains its chooser fields, its body untouched", 'moves: "parked"' in h and 'next: ""' in h and h.endswith("# H\n\nhis body\n"))
    open(os.path.join(vlt, "parked", "h.md"), "w").write(h.replace('next: ""', 'next: "agree"'))
    check("a parked note runs only resume or drop", V.apply_marks(vlt, rep) == [])
    open(os.path.join(vlt, "parked", "q.md"), "w").write(q.replace('next: ""', 'next: "resume"'))
    V.apply_marks(vlt, rep)
    r = open(os.path.join(vlt, "to-read", "q.md")).read()
    check("resume brings it back to to-read as proposed, its parked fields gone",
          'status: "proposed"' in V.split_front(r)[0] and not any(l.startswith(("wake:", "waits-on:", "parked:")) for l in V.split_front(r)[0])
          and "**agree**" in r
          and not os.path.exists(os.path.join(vlt, "parked", "q.md")))
    check("the parked moves are a set of their own", V.move_props("parked", in_to_read=False) == ["resume", "drop"] and V.move_set("parked") == "parked")

S = V.settled_status
check("each lifecycle folder settles its status", S("in-progress", "in progress") == ("building", None, None)
      and S("in-progress", "waiting") == ("waiting", None, None) and S("parked", "proposed") == ("parked", None, None)
      and S("to-read", "decided") == ("proposed", None, None) and S("to-read", "active") == ("proposed", None, None)
      and S("to-read", None) == (None, None, None) and S("to-read", "blocked") == ("blocked", None, None))
check("an archived outcome moves to next", S("archive", "accepted") == ("closed", None, "accept") and S("archive", "planned") == ("closed", None, "make-plan")
      and S("archive", "not now") == ("closed", None, "not-now"))
check("a verdict is a result: a fail waits on his word, a pass is read", S("to-read", "fail", "verify") == ("proposed", "fail", None)
      and S("to-read", "pass", "verify") == (None, "pass", None) and S("archive", "pass", "verify") == ("closed", "pass", None))
check("a sprint keeps its own status; a library page carries none", S("sprints", "active") == ("active", None, None) and S("library", "decided") == (None, None, None))
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "library"))
    open(os.path.join(t, "library", "l.md"), "w").write('---\ntype: "design"\nstatus: "decided"\nsource: "vault"\n---\n# L\n')
    check("sync takes status off a library page", len(V.settle_statuses(t)) == 1 and "status:" not in open(os.path.join(t, "library", "l.md")).read())
with tempfile.TemporaryDirectory() as t:
    vlt, rep = os.path.join(t, "v"), os.path.join(t, "r")
    os.makedirs(os.path.join(vlt, "to-read")); os.makedirs(rep)
    open(os.path.join(vlt, "to-read", "r.md"), "w").write('---\ntype: "review"\n---\n# R\n')
    to = V.move_note(vlt, rep, "to-read/r.md", "archive", "in a session", next_="make-plan")
    r = open(os.path.join(vlt, to)).read()
    check("a move into archive with --next keeps that word as next, status closed", 'next: "make-plan"' in r and 'status: "closed"' in r)
check("the statuses are seven", V.STATUSES == ("proposed", "blocked", "building", "built", "waiting", "parked", "closed"))
with tempfile.TemporaryDirectory() as t:
    for d in ("archive", "in-progress", "sprints"):
        os.makedirs(os.path.join(t, d))
    open(os.path.join(t, "archive", "a.md"), "w").write('---\ntype: "plan"\nstatus: "accepted"\n---\n# A\n\nhis body\n')
    open(os.path.join(t, "archive", "v.md"), "w").write('---\ntype: verify\nstatus: pass\n---\n# V\n')
    open(os.path.join(t, "in-progress", "b.md"), "w").write('---\ntype: "plan"\nstatus: "in-progress"\n---\n# B\n')
    open(os.path.join(t, "sprints", "s.md"), "w").write('---\ntype: "sprint"\nstatus: "active"\n---\n# S\n')
    fixes = V.settle_statuses(t)
    a = open(os.path.join(t, "archive", "a.md")).read()
    check("sync settles a native note's front matter, one line per fix, its body untouched", len(fixes) == 3
          and 'status: "closed"' in a and 'next: "accept"' in a and 'moves: "closed"' in a and a.endswith("# A\n\nhis body\n")
          and 'result: "pass"' in open(os.path.join(t, "archive", "v.md")).read()
          and 'status: "building"' in open(os.path.join(t, "in-progress", "b.md")).read()
          and 'status: "active"' in open(os.path.join(t, "sprints", "s.md")).read())
    check("a second pass has nothing to fix", V.settle_statuses(t) == [])
    V.write_move_sets(t)
    ms = {n: open(os.path.join(t, "ela", "moves", n + ".md")).read() for n in ("plan", "built", "parked", "closed")}
    check("each move set lists only its folder's statuses", "proposed" in ms["plan"] and "building" not in ms["plan"]
          and "waiting" in ms["built"] and "accept" in ms["built"] and "name: next" not in ms["closed"] and "closed" in ms["closed"]
          and "- name: status" in ms["parked"] and "proposed" not in ms["parked"])

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
bp = V.Note("days/2026/2026-10-28-brief.md", "Morning brief", "# B\n\n## Needs you\n\n### 1. x\n\n## The lanes this morning\n\n| | prod-3 |\n|---|---|\n\n"
            "## Sprint\n\nSprint · day 3 of 10 · 8 on track · 1 at risk · 0 off\n\n| item |\n", {"type": "day", "kind": "brief", "date": "2026-10-28"})
sp = V.Note("sprints/s.md", "Sprint 1", "# S", {"type": "sprint", "status": "active", "date": "2026-10-26"})
hm = V.home(day, datetime.datetime(2026, 10, 28, 9), [bp, sp])
check("Home embeds the page's lanes table beside Needs you", "#The lanes this morning]]" in hm and hm.index("#Needs you]]") < hm.index("#The lanes this morning]]"))
check("Home shows the page's sprint line, linked to its table, instead of the bare sprint link",
      "[[days/2026/2026-10-28-brief#Sprint|Sprint · day 3 of 10 · 8 on track · 1 at risk · 0 off]]" in hm and "[[sprints/s|Sprint 1]]" not in hm)
sys.exit(1 if failures else 0)
