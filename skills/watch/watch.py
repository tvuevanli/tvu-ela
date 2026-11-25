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

A state trigger (all but changed and answered) fires only when no decision was recorded since the ticket last moved,
so nothing is written on a schedule; a change trigger waits as pending until a decision takes it. Left alone: legacy
(no activity for LEGACY_DAYS, outside the active sprint and the current release lines), held tickets (holds.json,
`ela: hold <key>`), and a ticket that already had its set of writes today. The owner's tickets come first.

The decision itself is judgment: a model session (the runner starts one, as for its other judgment passes, following
/ela:watch) reads `prompt`, writes one decision per triggered ticket to a file, and `decide` checks and carries them:
act (the writes, one set per ticket a day, through `ela dry`'s tier-1 class board-watch, each announced by a signed
comment that jira.py signs and checks), ask (the owner's topic: today.md and his ela DM, `asks`/`dm`), or none.
Never by ela, always an ask: a terminal status, a Slack post under his name, a customer channel, anything about people.

A reply after ela's signed comment is judged too: the session marks each one the scan lists as disputing the comment or
not, and only a plain `"disputes": false` is agreement (unsure, or no mark, counts as a dispute). A dispute is a
correction under the demotion rule: `ela dry`'s record takes verdict corrected with the act id and the reply's link,
board-watch returns to confirm, the reply becomes an ask on today.md naming the ticket and the reply, and ela posts no
comment on that ticket for DISPUTE_QUIET_DAYS.

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
  answer  TOPIC A|B|C [--json]                  his letter on a topic (today.md's tick, or said): recorded; an option
                                                with writes is carried out at the next decide --apply
  asks    [--json]                              the open topics; the vault's sync puts them on ela/watch.md (and a
                                                line on today.md), where they live
  dm      [--apply] [--json]                    the owner's ela DM, a reminder only: at most one message a day, when a
                                                topic is new — the count, the new ones a line each, the vault page and
                                                the CLI verb; no thread per topic; a dry run unless --apply
Store: <reports>/ela/watch.json (per ticket: the last pass's snapshot, pending triggers, the last decision, the day of
its last set of writes, the comments ela said, the replies judged, the day a reply disputed ela), <reports>/ela/watch/<date>-scan.json, <reports>/ela/watch-topics.json,
<reports>/ela/drafts/watch/ (each comment's text, the file a write names).
Exit codes: 0 ok · 2 usage · 3 not found.
"""
import argparse, datetime, hashlib, json, os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "jira"))
sys.path.insert(0, os.path.join(SKILLS, "focus"))
import jira as J  # noqa: E402 — the signing rule and the comment's text: one place
import hold as H  # noqa: E402 — the holds, `ela: hold <key>`

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
    rows, skipped, tracked, replies = [], {"legacy": 0, "held": [], "done_today": []}, 0, []
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
        pend += [list(x) for x in new if list(x) not in pend]
        rec["pending"], rec["snap"] = pend, snap(iss)
        if legacy(iss, now, lines):
            skipped["legacy"] += 1
            continue
        tracked += 1
        if H.holding(holds, [key], fields(iss).get("summary") or "", now.date()):
            skipped["held"].append(key)
            continue
        if rec.get("acted") == today:
            skipped["done_today"].append(key)
            continue
        trig = [tuple(p) for p in pend] + answered_trigger(iss, rec, owner)
        if moved_since(iss, rec.get("decided")):
            trig += state_triggers(iss, now, owner)
        if not trig:
            continue
        f = fields(iss)
        rows.append({"key": key, "summary": f.get("summary") or "", "status": name(f.get("status")),
                     "assignee": name(f.get("assignee")) or None, "priority": name(f.get("priority")), "due": f.get("duedate"),
                     "labels": f.get("labels") or [], "updated": str(f.get("updated") or "")[:16],
                     "owner_held": is_owner(f.get("assignee"), owner), "chinese": J.chinese(ticket_text(iss)),
                     "quiet_until": quiet_until(rec) if (quiet_until(rec) or "") > today else None,
                     "triggers": [{"kind": k, "says": s} for k, s in trig]})
    rows.sort(key=lambda r: (not r["owner_held"], ("Highest", "High", "Medium", "Low", "Lowest").index(r["priority"])
                             if r["priority"] in ("Highest", "High", "Medium", "Low", "Lowest") else 5, r["key"]))
    out = {"date": today, "at": now.isoformat(timespec="seconds"), "tracked": tracked, "skipped": skipped,
           "triggered": rows[:MAX_PER_PASS], "waiting": [r["key"] for r in rows[MAX_PER_PASS:]], "owner": owner.get("name"),
           "replies": replies}
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
                        comments=[{"by": name(c.get("author")), "at": str(c.get("created") or "")[:16], "ela": is_ela(c),
                                   "text": clip(text_of(c.get("body")), 500)} for c in cs]))
    return out


def prompt_text(scanned, rows, decisions_path):
    L = [f"# The MH board watch · {scanned['date']}", "",
         f"Follow /ela:watch. {len(rows)} ticket{'s' if len(rows) != 1 else ''} due a decision; write one decision per "
         f"ticket to {decisions_path} as the skill describes, then check it with `ela watch decide --from {decisions_path}` "
         "(a dry run). Nothing here is applied by you.", ""]
    for r in rows:
        L += [f"## {r['key']} · {r['summary']}",
              f"{r['status']} · {r['assignee'] or 'nobody'} · {r['priority']}" + (f" · due {r['due']}" if r.get("due") else "")
              + (" · the owner's ticket" if r["owner_held"] else "") + (" · the ticket's text is Chinese" if r["chinese"] else "")
              + (f" · a reply disputed ela: no comment until {r['quiet_until']} (ask or none)" if r.get("quiet_until") else ""),
              ""] + [f"- trigger {t['kind']}: {t['says']}" for t in r["triggers"]]
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
    if v == "link":
        return f"ela jira link {key} {w['other']} --type {shlex.quote(str(w['type']))} --note-file {note}"
    raise ValueError(v)


def check_act(key, d, iss, rec, today):
    """Why a decision to act may not go out, or None."""
    if rec.get("acted") == today:
        return "one set of writes a day: this ticket had its set today"
    if (quiet_until(rec) or "") > today:
        return (f"a reply disputed ela's comment here on {rec['disputed']}: no comment from ela until {quiet_until(rec)}; "
                "an ask or none")
    writes = d.get("writes") or []
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


def act_writes(key, d, reports):
    """The decision's set as `ela dry` writes: the comment's file, then the field changes (each naming the note jira.py
    posts after it; the same note again is one comment, jira.py skips an identical one), or the comment alone."""
    text = d["comment"].strip()
    p = os.path.join(drafts_dir(reports), f"{key}-{hashlib.sha1(text.encode()).hexdigest()[:8]}.txt")
    why = clip(d.get("why") or "", 200) or "the board watch's decision"
    if d.get("writes"):
        return p, text, [{"target": key, "command": command_of(key, w, p), "why": why} for w in d["writes"]]
    return p, text, [{"target": key, "command": f"ela jira comment {key} --from-file {p}", "why": why}]


def dry_mod():
    sys.path.insert(0, os.path.join(SKILLS, "dry"))
    import dry as D                                            # noqa: E402 — the class, its record and its undo
    return D


def topic_id(key):
    return f"watch:{key}"


def put_topic(topics, key, d, today, summary=""):
    """The owner's topic for a ticket: one open topic per ticket; an ask on an open one updates it in place, so its
    thread and its first day stay."""
    tid = topic_id(key)
    t = topics["topics"].get(tid)
    opts = d.get("options") or [{"letter": "A", "text": "do what is proposed"}, {"letter": "B", "text": "leave it"}]
    opts = [{"letter": o.get("letter") or "ABC"[i], "text": o.get("text") or "", "writes": o.get("writes") or [],
             "comment": o.get("comment") or ""} for i, o in enumerate(opts[:3])]
    if t and not t.get("closed"):
        t.update(question=d["question"], options=opts, asked=today)
        return tid, False
    topics["topics"][tid] = {"id": tid, "key": key, "summary": summary, "question": d["question"], "options": opts,
                             "first": today, "asked": today, "thread": None, "posted": {}, "closed": None}
    return tid, True


def decide(decisions, scanned, facts, reports, now, apply=False, runner=None):
    """The session's decisions checked and carried. → {date, acts, asks, none, refused, answered}."""
    D = dry_mod()
    today = now.date()
    st, topics = load_state(reports), load_topics(reports)
    due = {r["key"]: r for r in scanned.get("triggered") or []}
    out = {"date": today.isoformat(), "acts": [], "asks": [], "none": [], "refused": [], "answered": []}
    out.update(judge_replies(decisions, scanned, st, topics, reports, now, apply))
    for d in decisions.get("decisions") or []:
        key, verdict = d.get("key"), d.get("verdict")
        if key not in due:
            out["refused"].append({"key": key, "why": "not due a decision in today's scan"}); continue
        iss = read_json(os.path.join(facts, "jira", "issues", f"{key}.json"), {})
        rec = st["tickets"].setdefault(key, {"first": today.isoformat()})
        if verdict == "act":
            problem = check_act(key, d, iss, rec, today.isoformat())
            if problem:
                out["refused"].append({"key": key, "why": problem}); continue
            path, text, writes = act_writes(key, d, reports)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            try:
                got = D.act(reports, CLASS, key, writes, today, apply=apply, runner=runner, now=now)
            except ValueError as e:
                out["refused"].append({"key": key, "why": str(e)}); continue
            out["acts"].append({"key": key, "writes": [w["command"] for w in writes], "comment": text, **got})
            if apply and got["state"] in ("applied", "open"):
                rec.update(acted=today.isoformat(), decided=now.isoformat(timespec="seconds"), verdict="act", pending=[])
                rec.setdefault("said", []).append(hashlib.sha1(norm(text).encode()).hexdigest()[:16])
        elif verdict == "ask":
            if not (d.get("question") or "").strip():
                out["refused"].append({"key": key, "why": "an ask carries its question"}); continue
            tid, new = put_topic(topics, key, d, today.isoformat(), due[key].get("summary") or "")
            out["asks"].append({"key": key, "topic": tid, "new": new, "question": d["question"]})
            if apply:
                rec.update(decided=now.isoformat(timespec="seconds"), verdict="ask", pending=[])
        elif verdict == "none":
            out["none"].append({"key": key, "why": d.get("why") or ""})
            if apply:
                rec.update(decided=now.isoformat(timespec="seconds"), verdict="none", pending=[])
        else:
            out["refused"].append({"key": key, "why": f"verdict {verdict!r}: act, ask or none"})
    out["answered"] = carry_answers(topics, st, facts, reports, now, apply, runner)
    if apply:
        write_json(state_path(reports), st)
        write_json(topics_path(reports), topics)
    return out


def disputes(mark):
    """Whether the session's mark on a reply counts as a dispute: anything but a plain false (unsure is a dispute)."""
    return mark is not False


def judge_replies(decisions, scanned, st, topics, reports, now, apply):
    """The session's marks on the replies the scan listed. Agreement is recorded as judged. A dispute is a correction:
    `ela dry`'s record takes verdict corrected (the act id, the reply's link) and the class returns to confirm; the
    reply becomes the owner's ask; the ticket is quiet for DISPUTE_QUIET_DAYS. A reply the session did not mark waits
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
                         f"{r['class']} is back at your confirm and ela stays off the ticket until {until}. What now?"),
            "options": [{"letter": "A", "text": "leave it to the thread on the ticket", "writes": [], "comment": ""},
                        {"letter": "B", "text": f"undo ela's act {undo}", "writes": [], "comment": ""}],
            "first": today, "asked": today, "thread": None, "posted": {}, "closed": None})
        notice = None
        if apply:
            notice = D.correct(reports, r["class"], "correction", ref=r.get("act") or r["key"],
                               note=f"{r['by']} disputed ela's comment on {r['key']}: {r['link']}", now=now)
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
        d = {"writes": opt.get("writes") or [], "comment": opt.get("comment") or "", "why": f"the owner's {c['letter']} on {t['id']}"}
        problem = check_act(key, d, iss, rec, today.isoformat())
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
            rec.setdefault("said", []).append(hashlib.sha1(norm(text).encode()).hexdigest()[:16])
    return done


def answer(reports, tid, letter, now):
    """His letter on a topic: recorded, the topic closed. → the topic; KeyError when unknown, ValueError for a letter it
    does not offer."""
    topics = load_topics(reports)
    t = topics["topics"].get(tid)
    if not t:
        raise KeyError(tid)
    letter = letter.upper()
    if letter not in [o["letter"] for o in t["options"]]:
        raise ValueError(f"{tid} offers {', '.join(o['letter'] for o in t['options'])}, not {letter}")
    if not t.get("closed"):
        t["closed"] = {"letter": letter, "at": now.isoformat(timespec="seconds")}
        write_json(topics_path(reports), topics)
    return t


def open_topics(reports):
    return [t for t in load_topics(reports)["topics"].values() if not t.get("closed")]


def asks(reports, today):
    """The open topics as today.md shows its asks: a question, lettered options, each letter answered by `ela watch
    answer`, which records it (the writes of a chosen option go out at the next pass)."""
    out = []
    for t in sorted(open_topics(reports), key=lambda t: (t["first"], t["key"])):
        text = f"{t['key']} {t.get('summary') or ''}: {t['question']}".strip()
        out.append({"id": t["id"], "question": text, "first": t["first"],
                    "options": [{"letter": o["letter"], "text": o["text"], "does": f"ela watch answer {t['id']} {o['letter']}",
                                 "recommended": i == 0} for i, o in enumerate(t["options"])],
                    "sig": hashlib.sha256(json.dumps([t["question"], t["options"]], sort_keys=True).encode()).hexdigest()[:12]})
    return out


# ── the owner's DM: a reminder, at most one a day, when a topic is new; the topics live on ela/watch.md ──────────
SLACK = os.path.join(SKILLS, "slack", "slack.py")


def jira_base(s=None):
    env = (s or site()).get("env")
    try:
        return next((l.split("=", 1)[1].strip().strip("'\"").rstrip("/") for l in open(os.path.expanduser(env))
                     if l.startswith("JIRA_BASE_URL=")), "")
    except (OSError, TypeError):
        return ""


WATCH_PAGE = "ela/watch.md"        # the vault page every open topic lives on; the DM only points at it


def page(reports, today, base=""):
    """ela/watch.md: every open topic, oldest first: the ticket, the question, each letter with the CLI line that
    answers it. The vault is where the topics live; Slack only reminds (the owner's word, 2026-11-25: he answers in
    the CLI, not in a thread)."""
    ts = sorted(open_topics(reports), key=lambda t: (t["first"], t["key"]))
    L = ["# Board watch · waiting for your letter", ""]
    if not ts:
        return "\n".join(L + ["Nothing waits: every topic has its letter.", ""])
    L += [f"{len(ts)} topic{'s' if len(ts) != 1 else ''} wait. Answer each in the CLI: `ela watch answer watch:<KEY> <letter>`; "
          "a chosen option's writes go out at the watch's next pass. `ela watch asks` lists the same.", ""]
    for t in ts:
        link = f"[{t['key']}]({base}/browse/{t['key']})" if base else t["key"]
        L += [f"### {link} {t.get('summary') or ''}".rstrip(), "", f"Open since {t['first']}. {t['question']}", ""]
        L += [f"- **{o['letter']}**: {o['text']} · `ela watch answer {t['id']} {o['letter']}`" for o in t["options"]]
        L += [""]
    return "\n".join(L)


def dm_plan(topics, today, base=""):
    """What today's DM pass sends: at most one reminder a day, and only when a topic is new since the last reminder:
    how many are new, how many wait in all, the new ones a line each, and where they live (the vault page) and how to
    answer (the CLI). No thread per topic, no repeat for an open one, no line when one settles: the vault page carries
    them (the owner's word, 2026-11-25). → [{kind: "reminder", topics: [ids], text}]."""
    day = today.isoformat()
    if topics["roots"].get(day):
        return []
    open_ = [t for t in topics["topics"].values() if not t.get("closed")]
    fresh = sorted((t for t in open_ if not t.get("thread")), key=lambda t: t["key"])
    if not fresh:
        return []
    lines = [f"ela · the board watch · {today:%a %m-%d}: {len(fresh)} new topic{'s' if len(fresh) != 1 else ''}, "
             f"{len(open_)} waiting in all. They are on the vault page {WATCH_PAGE[:-3]}; answer in the CLI with "
             "`ela watch answer watch:<KEY> <letter>`."]
    lines += [f"• {t['key']} {(t.get('summary') or '')[:70]}".rstrip() + (f" {base}/browse/{t['key']}" if base else "") for t in fresh]
    return [{"kind": "reminder", "topics": [t["id"] for t in fresh], "text": "\n".join(lines)}]


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
    if a.json:
        print(json.dumps({"date": got["date"], "decisions_file": path, "tickets": rows, "waiting": got.get("waiting"),
                          "replies": got.get("replies") or []},
                         ensure_ascii=False, indent=1))
    else:
        print(prompt_text(got, rows, path))


def cmd_decide(a):
    s = site()
    reports, facts = roots(s)
    if a.apply and os.environ.get("ELA_NO_APPLY"):
        print("refused: decide --apply inside an unattended session (ELA_NO_APPLY); the runner applies after the session",
              file=sys.stderr); sys.exit(EX_USAGE)
    now = now_tz()
    day = day_of(a)
    got = load_scan(reports, day)
    path = a.from_file or decisions_path(reports, day.isoformat())
    decisions = read_json(path, None)
    if decisions is None:
        print(f"no decisions in {path}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    r = decide(decisions, got, facts, reports, now, apply=a.apply)
    emit(a, r, [f"{x['key']}: reply {x['reply']} by {x['by']} disputes ela — corrected {x['act'] or x['key']}, asked as "
                f"{x['topic']}, no comment until {x['quiet_until']}" for x in r["disputes"]]
         + [f"{x['key']}: reply {x['reply']} by {x['by']} agrees" for x in r["agreed"]]
         + [f"{x['key']}: reply {x['reply']} refused — {x['why']}" for x in r["refused_replies"]]
         + [f"{x['key']}: act — {x['state']}" + "".join(f"\n    {d}" for d in x["did"]) for x in r["acts"]]
         + [f"{x['key']}: ask — {x['question']}" for x in r["asks"]] + [f"{x['key']}: nothing due — {x['why']}" for x in r["none"]]
         + [f"{x['key']}: refused — {x['why']}" for x in r["refused"]]
         + [f"{x['topic']}: the owner's letter — {x.get('state') or x.get('refused')}" for x in r["answered"]]
         + ([] if a.apply else ["dry run; --apply writes the acts and stores the asks"]))


def cmd_answer(a):
    s = site()
    try:
        t = answer(s.get("reports") or "", a.topic, a.letter, now_tz())
    except KeyError:
        print(f"no topic {a.topic}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)
    emit(a, t, [f"{t['id']}: {t['closed']['letter']} recorded"])


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
    p.add_argument("--date"); p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_decide)
    p = sub.add_parser("answer", help="his letter on a topic: recorded; a chosen option's writes go out at the next pass")
    p.add_argument("topic"); p.add_argument("letter"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_answer)
    p = sub.add_parser("asks", help="the open topics, as today.md shows them")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_asks)
    p = sub.add_parser("dm", help="the owner's ela DM: a reminder, at most one a day when a topic is new, pointing at ela/watch.md; a dry run unless --apply")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_dm)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
