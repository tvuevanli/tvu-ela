#!/usr/bin/env python3
"""mediahub-bot's knowledge proposals offline (Slack a stub transport, the files a temp directory): both routes read
into one record per claim, a route left unset is a state and a route set and unreadable a gap while the other is still
read, a second pass adds nothing, and the brief's proposals lane shows each with claim, evidence, source and thread."""
import datetime, json, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="ela-proposals-")
os.environ["ELA_FACTS_RUNTIME"] = os.path.join(TMP, "runtime")
os.environ["ELA_FACTS_QUIET"] = "1"
os.environ.pop("ELA_FACTS_FRESH", None)
for d in ("facts", "slack", "brief"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import facts as F  # noqa: E402
import proposals as P  # noqa: E402
import slack as S  # noqa: E402
import brief as B  # noqa: E402

F.links_update = lambda: {"read": [], "edges": 0}   # the index has its own test; it would read the real vault

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

NOW = datetime.datetime.now().astimezone()
CH = "C0TESTFEED1"
THREAD = "https://example.slack.com/archives/C0TESTCHAN1/p1000000000000001"

def post(claim, evidence, source="a person in the thread"):
    """The bot's reply text as mhbot/feedback.py `text` writes it, then as Slack returns it (& < > escaped)."""
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return (f"*Knowledge proposal* · from <{THREAD}|this thread>\n*Claim:* {esc(claim)}\n*Evidence:* {esc(evidence)}\n"
            f"*Source:* {source}\n`{P.MARK}`")

CLAIM_A = "A grid_decoder is not mediabox mode on prod-3 & its log is not in Loki."
CLAIM_B = "srt_copier is mediabox mode on prod-3."
PTS = f"{NOW.timestamp() - 3600:.6f}"
PARENT = {"ts": PTS, "user": "UBOT", "text": "*Knowledge proposals* · today", "reply_count": 3, "latest_reply": f"{NOW.timestamp() - 600:.6f}"}
REPLIES = [{"ts": f"{NOW.timestamp() - 1800:.6f}", "user": "UBOT", "text": post(CLAIM_A, "stated in the thread; support.mediaBox.type <none>")},
           {"ts": f"{NOW.timestamp() - 1200:.6f}", "user": "UBOT", "text": f"broken `{P.MARK}`"},
           {"ts": f"{NOW.timestamp() - 600:.6f}", "user": "U2", "text": "thanks"}]
calls = {"slack": 0}
S.token = lambda env_file=None: "xoxb-test"
def fake_fetch_history(tok, ch, oldest):
    calls["slack"] += 1
    return [dict(PARENT)] if ch == CH else []
def fake_call(method, tok, _soft=False, **params):
    calls["slack"] += 1
    if method == "conversations.replies":
        return {"messages": [dict(PARENT)] + [dict(r) for r in REPLIES]}
    return {"ok": True}
S.fetch_history, S.call = fake_fetch_history, fake_call

DIR = os.path.join(TMP, "mhbot", "data", "knowledge-proposals")
os.makedirs(DIR)
def bot_file(name, doc):
    json.dump(doc, open(os.path.join(DIR, name), "w", encoding="utf-8"))
stamp = NOW.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
bot_file("a.json", {"marker": P.MARK, "claim": "A  grid_decoder is NOT mediabox mode on prod-3 & its log is not in Loki.",
                    "evidence": "", "source": "person", "thread": THREAD, "written_at": stamp})
bot_file("b.json", {"marker": P.MARK, "claim": CLAIM_B, "evidence": "read the J2N label set", "source": "read", "thread": THREAD, "written_at": stamp})
bot_file("c.json.tmp", {"marker": P.MARK, "claim": "half a file", "source": "read"})
bot_file("d.json", {"claim": "no marker"})

SITE = {}
F.site = lambda: SITE
class A: env_file = None; source = ["proposals"]; fresh = False; json = False

# ── neither route configured: a state, not a gap ────────────────────────────────────────────────────
F.cmd_refresh(A())
wm = F.watermark("proposals")
check("nothing configured is a state with a read time, no gap and no Slack call",
      wm.get("state") == "not configured" and wm.get("at") and not wm.get("gap") and calls["slack"] == 0)

# ── both routes ────────────────────────────────────────────────────────────────────────────────────
SITE["knowledge_proposals"] = {"channel": CH, "dir": DIR}
F.cmd_refresh(A())
wm = F.watermark("proposals")
store = F.read_json(os.path.join(F.store_dir("proposals"), "proposals.json"))
a, b = store.get(P.key(CLAIM_A)), store.get(P.key(CLAIM_B))
check("the parser reads the bot's reply text, Slack's escapes undone", a and a["claim"] == CLAIM_A and a["evidence"].endswith("<none>"))
check("a claim sent both ways is one record with both routes (deduped by the bot's claim key)",
      len(store) == 2 and a["routes"] == ["channel", "files"] and a["post"].endswith(REPLIES[0]["ts"].replace(".", "")) and a["file"] == "a.json")
check("a file-only claim carries its source, evidence and thread", b and b["routes"] == ["files"] and b["source"] == "read"
      and b["evidence"] == "read the J2N label set" and b["thread"] == THREAD)
check("the source word becomes person|read", a["source"] == "person")
check("a .tmp file, a file without the marker and a marked reply that does not parse are skipped, not records",
      not any("half" in r["claim"] or "no marker" in r["claim"] for r in store.values()) and wm.get("new") == 2)
check("both routes read: no gap, state cleared", not wm.get("gap") and wm.get("state") is None)

# ── a second pass ─────────────────────────────────────────────────────────────────────────────────
F.cmd_refresh(A())
wm2 = F.watermark("proposals")
check("a second pass adds nothing and keeps the first-seen time", wm2.get("new") == 0
      and F.read_json(os.path.join(F.store_dir("proposals"), "proposals.json"))[P.key(CLAIM_A)]["seen_at"] == a["seen_at"])

# ── one route missing: a gap, the other still read ───────────────────────────────────────────────────
SITE["knowledge_proposals"] = {"channel": CH, "dir": os.path.join(TMP, "not-here")}
F.cmd_refresh(A())
wm = F.watermark("proposals")
check("a configured directory that is not there is a partial gap; the channel is still read",
      wm.get("gap", {}).get("partial") and "no directory" in wm["gap"]["why"] and len(P.rows()) == 2)

# ── every configured route unreadable: the source not read, the store kept ───────────────────────────
def no_token(env_file=None):
    raise SystemExit(3)
S.token = no_token
try:
    F.cmd_refresh(A()); code = 0
except SystemExit as e:
    code = e.code
wm = F.watermark("proposals")
check("every configured route failing is the source not read (exit 5), the gap names both, the store stands",
      code == 5 and "slack exit 3" in wm["gap"]["why"] and "no directory" in wm["gap"]["why"] and len(P.rows()) == 2)

# ── the brief's lane ─────────────────────────────────────────────────────────────────────────────────
lane = B.lane_proposals(None, 50, datetime.datetime.now(datetime.timezone.utc))
row = next((r for r in lane["rows"] if r["key"] == P.key(CLAIM_A)), None)
check("the proposals lane shows each with claim, evidence, source and the thread link",
      lane["count"] == 2 and row and row["claim"] == CLAIM_A and row["evidence"] and row["source"] == "person" and row["thread"] == THREAD)
check("the lane carries the store's gap, never an empty lane said as nothing proposed", "slack exit 3" in (lane.get("gap") or ""))
later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=5)
check("a proposal first seen before the window is counted as older, not shown", B.lane_proposals(None, 50, later)["count"] == 0
      and B.lane_proposals(None, 50, later)["older"] == 2)
check("the lane is one of the brief's lanes", "proposals" in B.LANES)

shutil.rmtree(TMP, ignore_errors=True)
if failures:
    print(f"proposals: {len(failures)} check(s) failed"); sys.exit(1)
print("proposals: all offline checks passed")
