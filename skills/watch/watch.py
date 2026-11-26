#!/usr/bin/env python3
"""watch — the MH board watched: every open MH ticket tracked each pass, a decision due on a trigger, ela's writes
signed. Stdlib only.

L1 capability (decision 2026-11-24, elak blueprint/decisions/2026-11-24-ela-watches-the-mh-board-and-acts-on-jira-
signing-each-write.md). Each pass reads every MH ticket that is not Done from the fact store (<runtime>/facts/jira/
issues), not only the owner's, and compares it with the last pass. A ticket is due a decision on a trigger:

  changed     a change that calls for a response: reopened or blocked, handed to the owner or to nobody, raised to
              Highest, or a new question addressed to the owner (on his ticket, or naming him)
  answered    a question the owner (or ela) asked on the ticket has a reply since
  unanswered  the last comment is someone's question, unanswered past QUESTION_WAIT_H
  unassigned  in progress, in review or reopened with nobody on it
  behind      its assignee wrote that it is fixed or merged while it is still in progress
  owner-held  assigned to the owner: ela settles it or hands it to whoever should hold it
  stalled     no activity past its status's threshold (STALL_DAYS)
  tracked     a ticket the owner asked ela to track (`track`) had a change by a person since its last decision: a
              field, a comment or a link, not by ela, the owner or an app (the fact store's changelog and comments)

A state trigger (all but changed and answered) fires only when no decision was recorded since the ticket last moved,
so nothing is written on a schedule; a change trigger waits as pending until a decision takes it. Left alone: legacy
(no activity for LEGACY_DAYS, outside the active sprint and the current release lines), held tickets (holds.json,
`ela: hold <key>`), and a ticket that already had its set of writes today. The owner's tickets come first.

The decision itself is judgment: a model session (the runner starts one, as for its other judgment passes, following
/ela:watch) reads `prompt`, writes one decision per triggered ticket to a file, and `decide` checks and carries them:
act (the writes, one set per ticket a day, through `ela dry`'s tier-1 class board-watch, each announced by a signed
comment that jira.py signs and checks), ask (the owner's topic: today.md and his ela DM, `asks`/`dm`), or none. An act
at low confidence writes nothing: it is held as the owner's topic, A its writes and comment exactly as decided, B leave
it, listed first on ela/watch.md under "Confirm first" (the owner's ruling, 2026-11-26).
Never by ela, always an ask: a terminal status, a Slack post under his name, a customer channel, anything about people.

A reply after ela's signed comment is judged too: the session marks each one the scan lists as disputing the comment or
not, and only a plain `"disputes": false` is agreement (unsure, or no mark, counts as a dispute). A dispute is a
correction that quiets the ticket, never the class: `ela dry`'s record takes verdict corrected with the act id, the
reply's link, the ticket and the field (comment), board-watch keeps its tier, the reply becomes an ask on today.md
naming the ticket and the reply, and ela posts no comment on that ticket for DISPUTE_QUIET_DAYS. A revert (`ela dry
undo`), his `wrong:` in did.md or `ela dry correct board-watch` quiets the field it names the same way. Each correction
is kept once in watch/corrections.jsonl with its case kind (the trigger kind, the field, how it was corrected).

  scan    [--date D] [--write] [--json]         every tracked ticket against the last pass; the triggered ones,
                                                the owner's first; --write stores the pass (<reports>/ela/watch.json,
                                                <reports>/ela/watch/<date>-scan.json)
  prompt  [--date D] [--json]                   the session's input: each triggered ticket, its triggers and facts
  decide  --from FILE [--date D] [--apply] [--json]
                                                the session's decisions checked and carried: replies judged (a dispute
                                                recorded as a correction and asked), acts run through
                                                `ela dry` (each a dry run unless --apply), asks stored as topics,
                                                and the owner's answered asks carried out; nothing is applied
                                                without --apply
  judge   [--date D] [--json]                   the judge queue: the owner's tickets in Review or handed to him, due a
                                                judging (one session per ticket, the runner's deep reading in its judge
                                                mode; plan ela/2026-11-26-plan-tickets-reach-you-judged)
  judge-prompt KEY [--write PAGE] [--date D] [--json]
                                                the judging session's input: the ticket, every comment, its links, its
                                                home in the vault, the owner's topics on it (a letter binds)
  decide  --judge KEY [--from FILE] [--apply]   the judging session's one decision (<reports>/ela/watch/<date>-judge-
                                                KEY.json), checked against the judge queue; an act or none closes the
                                                ticket's open topic as superseded
  judged  KEY --verdict TEXT | --failed         the runner's record of a judging, after the page and decide: one line,
                                                its own clock (watch.json `judgment`), appended to watch/judgments.jsonl
  answer  TOPIC A|B|C [WORDS…] [--json]         his letter on a topic (a tick or an `ela:` line on ela/watch.md, or
                                                said): recorded with his words; an option with writes is carried out at
                                                the next decide --apply. A letter other than A on a ruling is a
                                                correction, kept in watch/corrections.jsonl with its cause (or as
                                                waiting for one); a fact topic's words are the fact, kept by `ela asks`
  cause   TOPIC WORDS… [--json]                 the cause for an earlier correction that came without one
  track   KEY… [--why TEXT] [--until DATE] [--json]
                                                track tickets (<reports>/ela/watch/tracked.json): each is due a
                                                decision on any human change, so its state comes back judged; never
                                                legacy while tracked. --until ends it on that day
  untrack KEY… [--json]                         end tracking; the row is kept, marked ended
  review  prompt [--json] | settle --from FILE [--apply] | release [--apply]
                                                the second reading, once a pass after the decision: a ruling ask whose
                                                option A is only the watch's own writes, and a low act, wait as
                                                review-pending (off ela/watch.md and the DM) until a reader session with
                                                the decider's tools settles one by a first-hand source {kind, ref} from
                                                SOURCES, or releases it to the owner marked "read twice, not settled".
                                                release (the runner, on the reader's failure or timeout) hands every
                                                pending one to him marked "not read twice"; one pending past
                                                REVIEW_WAIT_H is shown so marked anyway. A settled low act stays held
                                                for him, its source shown (LOW_ACTS_SETTLE_ON_READ)
  measure [--weeks N] [--json]                  the share of ticket work ela settled without the owner, week by week:
                                                decisions (the backlog apart), corrections, nones a person overturned,
                                                and every ticket change attributed (app, ela unattended, the owner
                                                through ela, the owner in Jira, a person); the vault page
                                                ela/watch-measure.md, linked once from ela/watch.md
  asks    [--json]                              the open topics; the vault's sync puts them on ela/watch.md (and a
                                                line on today.md), where they live
  dm      [--apply] [--json]                    the owner's ela DM, a reminder only: at most one message a day, when a
                                                topic is new — the count, the new ones a line each, the vault page and
                                                the CLI verb; no thread per topic; a dry run unless --apply
Kept for the measure and any later replay: <reports>/ela/watch/decided.jsonl (each carried decision: verdict,
confidence, trigger kinds, fields written, and on a none `judged_unneeded`), <reports>/ela/watch/<date>-<HHMM>-prompt.json
(each pass's prompt as JSON, beside its scan).
Store: <reports>/ela/watch.json (per ticket: the last pass's snapshot, pending triggers, the last decision, the day of
its last set of writes, the comments ela said, the replies judged, the day a reply disputed ela), <reports>/ela/watch/<date>-scan.json, <reports>/ela/watch-topics.json,
<reports>/ela/drafts/watch/ (each comment's text, the file a write names), <reports>/ela/watch/corrections.jsonl
(his letters against ela, by class: the trigger kind, KINDS).
Exit codes: 0 ok · 2 usage · 3 not found.
"""
import argparse, datetime, hashlib, json, os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "jira"))
sys.path.insert(0, os.path.join(SKILLS, "focus"))
import jira as J  # noqa: E402 — the signing rule and the comment's text: one place
import hold as H  # noqa: E402 — the holds, `ela: hold <key>`
sys.path.insert(0, os.path.join(SKILLS, "slack"))
import tiers as TI  # noqa: E402 — the information tier of each kind of notice: one table
import slacktext as ST  # noqa: E402 — a Jira key as its link, a title cut at a word

SITE = os.path.expanduser("~/.claude/ela/site.json")
TZ = datetime.timezone(datetime.timedelta(hours=8))
EX_USAGE, EX_NOTFOUND = 2, 3
PROJECT = "MH"
CLASS = "board-watch"
LEGACY_DAYS = 60
QUESTION_WAIT_H = 48
STALL_DAYS = {"In Progress": 2, "Reopened": 2, "Review": 5, "Blocked": 7, "On Hold": 14}
ACTIVE = ("In Progress", "Review", "Reopened")
MOVED_MARGIN = datetime.timedelta(minutes=15)   # ela's own write moves the ticket: within this, it is not a move
MAX_PER_PASS = int(os.environ.get("ELA_WATCH_MAX") or 25)   # the session's load in one pass (the runner caps the rollout); the rest wait, the owner's first
DISPUTE_QUIET_DAYS = 7                         # no comment from ela on a ticket where a reply disputed it, for this long
VERBS = ("assign", "transition", "priority", "due", "link")
SPRINT_FIELD = "customfield_10020"
DONE = ("Done", "Cancelled", "Closed", "Failed", "Closed Ambigous")
QUESTION = re.compile(r"[?\uff1f]|\u5417[\u3002\s]*$|\u8bf7\u95ee|\bcan you\b|\bcould you\b|\bplease\b", re.I | re.M)
FIXED = re.compile(r"\b(?:fixed|merged|deployed|resolved)\b|\u5df2\u4fee\u590d|\u5df2\u5408\u5e76|\u5df2\u90e8\u7f72|\u5df2\u89e3\u51b3", re.I)
# a backstop for the rule the session follows: a comment ela writes is about the work, never about a person
ABOUT_PEOPLE = re.compile(r"\b(?:performance|lazy|careless|attitude|incompetent|ignor(?:ed|ing) (?:this|it)|always late|"
                          r"slow to respond|your fault|his fault|her fault)\b", re.I)


# ── the site and the stores ───────────────────────────────────────────────────────────────────────────────────────
def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def now_tz():
    return datetime.datetime.now(TZ)


def read_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    os.replace(path + ".tmp", path)


def state_path(reports):
    return os.path.join(reports, "ela", "watch.json")


def scan_path(reports, day):
    return os.path.join(reports, "ela", "watch", f"{day}-scan.json")


def topics_path(reports):
    return os.path.join(reports, "ela", "watch-topics.json")


def load_state(reports):
    st = read_json(state_path(reports), {})
    st.setdefault("tickets", {})
    st.setdefault("passes", [])
    return st


def load_topics(reports):
    t = read_json(topics_path(reports), {})
    t.setdefault("topics", {})
    t.setdefault("roots", {})
    return t


# ── reading a ticket ──────────────────────────────────────────────────────────────────────────────────────────────
def parse_ts(s):
    """A Jira time (`2026-11-20T10:00:00.000+0800`) as an aware datetime; None when it does not parse."""
    s = str(s or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?([+-]\d{2}):?(\d{2})?$", s)
    if m:
        return datetime.datetime.fromisoformat(f"{m.group(1)}{m.group(2)}:{m.group(3) or '00'}")
    try:
        d = datetime.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    except ValueError:
        return None


def name(v):
    return (v or {}).get("displayName") or (v or {}).get("name") or "" if isinstance(v, dict) else (v or "")


def fields(iss):
    return (iss or {}).get("fields") or {}


def is_open(iss):
    f = fields(iss)
    st = (f.get("status") or {})
    return not f.get("resolution") and ((st.get("statusCategory") or {}).get("key") != "done") and st.get("name") not in DONE


def comments(iss):
    c = (iss or {}).get("comments")
    if c is None:
        c = (fields(iss).get("comment") or {}).get("comments") or []
    return sorted(c, key=lambda x: str(x.get("created") or ""))


def text_of(body):
    if isinstance(body, str):
        return body
    try:
        return J.body_text(body) if body else ""
    except Exception:                                          # noqa: BLE001 — an odd body reads as empty
        return ""


def ticket_text(iss):
    f = fields(iss)
    return f"{f.get('summary') or ''}\n{text_of(f.get('description'))}"


def is_ela(c):
    return J.is_signed(text_of(c.get("body")))


def is_bot(c):
    """A comment no person wrote: an app's (Jira Automation copying a comment across, a bot)."""
    a = c.get("author") or {}
    return a.get("accountType") == "app" or name(a) in ("Automation for Jira",) or text_of(c.get("body")).startswith("(Copied from ")


def asks_something(text):
    """Whether a comment asks: a question mark or a request, links taken out (a URL's ? is not a question)."""
    return bool(QUESTION.search(re.sub(r"<?https?://\S+", " ", text or "")))


def is_owner(person, owner):
    if not person or not owner:
        return False
    if owner.get("id") and person.get("accountId"):
        return person["accountId"] == owner["id"]
    return bool(owner.get("name")) and name(person) == owner["name"]


def names_owner(text, owner):
    n = (owner or {}).get("name") or ""
    return bool(n) and (n.lower() in (text or "").lower() or ("@" + n.split()[0].lower()) in (text or "").lower())


def snap(iss):
    f = fields(iss)
    cs = comments(iss)
    last = cs[-1] if cs else {}
    return {"status": name(f.get("status")), "assignee": (f.get("assignee") or {}).get("accountId") or name(f.get("assignee")),
            "assignee_name": name(f.get("assignee")), "priority": name(f.get("priority")), "due": f.get("duedate"),
            "updated": str(f.get("updated") or iss.get("updated") or ""), "comments": len(cs),
            "last_comment": str(last.get("created") or "")}


def in_active_sprint(iss):
    return any(isinstance(s, dict) and s.get("state") == "active" for s in fields(iss).get(SPRINT_FIELD) or [])


def on_lines(iss, lines):
    labels = fields(iss).get("labels") or []
    return any(f"release:mh-{ln}" in labels or f"release:{ln}" in labels for ln in lines or [])


def legacy(iss, now, lines):
    moved = parse_ts(fields(iss).get("updated") or iss.get("updated"))
    quiet = moved is None or now - moved > datetime.timedelta(days=LEGACY_DAYS)
    return quiet and not in_active_sprint(iss) and not on_lines(iss, lines)


def current_lines():
    """The release lines in flight (the brief's followed lines: 2.2, 2.1 …); none when the map cannot be read."""
    try:
        sys.path.insert(0, os.path.join(SKILLS, "brief"))
        import brief as B                                      # noqa: E402
        return list(B.followed_lines())
    except Exception:                                          # noqa: BLE001
        return []


def owner_of(facts):
    """The owner as the fact store knows him: {id, name} from facts/jira/owner.json; {} when unknown."""
    d = read_json(os.path.join(facts or "", "jira", "owner.json"), {})
    a = (((d.get("issues") or [{}])[0].get("fields") or {}).get("assignee")) or {}
    return {"id": a.get("accountId"), "name": a.get("displayName")} if a else {}


def open_tickets(facts, project=PROJECT):
    d = os.path.join(facts or "", "jira", "issues")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.startswith(project + "-") and f.endswith(".json"):
            iss = read_json(os.path.join(d, f), None)
            if iss and is_open(iss):
                yield iss


# ── triggers ──────────────────────────────────────────────────────────────────────────────────────────────────────
def moved_since(iss, when):
    """Whether the ticket moved after `when` (an ISO time), ela's own write within MOVED_MARGIN aside."""
    if not when:
        return True
    moved, at = parse_ts(fields(iss).get("updated") or iss.get("updated")), parse_ts(when)
    return moved is None or at is None or moved > at + MOVED_MARGIN


def change_triggers(iss, prev, owner):
    """What changed since the last pass that calls for a response. → [(kind, says)]."""
    if not prev:
        return []
    s, out = snap(iss), []
    if s["status"] != prev.get("status") and s["status"] in ("Reopened", "Blocked"):
        out.append(("changed", f"moved {prev.get('status')} → {s['status']}"))
    if s["assignee"] != prev.get("assignee"):
        if not s["assignee"]:
            out.append(("changed", f"taken off {prev.get('assignee_name') or 'its assignee'}: nobody holds it"))
        elif is_owner(fields(iss).get("assignee"), owner):
            out.append(("changed", f"handed to the owner (from {prev.get('assignee_name') or 'nobody'})"))
    if s["priority"] == "Highest" and prev.get("priority") != "Highest":
        out.append(("changed", f"raised {prev.get('priority')} → Highest"))
    held = is_owner(fields(iss).get("assignee"), owner)
    for c in comments(iss):
        if str(c.get("created") or "") <= (prev.get("last_comment") or ""):
            continue
        t = text_of(c.get("body"))
        if is_ela(c) or is_bot(c) or is_owner(c.get("author"), owner):
            continue
        if asks_something(t) and (held or names_owner(t, owner)):
            out.append(("changed", f"{name(c.get('author'))} asked: {clip(t, 160)}"))
    return out


def answered_trigger(iss, rec, owner):
    """A question the owner or ela asked here, with a reply from someone else since the last decision."""
    cs = [c for c in comments(iss) if not is_bot(c)]
    for i in range(len(cs) - 1, 0, -1):
        c = cs[i]
        if is_ela(c) or is_owner(c.get("author"), owner):
            continue
        before = cs[i - 1]
        if (is_ela(before) or is_owner(before.get("author"), owner)) and asks_something(text_of(before.get("body"))):
            at, decided = parse_ts(c.get("created")), parse_ts(rec.get("decided"))
            if not decided or (at and at > decided):
                return [("answered", f"{name(c.get('author'))} replied to the question asked {str(before.get('created'))[:10]}: "
                                     f"{clip(text_of(c.get('body')), 160)}")]
        return []
    return []


# ── tracked tickets: the owner's word to follow a ticket's state ─────────────────────────────────────────────────────
def tracked_path(reports):
    return os.path.join(reports, "ela", "watch", "tracked.json")


def load_tracked(reports):
    d = read_json(tracked_path(reports), {})
    d.setdefault("tickets", {})
    return d


def tracking(reports, today):
    """The tickets tracked on `today`: {key: row}; an ended row or one past its until is not tracked."""
    return {k: r for k, r in (load_tracked(reports).get("tickets") or {}).items()
            if not r.get("ended") and (not r.get("until") or r["until"] >= today)}


def track(reports, keys, now, why=None, until=None):
    """Track tickets: each is due a decision on any human change. A ticket tracked again takes the new why and until and
    keeps its first day. → [row]."""
    d, out = load_tracked(reports), []
    for k in keys:
        k = k.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", k):
            raise ValueError(f"{k!r} is not a ticket key")
        if until and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", until):
            raise ValueError(f"--until {until!r}: a date YYYY-MM-DD")
        old = d["tickets"].get(k) or {}
        row = {"key": k, "since": old.get("since") if old and not old.get("ended") else now.isoformat(timespec="seconds"),
               "why": " ".join(str(why).split()) if why else old.get("why"), "until": until or None, "ended": None}
        d["tickets"][k] = row
        out.append(row)
    write_json(tracked_path(reports), d)
    return out


def untrack(reports, keys, now):
    """End tracking; the row is kept with the day it ended (nothing ela keeps is deleted). → [key ended]."""
    d = load_tracked(reports)
    done = []
    for k in keys:
        r = (d.get("tickets") or {}).get(k.strip().upper())
        if r and not r.get("ended"):
            r["ended"] = now.isoformat(timespec="seconds")
            done.append(r["key"])
    write_json(tracked_path(reports), d)
    return done


def changelog_of(facts):
    """The fact store's changelog histories by ticket (changes.json, the issues updated inside the horizon). → {key: [h]}."""
    out = {}
    for i in read_json(os.path.join(facts or "", "jira", "changes.json"), []) or []:
        if i.get("key"):
            out[i["key"]] = ((i.get("changelog") or {}).get("histories") or [])
    return out


def is_app(person):
    p = person or {}
    return p.get("accountType") == "app" or name(p) in ("Automation for Jira",)


def human_changes(iss, histories, since, owner):
    """What people changed on a ticket after `since`: field changes (status, assignee, priority, due, links …) and
    comments, not ela's (a signed comment, or a change on the owner's account), the owner's or an app's. → [says]."""
    t0, out = parse_ts(since), []
    for h in histories or []:
        at = parse_ts(h.get("created"))
        if not at or (t0 and at <= t0) or is_app(h.get("author")) or is_owner(h.get("author"), owner):
            continue
        for it in h.get("items") or []:
            f = it.get("field") or "?"
            out.append((str(h.get("created")), f"{name(h.get('author'))} changed {f}: {it.get('fromString') or '—'} → "
                                               f"{it.get('toString') or '—'}"))
    for c in comments(iss):
        at = parse_ts(c.get("created"))
        if not at or (t0 and at <= t0) or is_ela(c) or is_bot(c) or is_owner(c.get("author"), owner):
            continue
        out.append((str(c.get("created")), f"{name(c.get('author'))} commented: {clip(text_of(c.get('body')), 160)}"))
    return [x for _, x in sorted(out)]


def tracked_trigger(iss, rec, row, histories, owner):
    """A tracked ticket with a human change since its last decision (or since tracking began). → [(kind, says)]."""
    marks = [parse_ts(x) for x in (rec.get("decided"), row.get("since")) if x]
    since = max([m for m in marks if m], default=None)
    got = human_changes(iss, histories, since.isoformat() if since else None, owner)
    if not got:
        return []
    why = f" (tracked: {row['why']})" if row.get("why") else ""
    return [("tracked", "; ".join(got[-4:]) + (f"; and {len(got) - 4} more" if len(got) > 4 else "") + why)]


def state_triggers(iss, now, owner):
    """What the ticket's state calls for, whatever changed. → [(kind, says)]."""
    f, s, out = fields(iss), snap(iss), []
    if s["status"] in ACTIVE and not f.get("assignee"):
        out.append(("unassigned", f"{s['status']} with nobody on it"))
    cs = [c for c in comments(iss) if not is_bot(c)]
    if cs and s["status"] in ("In Progress", "Reopened"):
        last_by_assignee = next((c for c in reversed(cs) if f.get("assignee") and
                                 (c.get("author") or {}).get("accountId") == (f.get("assignee") or {}).get("accountId")), None)
        if last_by_assignee and FIXED.search(text_of(last_by_assignee.get("body"))):
            out.append(("behind", f"its assignee wrote it is done ({str(last_by_assignee.get('created'))[:10]}) while it is {s['status']}"))
    if cs:
        last = cs[-1]
        at = parse_ts(last.get("created"))
        t = text_of(last.get("body"))
        if (not is_ela(last) and not is_owner(last.get("author"), owner) and asks_something(t) and at
                and now - at > datetime.timedelta(hours=QUESTION_WAIT_H)):
            out.append(("unanswered", f"{name(last.get('author'))} asked {at:%m-%d} and nobody answered: {clip(t, 160)}"))
    if is_owner(f.get("assignee"), owner):
        out.append(("owner-held", "assigned to the owner: settle it or hand it to whoever should hold it"))
    moved = parse_ts(f.get("updated") or iss.get("updated"))
    lim = STALL_DAYS.get(s["status"])
    if lim and moved and now - moved > datetime.timedelta(days=lim):
        out.append(("stalled", f"{s['status']} and untouched for {(now - moved).days} days (threshold {lim})"))
    return out


def clip(text, n):
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


# ── replies to ela's signed comments ──────────────────────────────────────────────────────────────────────────────
def replies_to_ela(iss):
    """Each comment after a signed ela comment, a person's (a bot's copy aside), with the signed comment it follows:
    [(ela's comment, reply)]."""
    out, last = [], None
    for c in comments(iss):
        if is_ela(c):
            last = c
        elif last is not None and not is_bot(c):
            out.append((last, c))
    return out


def act_of(reports, key, at):
    """The board-watch act on record that ela's comment at `at` carried: the latest tier-1 row for the ticket written at
    or before it (within MOVED_MARGIN). → the record row, or None."""
    t, best = parse_ts(at), None
    for r in dry_mod().record(reports):
        if r.get("source") != "tier1" or r.get("target") != key or not r.get("act"):
            continue
        ra = parse_ts(r.get("at"))
        if t is None or ra is None or ra <= t + MOVED_MARGIN:
            best = r
    return best


def reply_id(c):
    return str(c.get("id") or c.get("created") or "")


def reply_link(base, key, cid):
    return f"{base}/browse/{key}?focusedCommentId={cid}" if base else f"{key} comment {cid}"


def quiet_until(rec):
    """The day ela may comment again on a ticket where a reply disputed it, or None when it is not quiet."""
    d = rec.get("disputed")
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=DISPUTE_QUIET_DAYS)).isoformat() if d else None


def quiets(reports, today):
    """The fields ela stays off, per ticket: a board-watch correction (a disputing reply, a revert, his `wrong:` or
    `ela dry correct`) quiets its field on its ticket for DISPUTE_QUIET_DAYS; the class keeps its tier (`ela dry`
    SCOPED; plan ela/2026-11-26-plan-sweep-judges-every-field, first slice 1). A correction naming no field quiets the
    ticket ("*"). → {key: {field: the day ela may write it again}}, only quiets still running on `today`."""
    D, out = dry_mod(), {}
    for r in D.record(reports):
        if r.get("source") != "correction" or r.get("class") not in D.SCOPED or not r.get("key"):
            continue
        try:
            until = (datetime.date.fromisoformat(str(r.get("at"))[:10]) + datetime.timedelta(days=DISPUTE_QUIET_DAYS)).isoformat()
        except ValueError:
            continue
        if until > today:
            f = out.setdefault(r["key"], {})
            fld = r.get("field") or "*"
            f[fld] = max(f.get(fld, ""), until)
    return out


def quiet_problem(writes, text, quiet):
    """Why a set touches a field a correction quieted on this ticket, or None. `quiet` is quiets()[key]."""
    if not quiet:
        return None
    if "*" in quiet:
        return f"a correction quieted this ticket: no write from ela until {quiet['*']}; an ask or none"
    for w in writes:
        v = "transition" if w.get("verb") == VERIFIED else w.get("verb")      # a close is a status change
        if v in quiet:
            return f"a correction quieted {v} on this ticket: not written by ela until {quiet[v]}; an ask or none"
    if text and "comment" in quiet:
        return f"a correction quieted ela's comments on this ticket until {quiet['comment']}; an ask or none"
    return None


def ela_replies(iss, rec, reports, base):
    """The replies to ela's signed comments on a ticket that no pass has judged yet, each with the act it answers."""
    key, judged, out = iss["key"], set(rec.get("judged") or []), []
    for ec, c in replies_to_ela(iss):
        rid = reply_id(c)
        if not rid or rid in judged:
            continue
        a = act_of(reports, key, ec.get("created")) or {}
        out.append({"key": key, "reply": rid, "by": name(c.get("author")), "at": str(c.get("created") or "")[:16],
                    "text": clip(text_of(c.get("body")), 500), "link": reply_link(base, key, rid),
                    "ela_comment": clip(J.unsigned(text_of(ec.get("body"))), 300), "ela_at": str(ec.get("created") or "")[:16],
                    "act": a.get("act"), "class": a.get("class") or CLASS, "summary": fields(iss).get("summary") or ""})
    return out


def scan(facts, reports, now, holds=None, lines=None, owner=None, write=False, base=None):
    """One pass. → {date, tracked, skipped: {legacy, held, done_today}, triggered: [row], waiting: [keys], replies:
    [the replies to ela's signed comments not judged yet]}. `base` the Jira URL a reply's link starts with."""
    st = load_state(reports)
    owner = owner_of(facts) if owner is None else owner
    holds = H.for_reports(reports, now.date()) if holds is None else holds
    lines = current_lines() if lines is None else lines
    today = now.date().isoformat()
    rows, skipped, tracked, replies, judge = [], {"legacy": 0, "held": [], "done_today": []}, 0, [], []
    quiet = quiets(reports, today)
    followed = tracking(reports, today)
    histories = changelog_of(facts) if followed else {}
    for iss in open_tickets(facts):
        key = iss["key"]
        rec = st["tickets"].setdefault(key, {"first": today})
        if any(is_ela(c) for c in comments(iss)):
            if base is None:
                base = jira_base()
            replies += ela_replies(iss, rec, reports, base)
        prev = rec.get("snap")
        pend = [p for p in rec.get("pending") or []]
        new = change_triggers(iss, prev, owner)
        if any(s.startswith("handed to the owner") for _, s in new):
            rec["handed"] = now.isoformat(timespec="seconds")   # the judging's own clock: kept past the quick pass's decision
        pend += [list(x) for x in new if list(x) not in pend]
        rec["pending"], rec["snap"] = pend, snap(iss)
        if legacy(iss, now, lines) and key not in followed:
            skipped["legacy"] += 1
            continue
        tracked += 1
        if H.holding(holds, [key], fields(iss).get("summary") or "", now.date()):
            skipped["held"].append(key)
            continue
        why = judge_due(iss, rec, owner, now)
        if why:
            f = fields(iss)
            judge.append({"key": key, "summary": f.get("summary") or "", "status": name(f.get("status")),
                          "priority": name(f.get("priority")), "updated": str(f.get("updated") or "")[:16], "why": why,
                          "handed": why == HANDED, "fails": int(rec.get("judge_fails") or 0)})
        if rec.get("acted") == today:
            skipped["done_today"].append(key)
            continue
        trig = [tuple(p) for p in pend] + answered_trigger(iss, rec, owner)
        if moved_since(iss, rec.get("decided")):
            trig += state_triggers(iss, now, owner)
        if key in followed:
            trig += tracked_trigger(iss, rec, followed[key], histories.get(key), owner)
        if not trig:
            continue
        f = fields(iss)
        rows.append({"key": key, "summary": f.get("summary") or "", "status": name(f.get("status")),
                     "assignee": name(f.get("assignee")) or None, "priority": name(f.get("priority")), "due": f.get("duedate"),
                     "labels": f.get("labels") or [], "updated": str(f.get("updated") or "")[:16],
                     "owner_held": is_owner(f.get("assignee"), owner), "chinese": J.chinese(ticket_text(iss)),
                     "quiet_until": quiet_until(rec) if (quiet_until(rec) or "") > today else None,
                     "quiet_fields": quiet.get(key) or None,
                     "tracked": {k: followed[key].get(k) for k in ("why", "until")} if key in followed else None,
                     "triggers": [{"kind": k, "says": s} for k, s in trig]})
    rows.sort(key=lambda r: (not (r["owner_held"] or r.get("tracked")), ("Highest", "High", "Medium", "Low", "Lowest").index(r["priority"])
                             if r["priority"] in ("Highest", "High", "Medium", "Low", "Lowest") else 5, r["key"]))
    out = {"date": today, "at": now.isoformat(timespec="seconds"), "tracked": tracked, "skipped": skipped,
           "triggered": rows[:MAX_PER_PASS], "waiting": [r["key"] for r in rows[MAX_PER_PASS:]], "owner": owner.get("name"),
           "replies": replies, "judge": judge_order(judge)}
    if write:
        st["passes"] = (st["passes"] + [{"at": out["at"], "tracked": tracked, "triggered": len(rows)}])[-60:]
        write_json(state_path(reports), st)
        write_json(scan_path(reports, today), out)
    return out


# ── the session's input ───────────────────────────────────────────────────────────────────────────────────────────
def prompt_rows(scanned, facts, keep=5):
    """Each triggered ticket with what the session judges it on: its fields, triggers and its last comments."""
    out = []
    for r in scanned.get("triggered") or []:
        iss = read_json(os.path.join(facts, "jira", "issues", f"{r['key']}.json"), {})
        cs = comments(iss)[-keep:]
        out.append(dict(r, description=clip(text_of(fields(iss).get("description")), 600),
                        links=len(fields(iss).get("issuelinks") or []),
                        comments=[{"by": name(c.get("author")), "at": str(c.get("created") or "")[:16], "ela": is_ela(c),
                                   "text": clip(text_of(c.get("body")), 500)} for c in cs]))
    return out


def precedent_lines(row, precedents, n=3):
    kinds = {t.get("kind") for t in row.get("triggers") or []}
    return [f"- {asks_mod().cite(p)}" for p in [p for p in precedents or [] if p.get("kind") in kinds][:n]]


def prompt_text(scanned, rows, decisions_path, precedents=()):
    L = [f"# The MH board watch · {scanned['date']}", "",
         f"Follow /ela:watch. {len(rows)} ticket{'s' if len(rows) != 1 else ''} due a decision; write one decision per "
         f"ticket to {decisions_path} as the skill describes, then check it with `ela watch decide --from {decisions_path}` "
         "(a dry run). Nothing here is applied by you.",
         "Every act and none carries \"confidence\": high | medium | low, and below high a \"doubt\": one line on what "
         "the evidence leaves open; decide refuses one without them. A low act writes nothing to Jira: it waits on "
         "ela/watch.md for the owner's confirm, its writes and comment as option A. An act you would not defend to the "
         "assignee is an ask.",
         "Every ask carries \"kind\": fact (ela cannot read it anywhere; add \"fact\": {\"kind\": one of "
         + ", ".join(asks_mod().FACT_KINDS) + ", \"key\": what it is about}; a fact already given is not asked again) or "
         "ruling (add \"why\": your leaning's reason, written into option A, so the owner answers right or wrong), and "
         "\"confidence\".", ""]
    for r in rows:
        L += [f"## {r['key']} · {r['summary']}",
              f"{r['status']} · {r['assignee'] or 'nobody'} · {r['priority']}" + (f" · due {r['due']}" if r.get("due") else "")
              + (" · the owner's ticket" if r["owner_held"] else "")
              + (f" · tracked on the owner's word: {r['tracked'].get('why') or 'no reason given'}" if r.get("tracked") else "") + (" · the ticket's text is Chinese" if r["chinese"] else "")
              + (f" · links {r['links']}: a comment is copied to each" if r.get("links") else "")
              + (f" · a reply disputed ela: no comment until {r['quiet_until']} (ask or none)" if r.get("quiet_until") else "")
              + (" · corrected, ela stays off: " + ", ".join(f"{'the ticket' if f == '*' else f} until {u}"
                                                            for f, u in sorted(r["quiet_fields"].items())) + " (ask or none)"
                 if r.get("quiet_fields") else ""),
              ""] + [f"- trigger {t['kind']}: {t['says']}" for t in r["triggers"]]
        cited = precedent_lines(r, precedents)
        if cited:
            L += ["", "Precedents (the owner's corrections of this kind; cite one if it decides the case; on a fail or a "
                  "\"nothing needed\" a precedent strengthens your leaning, it never replaces an ask):"] + cited
        if r.get("description"):
            L += ["", f"Description: {r['description']}"]
        L += [""] + [f"> {c['at']} {c['by']}{' (ela)' if c['ela'] else ''}: {c['text']}" for c in r["comments"]] + [""]
    if scanned.get("waiting"):
        L += [f"Waiting for the next pass: {', '.join(scanned['waiting'])}", ""]
    if scanned.get("replies"):
        L += ["# Replies to ela's signed comments", "",
              "For each, add {\"key\", \"reply\", \"disputes\": true | false | \"unsure\"} to the file's \"replies\" list: "
              "does it dispute what ela's comment said or did? Conservatively: false only when the reply plainly agrees, "
              "thanks, or answers without contesting; when unsure, it is a dispute.", ""]
        for x in scanned["replies"]:
            L += [f"## {x['key']} · reply {x['reply']} · {x['link']}",
                  f"> {x['ela_at']} ela: {x['ela_comment']}", f"> {x['at']} {x['by']}: {x['text']}", ""]
    return "\n".join(L)


# ── deciding ──────────────────────────────────────────────────────────────────────────────────────────────────────
def norm(text):
    return " ".join(J.unsigned(text or "").split()).casefold()


def said_before(iss, rec, text):
    """Whether ela already said this on the ticket: the same words (signature aside) in its record or its comments."""
    n = norm(text)
    if hashlib.sha1(n.encode()).hexdigest()[:16] in (rec.get("said") or []):
        return True
    return any(is_ela(c) and norm(text_of(c.get("body"))) == n for c in comments(iss))


def drafts_dir(reports):
    return os.path.join(reports, "ela", "drafts", "watch")


def command_of(key, w, note):
    """One write of a set as the exact command `ela dry` runs (jira.py signs and checks the note)."""
    v = w.get("verb")
    if v == "assign":
        return f"ela jira assign {key} --assignee {shlex.quote(str(w['assignee']))} --note-file {note}"
    if v == "transition":
        return f"ela jira transition {key} --to {shlex.quote(str(w['to']))} --note-file {note}"
    if v == "priority":
        return f"ela jira priority {key} --to {w['to']} --note-file {note}"
    if v == "due":
        return f"ela jira due {key} --date {w['date']} --note-file {note}"
    if v == "link":                                            # a link carries no comment (jira.py NOTE_VERBS)
        return f"ela jira link {key} {w['other']} --type {shlex.quote(str(w['type']))}"
    raise ValueError(v)


def check_act(key, d, iss, rec, today, quiet=None, runtime=None):
    """Why a decision to act may not go out, or None. `quiet` the fields a correction quieted here (quiets()[key]);
    `runtime` where a verified close's run is kept."""
    if rec.get("acted") == today:
        return "one set of writes a day: this ticket had its set today"
    vc = [w for w in d.get("writes") or [] if w.get("verb") == VERIFIED]
    if vc:
        if len(d.get("writes") or []) != 1:
            return "a verified close is its set's only write"
        if d.get("confidence") != "high":
            return "a verified close rests on a mechanical proof: confidence high, or a QA comment instead"
        problem = verified_gate(key, vc[0], runtime)
        if problem:
            return problem
        text = (d.get("comment") or "").strip()
        if not text or str(vc[0].get("lane")) not in text:
            return "a verified close carries the proof as its comment: the lane, the build and what passed"
        if ABOUT_PEOPLE.search(text):
            return "the comment speaks about a person; anything about people is the owner's: an ask"
        return J.language_problem(J.signed(text, "x"), ticket_text(iss)) or None
    if (quiet_until(rec) or "") > today:
        return (f"a reply disputed ela's comment here on {rec['disputed']}: no comment from ela until {quiet_until(rec)}; "
                "an ask or none")
    writes = d.get("writes") or []
    q = quiet_problem(writes, (d.get("comment") or "").strip(), quiet)
    if q:
        return q
    for w in writes:
        if w.get("verb") not in VERBS:
            return f"{w.get('verb')!r} is not a write ela makes itself ({', '.join(VERBS)}, and a comment); it is an ask"
        if w["verb"] == "transition" and J.terminal(str(w.get("to") or "")):
            return f"{w.get('to')} is a terminal status: the owner's word, an ask"
        if w["verb"] == "transition" and str(w.get("to") or "").strip().lower() == "closed":
            return "Closed is a terminal status: the owner's word, an ask"
        need = {"assign": "assignee", "transition": "to", "priority": "to", "due": "date", "link": "other"}[w["verb"]]
        if not w.get(need):
            return f"{w['verb']} needs {need}"
        if w["verb"] == "priority" and w["to"] not in J.PRIORITIES:
            return f"priority {w['to']!r} is not one of {', '.join(J.PRIORITIES)}"
        if w["verb"] == "due" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(w["date"])):
            return "due: a date YYYY-MM-DD"
        if w["verb"] == "link" and (not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", str(w["other"])) or not w.get("type")):
            return "link: another ticket's key and a type"
    if len({w["verb"] for w in writes}) != len(writes):
        return "one write per field in a set"
    text = (d.get("comment") or "").strip()
    if writes and all(w["verb"] == "link" for w in writes):
        return None if not text else ("a set of links alone carries no comment (MH's Automation copies it to the "
                                      "ticket just linked): drop the comment, or send it as its own act")
    if not text:
        return "every set carries its comment: what changed and why"
    if ABOUT_PEOPLE.search(text):
        return "the comment speaks about a person; anything about people is the owner's: an ask"
    problem = J.language_problem(J.signed(text, "x"), ticket_text(iss))
    if problem:
        return problem
    if said_before(iss, rec, text):
        return "ela already said this on the ticket: never a repeated comment"
    return None


def act_writes(key, d, reports, signer=None):
    """The decision's set as `ela dry` writes: the comment's file, then the field changes (each naming the note jira.py
    posts after it; the same note again is one comment, jira.py skips an identical one), or the comment alone. A
    verified close is `ela jira close --terminal`, its note the proof, signed here (the close posts it as written)."""
    writes = d.get("writes") or []
    if any(w.get("verb") == VERIFIED for w in writes):
        text = J.signed((d.get("comment") or "").strip(), signer or "the owner")
        p = os.path.join(drafts_dir(reports), f"{key}-{hashlib.sha1(text.encode()).hexdigest()[:8]}.txt")
        return p, text, [{"target": key, "command": f"ela jira close {key} --terminal --to Done --from-file {p} --no-mention",
                          "why": clip(d.get("why") or "", 200) or "verified by ela", "confidence": "high"}]
    links_only = bool(writes) and all(w.get("verb") == "link" for w in writes)
    text = "" if links_only else (d.get("comment") or "").strip()     # a set of links alone posts nothing on the ticket:
    #                                    MH's Automation copies a comment to the linked tickets (MH-3998, 2026-11-25)
    p = os.path.join(drafts_dir(reports), f"{key}-{hashlib.sha1(text.encode()).hexdigest()[:8]}.txt")
    why = clip(d.get("why") or "", 200) or "the board watch's decision"
    sure = {k: d[k] for k in ("confidence", "doubt") if d.get(k)}      # on each write's record row: did.md sorts by it
    if writes:                                                 # field changes first: their note must go out before a
        order = sorted(writes, key=lambda w: w.get("verb") == "link")   # link exists, or the rule copies it there too
        return p, text, [{"target": key, "command": command_of(key, w, p), "why": why, **sure} for w in order]
    return p, text, [{"target": key, "command": f"ela jira comment {key} --from-file {p}", "why": why, **sure}]


def asks_mod():
    sys.path.insert(0, os.path.join(SKILLS, "asks"))
    import asks as A                                           # noqa: E402 — the facts he gave, the precedents
    return A


def dry_mod():
    sys.path.insert(0, os.path.join(SKILLS, "dry"))
    import dry as D                                            # noqa: E402 — the class, its record and its undo
    return D


# ── a verified close (plan ela/2026-11-26-plan-sweep-judges-every-field, first slice 5) ──────────────────────────────
VERIFIED = "verified-close"             # its own class in `ela dry`, tier 1 by the owner's word of 2026-11-26


def verify_mod():
    sys.path.insert(0, os.path.join(SKILLS, "verify"))
    import verify as V                                         # noqa: E402 — the verdict of a run: one place
    return V


def verified_gate(key, w, runtime):
    """Why a verified close may not go out, or None. The proof is mechanical: a stored run of the ticket under
    <runtime>/browser/runs/<KEY>-…, its env.json proven on the lane the decision names, and its cases.json passing by
    /ela:verify's own verdict (verify.overall), not by the session's reading."""
    runs = os.path.realpath(os.path.join(runtime or "", "browser", "runs"))
    run = os.path.realpath(str(w.get("run") or ""))
    if not w.get("run") or os.path.dirname(run) != runs or not os.path.basename(run).startswith(key + "-"):
        return f"a verified close names its run, <runtime>/browser/runs/{key}-<date>"
    env = read_json(os.path.join(run, "env.json"), None)
    if not env or not str(env.get("verdict") or "").startswith("proven"):
        return "the run's lane is not proven (env.json from `ela browser env`): no verified close, a QA comment instead"
    lane = str(w.get("lane") or "")
    if not lane or str(env.get("lane") or "") != lane:
        return f"the run proved lane {env.get('lane')!r}, not {lane!r}"
    cases = read_json(os.path.join(run, "cases.json"), None)
    if cases is None:
        return "the run keeps no cases.json: nothing shows the cases passed"
    rows = cases.get("result") if isinstance(cases, dict) else cases
    verdict = verify_mod().overall(rows or [], env, read_json(os.path.join(run, "plan.json"), None))
    if verdict != "pass":
        return f"the run's verdict is {verdict}, not pass: a fail reopens with its evidence, anything else goes to QA"
    return None


# ── the second reading (plan ela/2026-11-26-plan-sweep-judges-every-field, first slice 3) ─────────────────────────────
# A case is settled on a second reading only by a first-hand source of one of these kinds, never by a second model's
# agreement: a closed list, so "the reader thought so" cannot pass as evidence.
SOURCES = ("reporter-comment",   # the reporter's (or assignee's) own comment on the ticket: its id or link
           "qa-report",          # QA's report: the mail, Slack permalink or Jira comment that carries it
           "build-record",       # a build or bundle record: the Jenkins build, the GM bundle, the image tag
           "config-value",       # a config value read first-hand: the config server key and environment
           "roster",             # the roster: who owns the area (ela team)
           "owner-fact")         # a fact the owner gave (ela asks fact): its kind and key
REVIEW_WAIT_H = 3                # a case still pending this long after it was decided reaches the owner, not read twice
LOW_ACTS_SETTLE_ON_READ = False  # first slice 4: a low act settled by the reader stays held until the owner's amendment
#                                  of decision 2026-11-24 is recorded beside it and SKILL.md says so; then it is written
NOT_READ_TWICE = "not read twice"
PRIORITY_ORDER = ("Lowest", "Low", "Medium", "High", "Highest")


def rereadable(writes, row):
    """Whether a case may go to the second reading: it carries writes, all within the watch's own verbs, none of them
    what is never ela's (a terminal status, a lowered priority). A close, release scope, a person, Slack, Fixed In or
    labels have no watch verb, so an ask about them goes straight to the owner."""
    if not writes:
        return False
    for w in writes:
        v = w.get("verb")
        if v not in VERBS:
            return False
        if v == "transition" and (J.terminal(str(w.get("to") or "")) or str(w.get("to") or "").strip().lower() == "closed"):
            return False
        if v == "priority" and row.get("priority") in PRIORITY_ORDER and w.get("to") in PRIORITY_ORDER \
                and PRIORITY_ORDER.index(w["to"]) < PRIORITY_ORDER.index(row["priority"]):
            return False
    return True


def review_state(t, now=None):
    """A topic's second-reading state: None (never sent), pending, settled, held (a low act the reader settled, kept for
    the owner), unsettled (read twice, reaches him) or released (not read twice: failure, timeout or REVIEW_WAIT_H)."""
    r = t.get("review") or {}
    st = r.get("state")
    if st == "pending" and now is not None:
        since = parse_ts(r.get("since"))
        if since and now - since > datetime.timedelta(hours=REVIEW_WAIT_H):
            return "released"
    return st


def visible(t, now=None):
    """Whether an open topic is the owner's to see: not while the second reading has it (until REVIEW_WAIT_H)."""
    return not t.get("closed") and review_state(t, now or now_tz()) != "pending"


def topic_id(key):
    return f"watch:{key}"


# The kinds of topic the watch raises, a closed list: the trigger that made the ticket due (scan's triggers). A
# correction is kept under its kind, so a precedent is cited only for the same kind of case.
KINDS = ("changed", "answered", "unassigned", "behind", "unanswered", "owner-held", "stalled", "tracked")
ASK_KINDS = ("fact", "ruling")         # what a topic needs from him: a fact ela cannot read, or a ruling


def put_topic(topics, key, d, today, summary="", cls=None):
    """The owner's topic for a ticket: one open topic per ticket; an ask on an open one updates it in place, so its
    thread and its first day stay; a new ask on a closed one keeps the closed topic, his letter with it, in `history`. A topic carries its class (the trigger kind), whether it needs a fact or a ruling, the
    session's confidence, and, for a ruling, ela's reason written into option A (plan 2026-11-26, asks teach ela)."""
    tid = topic_id(key)
    t = topics["topics"].get(tid)
    kind = d.get("kind") if d.get("kind") in ASK_KINDS else "ruling"
    why = " ".join(str(d.get("why") or (d.get("unsure") or {}).get("why") or "").split()).rstrip(".")
    opts = d.get("options") or [{"letter": "A", "text": "do what is proposed"}, {"letter": "B", "text": "leave it"}]
    opts = [{"letter": o.get("letter") or "ABC"[i], "text": o.get("text") or "", "writes": o.get("writes") or [],
             "comment": o.get("comment") or ""} for i, o in enumerate(opts[:3])]
    if kind == "ruling" and why and opts and "ela's reason:" not in opts[0]["text"]:
        opts[0]["text"] = f"{opts[0]['text']} — ela's reason: {clip(why, 200)}"
    meta = {"kind": kind, "confidence": d.get("confidence") if d.get("confidence") in LEVELS else None,
            "class": cls if cls in KINDS else None, "reason": why or None, **({"fact": d["fact"]} if d.get("fact") else {})}
    if t and not t.get("closed"):
        t.update(question=d["question"], options=opts, asked=today, unsure=d.get("unsure"), **meta)
        return tid, False
    was = ([*(t.get("history") or []), {k: v for k, v in t.items() if k != "history"}] if t else [])
    topics["topics"][tid] = {"id": tid, "key": key, "summary": summary, "question": d["question"], "options": opts,
                             "first": today, "asked": today, "thread": None, "posted": {}, "closed": None,
                             "unsure": d.get("unsure"), **meta, **({"history": was} if was else {})}
    return tid, True


def write_phrase(w, names):
    """One write of a set in plain words for an option's text."""
    v = w.get("verb")
    if v == "assign":
        return f"assign to {names.get(w['assignee']) or w['assignee']}"
    if v == "transition":
        return f"move to {w['to']}"
    if v == "priority":
        return f"priority {w['to']}"
    if v == "due":
        return f"due date {w['date']}"
    if v == "link":
        return f"link to {w['other']} ({w['type']})"
    return str(v)


def held_ask(d):
    """A low-confidence act as the owner's topic: nothing is written until he chooses A, which carries the writes and the
    comment exactly as the session decided them (through `answer` and the next `decide --apply`); B leaves the ticket."""
    D = dry_mod()
    names = D.roster_names() if any(w.get("verb") == "assign" for w in d.get("writes") or []) else {}
    said = [write_phrase(w, names) for w in d.get("writes") or []]
    text = (d.get("comment") or "").strip()
    if text and not (d.get("writes") and all(w.get("verb") == "link" for w in d["writes"])):
        said.append(f"comment \"{clip(text, 200)}\"")
    why = (d.get("why") or "").strip().rstrip(".") or "no reason was recorded"
    return {"question": f"ela would act here but is not sure. Why: {why}. Carry it out?", "kind": "ruling",
            "confidence": d.get("confidence") or "low", "why": why,
            "unsure": {"why": why, "doubt": (d.get("doubt") or "").strip()},
            "options": [{"letter": "A", "text": "carry it out: " + "; ".join(said), "writes": d.get("writes") or [],
                         "comment": d.get("comment") or ""},
                        {"letter": "B", "text": "leave it: nothing is written"}]}


LEVELS = ("low", "medium", "high")


def trigger_kind(row):
    """A due ticket's class for its topic: its first trigger's kind."""
    return next((t.get("kind") for t in row.get("triggers") or [] if t.get("kind") in KINDS), None)


def unsure(d):
    """What is wrong with an act's or a none's confidence: it must be high, medium or low, and below high it names its
    doubt (the owner reviews low first, so a missing level would hide one). → a reason, or None."""
    if d.get("confidence") not in LEVELS:
        return "an act or a none carries its confidence: high, medium or low"
    if d["confidence"] != "high" and not (d.get("doubt") or "").strip():
        return f"confidence {d['confidence']} carries its doubt: what the evidence leaves open"
    return None


FIELDS = ("assignee", "status", "priority", "due", "links", "comment")   # what a none may judge unneeded: a closed list
VERB_FIELD = {"assign": "assignee", "transition": "status", "priority": "priority", "due": "due", "link": "links",
              "verified-close": "status"}


def decided_path(reports):
    return os.path.join(reports, "ela", "watch", "decided.jsonl")


def log_decided(reports, rows):
    """Append the pass's carried decisions to decided.jsonl, the measure's record of what ela judged."""
    if not rows:
        return
    p = decided_path(reports)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def unneeded(d):
    """A none's `judged_unneeded`: the fields the session judged need no change, from FIELDS. → (list or None, problem)."""
    v = d.get("judged_unneeded")
    if v is None:
        return None, None
    if not isinstance(v, list) or any(x not in FIELDS for x in v):
        return None, f"judged_unneeded: a list from {', '.join(FIELDS)}"
    return sorted(set(v)), None


def decide(decisions, scanned, facts, reports, now, apply=False, runner=None, judge=None):
    """The session's decisions checked and carried. An act at low confidence passes the same gates and is then held as
    the owner's topic instead of written. With `judge` (a key), the judging session's one decision, checked against the
    scan's judge queue instead of the quick pass's tickets: an act or a none closes the ticket's open topic as
    superseded, and nobody's letters are carried here. → {date, acts, held, asks, none, refused, answered}."""
    D = dry_mod()
    today = now.date()
    st, topics = load_state(reports), load_topics(reports)
    due = ({r["key"]: r for r in scanned.get("judge") or [] if r["key"] == judge} if judge
           else {r["key"]: r for r in scanned.get("triggered") or []})
    out = {"date": today.isoformat(), "acts": [], "held": [], "asks": [], "none": [], "refused": [], "answered": []}
    out.update(judge_replies(decisions, scanned, st, topics, reports, now, apply))
    quiet = quiets(reports, today.isoformat())
    log = []

    def keep(key, verdict, d, **more):
        log.append({"at": now.isoformat(timespec="seconds"), "key": key, "verdict": verdict, "confidence": d.get("confidence"),
                    "kinds": [t["kind"] for t in due[key].get("triggers") or [] if t.get("kind") in KINDS], **more})
    for d in decisions.get("decisions") or []:
        key, verdict = d.get("key"), d.get("verdict")
        if key not in due:
            out["refused"].append({"key": key, "why": "not due judging in today's scan" if judge else
                                   "not due a decision in today's scan"}); continue
        iss = read_json(os.path.join(facts, "jira", "issues", f"{key}.json"), {})
        rec = st["tickets"].setdefault(key, {"first": today.isoformat()})
        if verdict in ("act", "none") and unsure(d):
            out["refused"].append({"key": key, "why": unsure(d)}); continue
        if verdict == "act":
            problem = check_act(key, d, iss, rec, today.isoformat(), quiet.get(key), os.path.dirname(facts or ""))
            if problem:
                out["refused"].append({"key": key, "why": problem}); continue
            if d["confidence"] == "low":                       # nothing to Jira: the owner confirms it first
                ask = held_ask(d)
                tid, new = put_topic(topics, key, ask, today.isoformat(), due[key].get("summary") or "", trigger_kind(due[key]))
                if new and rereadable(d.get("writes") or [], due[key]):
                    topics["topics"][tid]["review"] = {"state": "pending", "since": now.isoformat(timespec="seconds")}
                out["held"].append({"key": key, "topic": tid, "new": new, "question": ask["question"],
                                    "doubt": ask["unsure"]["doubt"], "proposed": ask["options"][0]["text"]})
                if apply:
                    rec.update(decided=now.isoformat(timespec="seconds"), verdict="ask", pending=[])
                    keep(key, "held", d, fields=[VERB_FIELD.get(w.get("verb")) for w in d.get("writes") or []])
                continue
            closing = any(w.get("verb") == VERIFIED for w in d.get("writes") or [])
            path, text, writes = act_writes(key, d, reports, (owner_of(facts) or {}).get("name") if closing else None)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            try:
                got = D.act(reports, VERIFIED if closing else CLASS, key, writes, today, apply=apply, runner=runner, now=now)
            except ValueError as e:
                out["refused"].append({"key": key, "why": str(e)}); continue
            out["acts"].append({"key": key, "writes": [w["command"] for w in writes], "comment": text, **got})
            if apply and got["state"] in ("applied", "open"):
                rec.update(acted=today.isoformat(), decided=now.isoformat(timespec="seconds"), verdict="act", pending=[],
                           kinds=[t["kind"] for t in due[key].get("triggers") or [] if t.get("kind") in KINDS])
                keep(key, "act", d, fields=[VERB_FIELD.get(w.get("verb")) for w in d.get("writes") or []]
                     + (["comment"] if text else []), state=got["state"])
                if judge:
                    supersede(topics, key, judge_path(reports, today.isoformat(), key), now)
                if text:
                    rec.setdefault("said", []).append(hashlib.sha1(norm(text).encode()).hexdigest()[:16])
        elif verdict == "ask":
            if not (d.get("question") or "").strip():
                out["refused"].append({"key": key, "why": "an ask carries its question"}); continue
            hollow = hollow_option(d)
            if hollow:
                out["refused"].append({"key": key, "why": hollow}); continue
            if d.get("kind") == "fact":                        # a fact he gave once is not asked again (plan 2026-11-26)
                f = d.get("fact") or {}
                try:
                    have = asks_mod().known(f.get("kind"), f.get("key"))
                except ValueError as e:
                    out["refused"].append({"key": key, "why": f"a fact ask names its fact {{kind, key}}: {e}"}); continue
                if have:
                    out.setdefault("known", []).append({"key": key, "fact": f, "value": have["value"], "source": have.get("source")})
                    continue
            tid, new = put_topic(topics, key, d, today.isoformat(), due[key].get("summary") or "", trigger_kind(due[key]))
            first = (d.get("options") or [{}])[0] if d.get("options") else {}
            if new and d.get("kind", "ruling") == "ruling" and rereadable(first.get("writes") or [], due[key]):
                topics["topics"][tid]["review"] = {"state": "pending", "since": now.isoformat(timespec="seconds")}
            out["asks"].append({"key": key, "topic": tid, "new": new, "question": d["question"],
                                "review": (topics["topics"][tid].get("review") or {}).get("state")})
            if apply:
                rec.update(decided=now.isoformat(timespec="seconds"), verdict="ask", pending=[])
                keep(key, "ask", d, ask=d.get("kind") if d.get("kind") in ASK_KINDS else "ruling")
        elif verdict == "none":
            fields_ok, problem = unneeded(d)
            if problem:
                out["refused"].append({"key": key, "why": problem}); continue
            sure = {"confidence": d["confidence"], "doubt": (d.get("doubt") or "").strip()}
            out["none"].append({"key": key, "why": d.get("why") or "", "judged_unneeded": fields_ok, **sure})
            if apply:                                          # the why and the level stay: ela/watch.md lists today's nones
                rec.update(decided=now.isoformat(timespec="seconds"), verdict="none", pending=[], why=clip(d.get("why") or "", 200), **sure)
                keep(key, "none", d, judged_unneeded=fields_ok)
                if judge:
                    supersede(topics, key, judge_path(reports, today.isoformat(), key), now)
        else:
            out["refused"].append({"key": key, "why": f"verdict {verdict!r}: act, ask or none"})
    out["answered"] = [] if judge else carry_answers(topics, st, facts, reports, now, apply, runner)
    if apply:
        out["corrections"] = fold_corrections(reports, st)
        log_decided(reports, log)
        write_json(state_path(reports), st)
        write_json(topics_path(reports), topics)
    return out


def disputes(mark):
    """Whether the session's mark on a reply counts as a dispute: anything but a plain false (unsure is a dispute)."""
    return mark is not False


def judge_replies(decisions, scanned, st, topics, reports, now, apply):
    """The session's marks on the replies the scan listed. Agreement is recorded as judged. A dispute is a correction:
    `ela dry`'s record takes verdict corrected (the act id, the reply's link, the ticket, field comment) and the class
    keeps its tier; the reply becomes the owner's ask; the ticket is quiet for DISPUTE_QUIET_DAYS. A reply the session did not mark waits
    for the next pass. → {disputes, agreed, refused_replies}."""
    D, today = dry_mod(), now.date().isoformat()
    listed = {(r["key"], str(r["reply"])): r for r in scanned.get("replies") or []}
    out = {"disputes": [], "agreed": [], "refused_replies": []}
    for j in decisions.get("replies") or []:
        r = listed.get((j.get("key"), str(j.get("reply"))))
        if not r:
            out["refused_replies"].append({"key": j.get("key"), "reply": j.get("reply"), "why": "not a reply today's scan listed"})
            continue
        rec = st["tickets"].setdefault(r["key"], {"first": today})
        if r["reply"] in (rec.get("judged") or []):
            continue
        rec.setdefault("judged", []).append(r["reply"])
        if not disputes(j.get("disputes")):
            out["agreed"].append({"key": r["key"], "reply": r["reply"], "by": r["by"]})
            continue
        rec["disputed"] = today
        until = quiet_until(rec)
        tid = f"{topic_id(r['key'])}:reply-{r['reply']}"
        undo = f"`ela dry undo {r['act']} --apply`" if r.get("act") else "on the ticket"
        topics["topics"].setdefault(tid, {
            "id": tid, "key": r["key"], "summary": r.get("summary") or "",
            "question": (f"{r['by']} disputed ela's comment ({r['link']}): \u201c{clip(r['text'], 160)}\u201d. "
                         f"ela stays off the ticket until {until}. What now?"),
            "options": [{"letter": "A", "text": "leave it to the thread on the ticket", "writes": [], "comment": ""},
                        {"letter": "B", "text": f"undo ela's act {undo}", "writes": [], "comment": ""}],
            "first": today, "asked": today, "thread": None, "posted": {}, "closed": None})
        notice = None
        if apply:
            notice = D.correct(reports, r["class"], "correction", ref=r.get("act") or r["key"],
                               note=f"{r['by']} disputed ela's comment on {r['key']}: {r['link']}", now=now,
                               extra={"key": r["key"], "field": "comment"})
        out["disputes"].append({"key": r["key"], "reply": r["reply"], "by": r["by"], "link": r["link"], "act": r.get("act"),
                                "class": r["class"], "topic": tid, "quiet_until": until, "notice": notice})
    return out


def carry_answers(topics, st, facts, reports, now, apply, runner):
    """The owner's letters that chose an option with writes: carried out once, signed like any act of the watch."""
    D, done = dry_mod(), []
    today = now.date()
    for t in topics["topics"].values():
        c = t.get("closed") or {}
        if not c.get("letter") or c.get("carried"):
            continue
        opt = next((o for o in t["options"] if o["letter"] == c["letter"]), None)
        if not opt or not (opt.get("writes") or opt.get("comment")):
            c["carried"] = "nothing to write"
            continue
        key = t["key"]
        iss = read_json(os.path.join(facts, "jira", "issues", f"{key}.json"), {})
        rec = st["tickets"].setdefault(key, {"first": today.isoformat()})
        d = {"writes": opt.get("writes") or [], "comment": opt.get("comment") or "", "why": f"the owner's {c['letter']} on {t['id']}",
             "confidence": "high"}                             # his word settles it: not a row to review first
        problem = check_act(key, d, iss, rec, today.isoformat(), quiets(reports, today.isoformat()).get(key))
        if problem:
            done.append({"topic": t["id"], "key": key, "refused": problem})
            continue
        path, text, writes = act_writes(key, d, reports)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        got = D.act(reports, CLASS, key, writes, today, apply=apply, runner=runner, now=now)
        done.append({"topic": t["id"], "key": key, **got})
        if apply and got["state"] == "applied":
            c["carried"] = now.isoformat(timespec="seconds")
            rec.update(acted=today.isoformat(), decided=now.isoformat(timespec="seconds"), verdict="act")
            if text:
                rec.setdefault("said", []).append(hashlib.sha1(norm(text).encode()).hexdigest()[:16])
    return done


def answer(reports, tid, letter, now, note=None):
    """His letter on a topic: recorded, the topic closed. `note` is his words with it. A letter other than A on a ruling
    goes against ela's proposal: it is kept in the watch's corrections with its cause, or as waiting for a cause when he
    gave none (the same row shape as dry's corpus; dry's record is not written). A fact topic's note is the fact.
    → the topic; KeyError when unknown, ValueError for a letter it does not offer."""
    topics = load_topics(reports)
    t = topics["topics"].get(tid)
    if not t:
        raise KeyError(tid)
    letter, note = letter.upper(), (" ".join(str(note).split()) if note else None)
    if letter not in [o["letter"] for o in t["options"]]:
        raise ValueError(f"{tid} offers {', '.join(o['letter'] for o in t['options'])}, not {letter}")
    if not t.get("closed"):
        t["closed"] = {"letter": letter, "at": now.isoformat(timespec="seconds"), **({"note": note} if note else {})}
        write_json(topics_path(reports), topics)
        if t.get("kind", "ruling") == "ruling" and letter != t["options"][0]["letter"]:
            correct(reports, t, letter, note, now, load_state(reports))
        f = t.get("fact") or {}
        if t.get("kind") == "fact" and note and f.get("kind") and f.get("key"):   # the fact he gave: kept, never asked again
            try:
                asks_mod().give(f["kind"], f["key"], note, tid, apply=True, now=now)
            except ValueError:
                pass
    return t


def corrections_path(reports):
    return os.path.join(reports, "ela", "watch", "corrections.jsonl")


def correct(reports, t, letter, note, now, st=None):
    """One correction row: {at, class, case_kind, target, act, verdict, cause, corpus, source}; corpus "admitted" with a
    cause, "waiting for a cause" without. `case_kind` is the trigger kind of the decision corrected (case_kind(), from
    the watch state `st`), so a later precedent is matched by the kind of case, as the folded dry corrections are;
    `class` falls back to it when the topic carried none. Only a letter against ela is written: an A is a measure
    (outcomes()), never a precedent."""
    kind = case_kind(reports, st, t["key"], now.isoformat()) if st else None
    p = corrections_path(reports)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now.isoformat(timespec="seconds"), "class": t.get("class") or kind, "case_kind": kind,
                            "target": t["key"], "act": t["id"],
                            "verdict": letter, "cause": note or None, "corpus": "admitted" if note else "waiting for a cause",
                            "kind": t.get("kind", "ruling"), "source": "watch"}, ensure_ascii=False) + "\n")


def case_kind(reports, st, key, at):
    """The trigger kind of the decision a correction answers: the kinds decide kept on the ticket, else the triggers in
    the scan of the correction's day or the day before. → a KINDS entry, or None."""
    for k in (st["tickets"].get(key) or {}).get("kinds") or []:
        if k in KINDS:
            return k
    try:
        day = datetime.date.fromisoformat(str(at)[:10])
    except ValueError:
        return None
    for d in (day, day - datetime.timedelta(days=1)):
        for r in read_json(scan_path(reports, d.isoformat()), {}).get("triggered") or []:
            if r.get("key") == key:
                k = trigger_kind(r)
                if k:
                    return k
    return None


def fold_corrections(reports, st):
    """Each board-watch correction in `ela dry`'s record (a disputing reply, a revert, his `wrong:`, `ela dry correct`),
    kept once in the watch's corrections with its case kind: the trigger kind as its class (what a precedent is matched
    by), and `case` = trigger:field:how. A dispute's note (the reply's link) or his `wrong:` cause is its cause; a bare
    undo waits for one. → [rows added]."""
    D = dry_mod()
    have = {r.get("act") for r in corrections(reports)}
    added = []
    for r in D.record(reports):
        if r.get("source") != "correction" or r.get("class") not in D.SCOPED or not r.get("key"):
            continue
        ref = f"dry:{r.get('target') or r['key']}@{r.get('at')}"
        if ref in have:
            continue
        kind = case_kind(reports, st, r["key"], r.get("at"))
        why = None if r.get("note") == "undone by ela dry undo" or (r.get("review") and r.get("corpus") != "admitted") else r.get("note")
        row = {"at": r.get("at"), "class": kind, "target": r["key"], "act": ref, "verdict": r.get("how") or "correction",
               "field": r.get("field"), "case": f"{kind or '?'}:{r.get('field') or 'ticket'}:{r.get('how') or 'correction'}",
               "cause": why or None, "corpus": "admitted" if why else "waiting for a cause", "kind": "correction", "source": "watch"}
        p = corrections_path(reports)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        have.add(ref)
        added.append(row)
    return added


def cause(reports, tid, note, now):
    """His cause for an earlier letter that went against ela and came without one: appended as the act's newer row."""
    topics = load_topics(reports)
    t = topics["topics"].get(tid)
    if not t or not (t.get("closed") or {}).get("letter"):
        raise KeyError(tid)
    t["closed"]["note"] = " ".join(str(note).split())
    write_json(topics_path(reports), topics)
    correct(reports, t, t["closed"]["letter"], t["closed"]["note"], now, load_state(reports))
    return t


def corrections(reports):
    """The watch's corrections, the newest row per act (a later cause completes an earlier wrong). → [row]."""
    rows = {}
    try:
        for line in open(corrections_path(reports), encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[r.get("act")] = r
    except OSError:
        pass
    return list(rows.values())


def outcomes(reports):
    """How the watch's topics ended, for ela's own measure: answered with A, against ela (with or without a cause),
    still open. A topic does not expire from ela/watch.md; one that ends unanswered is open, not agreed."""
    out = {"agreed": 0, "wrong": 0, "waiting_cause": 0, "open": 0, "superseded": 0}
    waiting = {r["act"] for r in corrections(reports) if r.get("corpus") == "waiting for a cause"}
    for t in load_topics(reports)["topics"].values():
        c = t.get("closed") or {}
        if c.get("by") == "second reading":                  # settled by ela, not an answer of his
            continue
        if c.get("superseded_by"):                         # a judgment took its place: neither agreed nor wrong
            out["superseded"] += 1
        elif not c.get("letter"):
            out["open"] += 1
        elif c["letter"] == t["options"][0]["letter"] or t.get("kind") == "fact":
            out["agreed"] += 1
        else:
            out["wrong"] += 1
            out["waiting_cause"] += t["id"] in waiting
    return out


def open_topics(reports, now=None):
    """The open topics the owner sees: a case the second reading still holds is left out (see `visible`)."""
    return [t for t in load_topics(reports)["topics"].values() if visible(t, now)]


def pending_review(reports, now=None):
    """The topics the second reading holds now."""
    return [t for t in load_topics(reports)["topics"].values()
            if not t.get("closed") and review_state(t, now or now_tz()) == "pending"]


def asks(reports, today):
    """The open topics as today.md shows its asks: a question, lettered options, each letter answered by `ela watch
    answer`, which records it (the writes of a chosen option go out at the next pass)."""
    out = []
    for t in sorted(open_topics(reports), key=lambda t: (not t.get("unsure"), t["first"], t["key"])):
        doubt = (t.get("unsure") or {}).get("doubt")
        text = f"{t['key']} {t.get('summary') or ''}: {t['question']}".strip() + (f" Doubt: {doubt}" if doubt else "")
        out.append({"id": t["id"], "question": text, "first": t["first"], "kind": t.get("kind"), "reason": t.get("reason"),
                    "options": [{"letter": o["letter"], "text": o["text"], "does": f"ela watch answer {t['id']} {o['letter']}",
                                 "recommended": i == 0} for i, o in enumerate(t["options"])],
                    "sig": hashlib.sha256(json.dumps([t["question"], t["options"]], sort_keys=True).encode()).hexdigest()[:12]})
    return out


# ── judging: a ticket that reaches the owner arrives judged, not listed (plan ela/2026-11-26-plan-tickets-reach-you-
# judged). The quick pass above decides many tickets in one session; a ticket assigned to him in Review, or handed to
# him, is also read in depth, one session per ticket (the runner's deep reading in its judge mode), and its verdict is
# what today.md shows where it names the ticket. The judgment keeps its own clock (`judgment`), apart from `decided`.
HANDED = "handed to you"
JUDGE_AGAIN_DAYS = 3                    # one re-judging in this many days, unless the status or the assignee changed
JUDGE_FAIL_BACK = 2                     # a pick that failed this often goes to the back of the queue
VERDICT_MAX = 160
QA_VERDICT = re.compile(r"\b(?:QA|tested|verified|retest(?:ed)?|TC\d+)\b[^\n]{0,80}?\b(?:pass(?:ed|es)?|fail(?:ed|s)?)\b|"
                        r"\b(?:pass(?:ed)?|fail(?:ed)?)\b[^\n]{0,40}?\b(?:TC\d+|test cases?|QA)\b|"
                        r"\u6d4b\u8bd5(?:\u901a\u8fc7|\u5931\u8d25|\u4e0d\u901a\u8fc7)|\u9a8c\u8bc1(?:\u901a\u8fc7|\u5931\u8d25)", re.I)
WRITE_WORDS = re.compile(r"^\s*(?:re-?assign|assign|hand (?:it )?(?:back|over|to)|move|transition|set (?:the |a )?(?:priority|due)|"
                         r"raise|lower|link)\b", re.I)


def judge_due(iss, rec, owner, now):
    """Why a ticket is due judging, or None: assigned to the owner, in Review or handed to him, and never judged, or since
    its judgment its status or assignee changed, or (after JUDGE_AGAIN_DAYS) someone other than him, ela or Jira
    Automation asked a question or gave a QA verdict on it."""
    f, s = fields(iss), snap(iss)
    if not is_owner(f.get("assignee"), owner):
        return None
    j = rec.get("judgment") or {}
    handed = bool(rec.get("handed")) and (not j.get("at") or rec["handed"] > j["at"])
    if s["status"] != "Review" and not handed:
        return None
    if not j.get("at"):
        return HANDED if handed else "in Review with you, never judged"
    if handed:
        return HANDED
    if s["status"] != j.get("status"):
        return f"moved {j.get('status')} → {s['status']} since its judgment"
    at = parse_ts(j["at"])
    if at and now - at < datetime.timedelta(days=JUDGE_AGAIN_DAYS):
        return None
    for c in comments(iss):
        ct = parse_ts(c.get("created"))
        if not ct or (at and ct <= at) or is_ela(c) or is_bot(c) or is_owner(c.get("author"), owner):
            continue
        t = text_of(c.get("body"))
        if asks_something(t):
            return f"{name(c.get('author'))} asked since its judgment"
        if QA_VERDICT.search(t):
            return f"{name(c.get('author'))} gave a QA verdict since its judgment"
    return None


def judge_order(rows):
    """The judge queue: a pick that failed JUDGE_FAIL_BACK times last, then by priority, a hand-over before a Review, the
    longest-waiting first."""
    pri = ("Highest", "High", "Medium", "Low", "Lowest")
    return sorted(rows, key=lambda r: (r.get("fails", 0) >= JUDGE_FAIL_BACK, pri.index(r["priority"]) if r.get("priority") in pri
                                       else 5, not r.get("handed"), r.get("updated") or "", r["key"]))


def hollow_option(d):
    """Why an ask is refused when one of its options names a write it does not carry, else None: ticking it would do
    nothing (the 2026-11-26 topic on MH-4065 offered "assign to Erin Zhang …" with no writes)."""
    for o in d.get("options") or []:
        if WRITE_WORDS.match(o.get("text") or "") and not (o.get("writes") or o.get("comment")):
            return (f"option {o.get('letter')} says \"{clip(o.get('text'), 60)}\" but carries no writes: give it the writes "
                    "and the comment, or word it as what the owner does himself")
    return None


def judge_path(reports, day, key):
    return os.path.join(reports, "ela", "watch", f"{day}-judge-{key}.json")


def supersede(topics, key, by, now):
    """The ticket's open topic closed by a judgment: no letter, kept, counted apart from agreed and wrong."""
    t = topics["topics"].get(topic_id(key))
    if t and not t.get("closed"):
        t["closed"] = {"superseded_by": by, "at": now.isoformat(timespec="seconds")}
    return t


def one_line(text):
    return " ".join((text or "").split())


def judged(reports, facts, key, now, verdict=None, failed=False):
    """The runner's record of a judging, after the ticket's page exists and `decide --judge` succeeded: the verdict (one
    line, ela's own) and the ticket's status and assignee at the time; or, `failed`, one more failure of the pick. Each
    judgment is also appended to <reports>/ela/watch/judgments.jsonl, so an earlier one is kept. → the record."""
    st = load_state(reports)
    rec = st["tickets"].setdefault(key, {"first": now.date().isoformat()})
    if failed:
        rec["judge_fails"] = int(rec.get("judge_fails") or 0) + 1
        write_json(state_path(reports), st)
        return {"key": key, "fails": rec["judge_fails"]}
    v = one_line(verdict)
    if not v:
        raise ValueError("a judgment carries its verdict: one line, ela's own")
    if len(v) > VERDICT_MAX:
        raise ValueError(f"the verdict is {len(v)} characters; one line of at most {VERDICT_MAX}: the reasons go on the ticket's page")
    iss = read_json(os.path.join(facts, "jira", "issues", f"{key}.json"), {})
    s = snap(iss)
    at = now.isoformat(timespec="seconds")
    j = {"key": key, "at": at, "verdict": v, "status": s["status"], "assignee": s["assignee"], "summary": fields(iss).get("summary") or ""}
    rec["judgment"], rec["judge_fails"] = {k: x for k, x in j.items() if k != "key"}, 0
    rec["decided"] = max(rec.get("decided") or "", at)      # a judgment is a decision: the quick pass waits for a move
    write_json(state_path(reports), st)
    p = os.path.join(reports, "ela", "watch", "judgments.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(j, ensure_ascii=False) + "\n")
    return j


def judgments(reports, since=None):
    """{key: judgment} for each ticket's latest judgment, at or after `since` (an ISO date) when given."""
    out = {}
    for key, rec in load_state(reports)["tickets"].items():
        j = rec.get("judgment") or {}
        if j.get("at") and (not since or j["at"][:10] >= since):
            out[key] = dict(j, key=key)
    return out


PAGE_DIRS = ("features", "projects")    # the vault's pages that hold a topic: a feature, else a project (the vault's homes)
FRONT_KEYS = re.compile(r"^keys:[ \t]*(.*)$", re.M)


def homes(vault, key):
    """The vault pages that already hold this ticket: the feature and project pages whose `keys` list its own key (a
    linked ticket does not count), then its ticket pages (`<date>-deep-<key>.md`), newest first. → [vault path]."""
    out, low = [], key.lower()
    for top in PAGE_DIRS:
        d = os.path.join(vault or "", top)
        for n in sorted(os.listdir(d)) if vault and os.path.isdir(d) else []:
            p = os.path.join(d, n, n + ".md") if not n.endswith(".md") else os.path.join(d, n)
            try:
                head = open(p, encoding="utf-8").read(4000)
            except OSError:
                continue
            m = head.startswith("---") and FRONT_KEYS.search(head.split("\n---", 1)[0])
            if m and key in re.findall(r"[A-Z][A-Z0-9]+-\d+", m.group(1)):
                out.append(os.path.relpath(p, vault).replace(os.sep, "/"))
    pages = []
    for top, dirs, fs in os.walk(vault) if vault and os.path.isdir(vault) else []:
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        pages += [os.path.relpath(os.path.join(top, f), vault).replace(os.sep, "/") for f in fs
                  if re.fullmatch(rf"\d{{4}}-\d{{2}}-\d{{2}}-deep-{re.escape(low)}(?:-judged)?\.md", f.lower())]
    return out + sorted(pages, key=os.path.basename, reverse=True)


JUDGED_DAYS = 7                         # how long a judgment stays on ela/watch.md's list
JUDGED_HEAD = "Your tickets judged"


def home_link(vault, key):
    """Where today.md and ela/watch.md send him for a judged ticket: the feature or project page listing its key, else its
    newest ticket page. → (vault path without .md, label) or None."""
    hs = homes(vault, key)
    if not hs:
        return None
    h = hs[0]
    if h.split("/", 1)[0] in PAGE_DIRS:
        try:
            m = re.search(r'^title:[ \t]*"?(.*?)"?[ \t]*$', open(os.path.join(vault, h), encoding="utf-8").read(2000), re.M)
        except OSError:
            m = None
        lab = (m.group(1) if m else "") or os.path.basename(h)[:-3]
        return h[:-3], lab.split(" · ")[0].replace("|", "/").replace("[", "").replace("]", "")
    return h[:-3], "its page"


def judged_section(reports, vault, today, base=""):
    """ela/watch.md's list of the owner's tickets judged in the last JUDGED_DAYS: each ticket, ela's verdict, its home."""
    got = judgments(reports, (today - datetime.timedelta(days=JUDGED_DAYS - 1)).isoformat())
    if not got:
        return []
    L = [f"## {JUDGED_HEAD}", "", "Your tickets in Review or handed to you, each read to the bottom by ela: its verdict, and "
         "the page with the facts, the next steps and a code reading of what QA did not test. Say so under one if it is wrong.", ""]
    for j in sorted(got.values(), key=lambda j: j["at"], reverse=True):
        link = f"[{j['key']}]({base}/browse/{j['key']})" if base else j["key"]
        h = home_link(vault, j["key"])
        L.append(f"- {link} {clip(j.get('summary'), 70)} · {j['status']} · {j['at'][5:10]}: {j['verdict']}"
                 + (f" → [[{h[0]}|{h[1]}]]" if h else ""))
    return L + [""]


def topics_on(reports, key):
    """Every watch topic on a ticket, the closed ones with his letter, oldest first: the current one and its history."""
    t = load_topics(reports)["topics"].get(topic_id(key))
    return [*(t.get("history") or []), {k: v for k, v in t.items() if k != "history"}] if t else []


def judge_prompt_text(row, iss, facts, reports, vault, page, path, base=""):
    """The judging session's input for one ticket (follow /ela:watch judge)."""
    f, key = fields(iss), row["key"]
    links = []
    for l in f.get("issuelinks") or []:
        o, how = (l.get("outwardIssue"), (l.get("type") or {}).get("outward")) if l.get("outwardIssue") else \
            (l.get("inwardIssue"), (l.get("type") or {}).get("inward"))
        if o:
            of = o.get("fields") or {}
            links.append(f"- {how} {o.get('key')} · {name(of.get('status'))} · {clip(of.get('summary'), 90)}")
    par = f.get("parent") or {}
    if par.get("key"):
        links.append(f"- parent {par['key']} · {clip((par.get('fields') or {}).get('summary'), 90)}")
    hs = homes(vault, key)
    L = [f"# Judge {key} · {f.get('summary') or ''}", "",
         f"Follow /ela:watch judge. Due because: {row['why']}. Write the ticket's page to {page} and your one decision to "
         f"{path}, then check it with `ela watch decide --judge {key} --from {path}` (a dry run). Run nothing with --apply; "
         "the runner applies it and records your verdict.", "",
         f"{name(f.get('status'))} · {name(f.get('assignee')) or 'nobody'} · {name(f.get('priority'))}"
         + (f" · due {f.get('duedate')}" if f.get("duedate") else "") + f" · labels {', '.join(f.get('labels') or []) or 'none'}"
         + (f" · fix versions {', '.join(v.get('name', '') for v in f.get('fixVersions') or [])}" if f.get("fixVersions") else ""), "",
         "## Its home in the vault", ""]
    L += [f"- {h}" for h in hs] or ["- none: the topic is new to the owner (see the skill: a feature page, or the ticket page as its entry)"]
    L += ["", "## Linked tickets (hints, not its home)", ""] + (links or ["- none"])
    ts = topics_on(reports, key)
    L += ["", "## The owner's topics on it (a letter he gave binds your verdict unless later evidence says otherwise)", ""]
    for t in ts:
        c = t.get("closed") or {}
        state = (f"answered {c['letter']} {c.get('at', '')[:16]}" + (f" — his words: {c['note']}" if c.get("note") else "")
                 if c.get("letter") else "superseded" if c.get("superseded_by") else "open")
        L += [f"- {t.get('first')} · {state} · {t.get('question')}"] + [f"    - {o['letter']}: {o['text']}" for o in t.get("options") or []]
    if not ts:
        L += ["- none"]
    L += ["", "## Description", "", clip(text_of(f.get("description")), 3000) or "(empty)", "", "## Comments, oldest first", ""]
    L += [f"> {str(c.get('created') or '')[:16]} {name(c.get('author'))}{' (ela)' if is_ela(c) else ''}"
          f"{' (copied by automation)' if is_bot(c) else ''}: {clip(text_of(c.get('body')), 1200)}" for c in comments(iss)] or ["(none)"]
    return "\n".join(L) + "\n"


# ── the owner's DM: a reminder, at most one a day, when a topic is new; the topics live on ela/watch.md ──────────
SLACK = os.path.join(SKILLS, "slack", "slack.py")

# ── the second reading's verbs ────────────────────────────────────────────────────────────────────────────────────
def review_path(reports, day):
    return os.path.join(reports, "ela", "watch", f"{day}-review.json")


def review_prompt(reports, facts, now):
    """The reader's input: each pending case with the decider's question, leaning, options and doubt, the ticket's
    fields and last comments, and the closed list of sources that may settle it. → {date, file, sources, cases}."""
    cases = []
    for t in sorted(pending_review(reports, now), key=lambda t: t["key"]):
        iss = read_json(os.path.join(facts, "jira", "issues", f"{t['key']}.json"), {})
        f = fields(iss)
        cases.append({"topic": t["id"], "key": t["key"], "summary": t.get("summary") or "", "held_act": bool(t.get("unsure")),
                      "question": t["question"], "reason": t.get("reason"), "doubt": (t.get("unsure") or {}).get("doubt"),
                      "options": [{"letter": o["letter"], "text": o["text"]} for o in t["options"]],
                      "status": name(f.get("status")), "assignee": name(f.get("assignee")) or None, "priority": name(f.get("priority")),
                      "comments": [{"by": name(c.get("author")), "at": str(c.get("created") or "")[:16], "ela": is_ela(c),
                                    "text": clip(text_of(c.get("body")), 500)} for c in comments(iss)[-5:]]})
    return {"date": now.date().isoformat(), "file": review_path(reports, now.date().isoformat()), "sources": list(SOURCES),
            "cases": cases}


def review_text(doc):
    L = [f"# The board watch · second reading · {doc['date']}", "",
         f"Follow /ela:watch, section \"The second reading\". {len(doc['cases'])} case{'s' if len(doc['cases']) != 1 else ''} "
         f"the decider could not settle. Write one entry per case to {doc['file']}, then check it with "
         f"`ela watch review settle --from {doc['file']}` (a dry run). A case is settled only by a first-hand source you "
         f"read yourself, given as {{\"kind\", \"ref\"}} with kind one of: {', '.join(doc['sources'])}. Agreeing with "
         "the decider is not a source.", ""]
    for c in doc["cases"]:
        L += [f"## {c['key']} · {c['summary']}", f"{c['status']} · {c['assignee'] or 'nobody'} · {c['priority']}"
              + (" · a low act, held" if c["held_act"] else " · a ruling ask"), "", f"Question: {c['question']}"]
        L += [f"- {o['letter']}: {o['text']}" for o in c["options"]]
        if c.get("doubt"):
            L += [f"Doubt: {c['doubt']}"]
        L += [""] + [f"> {x['at']} {x['by']}{' (ela)' if x['ela'] else ''}: {x['text']}" for x in c["comments"]] + [""]
    return "\n".join(L)


def review_settle(entries, reports, now, apply=False):
    """The reader's entries carried: {topic, settles, letter, source: {kind, ref}, why}. A case settles only with a
    letter the topic offers and a source from SOURCES with a ref; then a ruling ask is closed with that letter by the
    second reading (its writes go out at the next decide --apply, like his letter would), and a low act stays held for
    the owner with the source shown (LOW_ACTS_SETTLE_ON_READ). Anything else reaches the owner marked read twice, not
    settled, with what was tried. A pending case the file leaves out stays pending. → {settled, held, unsettled, refused}."""
    topics = load_topics(reports)
    out = {"settled": [], "held": [], "unsettled": [], "refused": []}
    log = []
    for e in entries.get("cases") or entries.get("entries") or []:
        t = topics["topics"].get(e.get("topic"))
        if not t or t.get("closed") or (t.get("review") or {}).get("state") != "pending":
            out["refused"].append({"topic": e.get("topic"), "why": "not a case the second reading holds"}); continue
        src, letter = e.get("source") or {}, str(e.get("letter") or "").upper()
        why = " ".join(str(e.get("why") or "").split())
        problem = None
        if e.get("settles") is True:
            if src.get("kind") not in SOURCES or not str(src.get("ref") or "").strip():
                problem = f"a settled case names its first-hand source {{kind, ref}}, kind one of {', '.join(SOURCES)}"
            elif letter not in [o["letter"] for o in t["options"]]:
                problem = f"{t['id']} offers {', '.join(o['letter'] for o in t['options'])}, not {letter or 'no letter'}"
        settles = e.get("settles") is True and not problem
        stamp = now.isoformat(timespec="seconds")
        if settles and t.get("unsure") and not LOW_ACTS_SETTLE_ON_READ:
            row = {"key": t["key"], "topic": t["id"], "letter": letter, "source": src, "why": why}
            out["held"].append(row)
            if apply:
                t["review"] = {"state": "held", "since": t["review"].get("since"), "read": stamp, "letter": letter,
                               "source": {"kind": src["kind"], "ref": src["ref"]}, "why": why}
        elif settles:
            out["settled"].append({"key": t["key"], "topic": t["id"], "letter": letter, "source": src, "why": why})
            if apply:
                t["review"] = {"state": "settled", "since": t["review"].get("since"), "read": stamp,
                               "source": {"kind": src["kind"], "ref": src["ref"]}, "why": why}
                t["closed"] = {"letter": letter, "at": stamp, "by": "second reading", "note": why or None}
        else:
            tried = problem or why or "the reader found no first-hand source"
            out["unsettled"].append({"key": t["key"], "topic": t["id"], "why": tried})
            if apply:
                t["review"] = {"state": "unsettled", "since": t["review"].get("since"), "read": stamp, "why": tried}
        held = settles and t.get("unsure") and not LOW_ACTS_SETTLE_ON_READ
        log.append({"at": stamp, "key": t["key"], "verdict": "reread", "topic": t["id"],
                    "outcome": "held" if held else "settled" if settles else "unsettled", "letter": letter if settles else None,
                    "source": src if settles else None})
    if apply:
        write_json(topics_path(reports), topics)
        log_decided(reports, log)
    return out


def review_release(reports, now, apply=False):
    """Every case the second reading still holds reaches the owner, marked not read twice: the runner calls it when the
    reader failed or timed out, so no case waits on a reading that will not come. → [topic ids]."""
    topics = load_topics(reports)
    done = []
    for t in topics["topics"].values():
        if not t.get("closed") and (t.get("review") or {}).get("state") == "pending":
            done.append(t["id"])
            if apply:
                t["review"] = dict(t["review"], state="released", read=now.isoformat(timespec="seconds"), why=NOT_READ_TWICE)
    if apply and done:
        write_json(topics_path(reports), topics)
    return done


def review_mark(t, now=None):
    """The line ela/watch.md shows under a topic the second reading saw, or None."""
    st, r = review_state(t, now or now_tz()), t.get("review") or {}
    if st == "held":
        src = r.get("source") or {}
        return (f"*Read twice*: the reader settles it ({r.get('letter')}) on {src.get('kind')} {src.get('ref')}"
                + (f" — {r['why']}" if r.get("why") else "") + ". Still yours: a low act is not written on a second reading yet.")
    if st == "unsettled":
        return f"*Read twice, not settled*: {r.get('why') or 'no first-hand source found'}."
    if st == "released":
        return f"*{NOT_READ_TWICE.capitalize()}*: the second reading did not run in time."
    return None


# ── the measure: how much ticket work ela settles without the owner ───────────────────────────────────────────────
MEASURE_PAGE = "ela/watch-measure.md"   # its own page: the daily pages stay free of ela's own numbers (plan asks-teach-it)
SETTLE_DAYS = 7                         # a none a person overturns within this is not settled
WRITE_FIELD = {"assign": "assignee", "transition": "status", "priority": "priority", "due": "duedate", "link": "link",
               "unlink": "link", "label": "labels", "labels": "labels", "fixed-in": "fix version", "fixedin": "fix version"}
CHANGE_FIELD = {"assignee": "assignee", "status": "status", "priority": "priority", "duedate": "due", "due date": "due",
                "link": "links", "comment": "comment"}
BACKLOG = ("unassigned", "behind", "unanswered", "owner-held", "stalled")   # state kinds: the ticket was waiting, not changed
WHO = ("app", "ela unattended", "owner through ela", "owner in Jira", "human")


def read_jsonl(path):
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def writes_log(reports):
    """ela's applied Jira writes (jira.py's writes.jsonl): [{at (datetime), key, verb, unattended}]. Unattended: written
    inside an unattended session, by a runner job, or by a tier-1 class at its pass (`word` "… (tier 1 by decision)");
    anything else was the owner's word in a session."""
    out = []
    for r in read_jsonl(os.path.join(reports, "ela", "writes.jsonl")):
        at = parse_ts(r.get("at"))
        if at and r.get("system") == "jira" and r.get("ok", True) and r.get("key"):
            alone = bool(r.get("unattended") or r.get("job")) or "(tier 1 by decision)" in str(r.get("word") or "")
            out.append({"at": at, "key": r["key"], "verb": str(r.get("verb") or ""), "unattended": alone})
    return out


def ela_write(writes, key, at, field):
    """The write in ela's log that made a change on the owner's account: same ticket, within MOVED_MARGIN, and the
    write's verb names this field (a comment matches any write: each field write posts its note). → row or None."""
    f = (field or "").lower()
    best = None
    for w in writes:
        if w["key"] != key or abs(w["at"] - at) > MOVED_MARGIN:
            continue
        wf = WRITE_FIELD.get(w["verb"])
        if f == "comment" or wf == f or (wf is None and w["verb"] != "comment"):   # an unknown verb matches by time alone
            if best is None or abs(w["at"] - at) < abs(best["at"] - at):
                best = w
    return best


def attribute(facts, reports, owner, start, end):
    """Every change to an MH ticket in [start, end): field changes from the fact store's changelog, comments from the
    issue files, each attributed: app; ela unattended or the owner through ela (the owner's account, matched to a write in
    writes.jsonl by ticket, field and time); the owner in Jira (his account, no write of ela's); human. → [{key, at,
    field, who, by}]."""
    writes, out, seen = writes_log(reports), [], set()

    def who(person, key, at, field, signed=False):
        if is_app(person):
            return "app"
        if is_owner(person, owner):
            w = ela_write(writes, key, at, field)
            if w:
                return "ela unattended" if w["unattended"] else "owner through ela"
            return "owner through ela" if signed else "owner in Jira"
        return "human"
    for k, hs in changelog_of(facts).items():
        if not k.startswith(PROJECT + "-"):
            continue
        for h in hs:
            at = parse_ts(h.get("created"))
            if not at or not (start <= at < end) or h.get("id") in seen:
                continue
            seen.add(h.get("id"))
            for it in h.get("items") or []:
                f = str(it.get("field") or "").lower()
                out.append({"key": k, "at": at.astimezone(TZ).isoformat(timespec="minutes"), "field": CHANGE_FIELD.get(f, f),
                            "who": who(h.get("author"), k, at, f), "by": name(h.get("author"))})
    d = os.path.join(facts or "", "jira", "issues")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not (fn.startswith(PROJECT + "-") and fn.endswith(".json")):
            continue
        iss = read_json(os.path.join(d, fn), {}) or {}
        for c in comments(iss):
            at = parse_ts(c.get("created"))
            if at and start <= at < end:
                out.append({"key": iss.get("key") or fn[:-5], "at": at.astimezone(TZ).isoformat(timespec="minutes"), "field": "comment",
                            "who": "app" if is_bot(c) else who(c.get("author"), iss.get("key"), at, "comment", is_ela(c)),
                            "by": name(c.get("author"))})
    return sorted(out, key=lambda x: x["at"])


def week_of(day):
    return day - datetime.timedelta(days=day.weekday())


def measure(facts, reports, owner, today, weeks=6):
    """The share of ticket work ela settled without the owner, per week (Monday first), newest first. Work is each
    decision the watch carried (decided.jsonl). Settled by ela: an act no correction touched, and a none no person
    overturned within SETTLE_DAYS (a change by a person to a field it judged unneeded); asks and held acts reach the owner.
    The backlog (decisions on a ticket only a state trigger made due: stalled, owner-held …) is counted apart. Every
    ticket change of the week is attributed (WHO). → [{week, ...}]."""
    decided = [r for r in read_jsonl(decided_path(reports)) if parse_ts(r.get("at"))]
    rereads = [r for r in decided if r.get("verdict") == "reread"]
    decided = [r for r in decided if r.get("verdict") != "reread"]
    corr = [r for r in corrections(reports) if r.get("kind") == "correction"]
    topics = load_topics(reports)["topics"].values()
    out = []
    for i in range(weeks):
        mon = week_of(today) - datetime.timedelta(days=7 * i)
        start = datetime.datetime.combine(mon, datetime.time(), TZ)
        end = start + datetime.timedelta(days=7)
        rows = [r for r in decided if start <= parse_ts(r["at"]) < end]
        changes = attribute(facts, reports, owner, start, end + datetime.timedelta(days=SETTLE_DAYS))
        week_changes = [c for c in changes if parse_ts(c["at"]) < end]

        def part(rs):
            acts = [r for r in rs if r["verdict"] == "act"]
            nones = [r for r in rs if r["verdict"] == "none"]
            def within(at, r):                         # after the decision, inside SETTLE_DAYS
                a, b = parse_ts(at), parse_ts(r["at"])
                return bool(a and b) and datetime.timedelta(minutes=-1) <= a - b <= datetime.timedelta(days=SETTLE_DAYS)
            hit = [r for r in acts if any(c.get("target") == r["key"] and within(c.get("at"), r) for c in corr)]
            over = [r for r in nones if any(c["key"] == r["key"] and c["who"] == "human" and within(c["at"], r)
                                            and c["field"] in (r.get("judged_unneeded") or []) for c in changes)]
            asks = [r for r in rs if r["verdict"] in ("ask", "held")]
            reread = [r for r in asks if any(x["key"] == r["key"] and x.get("outcome") == "settled" and within(x["at"], r)
                                             for x in rereads)]
            settled = len(acts) - len(hit) + len(nones) - len(over) + len(reread)
            return {"decided": len(rs), "acts": len(acts), "corrected": len(hit), "nones": len(nones),
                    "nones_unfielded": sum(1 for r in nones if r.get("judged_unneeded") is None), "overturned": len(over),
                    "asks": sum(1 for r in asks if r["verdict"] == "ask"), "held": sum(1 for r in asks if r["verdict"] == "held"),
                    "settled_on_review": len(reread),
                    "settled": settled, "share": round(settled / len(rs), 3) if rs else None}
        backlog = [r for r in rows if r.get("kinds") and all(k in BACKLOG for k in r["kinds"])]
        fresh = [r for r in rows if r not in backlog]
        answered = [t for t in topics if (t.get("closed") or {}).get("by") != "second reading"
                    and (t.get("closed") or {}).get("at", "")[:10] >= mon.isoformat()
                    and (t.get("closed") or {}).get("at", "")[:10] < (mon + datetime.timedelta(days=7)).isoformat()]
        out.append({"week": mon.isoformat(), "changed": part(fresh), "backlog": part(backlog),
                    "answers": {"agreed": sum(1 for t in answered if t["closed"].get("letter") == t["options"][0]["letter"]),
                                "against": sum(1 for t in answered if t["closed"].get("letter") != t["options"][0]["letter"]
                                               and t.get("kind", "ruling") == "ruling")},
                    "changes": {w: sum(1 for c in week_changes if c["who"] == w) for w in WHO},
                    "partial": mon == week_of(today)})
    return out


def pct(x):
    return "—" if x is None else f"{round(x * 100)}%"


def measure_page(facts, reports, owner, today):
    """ela/watch-measure.md: the share settled without the owner, this week against the last, then the weeks as a table
    and the attribution of every change, folded."""
    ws = measure(facts, reports, owner, today)
    now_, last = ws[0], ws[1] if len(ws) > 1 else None
    L = ["# Board watch · how much ela settles without you", "",
         f"This week so far: **{pct(now_['changed']['share'])}** of {now_['changed']['decided']} judged tickets settled without you"
         + (f"; last week {pct(last['changed']['share'])} of {last['changed']['decided']}." if last else "."),
         f"Backlog judged apart: {pct(now_['backlog']['share'])} of {now_['backlog']['decided']}.", "",
         "Settled = an act nobody corrected within a week, or a none nobody overturned (a person changing a field it judged "
         "unneeded). Asks and held acts reached you. Nothing here needs an answer.", "",
         "> [!note]- Week by week", ">",
         "> | week | judged | settled | share | acts (corrected) | nones (overturned) | asks | held | backlog share | your answers: agreed / against |",
         "> |---|---|---|---|---|---|---|---|---|---|"]
    for w in ws:
        c, b = w["changed"], w["backlog"]
        L.append(f"> | {w['week']}{' (so far)' if w['partial'] else ''} | {c['decided']} | {c['settled']} | {pct(c['share'])} | "
                 f"{c['acts']} ({c['corrected']}) | {c['nones']} ({c['overturned']}) | {c['asks']} | {c['held']} | "
                 f"{pct(b['share'])} of {b['decided']} | {w['answers']['agreed']} / {w['answers']['against']} |")
    L += ["", "> [!note]- Who changed MH tickets", ">", "> | week | " + " | ".join(WHO) + " |", "> |---|" + "---|" * len(WHO)]
    for w in ws:
        L.append(f"> | {w['week']} | " + " | ".join(str(w["changes"][x]) for x in WHO) + " |")
    unf = sum(w["changed"]["nones_unfielded"] + w["backlog"]["nones_unfielded"] for w in ws)
    if unf:
        L += ["", f"{unf} none{'s' if unf != 1 else ''} named no field judged unneeded (recorded before the field existed); "
              "they count as settled unless corrected."]
    return "\n".join(L + [""])


def prompt_keep_path(reports, now):
    return os.path.join(reports, "ela", "watch", f"{now:%Y-%m-%d-%H%M}-prompt.json")


def jira_base(s=None):
    env = (s or site()).get("env")
    try:
        return next((l.split("=", 1)[1].strip().strip("'\"").rstrip("/") for l in open(os.path.expanduser(env))
                     if l.startswith("JIRA_BASE_URL=")), "")
    except (OSError, TypeError):
        return ""


WATCH_PAGE = "ela/watch.md"        # the vault page every open topic lives on; the DM only points at it
SUMMARY_CUT = 90                   # a ticket's title in the reminder: whole up to here, then cut at a word


def page(reports, today, base="", vault=None, now=None):
    """ela/watch.md: every open topic, oldest first: the ticket, whether it needs a fact or a ruling, the session's
    confidence, the question, each letter as a box he ticks (or an `ela:` line he writes under it, read by
    settle_page) and the CLI line; a low-confidence act held for his confirm first, under its own heading, with its
    doubt. The vault is where the topics live; Slack only reminds (the owner's word, 2026-11-25)."""
    ts = sorted(open_topics(reports, now), key=lambda t: (t["first"], t["key"]))
    L = ["# Board watch · waiting for your letter", "", f"How much ela settles without you, week by week: [[{MEASURE_PAGE[:-3]}|the measure]].", ""]
    if not ts:
        return "\n".join(L + ["Nothing waits: every topic has its letter.", ""] + judged_section(reports, vault, today, base)
                         + nothing_due(reports, today, base))
    L += [f"{len(ts)} topic{'s' if len(ts) != 1 else ''} wait. Answer each here: tick a letter, or write `ela: B because …` "
          "under the topic (the words after the letter are kept as your reason; a fact topic's words are the fact). Or in "
          "the CLI: `ela watch answer watch:<KEY> <letter> [words]`. A chosen option's writes go out at the watch's next "
          "pass.", ""]
    unsure, rest = [t for t in ts if t.get("unsure")], [t for t in ts if not t.get("unsure")]

    def topic(t):
        link = f"[{t['key']}]({base}/browse/{t['key']})" if base else t["key"]
        doubt = (t.get("unsure") or {}).get("doubt")
        sure = f"confidence {t['confidence']}" if t.get("confidence") else "confidence not stated"
        return ([f"### {link} {t.get('summary') or ''}".rstrip(), "",
                 f"*{t.get('kind') or 'ruling'}* · {sure} · open since {t['first']}. {t['question']}", ""]
                + ([f"**Doubt**: {doubt}", ""] if doubt else [])
                + ([review_mark(t, now), ""] if review_mark(t, now) else [])
                + [f"- [ ] {o['letter']}{' (recommended)' if i == 0 and t.get('kind', 'ruling') == 'ruling' else ''}: {o['text']}"
                   for i, o in enumerate(t["options"])]
                + ["", f"CLI: `ela watch answer {t['id']} <letter> [words]`", ""])
    if unsure:                                             # the owner's ruling, 2026-11-26: a low act waits for him, first
        L += ["## Confirm first: ela was not sure", "", "ela would have written these itself, but the evidence does not "
              "settle them. Nothing goes to Jira until you choose A.", ""]
        for t in unsure:
            L += topic(t)
        if rest:
            L += ["## Asks", ""]
    for t in rest:
        L += topic(t)
    return "\n".join(L + judged_section(reports, vault, today, base) + nothing_due(reports, today, base))


# His answers written on ela/watch.md itself: a ticked option, or an `ela:` line under a topic, both with his words kept
TOPIC_HEAD = re.compile(r"^###[ \t]+\[?([A-Z][A-Z0-9]+-\d+)\b", re.M)
PAGE_TICK = re.compile(r"^[ \t]*(?:>[ \t]*)*[-*][ \t]+\[[xX]\][ \t]+([ABC])(?:[ \t]+\(recommended\))?:.*$", re.M)
PAGE_LINE = re.compile(r"^[ \t]*(?:[-*+][ \t]+|>[ \t]*)*ela[ \t]*[:：][ \t]*([ABCabc])(?:\.?|[ \t]*[.,:;\u2014\u2013-][ \t]*(\S.*?)"
                       r"|[ \t]+((?:because|since|as)\b.*?|因为.*?))[ \t]*$", re.M | re.I)


def page_answers(text):
    """His answers on ela/watch.md: [(topic id, letter, note)], one per topic, the first written under it. A tick's note
    is the plain line right under it; an `ela:` letter's is the words after it."""
    heads = [(m.start(), m.group(1)) for m in TOPIC_HEAD.finditer(text or "")]
    out, seen = [], set()

    def topic_at(pos):
        return next((k for at, k in reversed(heads) if at < pos), None)
    found = []
    for m in PAGE_TICK.finditer(text or ""):
        rest = (text[m.end():].split("\n", 2) + ["", ""])[1]
        note = None if (not rest.strip() or re.match(r"^[ \t]*(?:[-*+][ \t]+\[.\]|#|CLI:|ela[ \t]*[:：])", rest, re.I)) \
            else re.sub(r"^[ \t]*(?:[-*+>][ \t]*)*", "", rest).strip() or None
        found.append((m.start(), m.group(1), note))
    for m in PAGE_LINE.finditer(text or ""):
        if (m.group(2) or m.group(3)) and m.group(1).islower():
            continue                                       # `ela: a, b and c …` is a sentence, not a letter
        found.append((m.start(), m.group(1).upper(), ((m.group(2) or m.group(3) or "").strip() or None)))
    for pos, letter, note in sorted(found):
        key = topic_at(pos)
        if key and key not in seen:
            seen.add(key)
            out.append((topic_id(key), letter, note))
    return out


def settle_page(reports, text, now, dry_run=False):
    """The answers on ela/watch.md, recorded as `ela watch answer` records them, once each (an answered topic leaves the
    page). → [(topic, letter, note)] recorded; a letter the topic does not offer, or a topic closed already, is skipped."""
    done = []
    for tid, letter, note in page_answers(text):
        t = load_topics(reports)["topics"].get(tid)
        if not t or t.get("closed") or letter not in [o["letter"] for o in t["options"]]:
            continue
        if not dry_run:
            answer(reports, tid, letter, now, note=note)
        done.append((tid, letter, note))
    return done


def nones(reports, today):
    """Today's none verdicts from the store: [{key, why, confidence, doubt}], low confidence first. One recorded before
    confidence was is low; its why, when the store lacks it, is read from the day's decisions file."""
    day = today.isoformat()
    rows = [(k, r) for k, r in load_state(reports)["tickets"].items()
            if r.get("verdict") == "none" and (r.get("decided") or "")[:10] == day]
    if not rows:
        return []
    filed = {d.get("key"): d for d in (read_json(os.path.join(reports, "ela", "watch", f"{day}-decisions.json"), {})
                                       .get("decisions") or []) if isinstance(d, dict)}
    out = [{"key": k, "why": r.get("why") or (filed.get(k) or {}).get("why") or "",
            "confidence": r.get("confidence") if r.get("confidence") in LEVELS else "low", "doubt": r.get("doubt") or ""}
           for k, r in rows]
    return sorted(out, key=lambda x: (LEVELS.index(x["confidence"]), x["key"]))


def nothing_due(reports, today, base=""):
    """The closing section of ela/watch.md: what the watch judged had nothing due today, so a wrong none can be caught.
    Nothing to answer here: he corrects one by saying so."""
    got = nones(reports, today)
    if not got:
        return []
    L = ["## Judged nothing due today", "", "Tickets the watch looked at and left alone, the least sure first. Say so "
         "if one needed something.", ""]
    for x in got:
        link = f"[{x['key']}]({base}/browse/{x['key']})" if base else x["key"]
        lv = "" if x["confidence"] == "high" else f"**{x['confidence'].capitalize()}**: {x['doubt'] or 'no doubt was recorded'} — "
        L.append(f"- {link}: {lv}{x['why'] or 'no reason was recorded'}")
    return L + [""]


# ── the owner's DM: a reminder, at most one a day, when a topic is new; the topics live on ela/watch.md ──────────
SLACK = os.path.join(SKILLS, "slack", "slack.py")


def dm_plan(topics, today, base="", now=None):
    """What today's DM pass sends: at most one reminder a day, and only when a topic is new since the last reminder:
    how many are new, how many wait in all, the new ones a line each, and where they live (the vault page) and how to
    answer (the CLI). No thread per topic, no repeat for an open one, no line when one settles: the vault page carries
    them (the owner's word, 2026-11-25). → [{kind: "reminder", topics: [ids], text}]."""
    day = today.isoformat()
    if topics["roots"].get(day):
        return []
    open_ = [t for t in topics["topics"].values() if visible(t, now)]
    fresh = sorted((t for t in open_ if not t.get("thread")), key=lambda t: t["key"])
    if not fresh:
        return []
    if TI.tier("watch", "topic") != TI.I2:                    # a topic is his decision, not an interruption: the
        return []                                               # one reminder below is I2's Slack line, nothing more
    n = len(fresh)
    lines = [f"*Board watch:* {n} new topic{'s' if n != 1 else ''} for your answer · {len(open_)} waiting in all · {today:%a %m-%d}"]
    lines += [f"• {ST.key_link(t['key'], base)} {ST.esc(ST.cut(t.get('summary') or '', SUMMARY_CUT))}".rstrip() for t in fresh]
    lines += ["", f"They are on the vault page _{WATCH_PAGE[:-3]}_: tick a letter there, or answer in the CLI: `ela watch answer watch:<KEY> <letter>`"]
    return [{"kind": "reminder", "tier": TI.I2, "topics": [t["id"] for t in fresh], "text": "\n".join(lines)}]


def slack_post(argv, apply):
    """One post through the slack capability: (exit code, its JSON or None, text)."""
    cmd = ["python3", SLACK] + (["--env-file", site().get("env")] if site().get("env") else []) + argv + ["--json"] \
        + (["--apply"] if apply else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    try:
        return p.returncode, json.loads(p.stdout), p.stderr.strip()
    except ValueError:
        return p.returncode, None, (p.stdout + p.stderr).strip()


def dm(reports, now, apply=False, post=None, base=None):
    """Send today's reminder (dm_plan) to his DM through `ela slack post` (a dry run unless `apply`). → {sent, failed};
    applied, the store records the day's reminder and marks its topics reminded (their `thread`), so none is sent twice."""
    post = post or slack_post
    topics = load_topics(reports)
    today = now.date()
    day = today.isoformat()
    plan = dm_plan(topics, today, jira_base() if base is None else base)
    sent, failed = [], []
    tmp = os.path.join(reports, "ela", "watch", "dm")
    os.makedirs(tmp, exist_ok=True)
    for i, p in enumerate(plan):
        f = os.path.join(tmp, f"{day}-{i}.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(p["text"] + "\n")
        code, got, err = post(["post", "--dm", "me", "--file", f], apply)
        if code != 0:
            failed.append({"plan": p, "why": err or f"exit {code}"}); continue
        link = (got or {}).get("permalink")
        sent.append({"kind": p["kind"], "topics": p["topics"], "permalink": link, "dry_run": not apply, "text": p["text"]})
        if apply:
            topics["roots"][day] = link or True
            for tid in p["topics"]:
                t = topics["topics"][tid]
                t["thread"] = link or True
                t.setdefault("posted", {})[day] = link or True
    if apply:
        write_json(topics_path(reports), topics)
    return {"date": day, "sent": sent, "failed": failed}


# ── the verbs ─────────────────────────────────────────────────────────────────────────────────────────────────────
def roots(s):
    return s.get("reports") or "", os.path.join(s.get("runtime") or "", "facts")


def day_of(a):
    return datetime.date.fromisoformat(a.date) if getattr(a, "date", None) else now_tz().date()


def emit(a, obj, lines):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str) if getattr(a, "json", False) else "\n".join(lines))


def decisions_path(reports, day):
    return os.path.join(reports, "ela", "watch", f"{day}-decisions.json")


def cmd_scan(a):
    s = site()
    reports, facts = roots(s)
    got = scan(facts, reports, now_tz(), write=a.write)
    emit(a, got, [f"{got['tracked']} tracked · {got['skipped']['legacy']} legacy · {len(got['skipped']['held'])} held · "
                  f"{len(got['skipped']['done_today'])} written today · {len(got['triggered'])} due a decision"
                  + (f" · {len(got['waiting'])} waiting" if got["waiting"] else "")
                  + (f" · {len(got['replies'])} repl{'ies' if len(got['replies']) != 1 else 'y'} to ela to judge" if got["replies"] else "")]
         + [f"- {r['key']} {'(yours) ' if r['owner_held'] else ''}{clip(r['summary'], 60)} — "
            + "; ".join(f"{t['kind']}: {t['says']}" for t in r["triggers"]) for r in got["triggered"]]
         + ([] if a.write else ["dry run; --write stores the pass"]))


def load_scan(reports, day):
    got = read_json(scan_path(reports, day.isoformat()), None)
    if got is None:
        print(f"no scan for {day}: run `ela watch scan --write` first", file=sys.stderr); sys.exit(EX_NOTFOUND)
    return got


def cmd_prompt(a):
    s = site()
    reports, facts = roots(s)
    day = day_of(a)
    got = load_scan(reports, day)
    rows = prompt_rows(got, facts)
    path = decisions_path(reports, day.isoformat())
    try:
        cited = asks_mod().precedents(reports, "watch")
    except (ValueError, OSError):
        cited = []
    doc = {"date": got["date"], "decisions_file": path, "tickets": rows, "waiting": got.get("waiting"),
           "replies": got.get("replies") or [], "precedents": cited}
    write_json(prompt_keep_path(reports, now_tz()), doc)     # the corpus a later replay runs over
    if a.json:
        print(json.dumps({k: v for k, v in doc.items() if k != "precedents"}, ensure_ascii=False, indent=1))
    else:
        print(prompt_text(got, rows, path, cited))


def cmd_decide(a):
    s = site()
    reports, facts = roots(s)
    if a.apply and os.environ.get("ELA_NO_APPLY"):
        print("refused: decide --apply inside an unattended session (ELA_NO_APPLY); the runner applies after the session",
              file=sys.stderr); sys.exit(EX_USAGE)
    now = now_tz()
    day = day_of(a)
    got = load_scan(reports, day)
    path = a.from_file or (judge_path(reports, day.isoformat(), a.judge) if a.judge else decisions_path(reports, day.isoformat()))
    decisions = read_json(path, None)
    if decisions is None:
        print(f"no decisions in {path}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    r = decide(decisions, got, facts, reports, now, apply=a.apply, judge=a.judge)
    emit(a, r, [f"{x['key']}: reply {x['reply']} by {x['by']} disputes ela — corrected {x['act'] or x['key']}, asked as "
                f"{x['topic']}, no comment until {x['quiet_until']}" for x in r["disputes"]]
         + [f"{x['key']}: reply {x['reply']} by {x['by']} agrees" for x in r["agreed"]]
         + [f"{x['key']}: reply {x['reply']} refused — {x['why']}" for x in r["refused_replies"]]
         + [f"{x['key']}: act — {x['state']}" + "".join(f"\n    {d}" for d in x["did"]) for x in r["acts"]]
         + [f"{x['key']}: held for the owner's confirm ({x['topic']}) — {x['proposed']}" for x in r["held"]]
         + [f"{x['key']}: ask — {x['question']}" for x in r["asks"]] + [f"{x['key']}: nothing due — {x['why']}" for x in r["none"]]
         + [f"{x['key']}: refused — {x['why']}" for x in r["refused"]]
         + [f"{x['topic']}: the owner's letter — {x.get('state') or x.get('refused')}" for x in r["answered"]]
         + ([] if a.apply else ["dry run; --apply writes the acts and stores the asks"]))


def judge_row(got, key):
    row = next((r for r in got.get("judge") or [] if r["key"] == key), None)
    if row is None:
        print(f"{key} is not due judging in the scan of {got.get('date')}: `ela watch judge` lists the queue", file=sys.stderr)
        sys.exit(EX_NOTFOUND)
    return row


def cmd_judge(a):
    s = site()
    reports, _ = roots(s)
    got = load_scan(reports, day_of(a))
    q = got.get("judge") or []
    emit(a, {"date": got["date"], "judge": q}, [f"- {r['key']} {r['priority']} · {r['status']} · {clip(r['summary'], 60)} — {r['why']}"
                                               + (f" · failed {r['fails']}×" if r.get("fails") else "") for r in q]
         or ["nothing due judging"])


def cmd_judge_prompt(a):
    s = site()
    reports, facts = roots(s)
    day = day_of(a)
    row = judge_row(load_scan(reports, day), a.key)
    iss = read_json(os.path.join(facts, "jira", "issues", f"{a.key}.json"), None)
    if iss is None:
        print(f"no facts for {a.key}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    page = a.write or os.path.join(reports, "ela", f"{day.isoformat()}-deep-{a.key}-judged.md")
    path = judge_path(reports, day.isoformat(), a.key)
    if a.json:
        print(json.dumps({"key": a.key, "row": row, "page": page, "decision_file": path, "homes": homes(s.get("vault"), a.key),
                          "topics": topics_on(reports, a.key)}, ensure_ascii=False, indent=1))
    else:
        print(judge_prompt_text(row, iss, facts, reports, s.get("vault"), page, path, jira_base(s)))


def cmd_judged(a):
    s = site()
    reports, facts = roots(s)
    if not a.failed and not a.verdict:
        print("judged: --verdict TEXT, or --failed", file=sys.stderr); sys.exit(EX_USAGE)
    try:
        j = judged(reports, facts, a.key, now_tz(), verdict=a.verdict, failed=a.failed)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)
    emit(a, j, [f"{a.key}: failed {j['fails']}×" if a.failed else f"{a.key}: judged — {j['verdict']}"])


def cmd_answer(a):
    s = site()
    try:
        t = answer(s.get("reports") or "", a.topic, a.letter, now_tz(), note=" ".join(a.note or []) or None)
    except KeyError:
        print(f"no topic {a.topic}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)
    c = t["closed"]
    wrong = t.get("kind", "ruling") == "ruling" and c["letter"] != t["options"][0]["letter"]
    emit(a, t, [f"{t['id']}: {c['letter']} recorded" + (f", with the cause: {c['note']}" if wrong and c.get("note") else
                "; against ela's proposal and no cause given: add one with `ela watch cause " + t["id"] + " <why>`" if wrong else "")])


def cmd_cause(a):
    s = site()
    try:
        t = cause(s.get("reports") or "", a.topic, " ".join(a.why), now_tz())
    except KeyError:
        print(f"no answered topic {a.topic}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    emit(a, t, [f"{t['id']}: cause kept with the {t['closed']['letter']}"])


def cmd_track(a):
    try:
        got = track(site().get("reports") or "", a.keys, now_tz(), why=a.why, until=a.until)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)
    emit(a, got, [f"{r['key']}: tracked" + (f" until {r['until']}" if r["until"] else "") + (f" — {r['why']}" if r["why"] else "")
                  for r in got])


def cmd_untrack(a):
    got = untrack(site().get("reports") or "", a.keys, now_tz())
    emit(a, got, [f"{k}: no longer tracked" for k in got] or ["none of them was tracked"])


def cmd_review(a):
    s = site()
    reports, facts = roots(s)
    now = now_tz()
    if a.step == "prompt":
        doc = review_prompt(reports, facts, now)
        write_json(os.path.join(reports, "ela", "watch", f"{now:%Y-%m-%d-%H%M}-review-prompt.json"), doc)
        if a.json:
            print(json.dumps(doc, ensure_ascii=False, indent=1))
        else:
            print(review_text(doc) if doc["cases"] else "no case waits for a second reading")
        return
    if a.apply and os.environ.get("ELA_NO_APPLY"):
        print("refused: review --apply inside an unattended session (ELA_NO_APPLY); the runner applies after the session",
              file=sys.stderr); sys.exit(EX_USAGE)
    if a.step == "release":
        got = review_release(reports, now, apply=a.apply)
        emit(a, got, [f"{x}: to the owner, {NOT_READ_TWICE}" for x in got] or ["no case was pending"]
             + ([] if a.apply else ["dry run; --apply releases"]))
        return
    path = a.from_file or review_path(reports, now.date().isoformat())
    entries = read_json(path, None)
    if entries is None:
        print(f"no entries in {path}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    r = review_settle(entries, reports, now, apply=a.apply)
    emit(a, r, [f"{x['key']}: settled {x['letter']} on {x['source'].get('kind')} {x['source'].get('ref')}" for x in r["settled"]]
         + [f"{x['key']}: settled {x['letter']} on {x['source'].get('kind')} {x['source'].get('ref')}, held for the owner (a low act)" for x in r["held"]]
         + [f"{x['key']}: to the owner, read twice, not settled — {x['why']}" for x in r["unsettled"]]
         + [f"{x['topic']}: refused — {x['why']}" for x in r["refused"]] + ([] if a.apply else ["dry run; --apply carries them"]))


def cmd_measure(a):
    s = site()
    reports, facts = roots(s)
    ws = measure(facts, reports, owner_of(facts), now_tz().date(), weeks=a.weeks)
    emit(a, ws, [f"{w['week']}{' (so far)' if w['partial'] else ''}: {pct(w['changed']['share'])} of {w['changed']['decided']} "
                 f"settled without the owner · backlog {pct(w['backlog']['share'])} of {w['backlog']['decided']} · changes "
                 + ", ".join(f"{x} {w['changes'][x]}" for x in WHO) for w in ws])


def cmd_asks(a):
    got = asks(site().get("reports") or "", now_tz().date())
    emit(a, got, [f"- {x['question']} " + " · ".join(f"{o['letter']} {o['text']}" for o in x["options"]) for x in got]
         or ["no open topics"])


def cmd_dm(a):
    if a.apply and os.environ.get("ELA_NO_APPLY"):
        print("refused: dm --apply inside an unattended session (ELA_NO_APPLY)", file=sys.stderr); sys.exit(EX_USAGE)
    r = dm(site().get("reports") or "", now_tz(), apply=a.apply)
    emit(a, r, [f"{x['kind']} ({len(x['topics'])} new): {'dry run' if x['dry_run'] else x['permalink']}\n{x['text']}" for x in r["sent"]]
         + [f"failed {x['plan']['kind']}: {x['why']}" for x in r["failed"]]
         + ([] if r["sent"] or r["failed"] else ["nothing to send"]) + ([] if a.apply else ["dry run; --apply sends"]))


def main():
    ap = argparse.ArgumentParser(prog="ela watch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="the site's env file (bin/ela passes it)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="every tracked MH ticket against the last pass; the triggered ones; --write stores the pass")
    p.add_argument("--date"); p.add_argument("--write", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("prompt", help="the judgment session's input: each triggered ticket with its triggers and facts")
    p.add_argument("--date"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_prompt)
    p = sub.add_parser("decide", help="the session's decisions checked and carried; a dry run unless --apply")
    p.add_argument("--from", dest="from_file", help="the decisions file (default <reports>/ela/watch/<date>-decisions.json)")
    p.add_argument("--judge", metavar="KEY", help="the judging session's one decision on KEY, checked against the judge queue "
                   "(default file <reports>/ela/watch/<date>-judge-KEY.json)")
    p.add_argument("--date"); p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decide)
    p = sub.add_parser("judge", help="the judge queue of the day's scan: the owner's tickets due a judging, in order")
    p.add_argument("--date"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_judge)
    p = sub.add_parser("judge-prompt", help="the judging session's input for one ticket of the queue")
    p.add_argument("key"); p.add_argument("--write", metavar="PAGE", help="the ticket page the session writes "
                   "(default <reports>/ela/<date>-deep-KEY-judged.md, apart from a deep pick's page)")
    p.add_argument("--date"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_judge_prompt)
    p = sub.add_parser("judged", help="the runner's record of a judging: the verdict, or --failed")
    p.add_argument("key"); p.add_argument("--verdict", help="one line, ela's own verdict"); p.add_argument("--failed", action="store_true")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_judged)
    p = sub.add_parser("answer", help="his letter on a topic: recorded; a chosen option's writes go out at the next pass")
    p.add_argument("topic"); p.add_argument("letter")
    p.add_argument("note", nargs="*", help="his words after the letter: the cause of a letter against ela, or the fact asked for")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_answer)
    p = sub.add_parser("cause", help="the cause for an earlier letter against ela that came without one; kept in the watch's corrections")
    p.add_argument("topic"); p.add_argument("why", nargs="+"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_cause)
    p = sub.add_parser("track", help="track tickets: each is due a decision on any human change (field, comment, link)")
    p.add_argument("keys", nargs="+"); p.add_argument("--why", help="why he follows it; shown with the ticket in the prompt")
    p.add_argument("--until", help="the last day it is tracked (YYYY-MM-DD)")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_track)
    p = sub.add_parser("untrack", help="end tracking; the row is kept, marked ended")
    p.add_argument("keys", nargs="+"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_untrack)
    p = sub.add_parser("review", help="the second reading: prompt, settle --from FILE, release; a dry run unless --apply")
    p.add_argument("step", choices=("prompt", "settle", "release")); p.add_argument("--from", dest="from_file")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_review)
    p = sub.add_parser("measure", help="the share of ticket work ela settled without the owner, week by week, with every change attributed")
    p.add_argument("--weeks", type=int, default=6); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_measure)
    p = sub.add_parser("asks", help="the open topics, as today.md shows them")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_asks)
    p = sub.add_parser("dm", help="the owner's ela DM: a reminder, at most one a day when a topic is new, pointing at ela/watch.md; a dry run unless --apply")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_dm)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
