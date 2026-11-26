#!/usr/bin/env python3
"""The SessionStart hook's outputs stay under Claude Code's per-command cap, or say loudly that they do not.

Claude Code injects a hook command's output only up to 10,000 characters; past that the session sees a 2KB preview
(measured on 2.1.332, 2026-11-25). The working preferences therefore come as `prefs I/K` parts, each its own command:
together they are the section whole, and a section that needs more parts than hooks.json runs is named on the last
part's first line. Every output from 9,000 characters on starts with a warning. Offline: a temp HOME, no network.
"""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "session-start.sh")
CAP, WARN = 10000, 9000
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


def bullets(n, width=200):
    return "".join(f"- rule {i}: " + "w" * width + "\n  continued line of rule " + str(i) + "\n" for i in range(n))


def run(home, *args, root=ROOT, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ("ELA_GUEST", "ELA_RUNNER_JOB")}
    e.update(HOME=home, CLAUDE_PLUGIN_ROOT=root, CLAUDE_PROJECT_DIR=home)
    e.update(env or {})
    return subprocess.run(["bash", HOOK, *args], input="", capture_output=True, text=True, env=e, timeout=60).stdout


def home_with(prefs):
    h = tempfile.mkdtemp(prefix="ela-ss-")
    os.makedirs(os.path.join(h, ".claude", "ela"))
    json.dump({"elak": "<elak>"}, open(os.path.join(h, ".claude", "ela", "site.json"), "w"))
    open(os.path.join(h, ".claude", "ela", "working-with-evan.md"), "w", encoding="utf-8").write(prefs)
    return h


# 1. A ~15K preferences section comes whole in two parts, each under the warning line; a later section is a pointer.
section = "## Working preferences (test)\n" + bullets(60)
later = "## His day (test)\n- a later section, only pointed at\n"
h = home_with(section + "\n" + later)
p1, p2 = run(h, "prefs", "1/2"), run(h, "prefs", "2/2")
ctx = run(h)
check(len(section) > CAP, f"fixture too small: {len(section)}")
for name, out in (("part 1", p1), ("part 2", p2), ("context", ctx)):
    check(0 < len(out) < WARN, f"{name}: {len(out)} characters, expected 1..{WARN - 1}")
    check(not out.startswith("ela: WARNING"), f"{name}: unexpected warning")
body = "".join(o.split("\n", 1)[1] for o in (p1, p2))
check(body.rstrip() == section.rstrip(), "the two parts are not the preferences section whole")
check("a later section" not in p1 + p2 + ctx, "a later section was injected")
check('"His day (test)"' in ctx and "line " in ctx, "context lacks the pointer to the later section")
shutil.rmtree(h)

# 2. A section that needs three parts when hooks.json runs two: the last part names the lines that did not arrive.
h = home_with("## Working preferences (test)\n" + bullets(100))
p2 = run(h, "prefs", "2/2")
check(p2.startswith("ela: WARNING") and "need 3 parts" in p2 and "did not reach this session" in p2,
      f"overrun not named on the last part's first line: {p2[:200]!r}")
check(len(p2) <= CAP, f"overrun part itself over the cap: {len(p2)}")
check(not run(h, "prefs", "1/2").startswith("ela: WARNING"), "part 1 warned; only the last part names the overrun")
check(run(h, "prefs", "4/6") == "" and run(h, "prefs", "3/6").startswith("(ela:"), "a part past the section's end printed something")
shutil.rmtree(h)

# 3. A guest session gets no preferences.
h = home_with(section)
check(run(h, "prefs", "1/2", env={"ELA_GUEST": "1"}) == "", "a guest session got the owner's preferences")
shutil.rmtree(h)

# 3b. One source: elak's copy is read where site.json names an elak that holds it, the site copy on a remote site or
# where elak has none; every part and the pointer name the file that was read.
h = home_with("## Working preferences (site copy)\n- the site rule\n\n## Later (site)\n- x\n")
elak = os.path.join(h, "elak")
os.makedirs(os.path.join(elak, "blueprint"))
open(os.path.join(elak, "blueprint", "working-with-evan.md"), "w").write(
    "## Working preferences (elak)\n- the elak rule\n\n## Later (elak)\n- y\n")
sj = os.path.join(h, ".claude", "ela", "site.json")
json.dump({"elak": elak}, open(sj, "w"))
out, ctx = run(h, "prefs", "1/6"), run(h)
check("the elak rule" in out and "the site rule" not in out, f"elak's copy was not the one read: {out[:200]!r}")
check("~/elak/blueprint/working-with-evan.md" in out.split("\n", 1)[0], f"the part does not name elak's file: {out[:200]!r}")
check('"Later (elak)": `~/elak/blueprint/working-with-evan.md`' in ctx, "the pointer does not name elak's file")
json.dump({"elak": elak, "site": "remote"}, open(sj, "w"))
out = run(h, "prefs", "1/6")
check("the site rule" in out and "the elak rule" not in out, f"a remote site read <elak>, the published subset: {out[:200]!r}")
check("~/.claude/ela/working-with-evan.md" in out.split("\n", 1)[0], f"the part does not name the site copy: {out[:200]!r}")
json.dump({"elak": elak}, open(sj, "w"))
os.remove(os.path.join(elak, "blueprint", "working-with-evan.md"))
check("the site rule" in run(h, "prefs", "1/6"), "no fallback to the site copy when elak has no preferences file")
shutil.rmtree(h)

# 4. The default part warns on its first line near the cap and over it (an oversized context/evan.md).
for size, word in ((WARN + 200, "near the cap"), (CAP + 2000, "OVER the cap")):
    root = tempfile.mkdtemp(prefix="ela-ss-root-")
    os.makedirs(os.path.join(root, "context"))
    open(os.path.join(root, "context", "evan.md"), "w").write("x" * size + "\n")
    h = home_with(section)
    out = run(h, root=root)
    first = out.split("\n", 1)[0]
    check(first.startswith("ela: WARNING") and word in first, f"{size} characters: first line {first[:120]!r}")
    check(len(first) < 2000, "the warning does not fit the 2KB preview")
    shutil.rmtree(h); shutil.rmtree(root)

# 5. The repository's own context/evan.md leaves the default part room under the warning line.
check(len(open(os.path.join(ROOT, "context", "evan.md"), encoding="utf-8").read()) < WARN - 1500,
      "context/evan.md leaves under 1,500 characters for the knowledge-base and cwd lines")

# 6. hooks.json runs prefs 1/K .. K/K beside the default part under every SessionStart matcher.
hj = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))
for entry in hj["hooks"]["SessionStart"]:
    cmds = [x["command"].split("session-start.sh", 1)[1].split() for x in entry["hooks"] if "session-start.sh" in x["command"]]
    parts = [c[1] for c in cmds if c and c[0] == "prefs"]
    k = len(parts)
    check(k >= 1 and sorted(parts) == [f"{i}/{k}" for i in range(1, k + 1)], f"{entry['matcher']}: prefs parts {parts}")
    check(cmds and cmds[0] == [], f"{entry['matcher']}: the default part, which opens with the head, is not listed first")

# 6b. The head (what ela is for, the roots) opens context/evan.md within 2,000 characters: it is read on every turn of
# every session, and a root that grows a clause there is a rule that belongs in the preferences instead.
ev = open(os.path.join(ROOT, "context", "evan.md"), encoding="utf-8").read()
a, b = ev.find("## What ela is for"), ev.find("## How he works with you")
check(0 < a < 400 and b > a, "context/evan.md does not open with the head (## What ela is for … ## Roots)")
head = ev[a:b].strip()
check(len(head) <= 2000, f"the head is {len(head):,} characters, over 2,000")
check("## Roots" in head and all(f"- R{i} " in head for i in range(7)), "the head lacks one of the roots R0..R6")
check("## Who Evan is" not in ev, "the head sits beside the section it replaces")

# 7. The required phrases: the injected preferences still carry what each decision rests on.
# A rewrite of the preferences (a compression, a reorder, a merge of two rules) is gated by this list: one scenario per
# rule or dated refinement, each naming the boundary clauses a session decides by, plus every rule name that code or a
# hook cites and the closing marks that pane-mark and `ela session reap` read. The phrases are matched on the parts the
# hook injects for the owner's own text, whitespace collapsed, so a clause that fell out of the injected section fails
# here as surely as one that was reworded away. The text is the machine's (elak's copy, or the site file), so the
# check runs where that text exists and is skipped elsewhere; ELA_PREFS_CHECK=FILE checks a candidate text before it
# replaces the live one.
REQUIRED = {
    "design: a rework at scale is allowed (2026-11-26)": [
        "A rework at scale is allowed", "argued from the roots", "rebuilding the part from the root"],
    "slack: nothing posts on its own (2026-11-12)": [
        "Nothing posts to Slack on its own except the daily and weekly reports", "dry run first",
        "leaves only on his approve", "No timer, veto window or standing rule sends one for him", "retires tier 2"],
    "slack: a change he names with his send (2026-11-23)": [
        "a change he names with it", "without another preview", "another target", "other recipients or mentions",
        "a claim added or changed"],
    "slack: the #send tag (2026-11-26)": [
        "`#send`", "a post as ela to the thread or person the request names", "go under his own name",
        "commit to a date, an owner or a release scope", "a fact the session is not sure of", "a loose phrase",
        "lang-tag.sh"],
    "slack: messages go out under his own name (2026-10-20)": [
        "he sends it", "post as ela", "His private intent stays out"],
    "accounts: li is the default (2026-11-24)": [
        "`li` is the default", "`TVU_TEST_ACCOUNT`", "unless he names `el`", "no admin SID"],
    "accounts: ela verifies as li (2026-11-26)": [
        "switching `li`'s bundle", "A verified pass closes the ticket",
        "a fail reopens or reassigns it with the evidence", "a case ela cannot test goes to QA",
        "a passthrough case cannot use YouTube"],
    "tests and credentials": [
        "Tests never write to Slack or Jira", "Never record remote addresses or credentials"],
    "elak: the session that wrote it commits (2026-11-25)": [
        "the session that wrote it commits and pushes it", "No hook commits or pushes elak", "never `git add -A`",
        "Only what he asked to record goes in", "one-year test", "edits made by another session stay unstaged",
        "Never `--force`", "`git pull --rebase`"],
    "elak: a feature's mechanism (2026-11-26)": [
        "a feature's mechanism", "Judgments, verdicts and plans are not covered",
        "links to the elak entry, never copying it"],
    "no data is lost (2026-11-09, corrected 2026-11-10)": [
        "No data is lost", "Nothing ela keeps is deleted", "closed and kept", "is backed up",
        "Not every copy is data", "keep what exists nowhere else"],
    "notes of one kind (2026-11-09)": [
        "Notes of one kind follow one standard", "lints against it", "a correction from him updates it"],
    "visibility": ["shareable inside TVU", "addresses, credentials and anyone's words are not", "his alone"],
    "his messages are input": ["His messages are input, never artefacts", "record this verbatim"],
    "shared trees": ["Shared trees get finished writing", "in a later pass"],
    "evidence": ["A report is input; evidence is fact"],
    "gate (elak principle 7 points here by name)": [
        "Gate every non-trivial ask", "the strongest alternative including doing nothing",
        "dissent is recorded, never swallowed"],
    "ela's own design (2026-11-09)": [
        "ela's own design is ela's to decide", "first judge whether it is a real pain point",
        "no box asks his word", "Black-box development",
        "His word stays required for product, team and outward-facing matters"],
    "adversarial review (2026-11-25)": ["a reviewer that did not write it", "not ela's conclusion"],
    "review rounds (2026-11-26)": [
        "one round for a change inside ela's own machinery", "two for a change to what he reads",
        "three for a change that moves, rewrites or retires his notes", "act unasked where a colleague sees it",
        "Each round is a fresh reviewer", "A small fix still ships on ela's own judgment"],
    "ela runs on its own (2026-11-26)": [
        "names its kind, *fact* or *ruling*", "carries ela's leaning", "`wrong: <why>`",
        "a private, reversible call is always ela's", "the `ela dry` ladder",
        "only on a mechanical proof read first-hand", "anything signed or under his name stays his word"],
    "housekeeping on a ticket (2026-11-26)": [
        "housekeeping on a ticket ela is already working", "Nothing is lost", "The change announces itself",
        "a signed comment", "asks first only when it lacks the information to be sure",
        "Slack messages stay under"],
    "the decision heading (2026-11-25)": [
        "`⚖️ Needs your decision`", "`⚖️ 待你决策`", "answer in one word",
        "named only in the reply where it starts, finishes, fails or blocks", "A task he takes on himself is dropped",
        "The heading appears only while a decision is open"],
    "the out line (2026-11-24, extended 2026-11-25)": [
        "`— ela out 🦀`", "alone, as the reply's last line", "any decision the reply leaves open for him",
        "a signal the session waits for from another session", "any input it awaits from him", "`ela out?`",
        "checks each item above first-hand"],
    "the pending line (2026-11-25)": [
        "`⏳ ela pending · <what it waits for> · <until when>`", "exactly one of the two closes every reply",
        "CronCreate", "repeated on every reply while the wait lasts",
        "`ela session reap` never closes a session whose last reply ends with it",
        "only as true as the session that writes it"],
    "asks live in the vault (2026-11-25)": [
        "What waits for his word lives in the vault; Slack only reminds", "never the only place a question is",
        "He answers in the CLI"],
    "short head, folded rest (2026-11-20, 2026-11-26)": [
        "Show the short, important part; fold the rest", "`> [!note]-`", "a line of three dashes",
        "cut, not folded"],
    "language (2026-11-18, the tag 2026-11-24, Jira 2026-11-26)": [
        "Answer in English by default", "Domain terms", "Durable content", "A Jira comment is in one language, English",
        "English only, whatever that person's language", "`#zh`"],
    "slack mrkdwn (2026-11-13)": [
        "Slack's own mrkdwn", "`<url|label>`", "A bullet is the character `•`", "a space on both sides"],
    "lane names (2026-11-16)": ["MediaHub name first", "daily-wed (UR test2)"],
    "jira keys are links (2026-10-27, Slack 2026-11-26)": [
        "Every Jira key he reads is a link", "`<url|MH-1997>`", "no bare URL stands beside it",
        "cut at a word boundary"],
    "a ticket for another developer": ["carries no code-level detail"],
    "a command he runs (2026-11-25)": ["`! bash /tmp/st.sh`", "`bash -n`", "never prints a secret"],
    "he states needs": ["you decide specifics and say what you decided", "commits need no proposal first"],
    "options as he gave them (2026-10-14)": ["Options as he gave them", "no middle path is invented"],
    "where a capability counts (2026-09-04)": ["A capability counts where its users are"],
    "no historical burden": ["No historical burden", "retirement condition"],
    "merge requests (2026-09-29)": [
        "app layer first, then UR/J2N, then media", "staffing and performance are not his"],
}
REASONS = 17   # every rule that states its reason keeps it: the count of `Reason:` in the injected section


def squash(s):
    return " ".join(s.split())


cand = os.environ.get("ELA_PREFS_CHECK", "")
k = max(len([x for x in e["hooks"] if " prefs " in x["command"]]) for e in hj["hooks"]["SessionStart"])
h = home_with(open(cand, encoding="utf-8").read()) if cand else os.path.expanduser("~")
outs = [run(h, "prefs", f"{i}/{k}") for i in range(1, k + 1)]      # the file the hook itself resolves
if cand:
    shutil.rmtree(h)
if any(outs):
    for i, o in enumerate(outs, 1):
        check(not o.startswith("ela: WARNING"), f"the owner's preferences, part {i}/{k}: {o[:160]!r}")
    text = squash("".join(outs))
    for scenario, phrases in REQUIRED.items():
        for ph in phrases:
            check(squash(ph) in text, f"required phrase gone from the injected preferences ({scenario}): {ph!r}")
    check(text.count("Reason:") >= REASONS, f"{text.count('Reason:')} `Reason:` lines injected, expected {REASONS} or more")
else:
    print("session-start offline: no preferences on this machine, the required-phrase check is skipped")

if fails:
    print("session-start offline: FAILED"); [print("  " + f) for f in fails]; sys.exit(1)
print("session-start offline: ok")
