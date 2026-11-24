#!/usr/bin/env python3
"""ela learns from its own writes, offline, on a temp reports root (decision 2026-11-24, amendment on learning from
ela's own writes): his `ok` and `wrong: <why>` beside a line of did.md are read once each into the dry record before the
page is rewritten, and shown again beside the line; `wrong` returns the class to confirm and, with a why, admits the
case to the corpus; a dry-run vault pass reads but records nothing; the improve digest groups the day's misses per class
by cause; an improve item carrying a corpus case waits for his letter, and A admits it. Nothing reaches Jira."""
import datetime, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("dry", "vault", "improve"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import dry as D  # noqa: E402
import vault as V  # noqa: E402
import improve as I  # noqa: E402

RT = tempfile.TemporaryDirectory()
D.site = lambda: {"runtime": RT.name}

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

NOW = datetime.datetime.now(D.TZ).replace(microsecond=0)  # the vault pass stamps his marks with the real clock
DAY = NOW.date()
D_ = DAY.isoformat()
OK = lambda c, a: (0, "")

# ---- the parser -------------------------------------------------------------------------------------------------------
page = f"""# Done by ela

- {D_}-board-watch-MH-1#1. MH-1: assigned to its owner · `ela dry undo {D_}-board-watch-MH-1#1 --apply` ok
- {D_}-board-watch-MH-2#1. MH-2: link MH-2 contains SCTE-35 · `ela dry undo {D_}-board-watch-MH-2#1 --apply` — wrong: SCTE-35 is the standard, not a ticket
- {D_}-board-watch-MH-3#1. MH-3: comment · `ela dry undo {D_}-board-watch-MH-3#1 --apply`
    wrong
- 4. something the runner did · `ela: undo 4`
"""
marks = dict((i, (m, w)) for i, m, w in D.did_marks(page))
check("ok beside the undo word is read", marks.get(f"{D_}-board-watch-MH-1#1") == ("ok", None))
check("wrong: <why> keeps the why", marks.get(f"{D_}-board-watch-MH-2#1") == ("wrong", "SCTE-35 is the standard, not a ticket"))
check("a mark on the indented line under it counts; no why is None", marks.get(f"{D_}-board-watch-MH-3#1") == ("wrong", None))
check("an unmarked line yields nothing", "4" not in marks)

# ---- recording, through the vault page ----------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    R, VT = os.path.join(tmp, "reports"), os.path.join(tmp, "vault")
    os.makedirs(os.path.join(VT, "ela", "dry"))
    for key in ("MH-1", "MH-2", "MH-3"):
        cmd = f"ela jira comment {key} --from-file /tmp/x.md"
        D.act(R, "board-watch", key, [{"target": key, "command": cmd, "why": f"{key}: signed comment"}], DAY, apply=True, runner=OK, now=NOW)
    check("the class starts at tier 1 by decision", D.load_state(R)["board-watch"]["tier"] == 1)
    did_path = os.path.join(VT, "ela", "dry", "did.md")
    open(did_path, "w").write(f'---\ntype: "dry"\ndate: "{D_}"\n---\n' + page)

    V.dry_pages(VT, R, DAY, record=False)
    check("a dry-run pass records nothing", not [r for r in D.record(R) if r.get("review")])

    out = V.dry_pages(VT, R, DAY)["ela/dry/did.md"]
    rows = [r for r in D.record(R) if r.get("review")]
    check("one row per mark: ok confirmed, two wrongs corrected",
          sorted(r["verdict"] for r in rows) == ["confirmed", "corrected", "corrected"])
    check("wrong returns the class to confirm", D.load_state(R)["board-watch"]["tier"] == 3)
    check("the rewritten page shows each mark beside its line",
          f"- {D_}-board-watch-MH-1#1. MH-1: MH-1: signed comment · `no reverse atom: undo it on the ticket` — ok" in out
          and "— wrong: SCTE-35 is the standard, not a ticket" in out and "— wrong: (no cause given)" in out)
    check("the page says what the marks do", "`wrong: <why>`" in out and "corpus" in out)

    open(did_path, "w").write(out)
    V.dry_pages(VT, R, DAY)
    check("a mark is recorded once, however many passes read it", len([r for r in D.record(R) if r.get("review")]) == 3)

    cases = D.corpus_cases(R)
    check("only a wrong with a why is admitted to the corpus",
          [(c["class"], c["cause"]) for c in cases] == [("board-watch", "SCTE-35 is the standard, not a ticket")])

    # ---- improve: the day's misses grouped by cause, and a corpus case on his word ------------------------------------------
    for t in ("SCTE-35", "MH-2026"):
        D.append(R, {"at": NOW.isoformat(), "class": "link-named", "verdict": "cancelled", "letter": "B", "target": t,
                     "command": f"ela jira link MH-3997 {t} --type contains", "batch": f"{D_}-link-named-MH-3997", "source": "batch"})
    m = I.dry_misses(R, DAY.isoformat())
    by = {(g["class"], g["cause"]): g for g in m["groups"]}
    check("cancels with no reason group as one cause per class", len(by[("link-named", "no cause given")]["today"]) == 2)
    check("a why he gave is its own group", ("board-watch", "SCTE-35 is the standard, not a ticket") in by)
    check("the digest carries the misses", I.digest(DAY.isoformat(), R, os.path.join(tmp, "rt"), os.path.join(tmp, "mh"),
                                                    transcripts=os.path.join(tmp, "none"))["dry"]["groups"] == m["groups"])

    item = {"area": "ela", "problem": "link-named proposes a broadcast standard as a ticket", "evidence": [f"batch {D_}-link-named-MH-3997"],
            "fix": "a standards denylist in the selector", "who": "ela",
            "corpus": {"class": "link-named", "target": "SCTE-35", "command": "ela jira link MH-3997 SCTE-35 --type contains",
                       "cause": "SCTE-35 is the standard named in prose"}}
    check("a corpus case without its cause is refused", I.check([dict(item, corpus={"class": "link-named", "target": "SCTE-35"})], {}) != [])
    [iid] = I.add(R, [item], DAY.isoformat())
    rec = I.load(R)[iid]
    check("an item carrying a corpus case waits for his word", rec["who"] == "owner" and rec["state"] == "open" and rec["corpus"]["admitted"] is False)
    check("it is not in the corpus before he answers", [c["source"] for c in I.corpus(R)] == ["did.md"])
    check("and it is an ask on today.md", [a["id"] for a in I.asks(R)] == [f"improve:{iid}"])
    I.answer(R, iid, "A", DAY)
    check("A admits the case", sorted(c["source"] for c in I.corpus(R)) == ["did.md", f"improve:{iid}"])

if failures:
    print(f"\n{len(failures)} failed"); sys.exit(1)
print("\nall passed")
