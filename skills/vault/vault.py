#!/usr/bin/env python3
"""The owner's reading vault: a one-way, generated Obsidian mirror. Stdlib only.

L1: deterministic, no LLM. Every note in the vault is written by this script from a first-hand source and
overwritten on the next sync; nothing in it is maintained by hand (a hand-maintained vault was abandoned on
2026-10-10). Sources: elak's decisions and plans, and the reports root; a ticket key becomes a direct Jira link. The vault's
own `.obsidian/` and any file this script did not write are never touched; a file it wrote whose source is
gone is removed, by its manifest.

Usage:
    vault.py [--env-file F] sync [--dry-run] [--json]

Layout. Folder and file names are lowercase with hyphens, folders numbered in reading order; the readable title is
the note's first heading, and the links Home shows use it:
    home.md                                  the entry point: today's page embedded, then what is new or held back
    10-days/2026-10-23-brief.md              the judged morning page (14 days); -learned, -intake beside it
    20-reviews/2026-10-23-ela-review.md      reviews and reports written for the owner
    30-verify/mh-3103-2026-10-23.md          a verification: screenshots and PDF embedded, the full page linked
    40-decisions/2026-10-22-<slug>.md        elak decisions
    50-plans/2026-10-21-<slug>.md            elak plans (55-sprints/ once sprints are recorded)
    80-views/*.base                          Bases tables over the notes' properties
    90-attachments/                          images and PDFs the notes embed
elak knowledge, the status table and the working preferences are written for ela and stay out of the vault.
"""
import argparse, datetime, hashlib, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SITE = os.path.expanduser("~/.claude/ela/site.json")
MANIFEST = ".ela-sync.json"
KEY_RX = re.compile(r"(?<![\w/#=-])([A-Z][A-Z0-9]{1,9}-\d{1,6})(?![\w-])")
NOT_KEYS = re.compile(r"^(UTF|ISO|SHA|MD|RFC|CVE|HTTP|TLS|SSL|H|X|AV|AAC|MP|PR|MR|ENV|AWS|CN|QA|UR|J2N|S|W|SCTE|SMPTE|ST|ITU|BT|IEC|EBU|ATSC|DVB|IEEE|HEVC|AVC)-")
BAD_NAME = re.compile(r'[*"\\/<>:|?#^\[\]]')
DAYS_KEPT = 14
# addresses and credentials are never copied out of WSL: redacted in every note
REDACT = [(re.compile(r"\b(10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(:\d+)?\b"), "<address>"),
          (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "<token>"),
          (re.compile(r"(?i)\b(bearer|token|password|passwd|secret)(\s*[:=]\s*)\S{8,}"), r"\1\2<redacted>")]


def site():
    return json.load(open(SITE))


def slug(s, limit=60):
    """A path segment: lowercase, words joined by hyphens, no spaces; CJK kept as written; cut at a word."""
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", re.sub(r"['’]", "", (s or "").lower())).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0]
    return s or "untitled"


def undated(title, date):
    """A title without the date its file name already starts with, nor the weekday or separator around it."""
    if not date:
        return title
    t = re.sub(r"[\s,—-]*[（(]?" + re.escape(date) + r"[)）]?(\s*[（(][^)）]{1,6}[)）])?", " ", title)
    return re.sub(r"\s+", " ", t).strip(" ,—-")


def split_front(text):
    """(frontmatter lines without the fences, body). No YAML library: the block is kept as written."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[4:end].splitlines(), text[end + 4:].lstrip("\n")
    return [], text


def h1(body):
    m = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    return re.sub(r"[`*_]", "", m.group(1)).strip() if m else None


def yaml_value(v):
    return json.dumps(v, ensure_ascii=False)          # a JSON string or list is valid YAML


PROPS = ("type", "date", "kind", "status")   # the whole property vocabulary: a reader scans it, Bases sorts by it


def front(existing, props):
    """The note's properties, from the fixed vocabulary only. A source's own `status` is kept (a plan's decided or
    proposed); every other source key is ela's bookkeeping and stays out of the reader's panel."""
    src = {}
    for l in existing:
        m = re.match(r"^(status|decided|written):\s*['\"]?([^'\"]*)['\"]?\s*$", l)
        if m:
            src[m.group(1)] = m.group(2).strip()
    props = dict(props)
    if src.get("status") and not props.get("status"):
        props["status"] = src["status"].split(" — ")[0].split(" (")[0][:40]
    if not props.get("date") and (src.get("decided") or src.get("written")):
        props["date"] = (src.get("decided") or src.get("written"))[:10]
    lines = [f"{k}: {yaml_value(props[k])}" for k in PROPS if props.get(k)]
    return "---\n" + "\n".join(lines) + "\n---\n\n" if lines else ""


def redact(text):
    for rx, rep in REDACT:
        text = rx.sub(rep, text)
    return text


def keys_in(text):
    return {k for k in KEY_RX.findall(text or "") if not NOT_KEYS.match(k)}


# ── sources → planned notes ───────────────────────────────────────────────────────────────────────────

class Note:
    def __init__(self, path, title, body, props, front_lines=(), origin=None):
        self.path, self.title, self.body, self.props, self.front_lines, self.origin = path, title, body, props, list(front_lines), origin


def elak_notes(elak):
    out = git_md = subprocess.run(["git", "-C", elak, "ls-files", "*.md"], capture_output=True, text=True).stdout.split()
    notes, by_src = [], {}
    for rel in git_md:
        if rel.startswith(("elak/", "map/")) or rel.lower().endswith("readme.md"):   # the map and indexes are ela's
            continue
        text = open(os.path.join(elak, rel), encoding="utf-8").read()
        fl, body = split_front(text)
        parts = rel.split("/")
        base = os.path.splitext(parts[-1])[0]
        title = h1(body) or base.replace("-", " ")
        title = title if re.match(r"^(ela|elak)\b", title) else title[:1].upper() + title[1:]
        date = re.match(r"^(\d{4}-\d{2}-\d{2})-?(.*)$", base)
        area = None
        if parts[0] == "blueprint":
            kind = {"decisions": "decision", "plans": "plan", "sprints": "sprint"}.get(parts[1] if len(parts) > 2 else "", "blueprint")
            folder = {"decision": "40-decisions", "plan": "50-plans", "sprint": "55-sprints"}.get(kind, "blueprint")
            name = f"{date.group(1)}-{slug(undated(title, date.group(1)))}" if date else \
                ("overview" if base.lower() == "readme" else slug(title))
            area = "ela"
        elif parts[0] == "knowledge":
            kind = "knowledge"
            sub = parts[1:-1]
            folder = "knowledge/" + "/".join(sub)
            area = sub[1] if len(sub) > 1 and sub[0] in ("products", "platform") else (sub[0] if sub else None)
            name = slug(title) if base.lower() != "readme" else "overview"
        elif parts[0] == "map":
            kind, folder, name = "map", "70 Map/" + "/".join(parts[1:-1]), title
        else:
            kind, folder, name = "blueprint", "blueprint", ("elak-overview" if base.lower() == "readme" else slug(title))
        folder = folder.rstrip("/")
        n = Note(f"{folder}/{name}.md", title, body,
                 {"type": kind, "date": date.group(1) if date else None, "area": area},
                 fl, origin=os.path.join(elak, rel))
        notes.append(n); by_src[rel] = n
    return notes, by_src


def report_notes(reports, today):
    notes = []
    rd = os.path.join(reports, "runner")
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(brief|learned|intake)\.md$", f)
        if not m or (today - datetime.date.fromisoformat(m.group(1))).days >= DAYS_KEPT:
            continue
        d = datetime.date.fromisoformat(m.group(1))
        label = {"brief": "Brief", "learned": "Learned", "intake": "Intake"}[m.group(2)]
        fl, body = split_front(open(os.path.join(rd, f), encoding="utf-8").read())
        notes.append(Note(f"10-days/{m.group(1)}-{label.lower()}.md", f"{m.group(1)} {d:%a} {label}", body,
                          {"type": "day", "date": m.group(1), "kind": label.lower()}, fl))
    for sub in ("ela", ""):
        d = os.path.join(reports, sub) if sub else reports
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            p = os.path.join(d, f)
            if not f.endswith(".md") or f.lower() == "readme.md" or not os.path.isfile(p):
                continue
            fl, body = split_front(open(p, encoding="utf-8").read())
            base = f[:-3]
            m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
            date = m.group(1) if m else datetime.date.fromtimestamp(os.path.getmtime(p)).isoformat()
            title = h1(body) or re.sub(r"[-_]?\d{4}-\d{2}-\d{2}[-_]?", " ", base).replace("-", " ").strip()
            notes.append(Note(f"20-reviews/{date}-{slug(undated(title, date))}.md", undated(title, date), body,
                              {"type": "review", "date": date}, fl))
    return notes


def verify_notes(reports, helm_url):
    notes, files = [], []
    vd = os.path.join(reports, "verify")
    for name in sorted(os.listdir(vd)) if os.path.isdir(vd) else []:
        m = re.match(r"^([A-Z][A-Z0-9]+-\d+)-(\d{4}-\d{2}-\d{2})(\.html)?$", name)
        if not m:
            continue
        key, date, single = m.group(1), m.group(2), bool(m.group(3))
        p = os.path.join(vd, name)
        embeds = []
        if not single:
            for top, _, fs in os.walk(p):
                for f in sorted(fs):
                    if f.lower().endswith((".png", ".jpg", ".jpeg", ".pdf")):
                        dst = f"90-attachments/verify/{name.lower()}/{slug(os.path.splitext(os.path.relpath(os.path.join(top, f), p))[0], 80)}{os.path.splitext(f)[1].lower()}"
                        files.append((os.path.join(top, f), dst)); embeds.append(dst)
        url = f"{helm_url.rstrip('/')}/ela/verify/{name}{'' if single else '/'}" if helm_url else None
        pdfs = [e for e in embeds if e.endswith(".pdf")]
        imgs = [e for e in embeds if not e.endswith(".pdf")]
        body = [f"# {key} verification · {date}", "",
                f"Ticket {key} · " + (f"[the full record in the local Helm]({url})" if url else "the record is under the reports root"), ""]
        if pdfs:
            body += ["## Record", ""] + [f"![[{e}]]" for e in pdfs[:1]] + [""]
        if imgs:
            body += ["## Screenshots", ""] + [f"![[{e}]]" for e in imgs[:8]]
        notes.append(Note(f"30-verify/{key.lower()}-{date}.md", f"{key} verification {date}", "\n".join(body) + "\n",
                          {"type": "verify", "date": date, "ticket": key}))
    return notes, files


VIEWS = {
    "Decisions and plans": """filters:
  or:
    - 'type == "decision"'
    - 'type == "plan"'
views:
  - type: table
    name: All
    order: [file.name, type, date, status]
""",
    "Days and reviews": """filters:
  or:
    - 'type == "day"'
    - 'type == "review"'
    - 'type == "verify"'
views:
  - type: table
    name: Recent
    order: [file.name, type, date]
""",
    }


# ── links ─────────────────────────────────────────────────────────────────────────────────────────────

ELAK_PATH = re.compile(r"`(?:<elak>/)?((?:blueprint|knowledge|map)/[^`\s]+?\.md|README\.md)(#[^`]*)?`")
SEGMENT = re.compile(r"(```.*?```|\[[^\]]*\]\([^)]*\)|<https?://[^>]+>|https?://\S+|`[^`]*`|\[\[[^\]]*\]\])", re.S)
TITLES = {}
JIRA_BASE = [""]     # a ticket key becomes a direct Jira link: one click in reading mode
SLACK_LINK = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")


def link_text(text, by_src):
    text = SLACK_LINK.sub(lambda m: f"[{m.group(2)}]({m.group(1)})", text)

    def elak(m):
        n = by_src.get(m.group(1))
        if n:
            return f"[[{n.path[:-3]}{m.group(2) or ''}|{n.title}]]"
        t = TITLES.get(m.group(1))
        return f"*{t}*" if t else m.group(0)
    out = []
    for i, seg in enumerate(SEGMENT.split(text)):
        if i % 2:
            out.append(ELAK_PATH.sub(elak, seg) if seg.startswith("`") and not seg.startswith("```") else seg)
        else:
            out.append(KEY_RX.sub(lambda m: f"[{m.group(1)}]({JIRA_BASE[0]}/browse/{m.group(1)})" if JIRA_BASE[0] and not NOT_KEYS.match(m.group(1)) else m.group(1), seg))
    return "".join(out)


# ── the reading gate: the vault is how ela reports to the owner, so a note must be written for a person ─────
# Budgets in reading units (an English word, or two CJK characters). A note that fails is held back and listed on
# Home with its reason: a debt of the skill that wrote it, never a file the owner has to wade through.
BUDGET = {"day": 1200, "review": 2500, "decision": 1200, "plan": 2500, "sprint": 800}
MACHINE = re.compile(r"(/home/|/mnt/|\\\\wsl|<runtime>|<projects>|\{\s*\"[a-z_]+\"\s*:|Traceback \(most recent)")


def reading_units(text):
    return len(re.findall(r"[A-Za-z0-9][\w'’.-]*", text)) + len(re.findall(r"[\u4e00-\u9fff]", text)) // 2


def reading_gate(n):
    kind = n.props.get("type")
    if kind not in BUDGET:
        return []
    body = re.sub(r"```.*?```", "", n.body, flags=re.S)
    problems = []
    if not h1(n.body):
        problems.append("no title heading")
    units = reading_units(body)
    if units > BUDGET[kind]:
        problems.append(f"{units} words to read, budget {BUDGET[kind]}")
    lines = n.body.splitlines() or [""]
    code = sum(1 for l in re.findall(r"```.*?```", n.body, flags=re.S) for _ in l.splitlines())
    if code > max(12, len(lines) // 4):
        problems.append(f"{code} of {len(lines)} lines are code")
    machine = len(MACHINE.findall(n.body))
    if machine > 2:
        problems.append(f"{machine} machine paths or raw records")
    return problems


# ── the sync ──────────────────────────────────────────────────────────────────────────────────────────

def home(today, notes, held=()):
    days = sorted((n for n in notes if n.props.get("type") == "day" and n.props.get("kind") == "brief"), key=lambda n: n.path, reverse=True)
    reviews = sorted((n for n in notes if n.props.get("type") == "review"), key=lambda n: n.path, reverse=True)[:6]
    decisions = sorted((n for n in notes if n.props.get("type") in ("decision", "plan")), key=lambda n: n.path, reverse=True)[:6]
    learned = sorted((n for n in notes if n.props.get("kind") == "learned"), key=lambda n: n.path, reverse=True)[:1]
    L = [f"# ela · {today:%Y-%m-%d %a}", "",
         "*Generated by ela and rewritten on every sync; change things through ela, not here.*", ""]
    held_today = [p for n, p in held if n.props.get("type") == "day" and n.props.get("kind") == "brief" and n.props.get("date") == today.isoformat()]
    if days and days[0].props.get("date") == today.isoformat():
        L += [f"## Today · [[{days[0].path[:-3]}|{days[0].title}]]", "", f"![[{days[0].path[:-3]}]]", ""]
    elif held_today:
        L += ["## Today", "", f"**Today's page was held back** ({'; '.join(held_today[0])}). It is in your Slack DM; "
              "ela owes a shorter one.", ""]
    else:
        L += ["## Today", "", "No page yet today" + (f"; the latest is [[{days[0].path[:-3]}|{days[0].title}]]." if days else "."), ""]
    if learned:
        L += ["## Waiting for your word", "", f"- [[{learned[0].path[:-3]}|{learned[0].title}]] — candidate knowledge from your sessions", ""]
    L += ["## Recent reviews", ""] + [f"- {n.props.get('date')} [[{n.path[:-3]}|{n.title}]]" for n in reviews] + [""]
    L += ["## Recent decisions and plans", ""] + [f"- {n.props.get('date')} [[{n.path[:-3]}|{n.title}]]" for n in decisions] + [""]
    if held:
        L += ["## Held back", "", "Written by ela but not yet fit to read here; each is a rewrite ela owes.", ""]
        L += [f"- {n.title if n.title[:10] == (n.props.get('date') or '') else (n.props.get('date') or '') + ' ' + n.title} — {'; '.join(p)}"
              for n, p in held] + [""]
    L += ["## Views", "", "- [[80-views/decisions-and-plans.base|Decisions and plans]] · "
          "[[80-views/days-and-reviews.base|Days and reviews]]", ""]
    return Note("home.md", "Home", "\n".join(L), {"type": "home", "date": today.isoformat()})


def render(n, by_src):
    body = link_text(n.body, by_src)
    props = dict(n.props)
    return redact(front(n.front_lines, props) + body)


def cmd_sync(a):
    s = site()
    vault = s.get("vault")
    if not vault:
        sys.exit("site.json has no `vault` root — add the vault's path there")
    elak, reports = s.get("elak"), s.get("reports")
    env = a.env_file or s.get("env")
    today = datetime.date.today()
    enotes, by_all = elak_notes(elak)
    notes = report_notes(reports, today)
    vnotes, files = verify_notes(reports, s.get("helm_local_url"))
    notes += vnotes
    # elak's blueprint is the owner's to read (decisions, plans, status); a knowledge note enters only when a note he
    # reads cites it, one level deep, so the vault is not a second copy of ela's memory (decided 2026-10-23)
    # From elak, only what the owner decided or must decide (decisions, plans, sprints). Knowledge, the status table
    # and the working preferences are written for ela to read; a page that cites one shows its title as text.
    notes += [n for n in enotes if n.props["type"] in ("decision", "plan", "sprint")]
    kept = {id(n) for n in notes}
    by_src = {rel: n for rel, n in by_all.items() if id(n) in kept}
    TITLES.update({rel: n.title for rel, n in by_all.items()})
    JIRA_BASE[0] = next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "") if env else ""
    held = []
    passed = []
    for n in notes:
        p = reading_gate(n)
        (held.append((n, p)) if p else passed.append(n))
    notes = passed
    notes.append(home(today, notes, held))
    planned = {n.path: render(n, by_src) for n in notes}
    for name, text in VIEWS.items():
        planned[f"80-views/{slug(name)}.base"] = text
    # write only what changed; remove only what this script wrote before and no longer plans
    def fix_case(p):
        """On a case-insensitive disk a file written under a new capitalisation keeps its old name: rename it first."""
        d, name = os.path.split(p)
        for f in os.listdir(d):
            if f != name and f.lower() == name.lower():
                tmp = os.path.join(d, f + ".case")
                os.rename(os.path.join(d, f), tmp); os.rename(tmp, p)
                return
    try:
        old = set(json.load(open(os.path.join(vault, MANIFEST)))["files"])
    except (OSError, ValueError, KeyError):
        old = set()
    wrote, same, copied = [], 0, 0
    for rel, text in planned.items():
        p = os.path.join(vault, rel)
        try:
            if open(p, encoding="utf-8").read() == text and os.path.basename(p) in os.listdir(os.path.dirname(p)):
                same += 1; continue
        except OSError:
            pass
        wrote.append(rel)
        if not a.dry_run:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            fix_case(p)
            open(p, "w", encoding="utf-8").write(text)
    for src, rel in files:
        dst = os.path.join(vault, rel)
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
            continue
        copied += 1
        if not a.dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copyfile(src, dst)
    now_files = set(planned) | {rel for _, rel in files}
    # the vault sits on a case-insensitive disk: a rename that only changes case is the same file, never a removal
    lower = {r.lower() for r in now_files}
    gone = sorted(r for r in old - now_files if not r.startswith(".obsidian") and r.lower() not in lower)
    if not a.dry_run:
        for rel in gone:
            try:
                os.remove(os.path.join(vault, rel))
            except OSError:
                pass
        # folders this script emptied go too; a folder holding anything it did not write stays
        for d in sorted({os.path.dirname(r) for r in old if os.path.dirname(r)}, key=lambda x: -x.count("/")):
            parts = d.split("/")
            for i in range(len(parts), 0, -1):
                p = os.path.join(vault, *parts[:i])
                try:
                    os.rmdir(p)
                except OSError:
                    break
        json.dump({"synced": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "files": sorted(now_files)},
                  open(os.path.join(vault, MANIFEST), "w"), indent=0)
    r = {"dry_run": a.dry_run, "held": [{"note": n.path, "problems": p} for n, p in held], "notes": len(planned), "written": len(wrote), "unchanged": same, "files_copied": copied,
         "removed": gone}
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(f"{'DRY RUN — ' if a.dry_run else ''}vault: {r['notes']} notes ({r['written']} written, {same} unchanged), "
              f"{copied} files copied, {len(gone)} removed, {len(held)} held back")
        for g in gone[:20]:
            print(f"  removed {g}")
        for n, p in held:
            print(f"  held back {n.path}: {'; '.join(p)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="ela's env file (Jira credentials for the ticket notes)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync", help="regenerate the vault from elak, the reports root and Jira; --dry-run writes nothing")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sync)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
