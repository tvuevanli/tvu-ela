#!/usr/bin/env python3
"""improve — what the assistant as a whole should do better, found from the day's own record. Stdlib only.

The evening reader reviews one artefact (the morning page) and the Learned section records what the day taught. Neither
asks whether the system itself cost the owner time: a mediahub-bot answer a colleague had to question, an ela thread he
had to follow up twice, a vault line that needed a second round, a timer that failed again. This verb is that loop.

  digest --date D [--json]      the day's signals, deterministic: mediahub-bot's runs (verdict, confidence, gaps, the
                                thread's permalink, how many runs the thread took), ela's jobs (his Slack asks, his
                                vault lines, mentions; follow-ups in one thread; failed and stuck jobs; failed units),
                                his feedback, and the improvement items still open
  add FILE --date D             the items an evening session proposed (a JSON list), checked and stored; an item that
                                names `same_as` an open one is counted as seen again, not stored twice
  list [--open] [--json]        the store
  answer ID A|B                 his letter on an item that needs his word: A go (ela carries it out), B drop
  done ID --what TEXT           an item carried out, with what now behaves differently
  section --date D              the reader page's `## Improve` lines for that day
  pending                       one line for the desk session: the items ela should carry out next

An item: {id, area, problem, evidence, fix, who, first, seen, state}. `area` is one of AREAS. `who` is `ela` when the
fix is inside ela, the runner, the vault or Helm's ela-backed parts (ela decides and builds it, and reports the
outcome); `owner` when the fix changes what a colleague sees (mediahub-bot's answers, a post, a Jira habit), which
takes his word as an ask on today.md. States: open → go (his A, or `ela` items from the start) → done; or dropped.
Nothing is deleted (the no-data-lost rule): a dropped item stays in the store with the day and the letter.

Store: <reports>/ela/improve.json. mediahub-bot's run log: site.json `mhbot_data`, else MHBOT_ROOT/data, else
~/.local/share/mediahub-bot/data.
"""
import argparse, datetime, glob, hashlib, json, os, re, sys

SITE = os.path.expanduser("~/.claude/ela/site.json")
AREAS = ("mediahub-bot", "ela-bot", "vault", "runner", "ela")
WHO = ("ela", "owner")
DAILY_MAX = 3                                              # items a day may add or see again: the section is read, not skimmed
STUCK_S = 2 * 3600                                         # a job still `running` this long after it started is stuck
TEXT_MAX = 400
EX_USAGE, EX_NOTFOUND = 2, 3


def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def reports_root():
    return site().get("reports") or os.path.join(site().get("projects") or os.path.expanduser("~/projects"), "reports")


def runtime_root():
    return site().get("runtime") or os.path.join(site().get("projects") or os.path.expanduser("~/projects"), ".ela")


def mhbot_data():
    s = site().get("mhbot_data")
    if s:
        return s
    if os.environ.get("MHBOT_ROOT"):
        return os.path.join(os.environ["MHBOT_ROOT"], "data")
    return os.path.expanduser("~/.local/share/mediahub-bot/data")


def permalink(channel, ts):
    return f"https://tvunetworks.slack.com/archives/{channel}/p{str(ts).replace('.', '')}"


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write(text)
    os.replace(tmp, path)


def jsonl(path):
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        return []
    out = []
    with f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def moment(stamp):
    """An ISO stamp as an aware local time (a `Z` one is UTC, a naive one local), or None when it does not parse."""
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone()
    except (TypeError, ValueError):
        return None


def local_day(stamp):
    """The local day of an ISO stamp, or '' when it does not parse."""
    t = moment(stamp)
    return t.date().isoformat() if t else ""


def clip(text, n=TEXT_MAX):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ---- the day's signals ---------------------------------------------------------------------------------------------

def mhbot_runs(data, day):
    """mediahub-bot's tasks of the day, one row each: asked where, answered how, and how many runs its thread took."""
    rows = jsonl(os.path.join(data, "runs.jsonl"))
    tasks = {}
    for r in rows:
        t = r.get("task")
        if not t or local_day(r.get("at")) != day:
            continue
        x = tasks.setdefault(t, {"task": t})
        ev = r.get("event")
        if ev == "accepted":
            x.update(channel=r.get("channel"), thread_ts=r.get("thread_ts"), lane=r.get("lane"), mode=r.get("mode"),
                     asker=r.get("asker"))
        elif ev == "done":
            x.update(verdict=r.get("verdict"), confidence=r.get("confidence"), layer=r.get("layer"),
                     summary=clip(r.get("summary"), 300), gaps=r.get("gaps"), next_hop=r.get("next_hop"),
                     cost=r.get("cost"))
        elif ev in ("failed", "operator", "timeout", "refused"):
            x.setdefault("events", []).append({k: r.get(k) for k in ("event", "meta", "answered", "reason", "error") if r.get(k) is not None})
    try:
        threads = json.load(open(os.path.join(data, "threads.json"), encoding="utf-8"))
    except (OSError, ValueError):
        threads = {}
    out = []
    for x in tasks.values():
        if x.get("channel") and x.get("thread_ts"):
            x["permalink"] = permalink(x["channel"], x["thread_ts"])
            th = threads.get(f"{x['channel']}:{x['thread_ts']}") or {}
            x["thread_runs"] = th.get("runs")
            x["thread_askers"] = len(th.get("askers") or [])
        out.append(x)
    return sorted(out, key=lambda x: x["task"])


def ela_jobs(reports, day, now=None):
    """ela's jobs of the day by kind, his asks (Slack and vault) and mentions with their threads, follow-ups within one
    thread, failed jobs, and jobs still running long after they started."""
    now = now or datetime.datetime.now().astimezone()
    kinds, asks, failed, stuck = {}, [], [], []
    turns = {}
    for p in sorted(glob.glob(os.path.join(reports, "runner", "jobs", "*.json"))):
        try:
            j = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if local_day(j.get("created")) != day:
            continue
        kind, status = j.get("kind") or "?", j.get("status") or "?"
        kinds.setdefault(kind, {}).setdefault(status, 0)
        kinds[kind][status] += 1
        o = j.get("origin") or {}
        head = {"id": j.get("id"), "kind": kind, "status": status, "label": clip(o.get("label") or j.get("prompt"), 160)}
        if status == "failed":
            failed.append(dict(head, answer=clip(j.get("answer"), 300)))
        if status == "running":
            started = moment(j.get("started") or j.get("created"))
            if started and (now - started).total_seconds() > STUCK_S:
                stuck.append(dict(head, started=j.get("started")))
        if kind in ("owner", "vault", "mention", "session", "guest"):
            row = dict(head, answer=clip(j.get("answer") or j.get("summary"), 300))
            if o.get("channel") and o.get("thread_ts"):
                row["permalink"] = permalink(o["channel"], o["thread_ts"])
                key = o.get("thread_key") or f"{o['channel']}-{o['thread_ts']}"
                turns[key] = turns.get(key, 0) + 1
                row["thread"] = key
            asks.append(row)
    follow = sorted(((k, n) for k, n in turns.items() if n > 1), key=lambda kn: -kn[1])
    for a in asks:
        a["turns_in_thread"] = turns.get(a.get("thread"), 1)
    return {"kinds": kinds, "asks": asks, "follow_ups": [{"thread": k, "turns": n} for k, n in follow],
            "failed": failed, "stuck": stuck}


def failed_units(runtime, day):
    """The runner's units whose failure notice was written that day."""
    out = []
    for p in glob.glob(os.path.join(runtime, "runner", "failed-*.last")):
        if datetime.date.fromtimestamp(os.path.getmtime(p)).isoformat() == day:
            try:
                tail = open(p, encoding="utf-8", errors="replace").read()[-400:]
            except OSError:
                tail = ""
            out.append({"unit": os.path.basename(p)[len("failed-"):-len(".last")], "tail": clip(tail, 400)})
    return out


def feedback(reports, day):
    return [{"at": r.get("at"), "from": r.get("from"), "text": clip(r.get("text"), 300)}
            for r in jsonl(os.path.join(reports, "ela", "feedback.jsonl")) if local_day(r.get("at")) == day]


def digest(day, reports=None, runtime=None, data=None, now=None):
    reports, runtime, data = reports or reports_root(), runtime or runtime_root(), data or mhbot_data()
    return {"date": day,
            "mediahub_bot": mhbot_runs(data, day),
            "ela": ela_jobs(reports, day, now),
            "failed_units": failed_units(runtime, day),
            "feedback": feedback(reports, day),
            "open_items": [{k: v for k, v in r.items() if k in ("id", "area", "problem", "fix", "who", "state", "seen")}
                           for r in load(reports).values() if r["state"] in ("open", "go")]}


# ---- the store -----------------------------------------------------------------------------------------------------

def store_path(reports):
    return os.path.join(reports, "ela", "improve.json")


def load(reports):
    try:
        return json.load(open(store_path(reports), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(reports, recs):
    atomic_write(store_path(reports), json.dumps(recs, ensure_ascii=False, indent=1) + "\n")


def item_id(area, problem):
    return f"{area}-" + hashlib.sha1(f"{area}\n{problem}".encode()).hexdigest()[:8]


def check(items, recs):
    """The reasons a proposed list is refused, or []."""
    bad = []
    if not isinstance(items, list):
        return ["the file holds no JSON list"]
    if len(items) > DAILY_MAX:
        bad.append(f"{len(items)} items, at most {DAILY_MAX}")
    for k, it in enumerate(items, 1):
        if not isinstance(it, dict):
            bad.append(f"item {k} is not an object"); continue
        if it.get("evidence") is not None and not isinstance(it["evidence"], list):
            bad.append(f"item {k}: evidence is not a list")
        if it.get("same_as"):
            if it["same_as"] not in recs:
                bad.append(f"item {k}: same_as {it['same_as']} is not in the store")
            continue
        for f in ("area", "problem", "evidence", "fix", "who"):
            if not it.get(f):
                bad.append(f"item {k}: no {f}")
        if it.get("area") and it["area"] not in AREAS:
            bad.append(f"item {k}: area {it['area']} is not one of {', '.join(AREAS)}")
        if it.get("who") and it["who"] not in WHO:
            bad.append(f"item {k}: who {it['who']} is not ela or owner")
    return bad


def add(reports, items, day):
    """Store a day's items; → the ids touched. Raises ValueError with the reasons a list is refused."""
    recs = load(reports)
    bad = check(items, recs)
    if bad:
        raise ValueError("; ".join(bad))
    ids = []
    for it in items:
        if it.get("same_as"):
            r = recs[it["same_as"]]
            if day not in r["seen"]:
                r["seen"].append(day)
            r["evidence"] = (r.get("evidence") or []) + [clip(e, 300) for e in it.get("evidence") or []]
            if r["state"] == "dropped" and it.get("reopen"):
                r["state"], r["reopened"] = "open", day
            ids.append(r["id"]); continue
        i = item_id(it["area"], it["problem"])
        if i in recs:
            if day not in recs[i]["seen"]:
                recs[i]["seen"].append(day)
            ids.append(i); continue
        recs[i] = {"id": i, "area": it["area"], "problem": clip(it["problem"]), "evidence": [clip(e, 300) for e in it["evidence"]],
                   "fix": clip(it["fix"]), "who": it["who"], "first": day, "seen": [day],
                   "state": "go" if it["who"] == "ela" else "open"}
        ids.append(i)
    save(reports, recs)
    return ids


def answer(reports, ref, letter, today=None):
    """His letter on an item: A go, B drop. → the record. Raises KeyError, ValueError."""
    recs, letter = load(reports), str(letter).strip()[:1].upper()
    if ref not in recs:
        raise KeyError(ref)
    if letter not in ("A", "B"):
        raise ValueError(f"letter {letter} is not A (go) or B (drop)")
    r, day = recs[ref], (today or datetime.date.today()).isoformat()
    if r["state"] not in ("open",):
        raise ValueError(f"{ref} is {r['state']}, not waiting for a word")
    r["state"], r["answer"] = ("go" if letter == "A" else "dropped"), {"letter": letter, "at": day}
    save(reports, recs)
    return r


def done(reports, ref, what, today=None):
    recs = load(reports)
    if ref not in recs:
        raise KeyError(ref)
    r = recs[ref]
    if r["state"] == "dropped":
        raise ValueError(f"{ref} was dropped")
    r["state"], r["done"] = "done", {"at": (today or datetime.date.today()).isoformat(), "what": clip(what)}
    save(reports, recs)
    return r


def section(reports, day):
    """The reader page's Improve lines for that day: the items seen that day, then nothing else."""
    rows = [r for r in load(reports).values() if day in r.get("seen", [])]
    if not rows:
        return ["- Nothing to improve today."]
    out = []
    for r in sorted(rows, key=lambda r: (r["who"] != "owner", -len(r["seen"]), r["id"])):
        again = f" · seen {len(r['seen'])} days" if len(r["seen"]) > 1 else ""
        how = "needs your word on today.md" if r["who"] == "owner" and r["state"] == "open" else \
              {"go": "ela carries it out", "done": "done", "dropped": "dropped", "open": "open"}[r["state"]]
        out.append(f"- *{r['area']}*: {r['problem']} Fix: {r['fix']} — {how}{again} · `{r['id']}`")
    return out


def asks(reports, today=None):
    """The items that take an ordinary ask slot on today.md: those whose fix a colleague would see, not yet answered."""
    out = []
    for r in sorted(load(reports).values(), key=lambda r: r["first"]):
        if r["who"] != "owner" or r["state"] != "open":
            continue
        out.append({"id": f"improve:{r['id']}", "question": f"{r['area']}: {r['problem']} Proposed: {r['fix']}",
                    "sig": hashlib.sha1((r["problem"] + r["fix"]).encode()).hexdigest()[:12],
                    "options": [{"letter": "A", "text": "go", "does": f"ela improve answer {r['id']} A", "recommended": True},
                                {"letter": "B", "text": "drop it", "does": f"ela improve answer {r['id']} B", "recommended": False}]})
    return out


def pending(reports):
    rows = sorted((r for r in load(reports).values() if r["state"] == "go"), key=lambda r: (-len(r["seen"]), r["first"]))
    if not rows:
        return ""
    head = "; ".join(f"{r['area']}: {clip(r['problem'], 90)} (`{r['id']}`)" for r in rows[:3])
    return (f"ela improve: {len(rows)} item{'s' if len(rows) != 1 else ''} to carry out — {head}. "
            "`ela improve list --open` has the evidence and the fix; `ela improve done ID --what …` once it lands.")


# ---- the command line ----------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="improve", description=__doc__.split("\n\n")[0])
    ap.add_argument("--env-file", help="accepted from bin/ela; this verb reads no credential")
    ap.add_argument("--reports", help="the reports root (default: site.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("digest", help="the day's signals"); p.add_argument("--date"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("add", help="store the items an evening session proposed"); p.add_argument("file"); p.add_argument("--date")
    p = sub.add_parser("list", help="the store"); p.add_argument("--open", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("answer", help="his letter: A go, B drop"); p.add_argument("id"); p.add_argument("letter")
    p = sub.add_parser("done", help="an item carried out"); p.add_argument("id"); p.add_argument("--what", required=True)
    p = sub.add_parser("section", help="the reader page's Improve lines"); p.add_argument("--date")
    sub.add_parser("pending", help="one line for the desk session")
    a = ap.parse_args(argv)
    reports = a.reports or reports_root()
    day = getattr(a, "date", None) or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        print(f"improve: --date {day} is not YYYY-MM-DD", file=sys.stderr); sys.exit(EX_USAGE)
    if a.cmd == "digest":
        d = digest(day, reports)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
        else:
            e = d["ela"]
            print(f"{day}: mediahub-bot {len(d['mediahub_bot'])} tasks · ela asks {len(e['asks'])}, follow-up threads "
                  f"{len(e['follow_ups'])}, failed jobs {len(e['failed'])}, stuck {len(e['stuck'])} · failed units "
                  f"{len(d['failed_units'])} · feedback {len(d['feedback'])} · open items {len(d['open_items'])}")
    elif a.cmd == "add":
        try:
            ids = add(reports, json.load(open(a.file, encoding="utf-8")), day)
        except (OSError, ValueError) as err:
            print(f"improve add: {err}", file=sys.stderr); sys.exit(EX_USAGE)
        print(" ".join(ids) or "nothing")
    elif a.cmd == "list":
        rows = [r for r in load(reports).values() if not a.open or r["state"] in ("open", "go")]
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in sorted(rows, key=lambda r: r["first"]):
                print(f"{r['id']}  {r['state']:<7} {r['who']:<5} seen {len(r['seen'])}  {r['problem']}\n    fix: {r['fix']}")
                for ev in r.get("evidence") or []:
                    print(f"    · {ev}")
            if not rows:
                print("nothing")
    elif a.cmd == "answer":
        try:
            r = answer(reports, a.id, a.letter)
        except KeyError as err:
            print(f"improve answer: no item {err}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        except ValueError as err:
            print(f"improve answer: {err}", file=sys.stderr); sys.exit(EX_USAGE)
        print(f"{r['id']}: {r['state']}")
    elif a.cmd == "done":
        try:
            r = done(reports, a.id, a.what)
        except KeyError as err:
            print(f"improve done: no item {err}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        except ValueError as err:
            print(f"improve done: {err}", file=sys.stderr); sys.exit(EX_USAGE)
        print(f"{r['id']}: done")
    elif a.cmd == "section":
        print("\n".join(section(reports, day)))
    elif a.cmd == "pending":
        line = pending(reports)
        if line:
            print(line)


if __name__ == "__main__":
    main()
