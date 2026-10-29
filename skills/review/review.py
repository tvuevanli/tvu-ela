#!/usr/bin/env python3
"""ela's own output, reviewed: the workflow is judged on the pages ela writes, not on the owner noticing.

    review.py lint PAGE [--actions F] [--date D] [--json]
    review.py replay --date D [--json]
    review.py reader --date D [--check] [--json]

lint checks one page mechanically (a morning page, Changes, the lanes page, the board): every ticket key is a link,
every Do line is a box and none is a bare verb for him, every `apply N` has its action and its box, a count equals
the day's counts object, a key is an item once, a service is named by slug, a front-matter status is in the closed
set, and a bundle name is one the reads held. Exit 1 with one line per failure; `ela page-check` runs it.

replay compares what ela said on day D with what the sources show now: a `sure` ticket reading later contradicted
(moved back, reopened, a QA fail after it), a status, assignee or Fixed In a facts line stated that Jira did not
hold when the page was written, a drafted Fixed In clear of an empty field, a version the morning page called moved that the next lane read did
not hold, a nudge drafted for someone who had already answered, and an applied action after which the ticket did
not change for a working day. It writes <reports>/review/<D>-replay.json and prints one summary line for the facts
page. Exit 3 when Jira could not be read (the rows it could read are still written).

reader serves the evening session that reads the morning page as the owner would (skills/brief/SKILL.md §reader):
without --check it prints what the session reads (the page, its items, the actions, the replay and the lint) and
where it writes, <reports>/review/<D>-reader.md; with --check it verifies that file: one verdict per item from the
closed set and the page's three lines. Exit 1 naming each gap; a passing check writes <D>-reader.json, the
findings the next morning's judge reads.

Reads files and Jira only; nothing is posted or ticked.
"""
import argparse, datetime, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "brief"))
import brief as B  # noqa: E402  — the apply-N check and front matter, read the page-check way
sys.path.insert(0, os.path.join(HERE, "..", "vault"))
import vault as V  # noqa: E402  — the closed status set and the key pattern the vault links
sys.path.insert(0, os.path.join(HERE, "..", "ticket"))
import ticket as T  # noqa: E402  — the QA roster and the fail pattern a refresh reads with

SITE = os.path.expanduser("~/.claude/ela/site.json")
CODE_SPAN = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)
LINKED = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+|\[\[[^\]]*\]\]")
ITEM_RX = re.compile(r"^###\s+\d+\.\s", re.M)
DO_RX = re.compile(r"^\s*[-*]\s+\*\*Do:\*\*\s*(.*)$")
BOX_RX = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
DECISION_RX = re.compile(r"·\s*(?:decide\b|your call\b)", re.I)   # where a box with no write is decided (brief SKILL)
# a box he must still act on: a slash command, or a draft, list, lookup or question left for him to make
BARE_VERB_RX = re.compile(r"/ela:|^(?:draft|list|ask|run|check|look|read|find|write|go deep)\b", re.I)
VAGUE_SERVICE_RX = re.compile(r"\b(?:the|a)\s+(frontend|backend)\b(?!\s*[(:]?\s*[\w-]*\d)", re.I)
BUNDLE_RX = re.compile(r"\bmh\d+\.\d+@[a-z][\w-]*|\bMediaHub \d+\.\d+(?:\.\d+| rc\d+)(?: \([^)]*\))?")
# a count over another window or scope ("commits, 7 days", "8 commits on a branch") is not the day's
SCOPED = r"(?!,?\s*\d+\s+days|\s+(?:on|in|for|to|from|of|since|by|under)\b)"
# a count cited in prose or a heading, and the counts-object field it must equal; "(N · M as of" takes M
COUNT_PHRASES = (
    (re.compile(r"\b(\d+)\s+close-ready\b|\bclose-ready(?: tickets)?:?\s+(\d+)\b|Ready for a close proposal \((?:\d+ · )?(\d+)", re.I), "close_ready"),
    (re.compile(r"\b(\d+)\s+verified[- ]not[- ]fixed\b|Verified as not fixed \((?:\d+ · )?(\d+)", re.I), "verified_not_fixed"),
    (re.compile(r"\b(\d+)\s+(?:ela\s+)?jobs\b" + SCOPED, re.I), "jobs"),
    (re.compile(r"\b(\d+)\s+commits\b" + SCOPED, re.I), "commits"),
    (re.compile(r"\b(\d+)\s+tickets moved\b" + SCOPED, re.I), "tickets_moved"),
    (re.compile(r"\b(\d+)\s+builds\b" + SCOPED, re.I), "builds"),
)


def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def roots(s):
    p = s.get("projects", "")
    return s.get("reports") or os.path.join(p, "reports"), s.get("runtime") or os.path.join(p, ".ela"), s.get("vault")


def outside_code(text):
    """The page with code spans and fences blanked, line breaks kept so line numbers still hold."""
    return CODE_SPAN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def bare_keys(text, in_vault):
    """Ticket keys a reader sees as plain text. In the vault every key outside a link is bare; in a <reports> source
    the vault links keys on render, except inside code spans, which it leaves as written."""
    out = []
    if in_vault:
        plain = LINKED.sub(lambda m: " " * len(m.group(0)), outside_code(text))
        out = [m.group(1) for m in V.KEY_RX.finditer(plain)]
    else:
        for m in CODE_SPAN.finditer(text):
            out += [k.group(1) for k in V.KEY_RX.finditer(m.group(0)) if not m.group(0).startswith("```")]
    return sorted({k for k in out if not B.NOT_KEYS.match(k)})


def items(text):
    """The numbered items (`### N. …`): (heading line, facts line, body) each."""
    starts = [m.start() for m in ITEM_RX.finditer(text)]
    out = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        nxt = re.search(r"^##\s", text[s + 3:end], re.M)
        body = text[s:s + 3 + nxt.start()] if nxt else text[s:end]
        lines = body.splitlines()
        out.append((lines[0], lines[1] if len(lines) > 1 else "", body))
    return out


def do_lines(body):
    """The lines under an item's **Do:**: (line, text of a box or None)."""
    out, on = [], False
    for line in body.splitlines():
        m = DO_RX.match(line)
        if m:
            on = True
            if m.group(1).strip():
                out.append((line, None))
            continue
        if on:
            if not line.strip() or line.startswith("#"):
                break
            b = BOX_RX.match(line)
            out.append((line, b.group(1) if b else None))
    return out


NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
ORDINALS = {w: i for i, w in enumerate("zeroth first second third fourth fifth sixth seventh eighth ninth tenth".split())}
MORNING_RX = re.compile(r"\b(\d+)(?:st|nd|rd|th) morning\b")
SUMMARY_MORNING_RX = re.compile(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s+(?:\w+\s+){0,2}(?:is|are)\s+on\s+(?:their|its)\s+"
                                r"(\d+(?:st|nd|rd|th)|" + "|".join(ORDINALS) + r")\s+morning", re.I)


def summary_mornings(text):
    """Each "N items are on their Mth morning" in the summary above Needs you that the items' facts lines do not bear
    out: [(said, items on that morning)]. The summary and the items count from the same carried lane."""
    head = text.split("## Needs you", 1)[0] if "## Needs you" in text else ""
    have = [int(m.group(1)) for _, facts, _ in items(text) for m in [MORNING_RX.search(facts)] if m]
    out = []
    for m in SUMMARY_MORNING_RX.finditer(head):
        n = NUMBER_WORDS.get(m.group(1).lower(), None) if not m.group(1).isdigit() else int(m.group(1))
        o = m.group(2).lower()
        nth = int(re.match(r"\d+", o).group(0)) if o[0].isdigit() else ORDINALS[o]
        if n != have.count(nth):
            out.append((m.group(0), have.count(nth)))
    return out


UNTESTED_RX = re.compile(r"\buntested\b|\bno (?:QA )?report\b|\bnot (?:yet )?tested\b|\bwithout (?:a )?QA report\b", re.I)


def under_test_claims(text, build):
    """Sentences that call the build still under QA's test cycle untested or unreported: [sentence]."""
    if not build:
        return []
    rx = re.compile(r"\bbuild\s+" + re.escape(str(build)) + r"\b", re.I)
    return [x.strip()[:80] for x in re.split(r"(?<=[.;!?])\s+|\n", outside_code(text)) if rx.search(x) and UNTESTED_RX.search(x)]


def under_test(date):
    """The build under QA's test cycle on the morning of `date` ({build, due}), or None."""
    try:
        b = B.qa_cycle(datetime.date.fromisoformat(date))["under_test_build"]
    except (OSError, ValueError, KeyError):
        return None
    return {"build": b["build"], "due": b["due"]} if b else None


def lint(text, actions=None, counts=None, bundles=None, in_vault=False, brief=False, handles=None, testing=None):
    """One line per failure, empty when the page passes. `actions` the day's drafted writes (None: not checked),
    `counts` the day's counts object, `bundles` every bundle name the reads held (None: not checked), `handles`
    {Jira name: roster display name} for the people whose two differ (None: not checked), `testing` the build under
    QA's test cycle ({build, due}; None: not checked)."""
    fails = []
    for k in bare_keys(text, in_vault):
        fails.append(f"{k}: a ticket key that is not a link")
    if actions is not None:
        orphan, unboxed = B.page_check(text, actions)
        fails += [f"apply {n}: no such action in the actions file" for n in orphan]
        fails += [f"apply {n}: named without its box on the page" for n in unboxed]
    seen = {}
    for head, facts, body in items(text):
        title = head.lstrip("#").strip()
        numbers = []
        for line, box in do_lines(body):
            if box is None:
                fails.append(f"{title[:50]}: a Do line without a box: {line.strip()[:60]}")
            elif B.APPLY_RX.search(box):
                numbers.append(int(B.APPLY_RX.search(box).group(1)))
            elif BARE_VERB_RX.search(box.strip()):
                fails.append(f"{title[:50]}: a Do line left for him to do: {box.strip()[:60]}")
            elif not DECISION_RX.search(box):
                fails.append(f"{title[:50]}: a box with no apply number that does not say where it is decided: {box.strip()[:60]}")
        if numbers != sorted(numbers):
            fails.append(f"{title[:50]}: apply numbers descend: {', '.join(map(str, numbers))}")
        for k in set(B.keys_in(head + "\n" + facts)):
            seen.setdefault(k, []).append(title.split(".")[0])
    for k, where in sorted(seen.items()):
        if len(where) > 1:
            fails.append(f"{k}: an item {len(where)} times (items {', '.join(where)})")
    for x in under_test_claims(text, (testing or {}).get("build")):
        fails.append(f"build {testing['build']} is under test, its report due {testing['due'][5:]} evening; never untested: {x}")
    for said, real in summary_mornings(text):
        fails.append(f"summary: \"{said}\", but {real} item{'s' if real != 1 else ''} say so")
    plain = outside_code(text)
    for m in VAGUE_SERVICE_RX.finditer(plain):
        line = plain[:m.start()].count("\n") + 1
        fails.append(f"line {line}: \"{m.group(0)}\": name the service by its slug")
    status = B.front_matter(text).get("status")
    if status not in (None, "") and status not in V.STATUSES:
        fails.append(f"status {status!r}: not in the closed set ({', '.join(V.STATUSES)})")
    if counts:
        for rx, field in COUNT_PHRASES:
            if field not in counts:
                continue
            for m in rx.finditer(plain):
                n = int(next(g for g in m.groups() if g))
                if n != counts[field]:
                    fails.append(f"{field}: the page says {n}, the day's counts say {counts[field]}")
    for handle, name in sorted((handles or {}).items()):
        if re.search(r"(?<![\w@])" + re.escape(handle) + r"(?![\w])", plain):
            fails.append(f"{handle}: a Jira name; the page writes {name}")
    if bundles is not None:
        for name in sorted({m.group(0) for m in BUNDLE_RX.finditer(plain)}):
            if name not in bundles and not name.startswith("MediaHub "):
                fails.append(f"{name}: a bundle no read of the last 14 days holds")
    return list(dict.fromkeys(fails))


def page_date(path, text):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path)) or re.search(r"(\d{4}-\d{2}-\d{2})", text[:400])
    return m.group(1) if m else None


def day_counts(runtime, date):
    try:
        return json.load(open(os.path.join(runtime, "runner", f"{date}-changes.json"), encoding="utf-8")).get("counts") or {}
    except (OSError, ValueError):
        return None


def read_bundles(runtime):
    """Every bundle name the daily reads held: the changes files' new bundles and the matrix rows they wrote."""
    names = set()
    for f in sorted(glob.glob(os.path.join(runtime, "runner", "*-changes.json")))[-14:]:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names |= {str(b.get("name")) for b in d.get("bundles") or [] if b.get("name")}
    return names


def context(path, text, actions_path=None, date=None):
    """What lint compares a page with, found from the page's name and date: (actions, counts, bundles, in_vault, brief)."""
    s = site()
    reports, runtime, vault = roots(s)
    date = date or page_date(path, text)
    brief = bool(re.search(r"-brief\.md$", path))
    if not actions_path and brief and date:
        actions_path = os.path.join(reports, "runner", f"{date}-actions.json")
    actions = None
    if actions_path:
        try:
            actions = json.load(open(actions_path, encoding="utf-8"))
        except OSError:
            actions = []
    counts = day_counts(runtime, date) if date else None
    bundles = read_bundles(runtime)
    in_vault = bool(vault) and os.path.realpath(path).startswith(os.path.realpath(vault) + os.sep)
    return actions, counts, bundles or None, in_vault, brief


def stray_action_files(actions_path, actions):
    """Files in the day's action folder (<reports>/runner/actions/<date>/, beside the actions file) that no drafted
    action's command names: a draft the run abandoned but wrote. []: none, or no folder."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})-actions\.json$", actions_path or "")
    folder = os.path.join(os.path.dirname(actions_path), "actions", m.group(1)) if m else None
    if not folder or not os.path.isdir(folder):
        return []
    named = " ".join(a.get("command") or "" for a in actions or [])
    return sorted(f for f in os.listdir(folder) if f not in named)


def budget(path, text, actions_path=None):
    """The reading budget a runner day page overruns, as the vault counts it ("1,489 words, budget 1,200"), so the
    number matches Home's warning; None within budget or for a page the vault does not gate as a day page."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})-(brief|learned|week|changes)\.md$", path)
    if not m:
        return None
    body = V.split_front(text)[1]
    if m.group(2) == "brief":
        body = V.action_states(body, actions_path or os.path.join(os.path.dirname(path), f"{m.group(1)}-actions.json"))
    return next((p for p in V.reading_gate(V.Note(path, "", body, {"type": "day"})) if "words, budget" in p), None)


def roster_names():
    """Every roster display name, lowercased; empty when the roster cannot be read."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "team"))
        import team
        return {p["name"].lower() for p in team.read_roster(team.records())[1] if p.get("name")}
    except (SystemExit, ImportError, OSError, ValueError):
        return set()


def handles():
    """{Jira name: display name} for each roster person whose Jira name is not the display name: a page written for
    the owner names people the roster's way, never by a handle (the 2026-10-28 brief wrote Andyzhao beside
    Andy Zhao). Empty when the roster cannot be read."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "team"))
        import team                                     # the roster, read the team skill's way
        roster = team.read_roster(team.records())[1]
    except (SystemExit, ImportError, OSError, ValueError):
        return {}
    return {p["jira_name"]: p["name"] for p in roster
            if p.get("jira_name") and p.get("name") and p["jira_name"].lower() != p["name"].lower()}


def cmd_lint(args):
    try:
        text = open(args.page, encoding="utf-8").read()
    except OSError as e:
        print(f"lint: {e}", file=sys.stderr); sys.exit(2)
    try:
        actions, counts, bundles, in_vault, brief = context(args.page, text, args.actions, args.date)
    except ValueError as e:
        print(f"lint: {e}", file=sys.stderr); sys.exit(2)
    date = args.date or page_date(args.page, text)
    fails = lint(text, actions, counts, bundles, in_vault, brief, handles(), under_test(date) if brief and date else None)
    if args.json:
        print(json.dumps({"page": args.page, "failures": fails}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(fails))
    sys.exit(1 if fails else 0)



# ── replay: what ela said on a day, against what the sources show now ─────────────────────────────────

EX_REMOTE = 3
BACK = {"review": 2, "in review": 2, "done": 3, "closed": 3, "resolved": 3}
EARLY = {"backlog": 0, "to do": 0, "open": 0, "reopened": 0, "in progress": 1}
NUDGE_RX = re.compile(r"\b(?:ask|nudge|remind|chase|ping)\s+([A-Z][a-z]+)")
QUIET = ("helm lookout",)                               # Helm's auto-writes show under their own name, never a reply


def sure_rows(runtime, reports, date):
    """The `sure` readings ela gave on D: the refresh findings of a pass on D, and the fix pages' Timeline rows dated
    D whose reading is sure. (rows, gaps)."""
    out, gaps = [], []
    path = os.path.join(runtime, "runner", "ticket-findings.jsonl")
    seen_d = False
    try:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if str(r.get("pass_at") or "")[:10] == date:
                seen_d = True
                if r.get("sure") and str(r.get("reading", "")).startswith("sure"):
                    out.append({"key": r["key"], "reading": r["reading"], "at": r.get("at"), "source": "refresh"})
    except (OSError, ValueError):
        pass
    if not seen_d:
        gaps.append({"source": "ticket findings", "error": f"the findings file holds no pass of {date}; fix pages only"})
    md = date[5:]
    for key, page in T.pages(reports).items():
        try:
            text = open(page, encoding="utf-8").read()
        except OSError:
            continue
        for line in text.splitlines():
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
            if len(cells) >= 4 and cells[0] == md and cells[3].startswith("sure"):
                out.append({"key": key, "reading": cells[3], "at": f"{date}T23:59:59+0000", "source": "page"})
    return out, gaps


def contradicted(sure, issues, qa):
    """A sure reading that a later change on the ticket undoes: a status moved back or reopened, or a QA fail."""
    rows = []
    for s in sure:
        row, since = issues.get(s["key"]), B.parse_ts(s.get("at") or "")
        if not row or not since:
            continue
        for ev in row.get("events") or []:
            at = B.parse_ts(ev.get("at"))
            frm, to = str(ev.get("from") or "").lower(), str(ev.get("to") or "").lower()
            if at and at > since and ev.get("field") == "status" and (to == "reopened" or (frm in BACK and to in EARLY)):
                rows.append({"kind": "sure_contradicted", "key": s["key"], "said": s["reading"],
                             "now": f"status {ev.get('from')} → {ev.get('to')} by {ev.get('by')} ({ev.get('at', '')[:10]})"})
                break
        else:
            for c in row.get("comments") or []:
                at = B.parse_ts(c.get("at"))
                if at and at > since and str(c.get("by") or "").lower() in qa and T.FAIL_RX.search(c.get("text") or "") \
                        and not T.NO_REPRO_RX.search(c.get("text") or ""):
                    rows.append({"kind": "sure_contradicted", "key": s["key"], "said": s["reading"],
                                 "now": f"QA fail by {c.get('by')} ({c.get('at', '')[:10]}): {T.first_sentence(c.get('text') or '', 120)}"})
                    break
    return rows


def called_moves(page):
    """The morning page's lanes table: [(lane as shown, service, version called)] for each ▲ cell."""
    out, head = [], None
    for line in page.splitlines():
        if not line.startswith("|"):
            head = None if not line.strip() else head
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = cells
            continue
        for lane, cell in zip(head[1:], cells[1:]):
            m = re.match(r"▲\s*(\S+)", cell)
            if m and lane:
                svc = re.search(r"\(([\w-]+)\)\s*$", cells[0])
                out.append((lane, svc.group(1) if svc else cells[0], m.group(1)))
    return out


def miscalled(page, snap):
    """A version the page called moved that the next lane read does not hold: that read's version is older, or the
    lane is not read at all. A newer one is a later move, not a miscall."""
    shown = {v: k for k, v in B.LANE_SHOWN.items()}
    rows = []
    for lane, svc, called in called_moves(page):
        if not snap:
            break
        got = next((r for r in snap.get("rows") or [] if r["lane"] == shown.get(lane, lane) and r["service"] == svc), None)
        want, have = B.vkey(called), B.vkey((got or {}).get("version"))
        if want and (not have or have < want):
            rows.append({"kind": "version_miscalled", "key": None, "said": f"{lane} {svc} moved to {called}",
                         "now": f"the {snap.get('date')} read holds {B.short_version(got['version']) if got else 'no row'}"})
    return rows


def action_key(a):
    keys = B.keys_in(f"{a.get('command', '')} {a.get('text', '')}")
    return keys[0] if keys else None


def answered_nudges(actions, issues, me):
    """A nudge drafted for someone who had already answered: their latest comment on the ticket, before the draft, is
    later than the owner's latest."""
    rows = []
    for a in actions:
        m = NUDGE_RX.search(a.get("text") or "")
        key, drafted = action_key(a), B.parse_ts(a.get("drafted"))
        if not m or not key or key not in issues or not drafted:
            continue
        who = m.group(1).lower()
        last = lambda pred: max((B.parse_ts(c["at"]) for c in issues[key].get("comments") or []  # noqa: E731
                                 if pred(str(c.get("by") or "").lower()) and B.parse_ts(c["at"]) and B.parse_ts(c["at"]) < drafted), default=None)
        theirs, mine = last(lambda b: b.split()[:1] == [who]), last(lambda b: b == (me or "").lower())
        if theirs and (not mine or theirs > mine):
            rows.append({"kind": "nudge_answered", "key": key, "said": f"apply {a.get('n')}: {a.get('text', '')[:100]}",
                         "now": f"{m.group(1)} commented {theirs.isoformat(timespec='minutes')}, before the draft"})
    return rows


def next_workday_end(t):
    d = t.date() + datetime.timedelta(days=1)
    while not B.is_working_day(d):
        d += datetime.timedelta(days=1)
    return datetime.datetime.combine(d, datetime.time(23, 59), t.tzinfo)


def applied_no_change(actions, issues, me, now):
    """An applied action after which nobody but the owner and Helm changed the ticket for a working day."""
    rows = []
    for a in actions:
        key = action_key(a)
        at = B.parse_ts(a.get("applied"))
        if not at or not key:
            continue
        until = next_workday_end(at)
        if now < until:
            continue
        if key not in issues:
            continue
        row = issues[key]
        moved = [x for x in (row.get("events") or []) + (row.get("comments") or [])
                 if (t := B.parse_ts(x.get("at"))) and at < t <= until
                 and str(x.get("by") or "").lower() not in {(me or "").lower(), *QUIET}]
        if not moved:
            rows.append({"kind": "applied_no_change", "key": key, "said": f"apply {a.get('n')}: {a.get('text', '')[:100]}",
                         "now": f"applied {at.isoformat(timespec='minutes')}; no change by anyone else through {until.date()}"})
    return rows


def jira_changes(keys, since, e):
    """{key: {events, comments}} for the keys, read from Jira since a time; (issues, gaps)."""
    issues, gaps = {}, []
    for proj in sorted({k.split("-")[0] for k in keys}):
        try:
            got = B.run_json(["python3", B.JIRA, *e, "changes", "--project", proj, "--since", since, "--limit", "400", "--json"])
            issues.update({r["key"]: r for r in got["issues"] if r["key"] in keys})
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
            gaps.append({"source": f"jira {proj}", "error": str(x)[:200]})
    return issues, gaps


STATUS_NAMES = {"backlog", "to do", "open", "in progress", "review", "in review", "qa", "done", "closed", "reopened",
                "blocked", "resolved"}
CLEAR_RX = re.compile(r"\bfixed-in\s+([A-Z][A-Z0-9]+-\d+)\b.*--clear\b")


def field_claims(page, people, me):
    """What the page states a ticket's fields hold: [(key, field, value, where)]. Read from each item's facts line,
    where a field follows its key until the next key: a status (optionally ", assignee"), a roster name, "yours", or
    "Fixed In <value>". A field naming two people is not a claim about one ticket."""
    out = []
    for head, facts, _ in items(page):
        n = re.match(r"###\s+(\d+)\.", head)
        where = f"item {n.group(1)}" if n else head[:30]
        key = (B.keys_in(head) or [None])[0]
        for part in (p.strip() for p in facts.split(" · ")):
            k = re.fullmatch(r"(?:\[)?([A-Z][A-Z0-9]+-\d+)(?:\]\([^)]*\))?", part)
            if k:
                key = k.group(1); continue
            if not key or "/" in part:
                continue
            first, _, rest = part.partition(",")
            if first.strip().lower() in STATUS_NAMES:
                out.append((key, "status", first.strip(), where))
                if rest.strip().lower() in people:
                    out.append((key, "assignee", rest.strip(), where))
            elif part.lower() in people:
                out.append((key, "assignee", part, where))
            elif part.lower() == "yours" and me:
                out.append((key, "assignee", me, where))
            elif part.lower().startswith("fixed in "):
                out.append((key, "Fixed In", part[9:].strip(), where))
    return out


def value_at(current, events, field, t):
    """A field's value at time t: today's value with every later change of that field undone, newest first."""
    later = sorted((ev for ev in events if ev.get("field") == field and (B.parse_ts(ev["at"]) or t) > t),
                   key=lambda ev: B.parse_ts(ev["at"]), reverse=True)
    for ev in later:
        current = ev.get("from") or ""
    return current


def wrong_fields(claims, actions, fields, issues, t, aliases):
    """Field claims and drafted Fixed In clears that Jira contradicts at the page's time. `fields` {key: {status,
    assignee, Fixed In}} read now, `issues` the changes since, `aliases` {Jira name: display name}."""
    same = lambda a, b: (aliases.get(a, a) or "").strip().lower() == (aliases.get(b, b) or "").strip().lower()  # noqa: E731
    rows = []
    for key, field, said, where in claims:
        if key not in fields:
            continue
        was = value_at(fields[key].get(field) or "", (issues.get(key) or {}).get("events") or [], field, t)
        ok = bool(was) if field == "Fixed In" else same(said, was)
        if not ok:
            rows.append({"kind": "field_wrong", "key": key, "said": f"{where}: {field} {said}", "now": f"Jira held {was or 'nothing'}"})
    for a in actions:
        m = CLEAR_RX.search(a.get("command") or "")
        if m and m.group(1) in fields:
            was = value_at(fields[m.group(1)].get("Fixed In") or "", (issues.get(m.group(1)) or {}).get("events") or [], "Fixed In", t)
            if not was:
                rows.append({"kind": "field_wrong", "key": m.group(1), "said": f"apply {a.get('n')}: clear Fixed In",
                             "now": "Jira held no Fixed In: a write that changes nothing"})
    return rows


def jira_fields(keys, e):
    """{key: {status, assignee, Fixed In}} read from Jira now; (fields, gaps)."""
    out, gaps = {}, []
    for k in sorted(keys):
        try:
            f = B.run_json(["python3", B.JIRA, *e, "read", k, "--no-comments", "--json"])["fields"]
        except (B.LaneError, subprocess.TimeoutExpired, ValueError, KeyError) as x:
            gaps.append({"source": f"jira read {k}", "error": str(x)[:200]}); continue
        raw = f.get(T.J.FIXED_IN_FIELD)
        out[k] = {"status": (f.get("status") or {}).get("name") or "", "assignee": (f.get("assignee") or {}).get("displayName") or "",
                  "Fixed In": (raw if isinstance(raw, str) else T.J.body_text(raw) if raw else "").strip()}
    return out, gaps


COUNT_NAMES = (("sure_contradicted", "sure reading contradicted", "sure readings contradicted"),
               ("field_wrong", "field claim wrong", "field claims wrong"),
               ("version_miscalled", "version miscalled", "versions miscalled"),
               ("nudge_answered", "nudge already answered", "nudges already answered"),
               ("applied_no_change", "applied action with no change", "applied actions with no change"))


def summary(date, counts):
    """The facts-page line: "replay of 10-27: 0 sure readings contradicted, 1 version miscalled, …"."""
    return f"replay of {date[5:]}: " + ", ".join(f"{counts[k]} {one if counts[k] == 1 else many}" for k, one, many in COUNT_NAMES)


def replay(date, site_, e, me, now=None):
    now = now or datetime.datetime.now().astimezone()
    reports, runtime, _ = roots(site_)
    gaps = []
    try:
        page = open(os.path.join(reports, "runner", f"{date}-brief.md"), encoding="utf-8").read()
    except OSError:
        page = ""
        gaps.append({"source": "morning page", "error": f"no {date}-brief.md"})
    try:
        actions = json.load(open(os.path.join(reports, "runner", f"{date}-actions.json"), encoding="utf-8"))
    except (OSError, ValueError):
        actions = []
    sure, g = sure_rows(runtime, reports, date)
    gaps += g
    keys = {s["key"] for s in sure} | {k for a in actions if (k := action_key(a))}
    since = (datetime.date.fromisoformat(date) - datetime.timedelta(days=3)).isoformat() + " 00:00"
    issues, g = jira_changes(keys, since, e) if keys else ({}, [])
    gaps += g
    runner = os.path.join(runtime, "runner")
    nxt = (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()
    snap = B.snapshot_on_or_after(runner, nxt)
    if not snap:
        gaps.append({"source": "lane read", "error": f"no versions snapshot on or after {nxt}"})
    qa, _ = T.qa_names()
    aliases = handles()
    claims = field_claims(page, {n.lower() for n in aliases.values()} | {n.lower() for n in aliases} | roster_names(), me)
    fkeys = {c[0] for c in claims} | {m.group(1) for a in actions if (m := CLEAR_RX.search(a.get("command") or ""))}
    fields, g = jira_fields(fkeys, e) if fkeys else ({}, [])
    gaps += g
    more, g = jira_changes(fkeys - set(issues), since, e) if fkeys - set(issues) else ({}, [])
    issues, gaps = {**issues, **more}, gaps + g
    page_path = os.path.join(reports, "runner", f"{date}-brief.md")
    at = datetime.datetime.fromtimestamp(os.path.getmtime(page_path)).astimezone() if os.path.isfile(page_path) else now
    rows = contradicted(sure, issues, qa) + wrong_fields(claims, actions, fields, issues, at, aliases) + miscalled(page, snap) \
        + answered_nudges(actions, issues, me) + applied_no_change(actions, issues, me, now)
    counts = {k: sum(r["kind"] == k for r in rows) for k, _, _ in COUNT_NAMES}
    return {"date": date, "at": now.isoformat(timespec="seconds"), "counts": counts, "rows": rows,
            "read": {"sure_readings": len(sure), "field_claims": len(claims), "actions": len(actions), "called_moves": len(called_moves(page)),
                     "snapshot": (snap or {}).get("date")},
            "gaps": gaps, "summary": summary(date, counts)}


def cmd_replay(args):
    try:
        datetime.date.fromisoformat(args.date)
    except ValueError:
        print(f"replay: not a date: {args.date}", file=sys.stderr); sys.exit(2)
    s = site()
    e = ["--env-file", args.env_file] if args.env_file else []
    out = replay(args.date, s, e, B.owner_jira_name(e))
    reports, _, _ = roots(s)
    path = os.path.join(reports, "review", f"{args.date}-replay.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    T.atomic_write(path, json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        for r in out["rows"]:
            print(f"  {r['kind']}: {r['key'] or ''} {r['said']} — {r['now']}")
        for g in out["gaps"]:
            print(f"  not read: {g['source']}: {g['error'][:100]}")
        print(out["summary"])                               # last: the runner keeps the last line for the facts page
    if any(g["source"].startswith("jira") for g in out["gaps"]):
        sys.exit(EX_REMOTE)



# ── reader: the evening read of the morning page, as the owner would read it ───────────────────────────

VERDICTS = ("wrong", "handed back", "question", "noise", "tickable")   # in precedence order (brief SKILL §reader)
PAGE_LINES = ("Read first", "Skipped", "Missing")


def page_items(text):
    """The morning page's items: [{n, title, keys}]."""
    out = []
    for head, facts, _ in items(text):
        m = re.match(r"###\s+(\d+)\.\s+(.*)", head)
        if m:
            out.append({"n": int(m.group(1)), "title": m.group(2).strip(), "keys": B.keys_in(head + "\n" + facts)})
    return out


def reader_rows(text):
    """The reader file's item table: [{n, item, verdict, line}] from rows `| N. title | verdict | line |`."""
    out = []
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        m = re.match(r"(\d+)\.\s*(.*)", cells[0]) if len(cells) >= 3 else None
        if m:
            out.append({"n": int(m.group(1)), "item": m.group(2), "verdict": cells[1].lower(), "line": cells[2]})
    return out


def reader_check(page, reader):
    """Gaps in a reader file against its page: an item with no verdict or two, a verdict outside the set, an empty
    line, a missing page line."""
    fails = []
    rows, want = reader_rows(reader), page_items(page)
    by_n = {}
    for r in rows:
        by_n.setdefault(r["n"], []).append(r)
    for it in want:
        got = by_n.get(it["n"], [])
        if not got:
            fails.append(f"item {it['n']}: no verdict")
        elif len(got) > 1:
            fails.append(f"item {it['n']}: {len(got)} verdicts, one only")
    for r in rows:
        if r["n"] not in {i["n"] for i in want}:
            fails.append(f"item {r['n']}: not on the page")
        if r["verdict"] not in VERDICTS:
            fails.append(f"item {r['n']}: verdict {r['verdict']!r} is not one of {', '.join(VERDICTS)}")
        if not r["line"]:
            fails.append(f"item {r['n']}: a verdict without its line")
    for name in PAGE_LINES:
        if not re.search(r"^\s*[-*]\s+\*\*" + name + r":\*\*\s*\S", reader, re.M):
            fails.append(f"the page line **{name}:** is missing")
    return fails


KINDS = {"wrong": "wrong", "handed back": "handed-back", "question": "question"}


def reader_findings(page, reader):
    """The reader file as findings the next morning's judge takes as input: one per item read wrong, handed back or
    left as a question, and one for what he would skip: [{kind, item, key, what}]. Tickable and noise items are not
    findings; noise is already what Skipped says."""
    keys = {i["n"]: i["keys"] for i in page_items(page)}
    out = []
    for r in reader_rows(reader):
        if r["verdict"] in KINDS:
            k = keys.get(r["n"]) or B.keys_in(r["item"])
            out.append({"kind": KINDS[r["verdict"]], "item": r["n"], "key": k[0] if k else None, "what": r["line"]})
    m = re.search(r"^\s*[-*]\s+\*\*Skipped:\*\*\s*(.+)$", reader, re.M)
    if m:
        out.append({"kind": "skippable", "item": None, "key": None, "what": m.group(1).strip()})
    return out


def repeated_verdicts(reports, date):
    """Keys that carried the same reader verdict (other than tickable) on the two latest reader files up to D:
    {key: verdict}. The page fails §reader for each."""
    files = sorted(f for f in glob.glob(os.path.join(reports, "review", "*-reader.md")) if os.path.basename(f)[:10] <= date)[-2:]
    if len(files) < 2:
        return {}
    seen = []
    for f in files:
        try:
            rows = reader_rows(open(f, encoding="utf-8").read())
        except OSError:
            return {}
        seen.append({k: r["verdict"] for r in rows if r["verdict"] != "tickable" for k in B.keys_in(r["item"])})
    return {k: v for k, v in seen[1].items() if seen[0].get(k) == v}


def cmd_reader(args):
    reports, runtime, _ = roots(site())
    page_path = os.path.join(reports, "runner", f"{args.date}-brief.md")
    out_path = os.path.join(reports, "review", f"{args.date}-reader.md")
    try:
        page = open(page_path, encoding="utf-8").read()
    except OSError:
        print(f"reader: no morning page {page_path}", file=sys.stderr); sys.exit(2)
    if args.check:
        try:
            reader = open(out_path, encoding="utf-8").read()
            fails = reader_check(page, reader)
        except OSError:
            reader, fails = None, [f"no reader file {out_path}"]
        if not fails:                                   # the next morning's judge reads these (brief SKILL §3b)
            with open(out_path[:-3] + ".json", "w", encoding="utf-8") as f:
                json.dump(reader_findings(page, reader), f, ensure_ascii=False, indent=1)
        print(json.dumps({"reader": out_path, "failures": fails}, ensure_ascii=False) if args.json else "\n".join(fails))
        sys.exit(1 if fails else 0)
    ctx = {"date": args.date, "page": page_path, "write": out_path, "items": page_items(page),
           "verdicts": list(VERDICTS), "page_lines": list(PAGE_LINES),
           "actions": os.path.join(reports, "runner", f"{args.date}-actions.json"),
           "replay": os.path.join(reports, "review", f"{args.date}-replay.json"),
           "lint": lint(page, *context(page_path, page)[:4]),
           "rules": [os.path.expanduser("~/.claude/ela/working-with-evan.md"), "skills/brief/SKILL.md §reader"],
           "repeated": repeated_verdicts(reports, args.date)}
    if args.json:
        print(json.dumps(ctx, ensure_ascii=False, indent=1))
    else:
        print(f"read {page_path} as the owner; write {out_path}")
        for it in ctx["items"]:
            print(f"  {it['n']}. {it['title']}")
        for f in ctx["lint"]:
            print(f"  lint: {f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="ela's env file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint", help="mechanical checks on any page ela writes; exit 1 with one line per failure")
    p.add_argument("page")
    p.add_argument("--actions", help="the day's actions file (default <reports>/runner/<date>-actions.json for a brief page)")
    p.add_argument("--date", help="the page's day, YYYY-MM-DD (default: from its name or header)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("replay", help="what ela said on a day against what the sources show now; <reports>/review/<D>-replay.json")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("reader", help="the evening reader session's inputs, or --check its <reports>/review/<D>-reader.md")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--check", action="store_true", help="verify the reader file: one verdict per item, the page's three lines")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_reader)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
