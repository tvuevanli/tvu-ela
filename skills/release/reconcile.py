#!/usr/bin/env python3
"""A build a lane took, reconciled against Jira: what each ticket the build carries still lacks. Stdlib only.

L1, a module of the release verb (`ela release reconcile <lane> [--build N] [--batch [--apply]] [--json]`). The scope
is the build record (<reports>/releases/<line>/<date>-build-<n>-to-<lane>.json): its services, versions and ticket
keys. For each ticket of the build, read now:

  fixed-in  an entry for the slug of every service that carries it, at or past this build's version of it, in the
            same series. A bare entry (`unified-streaming@2.1.91`) and its canonical form (`2.1.91+382`) are one fix.
            None: the entry is missing. Only older ones: rework the build carries was not appended. An existing entry
            is never rewritten; the proposal is an append. `flag:no-version` and `flag:non-carrier` tickets owe none.
  label     the line's release label (map/release.yaml lines.<line>.label).
  status    at or past what the release thread announced (Review), when it announced one for the key.
  assignee  the person the thread announced (`改派 Erin`, `派 Alice：MH-…`), on a ticket not yet Done.

The release thread (the record's `source` permalink) is read for what it announced: per key, the status, the
assignee and the agent asked to do the Jira side; a key reverted and folded into another is not a Fixed In matter
and becomes an open question (ADR 0016) to that ticket's holder. A thread that cannot be read is a gap: Fixed In and
label are still judged, status and assignee are not.

Each run keeps its reading beside the record (`<name>.reconcile.json`): the release note's Jira gaps table and the
agent pattern read it. A miss of the same kind by the same agent on three builds becomes one open question to that
agent's owner, with a message drafted for the owner of ela to send; ela posts nothing in the thread.

The batch (`--batch`) is the rule-selected write: for each ticket with a gap, the Fixed In append and the label, run
through the jira capability's own verbs (dry run unless --apply; append-only; present entries skipped). Status,
assignee and folds are never in it.

Usage: reconcile.py --help    this text; the verb is `ela release reconcile`.
"""
import concurrent.futures, datetime, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SKILLS, "promote"))
sys.path.insert(0, os.path.join(SKILLS, "fixedin"))
sys.path.insert(0, os.path.join(SKILLS, "vault"))

KEY = re.compile(r"(?<![\w-])([A-Z][A-Z0-9]+-\d+)(?![\w-])")
PERMALINK = re.compile(r"https://[\w.-]+\.slack\.com/archives/[A-Z0-9]+/p\d{16}")
PAST_REVIEW = ("review", "done", "closed", "resolved", "cancelled")
TERMINAL = ("done", "closed", "resolved", "cancelled")
NO_FIXED_IN = ("flag:no-version", "flag:non-carrier")      # conventions.md: Fixed In stays empty and is not a gap
PATTERN_BUILDS = 3                                         # the same miss by the same agent on this many builds: a question
AUDIENCE = "sync-eng-qa-ux"                                # meetings.yaml: the engineering and QA sync hears release hygiene
KINDS = {"fixed-in": "no Fixed In", "rework": "rework not appended", "label": "no release label",
         "status": "status behind the thread", "assignee": "assignee not as announced"}

# the thread's words, as andyBot and the engineers' agents write them (11-10 and 11-11 release threads)
REVIEW_RX = re.compile(r"审查|\bReview\b")
ASSIGN_LIST_RX = re.compile(r"派\s*([A-Za-z][\w.]*)\s*[：:]\s*((?:[A-Z][A-Z0-9]+-\d+[\s、,，]*)+)")
ASSIGN_ALL_RX = re.compile(r"(?:改派|经办人(?:是|为)?)\s*([A-Za-z][\w.]*)")
FOLD_RX = re.compile(r"([A-Z][A-Z0-9]+-\d+)[^。\n]{0,40}?revert[^。\n]{0,20}?(?:并入|合并(?:到|进)?|folded into|into)\s*([A-Z][A-Z0-9]+-\d+)", re.I)
BOT_TO_RX = re.compile(r"@([A-Za-z][\w ]*?(?:Bot|bot|agent))\b")
JOB_URL_RX = re.compile(r"/job/([\w.-]+)/(\d+)/?")                                  # …/job/ur-caller/382/
JOB_SAID_RX = re.compile(r"([a-z][\w-]*)\s+v(\d+\.\d+\.\d+(?:\.\d+)?)\s*\(#(\d+)\)")        # ur-caller v2.1.90 (#381)
VERSION_SAID_RX = re.compile(r"\bv(\d+\.\d+\.\d+(?:\.\d+)?)\b")


def P():
    import promote                                         # noqa: E402 — the Fixed In grammar and the version order
    return promote


def R():
    import release                                         # noqa: E402 — the build records, the map
    return release


# ── reading a ticket ──────────────────────────────────────────────────────────────────────────────────

def fields(issue):
    return (issue or {}).get("fields") or {}


def fixed_in_text(issue):
    f = fields(issue)
    fid = (R().rmap("fixed_in") or {}).get("field") or "customfield_11252"
    raw = f.get(fid)
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("text", ""))
            if n.get("type") in ("hardBreak",):
                out.append("\n")
            for c in n.get("content") or []:
                walk(c)
            if n.get("type") == "paragraph":
                out.append("\n")
        elif isinstance(n, list):
            for c in n:
                walk(c)
    walk(raw)
    return "".join(out)


def name_of(issue, what):
    v = fields(issue).get(what)
    return (v or {}).get("displayName") or (v or {}).get("name") if isinstance(v, dict) else v


def same_person(announced, display):
    """`Erin` announced, `Erin Zhang` holds it: a name the thread wrote matches a word of the display name, or its start."""
    a, d = (announced or "").strip().lower(), (display or "").strip().lower()
    if not a or not d:
        return False
    return a == d or any(w == a or w.startswith(a) for w in re.split(r"[\s._-]+", d)) or d.replace(" ", "").startswith(a)


# ── the service a record line names ───────────────────────────────────────────────────────────────────

def slug_of(service):
    """The release map's slug for a record's service name (`UR Caller` → unified-streaming), through fixedin's one
    table of the names the team writes; None when it names none."""
    import fixedin as F                                    # noqa: E402
    return F.resolve_named_one(str(service or ""))


# ── the release thread ────────────────────────────────────────────────────────────────────────────────

def is_bot(user):
    return bool(re.search(r"bot$|agent$", (user or "").strip(), re.I))


def agent_owner(agent, humans):
    """The person behind an agent, by name: `Summer Slack Bot` is Summer Chen's, `andyBot` andyzhao's."""
    stem = re.sub(r"(?i)(slack\s*)?bot$|agent$", "", (agent or "").strip()).strip().split()
    stem = (stem[0] if stem else "").lower()
    if not stem:
        return None
    return next((h for h in humans if h.lower().startswith(stem) or h.lower().replace(" ", "").startswith(stem)), None)


def thread_reading(messages, keys=()):
    """What the release thread announced about Jira. → {announced: {key: {status, assignee, agent, ts}},
    folds: [{key, into, ts, text}], builds: {job: {version: Jenkins number}}, release_bot, humans}. A key is announced only in
    a message that says it is moved to Review; the agent is the bot that message asks, else its author (andyBot did
    the backend's itself on 11-10). A key folded into another is taken out of what is announced."""
    keys = set(keys)
    announced, folds, builds = {}, [], {}
    humans = list(dict.fromkeys(m.get("user") for m in messages if m.get("user") and not is_bot(m.get("user"))))
    release_bot = next((m.get("user") for m in messages if is_bot(m.get("user"))), None)
    for m in messages:
        text, who, ts = m.get("text") or "", m.get("user") or "", m.get("ts")
        for line in text.splitlines():                     # a Jenkins number is read on the line naming its version
            u, v = JOB_URL_RX.search(line), VERSION_SAID_RX.findall(line)
            if u and v:
                builds.setdefault(u.group(1), {})[v[-1]] = int(u.group(2))
            for j in JOB_SAID_RX.finditer(line):
                builds.setdefault(j.group(1), {})[j.group(2)] = int(j.group(3))
        for f in FOLD_RX.finditer(text):
            folds.append({"key": f.group(1), "into": f.group(2), "ts": ts, "agent": who,
                          "text": " ".join(text[max(0, f.start() - 10):f.end() + 20].split())})
        if not REVIEW_RX.search(text):
            continue
        asked = BOT_TO_RX.search(text)
        agent = asked.group(1).strip() if asked else who
        named = {}
        for a in ASSIGN_LIST_RX.finditer(text):
            for k in KEY.findall(a.group(2)):
                named[k] = a.group(1)
        whole = next((a.group(1) for a in ASSIGN_ALL_RX.finditer(text)), None)
        for k in dict.fromkeys(KEY.findall(text)):
            if keys and k not in keys:
                continue
            announced[k] = {"status": "Review", "assignee": named.get(k) or whole, "agent": agent, "ts": ts}
    folded = {f["key"] for f in folds}
    for k in folded:
        announced.pop(k, None)
    return {"announced": announced, "folds": folds, "builds": builds, "release_bot": release_bot, "humans": humans}


# ── one build ─────────────────────────────────────────────────────────────────────────────────────────

def build_numbers(reading):
    """{slug: {version: Jenkins number}} from the thread's build lines, through the map's job → slug."""
    jobs, out = R().rmap("jobs") or {}, {}
    for j, vs in ((reading or {}).get("builds") or {}).items():
        if j in jobs:
            out.setdefault(jobs[j], {}).update(vs)
    return out


def proposed_entry(slug, version, numbers):
    """The entry to append: canonical `M.m.p+BUILD` when the thread names the build of this version, else bare."""
    n = ((numbers or {}).get(slug) or {}).get(str(version).lstrip("v"))
    return f"{slug}@{version}+{n}" if n else f"{slug}@{version}"


def covers(entries, slug, version):
    """'ok' when an entry for the slug is at or past `version` in its series, 'older' when only earlier ones are,
    None when there is no entry for the slug in that series."""
    want = R().parse_version(version)
    mine = [e for e in entries if e["slug"] == slug and e.get("parsed") and want and e["parsed"][:2] == want[:2]]
    if not mine:
        return None
    return "ok" if any(P().cmp_versions(slug, e["parsed"], want) >= 0 for e in mine) else "older"


def reconcile(rec, issues, reading=None, label=None):
    """One build record against the tickets' Jira state and its thread. issues: {key: issue JSON or None};
    reading: thread_reading() or None (not read). → {build, lane, lane_name, line, name, label, rows, questions, gaps,
    ok}: rows are the tickets with a gap, each {key, agent, misses: [{kind, what, entry?}], add: [entries], label?};
    ok the keys that owe nothing."""
    label = label if label is not None else ((R().rmap("lines") or {}).get(str(rec.get("line"))) or {}).get("label")
    numbers = build_numbers(reading)
    gaps = [] if reading is not None else ["release thread not read: status and assignee not judged"]
    carried = {}
    for v in rec.get("services") or []:
        slug = slug_of(v.get("service"))
        for k in v.get("keys") or []:
            carried.setdefault(k, []).append((v.get("service"), slug, v.get("to")))
    announced = (reading or {}).get("announced") or {}
    rows, ok = [], []
    for k, svcs in carried.items():
        issue = issues.get(k)
        if not issue:
            gaps.append(f"{k}: not read in Jira")
            continue
        f = fields(issue)
        labels = f.get("labels") or []
        entries = P().parse_fixed_in(fixed_in_text(issue))
        misses, add = [], []
        if not any(l in labels for l in NO_FIXED_IN):
            for service, slug, to in svcs:
                if not slug:
                    gaps.append(f"{k}: {service} names no slug in the release map")
                    continue
                c = covers(entries, slug, to)
                if c == "ok":
                    continue
                e = proposed_entry(slug, to, numbers)
                have = "; ".join(f"{x['slug']}@{x['version']}" for x in entries if x["slug"] == slug)
                misses.append({"kind": "fixed-in" if c is None else "rework", "service": service, "entry": e,
                               "what": f"no {slug} entry for {to}" if c is None else f"{have} is older than {to}: append, never rewrite"})
                add.append(e)
        if label and label not in labels:
            misses.append({"kind": "label", "what": f"no {label}"})
        a = announced.get(k)
        status = name_of(issue, "status") or ""
        if a and a.get("status") and status.lower() not in PAST_REVIEW:
            misses.append({"kind": "status", "what": f"{status or 'no status'}; the thread announced {a['status']}"})
        holder = name_of(issue, "assignee")
        if a and a.get("assignee") and status.lower() not in TERMINAL and not same_person(a["assignee"], holder):
            misses.append({"kind": "assignee", "what": f"held by {holder or 'nobody'}; the thread announced {a['assignee']}"})
        if not misses:
            ok.append(k)
            continue
        agent = (a or {}).get("agent") or (reading or {}).get("release_bot")   # a key no agent was asked about: the release agent's
        rows.append({"key": k, "summary": f.get("summary") or "", "status": status, "assignee": holder, "agent": agent,
                     "asked": bool(a), "misses": misses, "add": add,
                     "label": label if any(m["kind"] == "label" for m in misses) else None})
    questions = []
    for fo in (reading or {}).get("folds") or []:
        issue = issues.get(fo["key"])
        st = name_of(issue, "status") if issue else None
        if issue and (st or "").lower() in TERMINAL:
            continue                                       # closed already: the world answered it
        questions.append({"kind": "fold", "key": fo["key"], "into": fo["into"], "status": st, "summary": fields(issue).get("summary") or "",
                          "holder": name_of(issue, "assignee") if issue else None, "agent": fo.get("agent"),
                          "text": f"{fo['key']} was reverted into {fo['into']} in build {rec.get('build')}"
                                  + (f" and is still in {st}" if st else "") + ": close it as folded, or does work remain?"})
    return {"build": str(rec.get("build")), "line": rec.get("line"), "lane": rec.get("lane"), "lane_name": rec.get("lane_name"),
            "name": rec.get("name") or R().build_name(rec), "date": rec.get("date"), "label": label, "rows": rows,
            "ok": ok, "questions": questions, "gaps": gaps, "humans": (reading or {}).get("humans") or []}


# ── reading the sources ───────────────────────────────────────────────────────────────────────────────

def _run(argv, timeout=120):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def _json_out(out):
    body = "\n".join(l for l in (out or "").splitlines() if not l.startswith("#"))   # the fact store's dated header
    try:
        return json.loads(body)
    except ValueError:
        return None


def read_issues(keys, env_file=None):
    """{key: issue JSON or None} through the jira capability's read (the fact store while fresh)."""
    def one(k):
        argv = ["python3", os.path.join(SKILLS, "jira", "jira.py")] + (["--env-file", env_file] if env_file else []) + ["read", k, "--json"]
        rc, out, _ = _run(argv)
        return k, _json_out(out) if rc == 0 else None
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        return dict(ex.map(one, list(dict.fromkeys(keys))))


def read_thread(rec, env_file=None):
    """The release thread's messages, or None when the record names none or it cannot be read."""
    m = PERMALINK.search(rec.get("source") or "")
    if not m:
        return None
    argv = ["python3", os.path.join(SKILLS, "slack", "slack.py")] + (["--env-file", env_file] if env_file else []) + ["read", "--json", m.group(0)]
    rc, out, _ = _run(argv)
    d = _json_out(out) if rc == 0 else None
    return (d or {}).get("messages") if isinstance(d, dict) else None


def record_keys(rec):
    return list(dict.fromkeys(k for v in rec.get("services") or [] for k in v.get("keys") or []))


def reading_path(reports, res):
    return os.path.join(reports or "", "releases", str(res["line"]), f"{res['name']}.reconcile.json")


def saved_readings(reports, lane=None):
    """Every kept reading under <reports>/releases/, oldest first; `lane` narrows to one lane (its id or name)."""
    root, out = os.path.join(reports or "", "releases"), []
    for line in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        d = os.path.join(root, line)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if f.endswith(".reconcile.json"):
                try:
                    r = json.load(open(os.path.join(d, f), encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not lane or R().lane_slug(lane) in (R().lane_slug(r.get("lane")), R().lane_slug(r.get("lane_name"))):
                    out.append(r)
    return sorted(out, key=lambda r: (r.get("date") or "", int(r["build"]) if str(r.get("build", "")).isdigit() else 0))


def saved_reading(reports, rec):
    p = os.path.join(reports or "", "releases", str(rec.get("line")), f"{rec.get('name') or R().build_name(rec)}.reconcile.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── what the reading becomes ──────────────────────────────────────────────────────────────────────────

def gaps_table(res):
    """The release note's `## Jira gaps`: ticket, what is missing, the proposed entry; '' when nothing is missing."""
    if not res or not res.get("rows"):
        return ""
    L = ["## Jira gaps", "", f"*Read {res.get('at', '')[:16].replace('T', ' ')}; the batch appends, it never rewrites.*" if res.get("at") else "",
         "", "| ticket | what is missing | proposed |", "|---|---|---|"]
    for r in res["rows"]:
        what = "; ".join(m["what"] for m in r["misses"])
        prop = "; ".join(r["add"] + ([f"label {r['label']}"] if r.get("label") else [])) or "—"
        L.append(f"| {r['key']} | {what} | {prop} |")
    for q in res.get("questions") or []:
        L.append(f"| {q['key']} | reverted into {q['into']}: an open question to {q.get('holder') or 'its holder'}, not a Fixed In matter | — |")
    return "\n".join(l for l in L if l is not None) + "\n"


def batchable(res):
    """The rows the batch writes: a Fixed In append or the label. Status, assignee and folds are never in it."""
    return [r for r in res.get("rows") or [] if r["add"] or r.get("label")]


def ask_text(results):
    """today.md's one ask for every build in the window: `<lane> build N: M tickets lack Fixed In or the label`."""
    rs = [r for r in results if batchable(r)]
    if not rs:
        return None
    keys = {x["key"] for r in rs for x in batchable(r)}
    lane = rs[0].get("lane_name") or rs[0]["lane"]
    builds = ", ".join(r["build"] for r in rs)
    return f"{lane} build{'s' if len(rs) > 1 else ''} {builds}: {len(keys)} ticket{'s' if len(keys) != 1 else ''} lack Fixed In or the label."


def batch_commands(res):
    """[(key, argv tail)] for the jira capability: one fixed-in append and one label add per ticket that owes them."""
    out = []
    for r in batchable(res):
        if r["add"]:
            out.append((r["key"], ["fixed-in", r["key"], "--add", "; ".join(r["add"])]))
        if r.get("label"):
            out.append((r["key"], ["label", r["key"], "--add", r["label"]]))
    return out


def run_batch(results, apply=False, env_file=None):
    """Each command through jira.py, dry run unless `apply`. → [(key, rc, text)]."""
    out = []
    for res in results:
        for key, tail in batch_commands(res):
            argv = ["python3", os.path.join(SKILLS, "jira", "jira.py")] + (["--env-file", env_file] if env_file else []) + tail + (["--apply"] if apply else [])
            rc, so, se = _run(argv)
            out.append((key, rc, (so.strip() or se.strip())))
    return out


# ── questions (ADR 0016) ──────────────────────────────────────────────────────────────────────────────

def agent_patterns(readings, n=PATTERN_BUILDS):
    """(agent, kind) missed on n or more builds → [{agent, kind, builds, keys}], from the kept readings."""
    seen = {}
    for r in readings:
        for row in r.get("rows") or []:
            ag = row.get("agent")
            if not ag:
                continue
            for m in row["misses"]:
                s = seen.setdefault((ag, m["kind"]), {"agent": ag, "kind": m["kind"], "builds": [], "keys": [], "humans": set()})
                if r["build"] not in s["builds"]:
                    s["builds"].append(r["build"])
                if row["key"] not in s["keys"]:
                    s["keys"].append(row["key"])
                s["humans"] |= set(r.get("humans") or [])
    out = []
    for s in seen.values():
        if len(s["builds"]) >= n:
            s["owner"] = agent_owner(s["agent"], sorted(s["humans"]))
            s.pop("humans")
            out.append(s)
    return out


def pattern_message(p, owner_first=""):
    to = (p.get("owner") or "").split()[0] if p.get("owner") else ""
    return (f"Hi {to or 'there'}, on builds {', '.join(p['builds'])} {p['agent']} left the same Jira gap after the release: "
            f"{KINDS.get(p['kind'], p['kind'])} ({', '.join(p['keys'][:6])}{' …' if len(p['keys']) > 6 else ''}). "
            "Could its instructions cover that step?" + (f" — {owner_first}" if owner_first else ""))


def raise_questions(state, results, readings, today, now_iso, owner_first="", drafts_dir=None, write=None):
    """Folds and three-build agent patterns into open-question records (questions.py add), once each; the fold's
    base is its ticket's state now, so its move or close answers it. → the ids added."""
    import questions as Q                                  # noqa: E402 — ADR 0016's one record store
    added = []
    for res in results:
        for q in res.get("questions") or []:
            where = f"releases/{res['line']}/{res['name']}"
            text = f"{q['text']} · {q.get('holder') or 'Not named'}"
            rid = Q.add(state, text, AUDIENCE, today, where)
            if rid:
                r = state["questions"][rid]
                r["lead"] = [q["key"]]
                r["base"] = {"at": now_iso, "tickets": {q["key"]: {"status": q.get("status"), "assignee": q.get("holder")}}}
                added.append(rid)
    for p in agent_patterns(readings):
        where = f"releases/agents/{R().lane_slug(p['agent'])}-{p['kind']}"
        text = (f"{p['agent']} left {KINDS.get(p['kind'], p['kind'])} on builds {', '.join(p['builds'])}: "
                f"can its release step cover it? · {p.get('owner') or 'Not named'}")
        rid = Q.add(state, text, AUDIENCE, today, where)
        if not rid:
            continue
        r = state["questions"][rid]
        r["lead"], r["keys"] = [], []
        r["message"] = pattern_message(p, owner_first)
        r["draft"] = {"to": p.get("owner") or "the agent's owner", "via": "a direct message, sent by the owner of ela",
                      "text": r["message"]}
        if drafts_dir and write:
            path = os.path.join(drafts_dir, f"question-{rid}.txt")
            write(path, r["message"] + "\n")
            r["draft"]["file"] = path
        added.append(rid)
    return added


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
