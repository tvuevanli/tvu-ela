#!/usr/bin/env python3
"""The vault as the work panel, offline (plan 2026-11-20): the watcher's stamp beside a line it took, a stamped line
never taken twice, a page he changed in the last ten minutes left to him, and Syncthing's conflict copies merged into
the live page and kept."""
import contextlib, io, json, os, sys, tempfile, time, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# ── the stamp ──────────────────────────────────────────────────────────────────────────────────────────────────
NOTE = "# Plan\n\n## Steps\n\n- one\nela: hold MH-4061 until 12-01\n\n- [x] Park it\n- [ ] Not now\n"
ids = V.line_ids("p.md", NOTE)
check("a line and a tick each get an id", [k for _, k, _ in ids] == ["line", "tick"])
hold_id, tick_id = ids[0][2], ids[1][2]
out, found = V.stamp_text("p.md", NOTE, hold_id, "✓ 10:42")
check("the stamp goes at the end of its line", "ela: hold MH-4061 until 12-01 ✓ 10:42\n" in out and found)
check("a stamped line keeps its id", [i for _, _, i in V.line_ids("p.md", out)] == [hold_id, tick_id])
again, _ = V.stamp_text("p.md", out, hold_id, "✓ 10:45")
check("a line keeps its first stamp", again == out)
out2, _ = V.stamp_text("p.md", out, tick_id, "queued 10:43")
check("a ticked box takes a stamp too", "- [x] Park it queued 10:43\n" in out2)
folded, _ = V.stamp_text("p.md", NOTE, hold_id, "✗ 10:42", "not held: nothing by that subject\nsecond line")
check("a longer result is a collapsed callout under the line, never open text",
      "ela: hold MH-4061 until 12-01 ✗ 10:42\n> [!note]- not held: nothing by that subject\n> second line\n" in folded)
check("an unknown id is not found", V.stamp_text("p.md", NOTE, "000000000000", "✓ 10:42") == (NOTE, False))
check("each stamp form is recognised", all(V.STAMP.search("ela: x " + m) for m in ("✓ 10:42", "✗ 9:05", "queued 13:00"))
      and not V.STAMP.search("ela: meet at 10:42"))
check("the parts of a merged apply box share the line's id", V.stamp_text("p.md", NOTE, hold_id + "-3", "✓ 10:42")[1])

ROWS = "## Board\n\n- MH-4061 10-bit through the switcher · Waiting\n  - [ ] up\n  ela: hold\n\n## Other\n\nela: down\n"
check("a bare verb acts on the row above it", V.row_at(ROWS, ROWS.index("ela: hold")) == "MH-4061 10-bit through the switcher · Waiting"
      and V.row_at(ROWS, ROWS.index("- [ ] up")) == V.row_at(ROWS, ROWS.index("ela: hold")))
check("a heading ends the search: no row", V.row_at(ROWS, ROWS.index("ela: down")) is None)

# ── guidance leaves a stamped line out ─────────────────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    vault, reports = os.path.join(d, "vault"), os.path.join(d, "reports")
    os.makedirs(os.path.join(vault, "ela")); os.makedirs(os.path.join(reports, "ela"))
    open(os.path.join(vault, "ela", "p.md"), "w").write(out2.replace("- [ ] Not now", "- [x] Not now"))
    site = os.path.join(d, "site.json"); json.dump({"vault": vault, "reports": reports}, open(site, "w"))
    V.SITE = site
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_guidance(types.SimpleNamespace(all=False, json=True))
    g = json.loads(buf.getvalue())["guidance"]
    check("guidance lists only what is not stamped", [x["says"] for x in g] == ["Not now"])
    check("guidance names the row a line sits under", g[0]["row"] == "one")
    with contextlib.redirect_stdout(io.StringIO()):
        V.cmd_stamp(types.SimpleNamespace(path="ela/p.md", id=g[0]["id"], mark=["✓", "10:50"], fold=None))
    check("the stamp verb writes the mark", "- [x] Not now ✓ 10:50" in open(os.path.join(vault, "ela", "p.md")).read())

# ── a page he is editing is his for ten minutes ────────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "today.md")
    open(p, "w").write("ela wrote this\n")
    mine = V.digest("ela wrote this\n")
    check("the page as the sync wrote it is not his edit", not V.his_recent_edit(p, mine))
    open(p, "w").write("ela wrote this\nela: hold MH-1\n")
    check("changed by him a moment ago: left to him", V.his_recent_edit(p, mine))
    check("changed eleven minutes ago: rewritten", not V.his_recent_edit(p, mine, now=time.time() + 660))
    check("no record yet: not taken for his edit", not V.his_recent_edit(p, None))
    V.atomic_write(p, "ela rewrote it in this run\n")
    check("ela's own write earlier in the same run is not his edit", not V.his_recent_edit(p, mine))

# ── a Syncthing conflict copy ──────────────────────────────────────────────────────────────────────────────────
LIVE = "---\ntitle: \"Sync\"\ntype: \"meeting\"\n---\n# Sync\n\n## Items\n\n- [ ] MH-1 raise\n- [ ] MH-2 raise\n\n## Notes\n\nfirst\n"
COPY = LIVE.replace("- [ ] MH-1 raise", "- [x] MH-1 raise").replace("first\n", "first\nela: drop MH-2\nmy own sentence\n") \
    + "- [x] a box only the copy has\n"
with tempfile.TemporaryDirectory() as vault:
    os.makedirs(os.path.join(vault, "meetings"))
    lp = os.path.join(vault, "meetings", "sync.md")
    cname = "sync.sync-conflict-20261117-104812-ABCDEFG.md"
    cp = os.path.join(vault, "meetings", cname)
    open(lp, "w").write(LIVE); open(cp, "w").write(COPY)
    check("a copy saved just now waits", V.merge_conflicts(vault, dry_run=True)[0].get("waits") == "saved just now")
    old = time.time() - 600
    for x in (lp, cp):
        os.utime(x, (old, old))
    r = V.merge_conflicts(vault)
    text = open(lp).read()
    check("his tick in the copy is ticked on the live page", "- [x] MH-1 raise" in text and "- [ ] MH-2 raise" in text)
    check("his ela: line is carried under the section it was written in",
          text.index("ela: drop MH-2") > text.index("## Notes"))
    check("a box the page lacks is written in", "- [x] a box only the copy has" in text)
    check("his prose is not carried but named in a fold that links the kept copy",
          "my own sentence" in text.split("[!note]-")[1] and "[[archive/sync-conflicts/" + cname[:-3] + "|the copy]]" in text
          and r[0]["left"] == ["my own sentence"])
    check("the copy is kept in archive/sync-conflicts/, never deleted",
          not os.path.exists(cp) and os.path.isfile(os.path.join(vault, "archive", "sync-conflicts", cname)))
    check("a merged copy is not merged again", V.merge_conflicts(vault) == [])
    # a generated page: the copy's other lines are ela's old text, not his
    open(cp, "w").write(COPY); os.utime(cp, (old, old)); os.utime(lp, (old, old))
    json.dump({"files": ["meetings/sync.md"], "native": []}, open(os.path.join(vault, V.MANIFEST), "w"))
    r = V.merge_conflicts(vault)
    check("on a generated page nothing but his word is named", r[0]["left"] == [] and r[0]["to"].endswith("-2.md"))

print(f"\n{len(failures)} failure(s)" if failures else "\nall ok")
sys.exit(1 if failures else 0)
