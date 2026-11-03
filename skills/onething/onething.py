#!/usr/bin/env python3
"""The owner's rows in the team's monthly One Thing sheet: the facts of his own day, the store his drafted rows live in,
the block the day's changes page carries, his rewording and his "pasted" ticks applied, and the lines he copies into
the sheet himself. Read-only toward Google, Jira and Slack; it writes only the store under the reports root (and a vault
note on request). Stdlib only.

  facts  (--date D | --month YYYY-MM)        his own Jira actions and Slack messages per day (Asia/Shanghai), Helm's
                                             auto-writes left out; --json for the drafting session
  sheet  --month YYYY-MM                     the rows already in that month's tab under his name (Drive export)
  render --rows FILE [--force]               the drafted rows into the store, <reports>/onething/<YYYY-MM>.json, one
                                             entry per working day (that date's entry replaced, other days untouched;
                                             a date already drafted is refused without --force, it may hold his
                                             edits); --out PATH writes a vault note instead, on request
  block  --date D [--json]                   the day's block for the changes page: the numbered row table, the
                                             evidence, a folded Copy to the sheet, one `pasted n` box per row
  apply  --date D --lines FILE [--json]      his lines from the page: a rewording replaces the row's text (kept under
                                             ela_lines); a ticked `pasted n` sets the flag
  post   (--date D | --month YYYY-MM) [--pick 1,3] [--all]
                                             the rows as the sheet takes them (plain keys), tab-separated, printed;
                                             a month: its rows not yet pasted; nothing is written anywhere
  import NOTE [--force] [--pasted]           one-off: a One Thing vault note's table into the store

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
TABLE_HEAD = "| # | date | Content Overview (edit freely) |"   # a vault note's table (render --out, import)
BLOCK_HEAD = "| # | date | Content Overview |"                  # the changes page's table: his rewording is an `ela:` line
BLOCK_TITLE = "## Your day, "                                   # the block's heading; the runner finds it by this prefix
COPY_FOLD = "> [!note]- Copy to the sheet"
SKIP_FIELDS = {"Fixed In", "labels", "Link", "RemoteIssueLink", "Rank"}   # bookkeeping, not work; Fixed In is mostly Helm's
EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5


def die(msg, code):
    print(msg, file=sys.stderr); sys.exit(code)


def env_args(a):
    return ["--env-file", a.env_file] if a.env_file else []


def setting(a, key, default=None):
    """A site env value: --env-file, else ELA_ENV_FILE (the adapter's), else the site's env named in site.json."""
    return gdoc.env_value(key, getattr(a, "env_file", None) or site().get("env")) or os.environ.get(key) or default


def whom(a):
    """The owner's name in column B; it lives in the site env, never in this file."""
    w = setting(a, "ONETHING_WHOM")
    if not w:
        die("no ONETHING_WHOM in the site env: the owner's name in the sheet's Whom column", EX_USAGE)
    return w


def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def reports_root(a=None):
    """The reports root (site.json `reports`, else <projects>/reports); --reports overrides it, for a test."""
    if a is not None and getattr(a, "reports", None):
        return a.reports
    s = site()
    return s.get("reports") or os.path.join(s.get("projects") or os.path.expanduser("~/projects"), "reports")


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


# ---------------------------------------------------------------- text helpers

def link_keys(text, base):
    """Bare ticket keys as Markdown links; keys already inside a link are left alone."""
    parts = re.split(r"(\[[^\]]*\]\([^)]*\))", text)
    return "".join(p if p.startswith("[") else KEY.sub(lambda m: f"[{m.group(0)}]({base}/browse/{m.group(0)})", p) for p in parts)


def plain(text):
    """A row as the sheet takes it: links to their text, wiki links to their name, table escapes undone."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return text.replace("\\|", "|").strip()


def jira_base(a=None):
    return (setting(a, "JIRA_BASE_URL") or setting(a, "JIRA_URL") or "https://tvunetworks.atlassian.net").rstrip("/")


def copy_lines(project, who, rows):
    """The rows as the sheet takes them, pasted at column A: Project, Whom, YYYY/MM/DD, Content (A–D)."""
    return [f"{project}\t{who}\t{d.replace('-', '/')}\t{t}" for _, d, t in rows]


def weekday(date):
    return datetime.date.fromisoformat(date).strftime("%a")


def now_iso():
    return datetime.datetime.now(TZ).isoformat(timespec="seconds")


# ---------------------------------------------------------------- the store

def store_path(reports, month):
    return os.path.join(reports, "onething", f"{month}.json")


def load_month(reports, month):
    """One month of the store: {month, days: [entry]}, empty when the file is not there."""
    try:
        data = json.load(open(store_path(reports, month), encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"month": month, "days": sorted(data.get("days") or [], key=lambda e: e["date"])}


def save_month(reports, data):
    """The month written whole, atomically; days sorted by date, rows numbered 1.. in order."""
    for e in data["days"]:
        for n, r in enumerate(e["rows"], 1):
            r["n"] = n
    data["days"].sort(key=lambda e: e["date"])
    p = store_path(reports, data["month"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def day_entry(reports, date):
    data = load_month(reports, date[:7])
    return next((e for e in data["days"] if e["date"] == date), None)


def put_day(reports, entry, force=False):
    """The date's entry into its month: appended, or replacing the one there (refused without force: it may hold his
    edits). Returns the store path."""
    data = load_month(reports, entry["date"][:7])
    have = next((e for e in data["days"] if e["date"] == entry["date"]), None)
    if have and not force:
        die(f"{entry['date']} is already drafted in {store_path(reports, entry['date'][:7])}; it may hold his edits; --force to replace it", EX_USAGE)
    data["days"] = [e for e in data["days"] if e["date"] != entry["date"]] + [entry]
    return save_month(reports, data)


def new_row(n, text, evidence=""):
    return {"n": n, "text": text.strip(), "evidence": (evidence or "").strip(), "pasted": False, "ela_lines": []}


def entries_from_spec(spec, drafted_at):
    """The rows file's rows grouped per date into store entries, numbered in the order given."""
    by = {}
    for r in spec.get("rows") or []:
        by.setdefault(r["date"], []).append(r)
    out = []
    for d in sorted(by):
        rows = [new_row(n, r["text"], r.get("evidence") or spec.get("evidence") or "") for n, r in enumerate(by[d], 1)]
        out.append({"date": d, "rows": rows, "drafted_at": drafted_at, "source_errors": list(spec.get("errors") or [])})
    return out


def all_entries(reports):
    """Every entry in the store, oldest first."""
    d = os.path.join(reports, "onething")
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if re.fullmatch(r"\d{4}-\d{2}\.json", f):
            out += load_month(reports, f[:-5])["days"]
    return out


# ---------------------------------------------------------------- the block (the changes page) and the month page

def copy_fold(tabs, lines, label=None):
    """The folded Copy to the sheet callout: the tab(s) named, the tab-separated lines in a fence inside it."""
    head = COPY_FOLD + (f" · {label}" if label else "")
    return [head, f"> Tab {', '.join(tabs)}. Paste at column A of the first empty row; it fills A–D.", "> ```", *[f"> {ln}" for ln in lines], "> ```"]


def block(entry, base, project, who):
    """The day's section for the changes page of the next working day: the heading, the numbered rows (keys linked),
    the evidence folded, the Copy to the sheet fold, one `pasted n` box per row, and how he rewords a row."""
    date, rows = entry["date"], entry["rows"]
    L = [f"{BLOCK_TITLE}{weekday(date)} {date}", "", BLOCK_HEAD, "|---|---|---|"]
    for r in rows:
        L.append(f"| {r['n']} | {date} | {link_keys(r['text'].replace('|', chr(92) + '|'), base)} |")
    ev = [r["evidence"] for r in rows if r.get("evidence")]
    if ev:
        L += ["", "> [!note]- Evidence"] + [f"> {e}" for e in dict.fromkeys(ev)]
    lines = copy_lines(project, who, [(r["n"], date, plain(r["text"])) for r in rows])
    L += [""] + copy_fold([tab_name(date[:7])], lines) + [""]
    L += [f"- [{'x' if r.get('pasted') else ' '}] pasted {r['n']}" for r in rows]
    how = "write `ela: <the row as you want it>` under this section" if len(rows) == 1 else "write `ela: <n>: <the row as you want it>` under this section"
    L += ["", f"*To reword, {how}; tick `pasted` once it is on the sheet. The month's unpasted rows: [[one-thing|One Thing]].*"]
    return "\n".join(L) + "\n", lines


PAGE_TITLE = "One Thing · {month}"


def month_page(reports, today, base, project, who):
    """The root page one-thing.md: the current month's rows not yet pasted, one Copy to the sheet block, one
    `pasted <date>[ n]` box per row, and the same for earlier months still unpasted. (text, count); (None, 0) when
    the store has nothing at all."""
    entries = all_entries(reports)
    if not entries:
        return None, 0
    month = today.isoformat()[:7]
    open_rows = [(e["date"], r) for e in entries for r in e["rows"] if not r.get("pasted")]
    this, earlier = [x for x in open_rows if x[0][:7] == month], [x for x in open_rows if x[0][:7] < month]
    title = PAGE_TITLE.format(month=month)
    L = [f"# {title}", ""]

    def section(rows, label):
        tabs = sorted({tab_name(d[:7]) for d, _ in rows})
        S = [BLOCK_HEAD.replace("# | date", "date | #"), "|---|---|---|"]
        for d, r in rows:
            S.append(f"| {d} | {r['n']} | {link_keys(r['text'].replace('|', chr(92) + '|'), base)} |")
        lines = copy_lines(project, who, [(r["n"], d, plain(r["text"])) for d, r in rows])
        S += [""] + copy_fold(tabs, lines, label) + [""]
        S += [f"- [ ] pasted {d}" + (f" {r['n']}" if sum(1 for x, _ in rows if x == d) > 1 else "") for d, r in rows]
        return S
    n = len(this) + len(earlier)
    if not open_rows:
        L += ["**In short.** Every drafted row is on the sheet. A day's row is drafted at 19:00 into its store and shown on the "
              "next morning's changes page; it appears here until you tick `pasted`.", ""]
    else:
        L += [f"**In short.** {n} row{'s' if n != 1 else ''} not yet on the sheet"
              + (f", {len(this)} of {tab_name(month)}" if this and earlier else "") + ". Copy the block, paste it at column A "
              "of the first empty row of the tab, then tick each `pasted` here (or on the day's changes page). To reword a "
              "row, write an `ela:` line under *Your day* on its changes page; the next pass applies it.", ""]
    if this:
        L += section(this, None) + [""]
    if earlier:
        L += ["## Earlier months", ""] + section(earlier, "earlier months") + [""]
    return "\n".join(L).rstrip("\n") + "\n", n


def site_values(a=None):
    """(jira base, project, whom) for the block's links and copy lines."""
    return jira_base(a), setting(a, "ONETHING_PROJECT", "MH"), whom(a)


def cmd_block(a):
    entry = day_entry(reports_root(a), a.date)
    if not entry:
        die(f"no One Thing row drafted for {a.date} in {store_path(reports_root(a), a.date[:7])}", EX_NOTFOUND)
    base, project, who = site_values(a)
    text, lines = block(entry, base, project, who)
    if a.json:
        print(json.dumps({"date": a.date, "store": store_path(reports_root(a), a.date[:7]), "heading": text.split("\n", 1)[0][3:],
                          "block": text, "rows": entry["rows"], "lines": lines, "drafted_at": entry.get("drafted_at")}, ensure_ascii=False))
    else:
        print(text, end="")


# ---------------------------------------------------------------- render

def render(spec, base, today, project=None, who=None):
    """A vault note (render --out); with `who`, the Copy to the sheet block for every row as drafted, so it is copy-ready."""
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
         "paste at column A. `ela onething import` reads this note into the store.", ""]
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


COPY_HEAD = "## Copy to the sheet"


def copy_section(text, tabs, nums, lines):
    """A note with its ## Copy to the sheet section written: one there already is replaced, else it goes last."""
    blk = [COPY_HEAD, "",
           f"Tab {', '.join(tabs)}, rows {nums}. Paste at column A of the first empty row; it fills A–D.", "",
           "```", *lines, "```", ""]
    start = text.find("\n" + COPY_HEAD + "\n")
    if start < 0:
        return text.rstrip("\n") + "\n\n" + "\n".join(blk)
    nxt = re.search(r"^## ", text[start + 1 + len(COPY_HEAD):], re.M)
    rest = text[start + 1 + len(COPY_HEAD) + nxt.start():] if nxt else ""
    return text[:start + 1] + "\n".join(blk) + ("\n" + rest if rest else "")


def cmd_render(a):
    spec = json.load(open(a.rows, encoding="utf-8"))
    for r in spec.get("rows") or []:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.get("date", "")) or not (r.get("text") or "").strip():
            die(f"a row needs date YYYY-MM-DD and text: {r}", EX_USAGE)
    today = datetime.datetime.now(TZ).date().isoformat()
    if a.out:                                           # a vault note on request, as before the store
        sheet = setting(a, "ONETHING_SHEET")
        spec.setdefault("sheet_url", f"https://docs.google.com/spreadsheets/d/{sheet}/edit" if sheet else "")
        if os.path.exists(a.out) and not a.force:
            die(f"{a.out} exists: it may hold your edits; --force to replace it", EX_USAGE)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(render(spec, jira_base(a), today, setting(a, "ONETHING_PROJECT", "MH"), whom(a)))
        print(a.out); return
    entries = entries_from_spec(spec, now_iso())
    if not entries:
        die("no rows in the file: a day with nothing of his gets no entry", EX_USAGE)
    reports = reports_root(a)
    have = [e["date"] for e in entries if day_entry(reports, e["date"])]
    if have and not a.force:
        die(f"already drafted: {', '.join(have)} in {os.path.join(reports, 'onething')}; the entry may hold his edits; --force to replace it", EX_USAGE)
    for e in entries:
        p = put_day(reports, e, force=True)
    print(f"{len(entries)} day(s) written: {', '.join(e['date'] for e in entries)} → {p if len({e['date'][:7] for e in entries}) == 1 else os.path.join(reports, 'onething')}")


# ---------------------------------------------------------------- apply

PASTED = re.compile(r"^pasted(?:\s+(\d{4}-\d{2}-\d{2}))?(?:\s+(\d+))?\s*$", re.I)
NUMBERED = re.compile(r"^(\d+)\s*[:：.)—–-]\s*(\S.*)$")


def apply_lines(reports, date, lines):
    """His lines applied to the store: `pasted [date] [n]` ticks the row; `n: text` rewords row n; a bare line rewords
    the day's one row. Each change is written once (a line applied at 13:00 is not applied again at 17:30). Returns
    {changed: [...], skipped: [...]}, having saved every month touched."""
    months, changed, skipped = {}, [], []

    def entry_of(d):
        m = d[:7]
        if m not in months:
            months[m] = load_month(reports, m)
        return next((e for e in months[m]["days"] if e["date"] == d), None)
    for raw in lines:
        line = raw.strip().strip('"').strip("'")
        if not line:
            continue
        t = PASTED.match(line)
        if t:
            d = t.group(1) or date
            if not d:
                skipped.append(f"{line}: no date"); continue
            e = entry_of(d)
            if not e:
                skipped.append(f"{line}: no row drafted for {d}"); continue
            n = int(t.group(2) or 1)
            r = next((r for r in e["rows"] if r["n"] == n), None)
            if not r:
                skipped.append(f"{line}: no row {n} on {d}"); continue
            if not r.get("pasted"):
                r["pasted"] = True; r["pasted_at"] = now_iso(); changed.append(f"{d} row {n} pasted")
            continue
        if re.match(r"^post\b", line, re.I):
            skipped.append(f"{line}: post prints the lines; it is not a rewording"); continue
        if not date:
            skipped.append(f"{line}: no date"); continue
        e = entry_of(date)
        if not e:
            skipped.append(f"{line}: no row drafted for {date}"); continue
        m = NUMBERED.match(line)
        if m:
            n, text = int(m.group(1)), m.group(2).strip()
        elif len(e["rows"]) == 1:
            n, text = 1, line
        else:
            skipped.append(f"{line}: the day has {len(e['rows'])} rows; start with the row number"); continue
        r = next((r for r in e["rows"] if r["n"] == n), None)
        if not r:
            skipped.append(f"{line}: no row {n} on {date}"); continue
        if r["text"] == text and r["ela_lines"] and r["ela_lines"][-1] == text:
            continue                                        # already applied at an earlier pass
        if not r["ela_lines"] or r["ela_lines"][-1] != text:
            r["ela_lines"].append(text)
        r["text"] = text; changed.append(f"{date} row {n} reworded")
    if changed:
        for data in months.values():
            save_month(reports, data)
    return {"changed": changed, "skipped": skipped}


def cmd_apply(a):
    try:
        lines = open(a.lines, encoding="utf-8").read().splitlines()
    except OSError as e:
        die(f"lines file: {e}", EX_NOTFOUND)
    got = apply_lines(reports_root(a), a.date, lines)
    got["date"] = a.date
    if a.json:
        print(json.dumps(got, ensure_ascii=False))
    else:
        print(f"{len(got['changed'])} change(s)" + (": " + "; ".join(got["changed"]) if got["changed"] else "")
              + (f"\nskipped: " + "; ".join(got["skipped"]) if got["skipped"] else ""))


# ---------------------------------------------------------------- post: the lines he pastes

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


def cmd_post(a):
    reports = reports_root(a)
    if a.date:
        e = day_entry(reports, a.date)
        if not e:
            die(f"no One Thing row drafted for {a.date}", EX_NOTFOUND)
        rows = [(r["n"], a.date, plain(r["text"])) for r in e["rows"] if a.all or a.pick or not r.get("pasted")]
        rows = pick(rows, a.pick) if a.pick else rows
    else:
        rows = [(r["n"], e["date"], plain(r["text"])) for e in load_month(reports, a.month)["days"] for r in e["rows"]
                if a.all or not r.get("pasted")]
    if not rows:
        die("no rows to paste" + ("" if a.all else "; --all includes the rows already pasted"), EX_NOTFOUND)
    lines = copy_lines(setting(a, "ONETHING_PROJECT", "MH"), whom(a), rows)
    tabs = sorted({tab_name(d[:7]) for _, d, _ in rows})
    if a.json:
        print(json.dumps({"tabs": tabs, "rows": [{"date": d, "n": n} for n, d, _ in rows], "lines": lines}, ensure_ascii=False)); return
    print(f"tab {', '.join(tabs)}, {len(rows)} row(s) (Project · Whom · Date · Content Overview), tab-separated; nothing is written to the sheet:\n", file=sys.stderr)
    print("\n".join(lines))


# ---------------------------------------------------------------- import: a vault note's table into the store

def note_rows(text, year_hint):
    """The numbered rows of a One Thing note or block: [(n, YYYY-MM-DD, text as written)]."""
    rows, on = [], False
    for line in text.splitlines():
        if line.strip() in (TABLE_HEAD, BLOCK_HEAD):
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


def note_evidence(text):
    """The words of the note's folded Evidence callout, one paragraph."""
    m = re.search(r"(?m)^> \[!note\]- Evidence[ \t]*\n((?:>.*\n?)+)", text)
    return " ".join(ln.lstrip("> ").strip() for ln in m.group(1).splitlines() if ln.strip("> ").strip()) if m else ""


def import_note(reports, text, name, year_hint, force=False, pasted=False):
    """A note's rows into the store, one entry per date, the note's evidence on each row, `imported_from` the note's
    file name. Returns the dates written."""
    rows = note_rows(text, year_hint)
    if not rows:
        die("no One Thing table in the note", EX_NOTFOUND)
    bad = [n for n, d, _ in rows if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
    if bad:
        die(f"row(s) {bad} carry no date (MM-DD or YYYY-MM-DD)", EX_USAGE)
    ev = note_evidence(text)
    by = {}
    for _, d, t in rows:
        by.setdefault(d, []).append(t)
    have = [d for d in by if day_entry(reports, d)]
    if have and not force:
        die(f"already drafted: {', '.join(sorted(have))}; --force to replace those days", EX_USAGE)
    stamp = now_iso()
    for d in sorted(by):
        entry = {"date": d, "rows": [dict(new_row(n, plain(t), ev), pasted=pasted) for n, t in enumerate(by[d], 1)],
                 "drafted_at": stamp, "source_errors": [], "imported_from": name}
        put_day(reports, entry, force=True)
    return sorted(by)


def cmd_import(a):
    if not os.path.isfile(a.note):
        die(f"no note {a.note}", EX_NOTFOUND)
    text = open(a.note, encoding="utf-8").read()
    year = re.search(r'^date: "(\d{4})', text, re.M) or re.search(r"(\d{4})-\d{2}-\d{2}", os.path.basename(a.note))
    dates = import_note(reports_root(a), text, os.path.basename(a.note), year.group(1) if year else datetime.date.today().year, a.force, a.pasted)
    print(f"{len(dates)} day(s) imported from {os.path.basename(a.note)}: {', '.join(dates)}"
          + (" (marked pasted)" if a.pasted else "") + f" → {os.path.join(reports_root(a), 'onething')}")


def main():
    p = argparse.ArgumentParser(prog="onething", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env-file")
    p.add_argument("--reports", help="the reports root (default: site.json); for a test")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facts"); g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--date"); g.add_argument("--month"); f.add_argument("--json", action="store_true")
    s = sub.add_parser("sheet"); s.add_argument("--month", required=True); s.add_argument("--json", action="store_true")
    r = sub.add_parser("render"); r.add_argument("--rows", required=True); r.add_argument("--out", help="a vault note instead of the store"); r.add_argument("--force", action="store_true")
    b = sub.add_parser("block"); b.add_argument("--date", required=True); b.add_argument("--json", action="store_true")
    ap = sub.add_parser("apply"); ap.add_argument("--date"); ap.add_argument("--lines", required=True); ap.add_argument("--json", action="store_true")
    o = sub.add_parser("post"); og = o.add_mutually_exclusive_group(required=True)
    og.add_argument("--date"); og.add_argument("--month"); o.add_argument("--pick", help="row numbers of the day, 1,3 · 2-4 · all")
    o.add_argument("--all", action="store_true", help="the rows already pasted too"); o.add_argument("--json", action="store_true")
    i = sub.add_parser("import"); i.add_argument("note"); i.add_argument("--force", action="store_true")
    i.add_argument("--pasted", action="store_true", help="the rows are on the sheet already")
    a = p.parse_args()
    if getattr(a, "month", None) and not re.fullmatch(r"\d{4}-\d{2}", a.month):
        die("--month is YYYY-MM", EX_USAGE)
    if getattr(a, "date", None) and a.cmd != "facts" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        die("--date is YYYY-MM-DD", EX_USAGE)
    {"facts": cmd_facts, "sheet": cmd_sheet, "render": cmd_render, "block": cmd_block, "apply": cmd_apply,
     "post": cmd_post, "import": cmd_import}[a.cmd](a)


if __name__ == "__main__":
    main()
