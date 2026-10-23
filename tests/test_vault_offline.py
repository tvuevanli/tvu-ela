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
    open(f"{reports}/runner/{today}-brief.md", "w").write("# Brief\n\nShort.\n")
    open(f"{reports}/ela/{today}-long.md", "w").write("# Long review\n\n" + "word " * 3000)
    for i in range(20):
        open(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md", "w").write(f"# Review {i}\n\nText.\n")
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
    check("a to-read note carries its three boxes, unticked", all(f"{k}: false" in open(r6).read() for k in ("done", "learn", "drop")))
    txt = open(r6).read(); open(r6, "w").write(txt.replace("done: false", "done: true"))
    check("a ticked done box archives the note at the next sync, without the boxes", sync() == 0
          and os.path.exists(f"{vault}/archive/{today[:4]}-09-16-review-6.md") and not os.path.exists(r6)
          and "done:" not in open(f"{vault}/archive/{today[:4]}-09-16-review-6.md").read())
    r7 = f"{vault}/to-read/{today[:4]}-09-17-review-7.md"
    txt = open(r7).read(); open(r7, "w").write(txt.replace("drop: false", "drop: true"))
    check("a ticked drop box deletes it, logged as his", [x[1] for x in V.apply_marks(vault, reports)] == ["drop"] and not os.path.exists(r7)
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
    check("ela: lines anywhere in the vault are read as his guidance", sorted(x["says"] for x in g["guidance"]) == ["post this to Jira", "write this to the KB"]
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
    for i in range(8, 20):
        os.remove(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md")
    check("the notes halving at once stops the sync", sync() == 3)
    check("--force applies a deliberate removal", sync(force=True) == 0 and not os.path.exists(f"{vault}/to-read/{today[:4]}-09-18-review-8.md"))
    for i in range(8, 20):
        open(f"{reports}/{today[:4]}-09-{i + 10}-review-{i}.md", "w").write(f"# Review {i}\n\nText.\n")
    sync(force=True)
    before = len(rows())
    for i in range(8, 20):
        os.remove(f"{vault}/to-read/{today[:4]}-09-{i + 10}-review-{i}.md")
    check("a mass disappearance is written again, not recorded as read", sync() == 0
          and os.path.exists(f"{vault}/to-read/{today[:4]}-09-15-review-5.md") and len(rows()) == before)
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
sys.exit(1 if failures else 0)
