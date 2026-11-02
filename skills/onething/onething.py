#!/usr/bin/env python3
"""The owner's rows in the team's monthly One Thing sheet: the facts of his own day, the vault note he edits, and the
lines he copies into the sheet himself. Read-only toward Google, Jira and Slack; it writes only vault notes. Stdlib only.

  facts  (--date D | --month YYYY-MM)        his own Jira actions and Slack messages per day (Asia/Shanghai), Helm's
                                             auto-writes left out; --json for the drafting session
  sheet  --month YYYY-MM                     the rows already in that month's tab under his name (Drive export)
  render --rows FILE [--out PATH]            the vault note from drafted rows: numbered table, keys as links, the days
                                             left out, the evidence; the path is printed
  post   NOTE --pick 1,3|all                 the picked rows as the sheet takes them (plain keys, no links), written
                                             into the note under ## Copy to the sheet as tab-separated lines to paste
                                             at column A, and printed; nothing is written to the sheet

Site env (the site's .env): ONETHING_SHEET (the spreadsheet id), ONETHING_WHOM (the name in column B),
ONETHING_PROJECT (column A, default MH), ONETHING_OWNER (his Jira and Slack display name; read from Jira when absent),
GOOGLE_TOKEN_FILE (read-only, shared with gdoc).
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote.
"""
import argparse, datetime, html, io, json, os, re, subprocess, sys, urllib.error, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gdoc"))
import gdoc  # noqa: E402  the read-only Google client and its scope allowlist

JIRA = os.path.join(HERE, "..", "jira", "jira.py")
SLACK = os.path.join(HERE, "..", "slack", "slack.py")
SITE = os.path.expanduser("~/.claude/ela/site.json")
TZ = datetime.timezone(datetime.timedelta(hours=8))     # the owner's day is Asia/Shanghai, where the sheet's dates are
KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
TABLE_HEAD = "| # | date | Content Overview (edit freely) |"
SKIP_FIELDS = {"Fixed In", "labels", "Link", "RemoteIssueLink", "Rank"}   # bookkeeping, not work; Fixed In is mostly Helm's
EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5


def die(msg, code):
    print(msg, file=sys.stderr); sys.exit(code)


def env_args(a):
    return ["--env-file", a.env_file] if a.env_file else []


def setting(a, key, default=None):
    return gdoc.env_value(key, a.env_file) or os.environ.get(key) or default


def whom(a):
    """The owner's name in column B; it lives in the site env, never in this file."""
    w = setting(a, "ONETHING_WHOM")
    if not w:
        die("no ONETHING_WHOM in the site env: the owner's name in the sheet's Whom column", EX_USAGE)
    return w


def run_json(cmd, timeout):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{os.path.basename(cmd[1])} exit {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")
    return json.loads(r.stdout)


def jira_time(s):
    return datetime.datetime.strptime(re.sub(r"\.\d+", "", s), "%Y-%m-%dT%H:%M:%S%z")


def local_day(stamp):
    """A Jira (2026-10-13T01:25:56.283-0700) or Slack epoch stamp as the owner's local date, YYYY-MM-DD."""
    if re.fullmatch(r"\d+(\.\d+)?", str(stamp)):
        return datetime.datetime.fromtimestamp(float(stamp), TZ).date().isoformat()
    return jira_time(stamp).astimezone(TZ).date().isoformat()


def window(a):
    if a.date:
        d = datetime.date.fromisoformat(a.date)
        return d, d
    y, m = map(int, a.month.split("-"))
    first = datetime.date(y, m, 1)
    last = datetime.date(y + m // 12, m % 12 + 1, 1) - datetime.timedelta(days=1)
    return first, min(last, datetime.datetime.now(TZ).date())


# ---------------------------------------------------------------- facts

def helm_write(issue, event):
    """A Fixed In or label Helm wrote under the owner's account: its comment says so within two minutes."""
    t = jira_time(event["at"])
    for c in issue.get("comments") or []:
        if "Helm" in (c.get("text") or "")[:120] and abs((jira_time(c["at"]) - t).total_seconds()) <= 120:
            return True
    return False


def jira_facts(changes, owner, first, last):
    """Per day: his own comments and moves, one entry per ticket, Helm's auto-writes and bookkeeping fields left out."""
    days, lo, hi = {}, first.isoformat(), last.isoformat()

    def slot(d, i):
        return days.setdefault(d, {}).setdefault(i["key"], {"key": i["key"], "summary": i.get("summary"), "moves": [], "comments": []})
    for i in changes.get("issues") or []:
        for e in i.get("events") or []:
            if e.get("by") != owner or e.get("field") in SKIP_FIELDS or helm_write(i, e):
                continue
            d = local_day(e["at"])
            if lo <= d <= hi:
                slot(d, i)["moves"].append(f"{e['field']}: {e.get('from')} → {e.get('to')}")
        for c in i.get("comments") or []:
            if c.get("by") != owner or "Helm" in (c.get("text") or "")[:120]:
                continue
            d = local_day(c["at"])
            if lo <= d <= hi:
                slot(d, i)["comments"].append((c.get("text") or "")[:1200])
    return {d: list(v.values()) for d, v in days.items()}


def slack_facts(search, owner, first, last):
    """Per day: his own messages, top-level and replies, once each, in time order."""
    seen, lo, hi = {}, first.isoformat(), last.isoformat()
    for m in search.get("messages") or []:
        for x in [m] + list(m.get("reply_hits") or []):
            if x.get("user") == owner and x.get("ts") not in seen:
                seen[x["ts"]] = {"ts": x["ts"], "channel": m.get("channel"), "permalink": m.get("permalink"),
                                 "text": (x.get("text") or "")[:1200]}
    days = {}
    for ts in sorted(seen, key=float):
        d = local_day(ts)
        if lo <= d <= hi:
            days.setdefault(d, []).append(seen[ts])
    return days


def owner_name(a):
    named = setting(a, "ONETHING_OWNER")
    if named:
        return named
    me = run_json(["python3", JIRA, *env_args(a), "jql", "assignee = currentUser() ORDER BY updated DESC", "--limit", "1", "--json"], 120)
    issues = me.get("issues") or []
    if not issues or not issues[0].get("assignee"):
        die("the owner's name is unknown: set ONETHING_OWNER in the site env", EX_NOTFOUND)
    return issues[0]["assignee"]


def cmd_facts(a):
    first, last = window(a)
    owner = owner_name(a)
    errors, jira, slack = [], {}, {}
    # Read from the day before: JQL reads a date in the Jira profile's zone and the clients' cutoffs in the machine's,
    # neither of which need be Asia/Shanghai; the facts are then cut to the owner's days here.
    since = (first - datetime.timedelta(days=1)).isoformat()
    try:
        ch = run_json(["python3", JIRA, *env_args(a), "changes", "--since", f"{since} 00:00", "--limit", "2000", "--json"], 900)
        jira = jira_facts(ch, owner, first, last)
    except (RuntimeError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append(f"jira not read: {e}")
    try:
        sl = run_json(["python3", SLACK, *env_args(a), "search", ".", "--since", since, "--threads", "--json"], 3000)
        slack = slack_facts(sl, owner, first, last)
    except (RuntimeError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append(f"slack not read: {e}")
    days, d = [], first
    while d <= last:
        k = d.isoformat()
        days.append({"date": k, "weekday": d.strftime("%a"), "jira": jira.get(k, []), "slack": slack.get(k, [])})
        d += datetime.timedelta(days=1)
    out = {"owner": owner, "from": first.isoformat(), "to": last.isoformat(), "days": days, "errors": errors}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for day in days:
            print(f"== {day['date']} {day['weekday']}  jira {len(day['jira'])} · slack {len(day['slack'])}")
            for t in day["jira"]:
                print(f"   {t['key']} {t['summary'] or ''}"[:140])
            for m in day["slack"]:
                print(f"   #{m['channel']} {m['text'][:120]}".replace("\n", " "))
        for e in errors:
            print(e, file=sys.stderr)
    sys.exit(EX_REMOTE if len(errors) == 2 else 0)


# ---------------------------------------------------------------- the sheet

def tab_name(month):
    y, m = map(int, month.split("-"))
    return f"{y}.{m}月"


def xlsx_rows(blob, tab):
    """One tab of an xlsx export as rows of {column letter: text}; None when the tab is absent."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    wb = z.read("xl/workbook.xml").decode()
    rels = z.read("xl/_rels/workbook.xml.rels").decode()
    rid = None
    for attrs in re.findall(r"<sheet ([^>]*)/>", wb):
        name = re.search(r'name="([^"]*)"', attrs)
        if name and html.unescape(name.group(1)) == tab:
            rid = re.search(r'r:id="([^"]*)"', attrs).group(1)
    if not rid:
        return None
    target = (re.search(rf'<Relationship [^>]*Id="{rid}"[^>]*Target="([^"]*)"', rels)
              or re.search(rf'<Relationship [^>]*Target="([^"]*)"[^>]*Id="{rid}"', rels))
    path = "xl/" + target.group(1).lstrip("/").removeprefix("xl/")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = [html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)))
                  for si in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    rows = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", z.read(path).decode(), re.S):
        cells = {}
        for col, attrs, body in re.findall(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', row, re.S):
            v = re.search(r"<v>(.*?)</v>", body or "")
            if v:
                cells[col] = shared[int(v.group(1))] if 't="s"' in attrs else html.unescape(v.group(1))
            else:
                t = re.search(r"<t[^>]*>(.*?)</t>", body or "", re.S)
                if t:
                    cells[col] = html.unescape(t.group(1))
        if cells:
            rows.append(cells)
    return rows


def cell_date(v):
    """A date cell as YYYY-MM-DD: a serial (46303) or text such as 2026/10/12 or 2026-10-12."""
    v = (v or "").strip()
    if re.fullmatch(r"\d+(\.0+)?", v):
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v)))).isoformat()
    m = re.match(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", v)
    return datetime.date(*map(int, m.groups())).isoformat() if m else v


def owner_rows(a, month):
    sheet = setting(a, "ONETHING_SHEET")
    if not sheet:
        die("no ONETHING_SHEET in the site env: the One Thing spreadsheet's id", EX_USAGE)
    g = gdoc.Google(a.env_file)
    url = (f"https://www.googleapis.com/drive/v3/files/{sheet}/export?mimeType="
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    try:
        blob = urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {g.access}"}), timeout=60).read()
    except urllib.error.HTTPError as e:
        die(f"google: sheet export failed (HTTP {e.code})", EX_AUTH if e.code in (401, 403) else EX_REMOTE)
    rows = xlsx_rows(blob, tab_name(month))
    if rows is None:
        die(f"no tab {tab_name(month)} in the sheet", EX_NOTFOUND)
    w = whom(a)
    return [{"project": r.get("A", ""), "whom": r.get("B", ""), "date": cell_date(r.get("C")), "text": r.get("D", "")}
            for r in rows[1:] if r.get("B", "").strip() == w]


def cmd_sheet(a):
    rows = owner_rows(a, a.month)
    if a.json:
        print(json.dumps({"tab": tab_name(a.month), "rows": rows}, ensure_ascii=False, indent=1))
    else:
        print(f"{tab_name(a.month)}: {len(rows)} row(s) under {whom(a)}")
        for r in rows:
            print(f"  {r['date']}  {r['text'][:120]}")


# ---------------------------------------------------------------- the note

def link_keys(text, base):
    """Bare ticket keys as Markdown links; keys already inside a link are left alone."""
    parts = re.split(r"(\[[^\]]*\]\([^)]*\))", text)
    return "".join(p if p.startswith("[") else KEY.sub(lambda m: f"[{m.group(0)}]({base}/browse/{m.group(0)})", p) for p in parts)


def plain(text):
    """A row as the sheet takes it: links to their text, wiki links to their name, table escapes undone."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return text.replace("\\|", "|").strip()


def jira_base(a):
    return (setting(a, "JIRA_BASE_URL") or setting(a, "JIRA_URL") or "https://tvunetworks.atlassian.net").rstrip("/")


def render(spec, base, today, project=None, who=None):
    """The note; with `who`, the Copy to the sheet block for every row as drafted, so a fresh note is copy-ready."""
    rows = sorted(spec.get("rows") or [], key=lambda r: r["date"])
    dates = [r["date"] for r in rows] or [spec.get("from") or today]
    span = dates[0] if dates[0] == dates[-1] else f"{dates[0]} to {dates[-1]}"
    title = f"One Thing rows: {span}"
    tab = tab_name(dates[0][:7])
    sheet = spec.get("sheet_url") or ""
    where = f"[the One Thing sheet]({sheet})" if sheet else "the One Thing sheet"
    L = ["---", f'title: "{title}"', f'aliases: ["{title}"]', 'type: "report"', f'date: "{today}"',
         f'target: "the One Thing sheet, tab {tab}"', 'source: "vault"', 'status: "proposed"',
         f'progress: "{today}: drafted; nothing written to the sheet"', 'ela: ""', "---", f"# {title}", "",
         f"**In short.** {len(rows)} draft row(s) for {where}, tab {tab}, each the day's work you did yourself. "
         "**Nothing is on the sheet.** *Copy to the sheet* at the bottom holds every row as drafted, plain keys, ready to "
         "paste at column A. After you edit rows, write `ela: post all` to refresh it, or `ela: post 1, 3` for some.", ""]
    if spec.get("existing"):
        L += ["Already on the sheet under your name: " + ", ".join(sorted(set(spec["existing"]))) + ".", ""]
    if spec.get("left_out"):
        L += ["Left out: " + "; ".join(f"{x['date']} ({x['why']})" for x in spec["left_out"]) + ".", ""]
    L += ["## Waiting for your word", "", TABLE_HEAD, "|---|---|---|"]
    for n, r in enumerate(rows, 1):
        L.append(f"| {n} | {r['date']} | {link_keys(r['text'].replace('|', chr(92) + '|'), base)} |")
    L += ["", "> [!note]- Evidence",
          "> " + (spec.get("evidence") or "Your own Jira comments and moves and your own Slack messages that day, "
                  "dates in Asia/Shanghai; Helm's auto-writes left out."), ""]
    text = "\n".join(L) + "\n"
    if who and rows:
        out = [(n, r["date"], plain(r["text"])) for n, r in enumerate(rows, 1)]
        text = copy_section(text, sorted({tab_name(d[:7]) for _, d, _ in out}), "all",
                            copy_lines(project or "MH", who, out))
    return text


def cmd_render(a):
    spec = json.load(open(a.rows, encoding="utf-8"))
    for r in spec.get("rows") or []:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.get("date", "")) or not (r.get("text") or "").strip():
            die(f"a row needs date YYYY-MM-DD and text: {r}", EX_USAGE)
    today = datetime.datetime.now(TZ).date().isoformat()
    sheet = setting(a, "ONETHING_SHEET")
    spec.setdefault("sheet_url", f"https://docs.google.com/spreadsheets/d/{sheet}/edit" if sheet else "")
    out = a.out
    if not out:
        vault = json.load(open(SITE)).get("vault") if os.path.isfile(SITE) else None
        if not vault:
            die("no vault in site.json and no --out", EX_USAGE)
        dates = sorted(r["date"] for r in spec.get("rows") or []) or [today]
        name = f"{dates[-1]}-one-thing.md" if dates[0] == dates[-1] else f"{today}-one-thing-{dates[0][:7]}.md"
        out = os.path.join(vault, "to-read", name)
    if os.path.exists(out) and not a.force:
        die(f"{out} exists: it may hold your edits; --force to replace it", EX_USAGE)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    text = render(spec, jira_base(a), today, setting(a, "ONETHING_PROJECT", "MH"), whom(a))
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(out)


# ---------------------------------------------------------------- post

def note_rows(text, year_hint):
    """The numbered rows of a One Thing note: [(n, YYYY-MM-DD, text as written)]."""
    rows, on = [], False
    for line in text.splitlines():
        if line.strip() == TABLE_HEAD:
            on = True
            continue
        if not on:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) != 3 or not cells[0].isdigit():
            continue
        d = cells[1]
        if re.fullmatch(r"\d{2}-\d{2}", d):
            d = f"{year_hint}-{d}"
        rows.append((int(cells[0]), d, cells[2]))
    return rows


def pick(rows, spec):
    if spec.strip().lower() == "all":
        return rows
    want = set()
    for part in re.split(r"[,\s&]+|and", spec.strip()):
        part = part.strip()
        if re.fullmatch(r"\d+-\d+", part):
            lo, hi = map(int, part.split("-")); want |= set(range(lo, hi + 1))
        elif part.isdigit():
            want.add(int(part))
        elif part:
            die(f"not a row number: {part}", EX_USAGE)
    missing = want - {n for n, _, _ in rows}
    if missing:
        die(f"no row {', '.join(map(str, sorted(missing)))} in the note", EX_NOTFOUND)
    return [r for r in rows if r[0] in want]


COPY_HEAD = "## Copy to the sheet"


def copy_lines(project, who, rows):
    """The picked rows as the sheet takes them, pasted at column A: Project, Whom, YYYY/MM/DD, Content (A–D)."""
    return [f"{project}\t{who}\t{d.replace('-', '/')}\t{t}" for _, d, t in rows]


def copy_section(text, tabs, nums, lines):
    """The note with its ## Copy to the sheet section written: one there already is replaced, else it goes last."""
    block = [COPY_HEAD, "",
             f"Tab {', '.join(tabs)}, rows {nums}. Paste at column A of the first empty row; it fills A–D.", "",
             "```", *lines, "```", ""]
    start = text.find("\n" + COPY_HEAD + "\n")
    if start < 0:
        return text.rstrip("\n") + "\n\n" + "\n".join(block)
    nxt = re.search(r"^## ", text[start + 1 + len(COPY_HEAD):], re.M)
    rest = text[start + 1 + len(COPY_HEAD) + nxt.start():] if nxt else ""
    return text[:start + 1] + "\n".join(block) + ("\n" + rest if rest else "")


def set_progress(text, line):
    return re.sub(r'^progress: ".*"$', lambda _: f'progress: "{line}"', text, count=1, flags=re.M)


def cmd_post(a):
    if not os.path.isfile(a.note):
        die(f"no note {a.note}", EX_NOTFOUND)
    text = open(a.note, encoding="utf-8").read()
    year = re.search(r'^date: "(\d{4})', text, re.M) or re.search(r"(\d{4})-\d{2}-\d{2}", os.path.basename(a.note))
    rows = note_rows(text, year.group(1) if year else datetime.date.today().year)
    if not rows:
        die("no One Thing table in the note", EX_NOTFOUND)
    chosen = pick(rows, a.pick)
    out = [(n, d, plain(t)) for n, d, t in chosen]
    bad = [n for n, d, _ in out if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
    if bad:
        die(f"row(s) {bad} carry no date the sheet can take (MM-DD or YYYY-MM-DD)", EX_USAGE)
    lines = copy_lines(setting(a, "ONETHING_PROJECT", "MH"), whom(a), out)
    tabs = sorted({tab_name(d[:7]) for _, d, _ in out})
    nums = ", ".join(str(n) for n, _, _ in out)
    stamp = datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    text = set_progress(copy_section(text, tabs, nums, lines), f"{stamp}: rows {nums} ready to copy")
    with open(a.note, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"tab {', '.join(tabs)}, rows {nums} (Project · Whom · Date · Content Overview), tab-separated:\n")
    print("\n".join(lines))
    print(f"\nwritten under {COPY_HEAD} in {a.note}; nothing is written to the sheet.")


def main():
    p = argparse.ArgumentParser(prog="onething", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env-file")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facts"); g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--date"); g.add_argument("--month"); f.add_argument("--json", action="store_true")
    s = sub.add_parser("sheet"); s.add_argument("--month", required=True); s.add_argument("--json", action="store_true")
    r = sub.add_parser("render"); r.add_argument("--rows", required=True); r.add_argument("--out"); r.add_argument("--force", action="store_true")
    o = sub.add_parser("post"); o.add_argument("note"); o.add_argument("--pick", required=True)
    a = p.parse_args()
    if getattr(a, "month", None) and not re.fullmatch(r"\d{4}-\d{2}", a.month):
        die("--month is YYYY-MM", EX_USAGE)
    {"facts": cmd_facts, "sheet": cmd_sheet, "render": cmd_render, "post": cmd_post}[a.cmd](a)


if __name__ == "__main__":
    main()
