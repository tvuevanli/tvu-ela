#!/usr/bin/env python3
"""ela teamreport, offline: the day's data from a fact store, a past day found by its changelog, the quiet and
incomplete stubs, the checks on a narrative, the published file and the side-by-side note with Helm's report."""
import datetime, io, json, os, sys, tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="teamreport-")
os.environ["ELA_FACTS_RUNTIME"] = os.path.join(TMP, "runtime")
os.environ["ELA_TEAMREPORT_PUBLISHED"] = os.path.join(TMP, "published")
sys.path.insert(0, os.path.join(ROOT, "skills", "teamreport"))
import teamreport as TR  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

TZ = datetime.datetime.now().astimezone().tzinfo
DAY = "2026-11-24"
NOW = datetime.datetime(2026, 11, 24, 22, 0, tzinfo=TZ)
def at(h, m=0, day=24):
    return datetime.datetime(2026, 11, day, h, m, tzinfo=TZ)
def jt(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.000%z")

TR.roster = lambda: ({"U1": "Dev One", "U2": "QA Two"}, {"qa@example.com": "QA Two", "dev@example.com": "Dev One"},
                     [("app", ["Dev One"]), ("qa", ["QA Two"])])
TR.F.now = lambda: NOW


def put(rel, obj):
    p = os.path.join(os.environ["ELA_FACTS_RUNTIME"], "facts", rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p, "w"))


def issue(key, summary, created, updated, status="In Progress", histories=(), comments=()):
    return {"key": key, "fields": {"summary": summary, "status": {"name": status}, "priority": {"name": "High"},
                                   "assignee": {"displayName": "Dev One"}, "created": jt(created), "updated": jt(updated)},
            "changelog": {"histories": [{"created": jt(t), "items": [{"field": "status", "toString": to}]} for t, to in histories]},
            "comments": [{"created": jt(t)} for t in comments]}


put("jira/changes.json", [
    issue("MH-10", "SRT model rebuild", at(9, day=20), at(15)),                                   # moved today
    issue("MH-11", "New HDR setting [UI]", at(10), at(11)),                                      # created today
    issue("MH-12", "Old fix, moved again since", at(9, day=10), at(2, day=25), status="Done", histories=[(at(14), "Done")]),                                          # updated after the day; its history says today
    issue("MH-13", "Untouched", at(9, day=12), at(9, day=21)),
    issue("UR-5", "Another project", at(9), at(10)),
])
put("jira/watermark.json", {"at": NOW.isoformat()})
put("jira/queries/board-state.json", {"at": NOW.isoformat(), "issues": [
    {"key": "MH-20", "fields": {"summary": "Collector crashes", "status": {"name": "Blocked"}, "assignee": {"displayName": "Dev One"},
                                "priority": {"name": "High"}, "updated": jt(NOW - datetime.timedelta(days=70))}},
    {"key": "MH-10", "fields": {"summary": "SRT model rebuild", "status": {"name": "In Progress"}, "assignee": {"displayName": "Dev One"},
                                "priority": {"name": "High"}, "updated": jt(at(15))}}]})
ts = lambda t: f"{t.timestamp():.6f}"  # noqa: E731
put("slack/channels.json", {"channels": [{"id": "CPRJ", "name": "prj_dev_mediahub"}, {"id": "COTH", "name": "general"}]})
put("slack/users.json", {"users": {"U3": {"name": "outsider"}}})
put("slack/watermark.json", {"at": NOW.isoformat()})
root = ts(at(10))
put("slack/CPRJ.json", {"messages": {root: {"user": "U1", "ts": root, "text": "Customer escalation on preview, see MH-10"},
                                     ts(at(11)): {"user": "UB", "ts": ts(at(11)), "bot_id": "B1", "text": "a bot"},
                                     ts(at(9, day=23)): {"user": "U1", "ts": ts(at(9, day=23)), "text": "yesterday"}},
                        "replies": {root: {"messages": [{"user": "U1", "ts": root, "text": "parent again"},
                                                        {"user": "U2", "ts": ts(at(12)), "thread_ts": root, "text": "QA reproduced it"}]}}})
put("slack/COTH.json", {"messages": {ts(at(13)): {"user": "U3", "ts": ts(at(13)), "text": "lunch?"}}, "replies": {}})
put("mail/watermark.json", {"at": NOW.isoformat()})
put("mail/index.json", {"release": {"ids": ["m1", "m2"]}, "test-report": {"ids": ["m3"]}, "team": {"ids": ["m3", "m4", "m5"]}})
def mail(mid, subject, frm, t, body="body"):
    put(f"mail/messages/{mid}.json", {"id": mid, "subject": subject, "from": frm, "date": "x", "internal_date": int(t.timestamp()), "body": body})
mail("m1", "[Release Mediahub QA-AWS3] For 2.1 Release build 100", "Dev One <dev@example.com>", at(9), "fixes MH-11")
mail("m2", "[Release PP-PROD2] Producer release backend v2.2.508", "Someone <someone@example.com>", at(10))
mail("m3", "Summary Test Report for MeshAdapter Module v1.0.14", "QA Two <qa@example.com>", at(18), "55 cases, 45 pass")
mail("m4", "[copier docker.tvunetworks.com/x/copier:1.0.80]", "Dev One <dev@example.com>", at(16), "optimize interleave")
mail("m5", "Release notes", "Dev One <dev@example.com>", at(9, day=22))

# ── the day's input ──────────────────────────────────────────────────────────────────────────────────
inp = TR.daily_input(DAY, NOW)
check("a day with activity needs the model", inp["state"] == "ok" and inp["prompt"])
p = inp["prompt"]
check("the day's MH tickets: moved, created, and a past move found in the changelog", all(f"[{k}]" in p for k in ("MH-10", "MH-11", "MH-12")))
check("an untouched ticket and another project are left out", "[MH-13]" not in p and "[UR-5]" not in p)
check("Blocked comes from the standing query, with its age", "[MH-20] Collector crashes" in p and "blocked for=70d" in p)
check("human Slack posts and replies inside the day, with the parent", "Customer escalation on preview" in p and "QA reproduced it" in p
      and 'replying to "Customer escalation' in p and "a bot" not in p and "yesterday" not in p)
check("Slack authors resolve through the roster, else the store's names", "@QA Two" in p and "@outsider" in p)
check("the project channel is its own section", "## Project channel — #prj_dev_mediahub" in p)
check("an env deployment is marked as Helm's block", "[release/QA — Helm's block" in p and "For 2.1 Release build 100" in p)
check("another product's release by a non-team sender is dropped", "Producer release" not in p)
check("a module QA report and an image release are the narrative's", '[QA report] "Summary Test Report for MeshAdapter' in p and "[docker release] copier:1.0.80 —" in p)
check("mail outside the day is not read", "Release notes" not in p)
check("the rules and the data are framed", p.index("Write the MediaHub team's end-of-day report for 2026-11-24") < p.index("--- BEGIN DATA ---") < p.index("--- END DATA ---"))
check("the input keys are the data's", {"MH-10", "MH-11", "MH-12", "MH-20"} <= set(inp["keys"]) and "MH-13" not in inp["keys"])
check("sources carry status and counts", inp["sources"]["slack"]["count"] == 3 and inp["sources"]["mail"]["count"] == 3 and inp["sources"]["jira"]["status"] == "ok")

saved = TR.MAX_SLACK
TR.MAX_SLACK = 2
capped = TR.daily_input(DAY, NOW)
check("Slack past the cap keeps the project channel first and says so", capped["sources"]["slack"] == {**capped["sources"]["slack"], "count": 2, "cap_hit": True, "seen": 3}
      and "lunch?" not in capped["prompt"] and "QA reproduced it" in capped["prompt"])
TR.MAX_SLACK = saved

# ── quiet and incomplete days ────────────────────────────────────────────────────────────────────────
q = TR.daily_input("2026-11-15", datetime.datetime(2026, 11, 15, 22, 0, tzinfo=TZ))
check("a day with nothing in any source is quiet, with no prompt", q["state"] == "quiet" and not q["prompt"])
put("slack/watermark.json", {"at": NOW.isoformat(), "gap": {"why": "channels not read whole: #general"}})
q = TR.daily_input("2026-11-15", datetime.datetime(2026, 11, 15, 22, 0, tzinfo=TZ))
check("a quiet day with a source gap is incomplete, not quiet", q["state"] == "incomplete" and q["sources"]["slack"]["status"] == "gap")
put("slack/watermark.json", {"at": NOW.isoformat()})

# ── the checks on a narrative ────────────────────────────────────────────────────────────────────────
raw = """# Daily Report — 2026-11-24

**Summary**

- SRT model rebuild kicked off (MH-10, MH-999).

**Release & QA**

- QA-AWS3 took build 100.

**Pushed forward**

## Extra heading

**HDR setting (MH-11, MH-404)** — shipped.

_Sources: jira ok(3)_
"""
clean, removed = TR.check_narrative(raw, "daily", inp["keys"])
check("a document title is dropped", "Daily Report" not in clean and removed.get("lines"))
check("Helm's Release & QA section is removed whole", "Release & QA" not in clean and "build 100" not in clean and removed["sections"] == ["**Release & QA**"])
check("a # heading becomes a bold header", "**Extra heading**" in clean)
check("unknown keys are removed and the parenthesis tidied", "MH-999" not in clean and "MH-404" not in clean and "(MH-10)" in clean
      and "(MH-11)" in clean and removed["keys"] == ["MH-404", "MH-999"])
check("the Sources line is removed", "_Sources" not in clean)
check("versions stay in the daily (image releases are the narrative's)", "1.0.80" in TR.check_narrative("**Summary**\n- copier:1.0.80 shipped", "daily", [])[0])
w, wr = TR.check_narrative("**Week in one paragraph**\nA week on build 2.1.22 and mh2.1@qa-q8.\n\n**Themes**\n- **SRT** — moved (MH-10)\n\n"
                           "**Monday**\n- per day\n\n**Numbers**\n- 7 closed\n", "weekly", ["MH-10"])
check("the weekly drops version tokens, per-day and Helm's sections", "2.1.22" not in w and "mh2.1@" not in w and "**Monday**" not in w
      and "**Numbers**" not in w and "(MH-10)" in w and set(wr["sections"]) == {"**Monday**", "**Numbers**"})
check("required sections are named when missing", TR.missing_sections("**Themes**\n- x", "weekly") == ["week in one paragraph"])

# ── write and publish ────────────────────────────────────────────────────────────────────────────────
def run(argv):
    buf = io.StringIO()
    code = 0
    try:
        with redirect_stdout(buf):
            TR.main(argv)
    except SystemExit as e:
        code = e.code or 0
    return code, buf.getvalue()

code, out = run(["prompt", "daily", "--date", DAY, "--json"])
meta = json.loads(out)
check("prompt writes the prompt and the input under the drafts", code == 0 and meta["model_needed"] and os.path.isfile(meta["prompt"])
      and os.path.isfile(os.path.join(os.path.dirname(meta["prompt"]), "input.json")))
code, _ = run(["write", "daily", "--date", DAY])
check("write without a narrative is refused on a day with activity", code == TR.EX_USAGE)
nf = os.path.join(TMP, "narrative.md")
open(nf, "w").write(raw)
code, out = run(["write", "daily", "--date", DAY, "--narrative", nf, "--json"])
doc = json.load(open(TR.published_path("daily", DAY)))
check("write publishes the checked narrative", code == 0 and doc["narrative"] == clean and doc["model"] is True)
check("the file carries the schema's fields", all(k in doc for k in ("schema", "kind", "id", "date", "state", "generated_at", "writer",
                                                                      "narrative", "keys", "sources", "window", "removed")) and doc["keys"] == ["MH-10", "MH-11"])
check("the schema is published beside the reports", os.path.isfile(os.path.join(os.environ["ELA_TEAMREPORT_PUBLISHED"], "reports", "README.md")))
open(nf, "w").write("**Summary**\n- the token is " + "xo" + "xb-123456789012-123456789012-" + "abcdefghijklmnopqrstuvwx" + "\n")   # built, so this file carries none
code, _ = run(["write", "daily", "--date", DAY, "--narrative", nf])
check("the publish guard refuses a credential and keeps the published copy", code == TR.EX_REFUSED
      and json.load(open(TR.published_path("daily", DAY)))["narrative"] == clean)
code, _ = run(["prompt", "daily", "--date", "2026-11-15"])
code, _ = run(["write", "daily", "--date", "2026-11-15"])
stub = json.load(open(TR.published_path("daily", "2026-11-15")))
check("a quiet day publishes the stub with no model", code == 0 and stub["state"] == "quiet" and stub["model"] is False and "Quiet day" in stub["narrative"])

# ── the weekly ───────────────────────────────────────────────────────────────────────────────────────
TR.F.now = lambda: datetime.datetime(2026, 11, 30, 8, 30, tzinfo=TZ)
wk = TR.weekly_input("2026-W48", datetime.datetime(2026, 11, 30, 8, 30, tzinfo=TZ))
wp = wk["prompt"]
check("the weekly reads the week's published dailies", wk["sources"]["dailies"]["dates"] == [DAY] and "--- BEGIN DAILY DATA 2026-11-24 ---" in wp)
check("the weekly's arc index and sections come from the store", "- MH-10: 2026-11-24 only" in wp and "**Blocked & at risk**" in wp
      and "MH-20 Collector crashes" in wp and "over 60 days 1" in wp)
check("the weekly counts created and closed in the week", wk["counts"]["created"] == 1 and wk["counts"]["closed"] == 1)
check("the weekly rules name the week", "ISO week 2026-W48 (2026-11-23 to 2026-11-29)" in wp)
check("the last full week from a Monday", TR.last_full_week(datetime.date(2026, 11, 30)) == "2026-W48")

# ── compare ──────────────────────────────────────────────────────────────────────────────────────────
helm = os.path.join(TMP, "helm")
os.makedirs(os.path.join(helm, "reports"))
open(os.path.join(helm, "reports", f"{DAY}.md"), "w").write(
    "---\ndate: 2026-11-24\ngenerated_at: 2026-11-24T14:00:00Z\nlegs: {}\n---\n\n# Daily Report — 2026-11-24\n\n**Summary**\n\n- CSC landed (MH-10, MH-30).\n\n"
    "**Release & QA**\n\n- QA-AWS3 (MH-31)\n\n_Sources: jira ok(14)_\n")
r = TR.compare("daily", DAY, helm)
note = open(r["path"]).read()
check("compare writes the note under drafts/report-compare", r["path"].endswith(os.path.join("drafts", "report-compare", f"daily-{DAY}.md")))
check("compare names the keys only one side cites, Helm's block aside", r["helm_only"] == ["MH-30"] and r["ela_only"] == ["MH-11"] and r["both"] == 1)
check("compare carries both texts", "## Helm" in note and "CSC landed" in note and "## ela" in note and "SRT model rebuild" in note)
r = TR.compare("daily", "2026-11-23", helm)
check("compare says when Helm has not written the day", r["helm"] is False and "Helm has not written" in open(r["path"]).read())

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
if failures:
    print(f"teamreport: {len(failures)} check(s) failed")
    sys.exit(1)
print("teamreport: all checks passed")
