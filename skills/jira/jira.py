#!/usr/bin/env python3
"""Jira capability — read, search, and gated writes. Stdlib only.

This is an L1 atomic capability: deterministic, no LLM, callable by anything
(a Claude session via the skill, Helm ops via subprocess, a future MCP server).
Credentials are site state resolved from the environment or an env file.

Usage:
    jira.py read MH-3454 [--deep] [--no-comments] [--json]
    jira.py files MH-3454 [--id <attachment id>] [--out DIR]   # a tester's screenshot, on disk
    jira.py read https://tvunetworks.atlassian.net/browse/MH-3454
    jira.py jql 'project=MH AND text ~ "CSC"' [--limit 50] [--json]
    jira.py create-subtask --parent MH-3513 --summary '[App] ...' \
            [--description TEXT] [--assignee EMAIL|ACCOUNTID] [--apply] [--json]
    jira.py comment MH-1 [MH-2 …] --text '…' | --from-file f   [--apply]   # identical text is never re-posted
    jira.py transition MH-1 [MH-2 …] --to Review               [--apply]   # transition looked up by target status
    jira.py label MH-1 [MH-2 …] --add a,b --remove c           [--apply]   # only the delta is written
    jira.py link MH-1 MH-2 --type Blocks|"is blocked by"|Relates [--apply]  # existing link of that type is a no-op
    jira.py fixed-in MH-1 [MH-2 …] --add 'slug@1.2.3; slug2@4.5.6' [--apply]  # append-only; present entries skipped

Writes are dry-run by default; --apply performs the create. Safety gates
(title token vocabulary, duplicate detection) live here and cannot be
bypassed by any caller. Confirmation UX belongs to the caller.

Exit codes: 0 ok (including idempotent "already exists"), 1 API/transport
error, 2 validation error.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))

ENV_KEYS = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_TOKEN")

# Closed vocabulary — one token, one owning layer. A title that does not start
# with exactly one of these is invalid; no caller may create it.
LAYER_TOKENS = ("[Infra]", "[J2N]", "[Media]", "[App]", "[UI]", "[QA]", "[Design]")

# The MH "Fixed In" field (map/release.yaml fixed_in.field). Its value is a
# '; '-separated union of <slug>@<version> entries, append-only by convention:
# an older entry stays when a newer build is added, so no atom removes one.
FIXED_IN_FIELD = "customfield_11252"
FIXED_IN_ENTRY = re.compile(r"^[a-z0-9][a-z0-9-]*@[0-9A-Za-z][0-9A-Za-z.+:_-]*$")


def load_env(env_file):
    """Resolve credentials: process env wins, then the env file."""
    creds = {k: os.environ.get(k) for k in ENV_KEYS}
    path = env_file or os.environ.get("JIRA_ENV_FILE") or os.environ.get("ELA_ENV_FILE")
    if path and not all(creds.values()):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    if k in ENV_KEYS and not creds.get(k):
                        creds[k] = v.strip().strip('"').strip("'")
        except OSError as exc:
            sys.exit(f"cannot read env file {path}: {exc}")
    missing = [k for k in ENV_KEYS if not creds.get(k)]
    if missing:
        sys.exit(
            "missing credentials: " + ", ".join(missing) +
            "\nSet them in the environment, or pass --env-file / $JIRA_ENV_FILE."
        )
    creds["JIRA_BASE_URL"] = creds["JIRA_BASE_URL"].rstrip("/")
    return creds


def _request(creds, path, params=None, payload=None, method="GET"):
    url = creds["JIRA_BASE_URL"] + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = base64.b64encode(
        f'{creds["JIRA_EMAIL"]}:{creds["JIRA_TOKEN"]}'.encode()
    ).decode()
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        sys.exit(f"jira {method} {path} failed: HTTP {exc.code} {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"jira {method} {path} failed: {exc}")


def api_get(creds, path, params=None):
    return _request(creds, path, params=params)


def api_post(creds, path, payload):
    return _request(creds, path, payload=payload, method="POST")


# ── ADF rendering ─────────────────────────────────────────────────────────────

def adf_to_text(adf, indent=0):
    """Render Atlassian Document Format to readable plain text."""
    if not adf or not isinstance(adf, dict):
        return ""
    out = []

    def walk(node, depth, prefix=""):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        kids = node.get("content") or []

        if t == "text":
            text = node.get("text", "")
            for mark in node.get("marks") or []:
                if mark.get("type") == "code":
                    text = f"`{text}`"
                elif mark.get("type") == "link":
                    href = (mark.get("attrs") or {}).get("href", "")
                    if href and href != text:
                        text = f"{text} <{href}>"
            out.append(text)
            return
        if t == "hardBreak":
            out.append("\n" + "  " * depth)
            return
        if t == "mention":
            out.append("@" + (node.get("attrs") or {}).get("text", "?").lstrip("@"))
            return
        if t == "emoji":
            out.append((node.get("attrs") or {}).get("text", ""))
            return
        if t == "inlineCard":
            out.append((node.get("attrs") or {}).get("url", ""))
            return
        if t == "rule":
            out.append("\n" + "-" * 40 + "\n")
            return
        if t == "codeBlock":
            lang = (node.get("attrs") or {}).get("language", "")
            out.append(f"\n```{lang}\n")
            for k in kids:
                walk(k, depth)
            out.append("\n```\n")
            return
        if t == "heading":
            level = (node.get("attrs") or {}).get("level", 1)
            out.append("\n" + "#" * level + " ")
            for k in kids:
                walk(k, depth)
            out.append("\n")
            return
        if t == "paragraph":
            out.append("  " * depth + prefix)
            for k in kids:
                walk(k, depth)
            out.append("\n")
            return
        if t in ("bulletList", "orderedList"):
            for i, k in enumerate(kids, 1):
                mark = "- " if t == "bulletList" else f"{i}. "
                walk(k, depth, mark)
            return
        if t == "listItem":
            first = True
            for k in kids:
                walk(k, depth + 1, prefix if first else "")
                first = False
            return
        if t == "blockquote":
            out.append("> ")
            for k in kids:
                walk(k, depth)
            return
        if t in ("table",):
            out.append("\n")
            for k in kids:
                walk(k, depth)
            return
        if t == "tableRow":
            cells = []
            for cell in kids:
                sub = []
                _collect_text(cell, sub)
                cells.append(" ".join("".join(sub).split()))
            out.append("| " + " | ".join(cells) + " |\n")
            return
        if t == "mediaSingle" or t == "mediaGroup" or t == "media":
            attrs = node.get("attrs") or {}
            name = attrs.get("alt") or attrs.get("id") or "attachment"
            if t == "media":
                out.append(f"[media: {name}]\n")
                return
        for k in kids:
            walk(k, depth)

    def _collect_text(node, acc):
        if not isinstance(node, dict):
            return
        if node.get("type") == "text":
            acc.append(node.get("text", ""))
        for k in node.get("content") or []:
            _collect_text(k, acc)

    for node in adf.get("content") or []:
        walk(node, indent)
    text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def body_text(field):
    """A description/comment field is ADF (v3) or plain string (v2)."""
    if isinstance(field, str):
        return field.strip()
    return adf_to_text(field)


# ── people (the published roster, through the team capability) ───────────────

_TEAM, _PEOPLE = None, None


def roster_people():
    """The published roster via skills/team; [] when this site has none — a mention then refuses, never guesses."""
    global _TEAM, _PEOPLE
    if _PEOPLE is None:
        try:
            sys.path.insert(0, os.path.join(HERE, "..", "team"))
            import team as T
            _TEAM, _PEOPLE = T, T.read_roster()[1]
        except (SystemExit, Exception):
            _TEAM, _PEOPLE = None, []
    return _PEOPLE


def person_area(display_name):
    """The roster area of a Jira display name ('' when unknown) — the sign-off check reads it, nothing else."""
    dn = (display_name or "").strip().lower()
    for p in roster_people():
        if dn and dn in {(p.get("name") or "").lower(), (p.get("jira_name") or "").lower()}:
            return p.get("area") or ""
    return ""


MENTION_RX = re.compile(r"(?<![\w@/.:])@([A-Za-z][A-Za-z0-9._-]{1,30})")


def resolve_mentions(text):
    """`@name` tokens → {name: (accountId, display name)} through the roster. A name the roster cannot settle to
    exactly one person with a Jira id is returned apart; the caller refuses rather than post a bare '@name',
    because a plain-text name notifies nobody (published people/roster.md: a person not listed is unknown)."""
    found, unresolved = {}, []
    people = roster_people()
    for m in MENTION_RX.finditer(text or ""):
        name = m.group(1)
        if name in found or name in unresolved:
            continue
        hits = [p for p in (_TEAM.find(people, name) if (_TEAM and people) else []) if p.get("jira")]
        if len(hits) == 1:
            found[name] = (hits[0]["jira"], hits[0]["name"])
        else:
            unresolved.append(name)
    return found, unresolved


def _inline(line, mentions):
    nodes, pos = [], 0
    for m in MENTION_RX.finditer(line):
        if m.group(1) not in mentions:
            continue
        if m.start() > pos:
            nodes.append({"type": "text", "text": line[pos:m.start()]})
        aid, disp = mentions[m.group(1)]
        nodes.append({"type": "mention", "attrs": {"id": aid, "text": "@" + disp}})
        pos = m.end()
        # `@Erin Zhang`: the rest of the display name typed after the token is the same person, not more text
        rest = disp.lower().split()[1:]
        tail = line[pos:]
        for word in rest:
            tm = re.match(r"\s+(" + re.escape(word) + r")\b", tail, re.I)
            if not tm:
                break
            pos += tm.end(); tail = line[pos:]
    if pos < len(line):
        nodes.append({"type": "text", "text": line[pos:]})
    return nodes or [{"type": "text", "text": line}]


DETAIL_RX = re.compile(r"^-{3,}\s*(.*?)\s*-*$")


def apply_mentions(node, mentions):
    """Replace `@name` inside every text node of an ADF tree with a mention node (in place)."""
    if not mentions or not isinstance(node, dict):
        return node
    kids = node.get("content")
    if isinstance(kids, list):
        out = []
        for k in kids:
            if isinstance(k, dict) and k.get("type") == "text" and MENTION_RX.search(k.get("text") or ""):
                for n in _inline(k["text"], mentions):
                    if n["type"] == "text" and k.get("marks"):
                        n = dict(n, marks=k["marks"])
                    out.append(n)
            else:
                out.append(apply_mentions(k, mentions))
        node["content"] = out
    return node


def comment_to_adf(text, mentions=None):
    """A comment: the Markdown subset (bold, code, bullets, numbered lists, headings) above and inside the
    `---` fold, with `@name` as mention nodes — one renderer for comment and close."""
    return apply_mentions(markdown_to_adf(text), mentions or {})


def text_to_adf(text, mentions=None, detail=False):
    """Plain text → ADF, one paragraph per non-empty line.
    `mentions` ({name: (accountId, display)}) turns `@name` into a real mention node.
    With `detail`, a line of three or more dashes starts a collapsed block that holds everything after it — the
    words on that line are its title (default 'Technical detail'). The short part is what a person reads; the
    block is what an agent or an investigator opens. Two registers, one comment."""
    mentions, top, rest, title, inside = mentions or {}, [], [], "Technical detail", False
    for line in (text or "").splitlines():
        m = DETAIL_RX.match(line.strip()) if detail else None
        if m and not inside:
            inside, title = True, (m.group(1).strip() or title)
            continue
        if not line.strip():
            continue
        (rest if inside else top).append({"type": "paragraph", "content": _inline(line, mentions)})
    if rest:
        top.append({"type": "expand", "attrs": {"title": title}, "content": rest})
    return {"type": "doc", "version": 1, "content": top or [{"type": "paragraph"}]}


MARK_RX = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
HEADING_RX = re.compile(r"^(#{1,3})\s+(.*)$")
BULLET_RX = re.compile(r"^[-*]\s+(.*)$")
NUMBERED_RX = re.compile(r"^\d+\.\s+(.*)$")


def _marked(line):
    """`**bold**` and `` `code` `` as ADF marks; everything else is plain text."""
    nodes = []
    for part in MARK_RX.split(line):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            nodes.append({"type": "text", "text": part[2:-2], "marks": [{"type": "strong"}]})
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            nodes.append({"type": "text", "text": part[1:-1], "marks": [{"type": "code"}]})
        else:
            nodes.append({"type": "text", "text": part})
    return nodes or [{"type": "text", "text": line}]


def _md_blocks(lines):
    blocks, lst = [], None
    for line in lines:
        s = line.strip()
        if not s:
            lst = None
            continue
        h, b, n = HEADING_RX.match(s), BULLET_RX.match(s), NUMBERED_RX.match(s)
        if h:
            lst = None
            blocks.append({"type": "heading", "attrs": {"level": len(h.group(1))}, "content": _marked(h.group(2))})
        elif b or n:
            kind = "bulletList" if b else "orderedList"
            if not lst or lst["type"] != kind:
                lst = {"type": kind, "content": []}
                blocks.append(lst)
            item = (b or n).group(1)
            lst["content"].append({"type": "listItem", "content": [{"type": "paragraph", "content": _marked(item)}]})
        else:
            lst = None
            blocks.append({"type": "paragraph", "content": _marked(line)})
    return blocks


def markdown_to_adf(text):
    """A ticket description in a Markdown subset → ADF: `#`..`###` headings, `- `/`* ` bullets, `1. ` numbered
    lists, `**bold**`, `` `code` ``. A line of three or more dashes folds everything after it into a collapsed
    block titled by the words on that line (default 'Technical detail'), as in a comment. A line with none of
    these is a plain paragraph, exactly as `text_to_adf` renders it, so a plain-text description is unchanged."""
    top, rest, title, inside = [], [], "Technical detail", False
    for line in (text or "").splitlines():
        m = DETAIL_RX.match(line.strip())
        if m and not inside:
            inside, title = True, (m.group(1).strip() or title)
            continue
        (rest if inside else top).append(line)
    content, folded = _md_blocks(top), _md_blocks(rest)
    if folded:
        content.append({"type": "expand", "attrs": {"title": title}, "content": folded})
    return {"type": "doc", "version": 1, "content": content or [{"type": "paragraph"}]}


# ── Rendering ────────────────────────────────────────────────────────────────

def name_of(obj, key="displayName"):
    return (obj or {}).get(key) or "—"


def short_date(s):
    return (s or "")[:16].replace("T", " ")


def fetch_comments(creds, key):
    cdata = api_get(creds, f"/rest/api/3/issue/{key}/comment",
                    {"maxResults": 100, "orderBy": "created"})
    return cdata.get("comments") or []


def print_issue(creds, key, deep=False, comments=True, seen=None):
    seen = seen if seen is not None else set()
    if key in seen:
        return
    seen.add(key)

    data = api_get(creds, f"/rest/api/3/issue/{key}", {
        "fields": "*all",
        "expand": "renderedFields",
    })
    f = data.get("fields") or {}

    print("=" * 78)
    print(f"{data.get('key')}  {f.get('summary', '')}")
    print("=" * 78)
    print(f"url        {creds['JIRA_BASE_URL']}/browse/{data.get('key')}")
    print(f"type       {name_of(f.get('issuetype'), 'name')}"
          f"    status  {name_of(f.get('status'), 'name')}"
          f"    priority  {name_of(f.get('priority'), 'name')}")
    print(f"assignee   {name_of(f.get('assignee'))}"
          f"    reporter  {name_of(f.get('reporter'))}")
    print(f"created    {short_date(f.get('created'))}"
          f"    updated  {short_date(f.get('updated'))}")
    if f.get("resolution"):
        print(f"resolution {name_of(f.get('resolution'), 'name')}"
              f"    at  {short_date(f.get('resolutiondate'))}")
    if f.get("labels"):
        print(f"labels     {', '.join(f['labels'])}")
    if f.get("components"):
        print(f"components {', '.join(c.get('name', '') for c in f['components'])}")
    if f.get("fixVersions"):
        print(f"fixVersions {', '.join(v.get('name', '') for v in f['fixVersions'])}")
    if f.get("parent"):
        p = f["parent"]
        print(f"parent     {p.get('key')}  {(p.get('fields') or {}).get('summary', '')}")

    desc = body_text(f.get("description"))
    print("\n--- description ---")
    print(desc if desc else "(empty)")

    links = f.get("issuelinks") or []
    if links:
        print("\n--- links ---")
        for l in links:
            if l.get("outwardIssue"):
                rel = (l.get("type") or {}).get("outward", "relates to")
                other = l["outwardIssue"]
            elif l.get("inwardIssue"):
                rel = (l.get("type") or {}).get("inward", "relates to")
                other = l["inwardIssue"]
            else:
                continue
            of = other.get("fields") or {}
            print(f"  {rel:<22} {other.get('key'):<10} "
                  f"[{name_of(of.get('status'), 'name')}] {of.get('summary', '')}")

    subs = f.get("subtasks") or []
    if subs:
        print("\n--- subtasks ---")
        for s in subs:
            sf = s.get("fields") or {}
            print(f"  {s.get('key'):<10} [{name_of(sf.get('status'), 'name')}] "
                  f"{sf.get('summary', '')}")

    atts = f.get("attachment") or []
    if atts:
        print("\n--- attachments ---")
        for a in atts:
            print(f"  {a.get('id'):<10} {a.get('filename')}  ({a.get('size')} B, "
                  f"{short_date(a.get('created'))}, {name_of(a.get('author'))})")
        print(f"  # download: jira.py files {key} [--id <id>] [--out DIR]")

    if comments:
        cs = fetch_comments(creds, key)
        print(f"\n--- comments ({len(cs)}) ---")
        for c in cs:
            print(f"\n[{short_date(c.get('created'))}] {name_of(c.get('author'))}")
            print(body_text(c.get("body")) or "(empty)")
    print()

    if deep:
        related = []
        for l in links:
            other = l.get("outwardIssue") or l.get("inwardIssue")
            if other:
                related.append(other.get("key"))
        related += [s.get("key") for s in subs]
        if f.get("parent"):
            related.append(f["parent"].get("key"))
        for k in related:
            if k and k not in seen:
                print_issue(creds, k, deep=False, comments=comments, seen=seen)


# ── Subcommands ──────────────────────────────────────────────────────────────

def extract_key(target):
    m = re.search(r"([A-Z][A-Z0-9]+-\d+)", target.upper())
    if not m:
        sys.exit(f"cannot find an issue key in {target!r}")
    return m.group(1)


def default_out_dir():
    """Downloads are working state: <runtime> when the site names one, and nothing there is a record."""
    try:
        with open(os.path.expanduser("~/.claude/ela/site.json")) as fh:
            s = json.load(fh)
        root = s.get("runtime") or (s.get("projects") and os.path.join(s["projects"], ".ela"))
        if root:
            return os.path.join(root, "jira-files")
    except (OSError, ValueError):
        pass
    return os.path.join(os.getcwd(), "jira-files")


def cmd_files(creds, args):
    """Download an issue's attachments. A tester's screenshot is usually the whole evidence, and a
    filename in a list is not evidence. Writes to disk only; nothing is sent anywhere."""
    key = extract_key(args.target)
    data = api_get(creds, f"/rest/api/3/issue/{key}", {"fields": "attachment"})
    atts = ((data.get("fields") or {}).get("attachment")) or []
    if args.id:
        atts = [a for a in atts if str(a.get("id")) == str(args.id)]
    out = os.path.abspath(args.out or default_out_dir())
    os.makedirs(out, exist_ok=True)
    token = base64.b64encode(f'{creds["JIRA_EMAIL"]}:{creds["JIRA_TOKEN"]}'.encode()).decode()
    got, skipped = [], []
    for a in atts:
        url = a.get("content")
        if not url:
            skipped.append({"id": a.get("id"), "filename": a.get("filename"), "why": "no content url"}); continue
        name = f"{a.get('id')}-{re.sub(r'[^A-Za-z0-9._-]+', '_', a.get('filename') or 'file')}"
        path = os.path.join(out, name)
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            skipped.append({"id": a.get("id"), "filename": a.get("filename"), "why": repr(exc)}); continue
        got.append({"id": a.get("id"), "filename": a.get("filename"), "mime": a.get("mimeType"),
                    "bytes": os.path.getsize(path), "path": path, "author": name_of(a.get("author")),
                    "created": a.get("created")})
    if args.json:
        print(json.dumps({"key": key, "out": out, "count": len(got), "files": got, "skipped": skipped},
                         ensure_ascii=False))
        return
    for g in got:
        print(f"{g['path']}  ({g['mime']}, {g['bytes']} B, by {g['author']})")
    for s in skipped:
        print(f"skipped {s['filename']}: {s['why']}", file=sys.stderr)
    if not got:
        print(f"{key} has no attachment" + (f" with id {args.id}" if args.id else ""), file=sys.stderr)
        sys.exit(2 if not skipped else 1)


def cmd_read(creds, args):
    key = extract_key(args.target)
    if args.json:
        data = api_get(creds, f"/rest/api/3/issue/{key}", {"fields": "*all"})
        out = {
            "key": data.get("key"),
            "url": f"{creds['JIRA_BASE_URL']}/browse/{data.get('key')}",
            "fields": data.get("fields") or {},
        }
        if not args.no_comments:
            out["comments"] = fetch_comments(creds, key)
        print(json.dumps(out, ensure_ascii=False))
        return
    print_issue(creds, key, deep=args.deep, comments=not args.no_comments)


def cmd_jql(creds, args):
    # /search/jql pages at 100; follow nextPageToken until --limit rows or the last page.
    issues, token = [], None
    while len(issues) < args.limit:
        params = {
            "jql": args.jql,
            "maxResults": min(100, args.limit - len(issues)),
            "fields": "summary,status,assignee,reporter,issuetype,priority,labels,parent,subtasks,created,updated",
        }
        if token:
            params["nextPageToken"] = token
        data = api_get(creds, "/rest/api/3/search/jql", params)
        issues += data.get("issues") or []
        token = data.get("nextPageToken")
        if not token or data.get("isLast"):
            break
    if args.json:
        rows = [{
            "key": i.get("key"),
            "summary": (i.get("fields") or {}).get("summary", ""),
            "status": name_of((i.get("fields") or {}).get("status"), "name"),
            "assignee": name_of((i.get("fields") or {}).get("assignee")),
            "reporter": name_of((i.get("fields") or {}).get("reporter")),
            "type": name_of((i.get("fields") or {}).get("issuetype"), "name"),
            "priority": name_of((i.get("fields") or {}).get("priority"), "name"),
            "labels": (i.get("fields") or {}).get("labels") or [],
            "parent": ((i.get("fields") or {}).get("parent") or {}).get("key"),
            "subtasks": len((i.get("fields") or {}).get("subtasks") or []),
            "created": (i.get("fields") or {}).get("created"),
            "updated": (i.get("fields") or {}).get("updated"),
        } for i in issues]
        print(json.dumps({"jql": args.jql, "count": len(rows), "issues": rows},
                         ensure_ascii=False))
        return
    print(f"# {len(issues)} issue(s) for: {args.jql}\n")
    for i in issues:
        f = i.get("fields") or {}
        print(f"{i.get('key'):<10} [{name_of(f.get('status'), 'name'):<12}] "
              f"{name_of(f.get('assignee')):<16} {f.get('summary', '')}")


def validate_summary(summary):
    """The seven-token gate: '[Token] action', no dash separator, one token."""
    token = next((t for t in LAYER_TOKENS if summary.startswith(t)), None)
    if token is None:
        return (f"title must start with one of {' '.join(LAYER_TOKENS)}; "
                f"got {summary!r}")
    rest = summary[len(token):]
    if not rest.startswith(" ") or not rest[1:].strip():
        return f"expected '{token} <action>' with a single space; got {summary!r}"
    if re.match(r"^\s*[—–-]+\s", rest[1:]):
        return (f"dash separator after the token is deprecated; "
                f"write '{token} <action>': {summary!r}")
    return None


def _norm(s):
    return " ".join((s or "").split()).casefold()


def resolve_assignee(creds, who):
    """Email or accountId → accountId; without either, the token's own account."""
    if not who or who.lower() == "me":
        me = api_get(creds, "/rest/api/3/myself")
        return me["accountId"], f"{me.get('displayName')} (self)"
    if "@" not in who:
        # Jira hides most users' email addresses; an accountId works directly.
        u = api_get(creds, "/rest/api/3/user", {"accountId": who})
        return u["accountId"], u.get("displayName", who)
    users = api_get(creds, "/rest/api/3/user/search", {"query": who})
    hits = [u for u in users
            if (u.get("emailAddress") or "").casefold() == who.casefold()]
    if len(hits) != 1:
        print(f"assignee {who!r}: {len(hits)} exact match(es) "
              f"among {len(users)} result(s) — not resolved; "
              f"pass the accountId instead", file=sys.stderr)
        sys.exit(2)
    return hits[0]["accountId"], hits[0].get("displayName", who)


def cmd_assign(creds, args):
    """Re-assign one issue. Idempotent; dry-run default."""
    key = extract_key(args.target)
    data = api_get(creds, f"/rest/api/3/issue/{key}",
                   {"fields": "summary,assignee,status"})
    f = data.get("fields") or {}
    cur = f.get("assignee") or {}
    account_id, assignee_name = resolve_assignee(creds, args.assignee)
    result = {"key": key, "summary": f.get("summary"),
              "from": cur.get("displayName"), "to": assignee_name,
              "dry_run": not args.apply, "changed": False}
    if cur.get("accountId") == account_id:
        if args.json: print(json.dumps(result, ensure_ascii=False))
        else: print(f"{key} already assigned to {assignee_name}")
        return
    if not args.apply:
        if args.json: print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"DRY RUN — {key}  {f.get('summary','')}")
            print(f"  assignee  {cur.get('displayName') or 'Unassigned'} -> {assignee_name}")
            print("pass --apply to re-assign")
        return
    _request(creds, f"/rest/api/3/issue/{key}/assignee",
             payload={"accountId": account_id}, method="PUT")
    result["changed"] = True
    if args.json: print(json.dumps(result, ensure_ascii=False))
    else: print(f"{key} assigned: {cur.get('displayName') or 'Unassigned'} -> {assignee_name}")


def cmd_create(creds, args):
    """Create a parent-level issue. No layer-token requirement — tokens mark
    single-layer subtasks; a parent carries the cross-layer scope."""
    result = {
        "project": args.project,
        "type": args.type,
        "summary": args.summary,
        "dry_run": not args.apply,
        "created": False,
        "key": None,
        "url": None,
        "duplicate_of": None,
    }
    if not args.summary.strip():
        print("summary must not be empty", file=sys.stderr)
        sys.exit(2)

    # Idempotency: an open issue in the project with the same normalized
    # summary is the same request.
    want = _norm(args.summary)
    quoted = args.summary.replace('"', '\\"')
    data = api_get(creds, "/rest/api/3/search/jql", {
        "jql": (f'project = {args.project} AND statusCategory != Done '
                f'AND summary ~ "\\"{quoted}\\"" ORDER BY created DESC'),
        "maxResults": 20, "fields": "summary",
    })
    for i in data.get("issues") or []:
        if _norm((i.get("fields") or {}).get("summary")) == want:
            result["duplicate_of"] = i.get("key")
            result["url"] = f"{creds['JIRA_BASE_URL']}/browse/{i.get('key')}"
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"already exists: {i.get('key')}  {result['url']}")
            return

    account_id, assignee_name = resolve_assignee(creds, args.assignee)
    result["assignee"] = assignee_name

    if not args.apply:
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"DRY RUN — would create in {args.project}:")
            print(f"  type      {args.type}")
            print(f"  summary   {args.summary}")
            print(f"  assignee  {assignee_name}")
            if args.description:
                print(f"  description  {len(args.description)} chars")
            print("pass --apply to create")
        return

    fields = {
        "project": {"key": args.project},
        "issuetype": {"name": args.type},
        "summary": args.summary,
        "assignee": {"accountId": account_id},
    }
    if args.description:
        fields["description"] = markdown_to_adf(args.description)
    resp = api_post(creds, "/rest/api/3/issue", {"fields": fields})
    result["created"] = True
    result["key"] = resp.get("key")
    result["url"] = f"{creds['JIRA_BASE_URL']}/browse/{resp.get('key')}"
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"created {result['key']}  {result['url']}  → {assignee_name}")


def cmd_create_subtask(creds, args):
    result = {
        "parent": args.parent.upper(),
        "summary": args.summary,
        "dry_run": not args.apply,
        "created": False,
        "key": None,
        "url": None,
        "duplicate_of": None,
    }

    err = validate_summary(args.summary)
    if err:
        print(f"invalid title: {err}", file=sys.stderr)
        sys.exit(2)

    parent = api_get(creds, f"/rest/api/3/issue/{result['parent']}",
                     {"fields": "summary,project,issuetype,subtasks"})
    pf = parent.get("fields") or {}
    if (pf.get("issuetype") or {}).get("subtask"):
        print(f"{result['parent']} is itself a subtask — cannot parent another",
              file=sys.stderr)
        sys.exit(2)
    project_key = (pf.get("project") or {}).get("key")

    # Idempotency: an existing subtask with the same (normalized) title is the
    # same request — report it and succeed without creating a twin.
    want = _norm(args.summary)
    for s in pf.get("subtasks") or []:
        have = _norm((s.get("fields") or {}).get("summary"))
        if have == want:
            result["duplicate_of"] = s.get("key")
            result["url"] = f"{creds['JIRA_BASE_URL']}/browse/{s.get('key')}"
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"already exists: {s.get('key')}  {result['url']}")
            return

    account_id, assignee_name = resolve_assignee(creds, args.assignee)
    result["assignee"] = assignee_name

    if not args.apply:
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"DRY RUN — would create under {result['parent']} "
                  f"({pf.get('summary', '')}):")
            print(f"  project   {project_key}")
            print(f"  type      {args.issuetype}")
            print(f"  summary   {args.summary}")
            print(f"  assignee  {assignee_name}")
            if args.description:
                print(f"  description  {len(args.description)} chars")
            print("pass --apply to create")
        return

    fields = {
        "project": {"key": project_key},
        "parent": {"key": result["parent"]},
        "issuetype": {"name": args.issuetype},
        "summary": args.summary,
        "assignee": {"accountId": account_id},
    }
    if args.description:
        fields["description"] = markdown_to_adf(args.description)
    resp = api_post(creds, "/rest/api/3/issue", {"fields": fields})
    result["created"] = True
    result["key"] = resp.get("key")
    result["url"] = f"{creds['JIRA_BASE_URL']}/browse/{resp.get('key')}"
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"created {result['key']}  {result['url']}  → {assignee_name}")


# ── write atoms: comment · transition · label · link ─────────────────────────
# Every atom: dry-run by default, --apply to execute, idempotent (a repeat is a
# no-op that says so), one JSON result shape. Confirmation UX is the caller's.

def _keys(targets):
    return [extract_key(t) for t in targets]


def _issue(creds, key, fields):
    return api_get(creds, f"/rest/api/3/issue/{key}", {"fields": fields}).get("fields") or {}


def _emit(args, result, text_lines):
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for line in text_lines:
            print(line)


def _read_text(args):
    text = getattr(args, "text", None)
    if getattr(args, "from_file", None):
        with open(args.from_file, encoding="utf-8") as fh:
            text = fh.read().rstrip("\n")
    return text or ""


def participant_mentions(creds, key, names, comments=None):
    """`@name` tokens the roster could not settle, looked up among the issue's own participants — assignee, reporter
    and every comment author — whose account ids Jira already shows. A name is taken only when it matches exactly one
    participant (whole display name, or its first word, case-insensitive); two matches stay unresolved, because the
    wrong person notified is worse than none. The roster stays the rule; this is the ticket itself supplying the id
    the roster lacks (2026-10-21, MH-2519: the scheduler service's owner had no Jira id on file)."""
    found, left = {}, []
    try:
        issue = api_get(creds, f"/rest/api/3/issue/{key}", {"fields": "assignee,reporter"})
    except Exception:
        issue = {}
    f = issue.get("fields") or {}
    people = {}
    for u in [f.get("assignee"), f.get("reporter")] + [c.get("author") for c in (comments if comments is not None else fetch_comments(creds, key))]:
        if u and u.get("accountId") and u.get("displayName"):
            people[u["accountId"]] = u["displayName"]
    for name in names:
        n = name.strip().lower()
        hits = {aid: d for aid, d in people.items() if d.lower() == n or d.lower().split()[0] == n}
        if len(hits) == 1:
            (aid, disp), = hits.items()
            found[name] = (aid, disp)
        else:
            left.append(name)
    return found, left


def _comment_one(creds, key, text, apply, mention=True, edit=None):
    """Post one comment to one issue. Idempotent on identical rendered text; `@name` resolved through the roster,
    then among the issue's own participants."""
    mentions, unresolved = resolve_mentions(text) if mention else ({}, [])
    existing = fetch_comments(creds, key)
    from_ticket = {}
    if unresolved:
        from_ticket, unresolved = participant_mentions(creds, key, unresolved, existing)
        mentions.update(from_ticket)
    if unresolved:
        return ({"key": key, "error": "unresolved mention(s): " + ", ".join("@" + u for u in unresolved)},
                [f"{key}: @{', @'.join(unresolved)} is not one person with a Jira id in the roster, nor one participant "
                 f"of {key} — add them to elak people.yaml and `ela publish roster`, or write the name without @"])
    adf = comment_to_adf(text, mentions)
    rendered = body_text(adf)
    r = {"key": key, "dry_run": not apply, "posted": False, "duplicate_of": None, "chars": len(text), "edit": edit,
         "mentions": [d for _, d in mentions.values()], "mentions_from_ticket": [d for _, d in from_ticket.values()],
         "detail": any(n.get("type") == "expand" for n in adf["content"])}
    if edit:
        old = next((c for c in existing if str(c.get("id")) == str(edit)), None)
        if not old:
            return dict(r, error=f"no comment {edit} on {key}"), [f"{key}: no comment with id {edit}"]
        before = body_text(old.get("body"))
        if _norm(before) == _norm(rendered):
            return r, [f"{key}: comment {edit} already reads so — skipped"]
        if not apply:
            return r, [f"DRY RUN — edit comment {edit} on {key} ({name_of(old.get('author'))}, {(old.get('created') or '')[:16]}):",
                       "  was: " + before.replace("\n", "\n       "), "  now: " + rendered.replace("\n", "\n       ")]
        _request(creds, f"/rest/api/3/issue/{key}/comment/{edit}", payload={"body": adf}, method="PUT")
        r["posted"], r["comment_id"] = True, edit
        return r, [f"{key}: comment {edit} edited"]
    dup = next((c for c in existing if _norm(body_text(c.get("body"))) == _norm(rendered)), None)
    r["duplicate_of"] = (dup or {}).get("id")
    if dup:
        return r, [f"{key}: identical comment already posted ({(dup.get('created') or '')[:16]}) — skipped"]
    if not apply:
        shown = rendered.replace("\n", "\n  ")
        return r, [f"DRY RUN — comment on {key} ({len(text)} chars"
                   + (f", mentions {', '.join(r['mentions'])}" if r["mentions"] else "")
                   + (f" ({', '.join(r['mentions_from_ticket'])} resolved from the ticket's participants, not the roster)" if r["mentions_from_ticket"] else "")
                   + (", technical detail collapsed" if r["detail"] else "") + "):", "  " + shown]
    resp = api_post(creds, f"/rest/api/3/issue/{key}/comment", {"body": adf})
    r["posted"], r["comment_id"] = True, resp.get("id")
    return r, [f"{key}: comment posted (id {resp.get('id')})"]


def cmd_comment(creds, args):
    """Post one comment to one or more issues. Idempotent on identical text."""
    text = _read_text(args)
    if not text.strip():
        sys.exit("comment: empty text")
    results, lines = [], []
    for key in _keys(args.targets):
        r, ls = _comment_one(creds, key, text, args.apply, mention=not args.no_mention, edit=args.edit)
        results.append(r); lines += ls
    if any("error" in r for r in results):
        _emit(args, {"results": results} if len(results) > 1 else results[0], lines); sys.exit(2)
    if not args.apply and any(not r["duplicate_of"] and not r.get("posted") for r in results):
        lines.append("pass --apply to post")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


# ── transitions: one hop looked up live, or the lifecycle walked hop by hop ───

STATUS_PATH = ["Backlog", "In Progress", "Review", "Done"]
# A terminal status is the owner's own click in Jira. ela proposes a close (Fixed In, comment, flag:closing, the
# ticket assigned to him) and never performs the transition — so a close he does not know about cannot happen
# (conventions.md section Clean-up rules, 2026-10-21).
TERMINAL = {"Done", "Cancelled", "Failed", "Closed Ambigous"}


def terminal(to):
    return _norm(to) in {_norm(x) for x in TERMINAL}
CLOSING_FLAG = "flag:closing"   # a close announced, waiting out its objection window (conventions.md § Clean-up rules)   # the MH lifecycle (published mediahub/jira/status-spec.md)


def plan_path(cur, to):
    """The statuses from `cur` to `to` along the MH lifecycle, inclusive; None when either is off the path or `to`
    lies behind `cur`. Jira exposes only the current status's transitions, so a plan is walked live, one hop at a
    time, and each hop is a write the assignee is notified of."""
    names = [_norm(s) for s in STATUS_PATH]
    try:
        i, j = names.index(_norm(cur)), names.index(_norm(to))
    except ValueError:
        return None
    return STATUS_PATH[i:j + 1] if j > i else None


def _transitions(creds, key):
    return api_get(creds, f"/rest/api/3/issue/{key}/transitions", {"expand": "transitions.fields"}).get("transitions") or []


def _hop(trans, to):
    hit = next((t for t in trans if _norm((t.get("to") or {}).get("name")) == _norm(to)), None)
    if not hit:
        return None, None
    required = sorted(n for n, fd in (hit.get("fields") or {}).items() if isinstance(fd, dict) and fd.get("required") and not fd.get("hasDefaultValue"))
    return hit, required


def _transition_one(creds, key, to, apply, path=False):
    """Move one issue to `to`. Direct when Jira offers it; with `path`, along STATUS_PATH hop by hop. Stops, without
    writing, at a hop that needs a field, and at Review → Done while the assignee is in the product area — that is
    the product sign-off the status spec describes, and it is theirs to give."""
    f = _issue(creds, key, "summary,status,assignee")
    cur = name_of(f.get("status"), "name")
    r = {"key": key, "from": cur, "to": to, "dry_run": not apply, "changed": False, "walked": []}
    if _norm(cur) == _norm(to):
        return r, [f"{key}: already {cur}"]
    if terminal(to):
        r["error"] = f"{to} is a terminal status: ela never performs that transition — propose it with `close` (the ticket is assigned to the owner, who clicks Done in Jira)"
        return r, [f"{key}: {r['error']}"]
    trans = _transitions(creds, key)
    hit, required = _hop(trans, to)
    hops = [to] if hit else None
    if not hit and path:
        plan = plan_path(cur, to) or (plan_path(cur, "Done") if _norm(to) not in {_norm(x) for x in STATUS_PATH} else None)
        if plan:
            hops = plan[1:]
            if _norm(hops[-1]) != _norm(to):
                hops.append(to)                  # walked toward Done until Jira offers the target (Cancelled, On Hold)
            hit, required = _hop(trans, hops[0])
    if not hit:
        opts = ", ".join(sorted({(t.get("to") or {}).get("name", "?") for t in trans}))
        r["error"] = f"no transition from {cur} to {to}; available: {opts}" + ("" if path or not plan_path(cur, to) else " (pass --path to walk the lifecycle)")
        return r, [f"{key}: {r['error']}"]
    assignee = name_of(f.get("assignee"))
    # The sign-off gate of status-spec.md is a ticket parked in Review for product; a Backlog or In Progress ticket that
    # happens to be assigned to product was never parked, so the walk to Done is not a sign-off skipped.
    signoff = _norm(cur) == _norm("Review") and _norm(hops[-1]) == _norm("Done") and person_area(assignee) == "product"
    if signoff:
        r["error"] = f"product sign-off pending: {assignee} holds {key} in Review, and Review → Done is theirs to give"
        return r, [f"{key}: {r['error']}"]
    if required:
        r["error"] = f"transition '{hit.get('name')}' needs fields {', '.join(required)} — not walked"
        return r, [f"{key}: {r['error']}"]
    r["transition"] = hit.get("name"); r["hops"] = hops
    if not apply:
        walk = " -> ".join([cur] + hops)
        note = "" if len(hops) == 1 else f"\n  ({len(hops)} hops: later ones looked up live; the assignee is notified at every hop)"
        return r, [f"DRY RUN — {key}  {f.get('summary','')}\n  status  {walk}  (transition '{hit.get('name')}' first){note}"]
    lines = []
    for n, h in enumerate(hops):
        if n:
            trans = _transitions(creds, key)
            early, early_req = _hop(trans, to)
            if early and _norm(h) != _norm(to):          # the target became reachable before the plan's end
                hit, required, h = early, early_req, to
            else:
                hit, required = _hop(trans, h)
            if not hit:
                r["error"] = f"no transition from {cur} to {h} (after {' -> '.join(r['walked'])})"
                return r, lines + [f"{key}: {r['error']}"]
            if required:
                r["error"] = f"transition '{hit.get('name')}' needs fields {', '.join(required)} — stopped at {cur}"
                return r, lines + [f"{key}: {r['error']}"]
        api_post(creds, f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": hit["id"]}})
        r["walked"].append(h); lines.append(f"{key}: {cur} -> {h}"); cur = h
        if _norm(h) == _norm(to):
            break
    r["changed"] = True
    return r, lines


def cmd_transition(creds, args):
    """Move issues to a target status by name; the transition is looked up, never guessed."""
    results, lines = [], []
    for key in _keys(args.targets):
        r, ls = _transition_one(creds, key, args.to, args.apply, path=args.path)
        results.append(r); lines += ls
    if not args.apply and any("hops" in r and not r["changed"] for r in results):
        lines.append("pass --apply to transition")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)
    if any("error" in r for r in results):
        sys.exit(2)


def _label_one(creds, key, add, rem, apply):
    f = _issue(creds, key, "summary,labels")
    cur = f.get("labels") or []
    to_add = [x for x in add if x not in cur]
    to_rem = [x for x in rem if x in cur]
    r = {"key": key, "labels": cur, "add": to_add, "remove": to_rem, "dry_run": not apply, "changed": False}
    if not to_add and not to_rem:
        return r, [f"{key}: labels already as requested ({' '.join(cur) or 'none'})"]
    if not apply:
        return r, [f"DRY RUN — {key}  {f.get('summary','')}\n  labels  {' '.join(cur) or '(none)'}"
                   + (f"\n  + {' '.join(to_add)}" if to_add else "") + (f"\n  - {' '.join(to_rem)}" if to_rem else "")]
    ops = [{"add": x} for x in to_add] + [{"remove": x} for x in to_rem]
    _request(creds, f"/rest/api/3/issue/{key}", payload={"update": {"labels": ops}}, method="PUT")
    r["changed"] = True
    return r, [f"{key}: labels " + " ".join((["+" + x for x in to_add] + ["-" + x for x in to_rem]))]


def _split_csv(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def cmd_label(creds, args):
    """Add and/or remove labels. Idempotent: only the actual delta is written."""
    add, rem = _split_csv(args.add), _split_csv(args.remove)
    if not add and not rem:
        sys.exit("label: nothing to do — pass --add and/or --remove")
    results, lines = [], []
    for key in _keys(args.targets):
        r, ls = _label_one(creds, key, add, rem, args.apply)
        results.append(r); lines += ls
    if not args.apply and any(r["add"] or r["remove"] for r in results):
        lines.append("pass --apply to change labels")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


def _link_types(creds):
    return api_get(creds, "/rest/api/3/issueLinkType").get("issueLinkTypes") or []


def _resolve_link(creds, phrase):
    """'Blocks' | 'blocks' | 'is blocked by' | 'relates to' | 'contains' … → (type name, direction).
    direction 'outward' means <key> <outward phrase> <other>; 'inward' the reverse."""
    for t in _link_types(creds):
        if _norm(phrase) == _norm(t["name"]) or _norm(phrase) == _norm(t["outward"]):
            return t, "outward"
        if _norm(phrase) == _norm(t["inward"]):
            return t, "inward"
    names = ", ".join(f"{t['name']} ({t['outward']} / {t['inward']})" for t in _link_types(creds) if "WBSGantt" not in t["name"])
    sys.exit(f"link: unknown type or phrase {phrase!r}; use one of: {names}")


def cmd_link(creds, args):
    """Link <key> to <other>: '<key> <phrase> <other>'. Idempotent per (type, pair)."""
    key, other = extract_key(args.target), extract_key(args.other)
    t, direction = _resolve_link(creds, args.type)
    f = _issue(creds, key, "summary,issuelinks")
    exists = None
    for l in f.get("issuelinks") or []:
        if (l.get("type") or {}).get("name") != t["name"]:
            continue
        o = (l.get("outwardIssue") or {}).get("key"); i = (l.get("inwardIssue") or {}).get("key")
        if (direction == "outward" and o == other) or (direction == "inward" and i == other):
            exists = l; break
    phrase = t["outward"] if direction == "outward" else t["inward"]
    r = {"key": key, "other": other, "type": t["name"], "reads": f"{key} {phrase} {other}", "dry_run": not args.apply, "created": False,
         "existing_link_id": (exists or {}).get("id")}
    if exists:
        _emit(args, r, [f"{key} {phrase} {other}: link already exists"]); return
    if not args.apply:
        _emit(args, r, [f"DRY RUN — {key} {phrase} {other}  ({t['name']})", "pass --apply to link"]); return
    payload = {"type": {"name": t["name"]},
               "outwardIssue": {"key": key if direction == "outward" else other},
               "inwardIssue": {"key": other if direction == "outward" else key}}
    api_post(creds, "/rest/api/3/issueLink", payload)
    r["created"] = True
    _emit(args, r, [f"linked: {key} {phrase} {other}"])


def fixed_in_entries(text):
    return [e.strip() for e in re.split(r"[;\n]", text or "") if e.strip()]


def fixed_in_merge(current, add):
    """Append-only union: current entries keep their order, new ones follow, duplicates dropped."""
    cur = fixed_in_entries(current)
    new = []
    for e in add:
        if e not in cur and e not in new:
            new.append(e)
    return cur, new, "; ".join(cur + new)


def _fixed_in_one(creds, key, add, apply, remove=None, clear=False):
    """Append entries; `remove` takes named entries out and `clear` empties the field — both only for a value that
    should never have been written (an automated write on a `flag:no-version` ticket), behind the same --apply."""
    f = _issue(creds, key, f"summary,{FIXED_IN_FIELD}")
    raw = f.get(FIXED_IN_FIELD)
    current = body_text(raw) if raw else ""
    cur, new, value = fixed_in_merge(current, add or [])
    gone = []
    if clear:
        gone, cur_after = list(cur), []
    else:
        gone = [e for e in (remove or []) if e in cur]
        cur_after = [e for e in cur if e not in gone]
    value = "; ".join(cur_after + new)
    r = {"key": key, "current": "; ".join(cur), "add": new, "remove": gone, "value": value, "dry_run": not apply, "changed": False}
    if not new and not gone:
        return r, [f"{key}: Fixed In already as requested ({r['current'] or 'empty'})"]
    if not apply:
        return r, [f"DRY RUN — {key}  {f.get('summary','')}\n  Fixed In  {r['current'] or '(empty)'}"
                   + (f"\n  + {'; '.join(new)}" if new else "") + (f"\n  - {'; '.join(gone)}" if gone else "")
                   + (f"\n  = {value or '(empty)'}" if gone else "")]
    body = (value if isinstance(raw, str) else text_to_adf(value)) if value else None
    _request(creds, f"/rest/api/3/issue/{key}", payload={"fields": {FIXED_IN_FIELD: body}}, method="PUT")
    after = _issue(creds, key, FIXED_IN_FIELD).get(FIXED_IN_FIELD)
    r["changed"], r["value"] = True, "; ".join(fixed_in_entries(body_text(after) if after else ""))
    return r, [f"{key}: Fixed In = {r['value']}"]


def _fixed_in_args(text):
    add = fixed_in_entries(text)
    bad = [e for e in add if not FIXED_IN_ENTRY.match(e)]
    if not add or bad:
        sys.exit(f"fixed-in: entries must be <slug>@<version>; bad: {', '.join(bad) or '(none given)'}")
    return add


def cmd_fixed_in(creds, args):
    """Append <slug>@<version> entries to Fixed In. Idempotent: present entries are skipped."""
    add = _fixed_in_args(args.add) if args.add else []
    remove = fixed_in_entries(args.remove) if args.remove else []
    if not add and not remove and not args.clear:
        sys.exit("fixed-in: pass --add, --remove or --clear")
    results, lines = [], []
    for key in _keys(args.targets):
        r, ls = _fixed_in_one(creds, key, add, args.apply, remove=remove, clear=args.clear)
        results.append(r); lines += ls
    if not args.apply and any(r["add"] or r["remove"] for r in results):
        lines.append("pass --apply to write")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


# ── attach: one file onto an issue ───────────────────────────────────────────

def cmd_attach(creds, args):
    """Attach one file to one issue — dry run names the file and its size; --apply uploads. A file of the same name
    already on the issue is a no-op, so a re-run does not pile up copies."""
    key = extract_key(args.target)
    path = os.path.realpath(args.file)
    if not os.path.isfile(path):
        sys.exit(f"attach: no such file {path}")
    name, size = os.path.basename(path), os.path.getsize(path)
    f = _issue(creds, key, "summary,attachment")
    dup = next((a for a in f.get("attachment") or [] if a.get("filename") == name), None)
    r = {"key": key, "file": name, "bytes": size, "dry_run": not args.apply, "uploaded": False, "duplicate_of": (dup or {}).get("id")}
    if dup:
        _emit(args, r, [f"{key}: {name} is already attached (id {dup.get('id')}, {short_date(dup.get('created'))}) — skipped"]); return
    if not args.apply:
        _emit(args, r, [f"DRY RUN — attach {name} ({size} bytes) to {key}  {f.get('summary','')}", "pass --apply to upload"]); return
    import mimetypes, uuid
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode() \
        + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    import base64 as _b64, urllib.request
    req = urllib.request.Request(creds["JIRA_BASE_URL"].rstrip("/") + f"/rest/api/3/issue/{key}/attachments", data=body, method="POST")
    req.add_header("Authorization", "Basic " + _b64.b64encode(f"{creds['JIRA_EMAIL']}:{creds['JIRA_TOKEN']}".encode()).decode())
    req.add_header("X-Atlassian-Token", "no-check"); req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode() or "[]")
    r["uploaded"], r["attachment_id"] = True, (out[0].get("id") if out else None)
    _emit(args, r, [f"{key}: attached {name} (id {r['attachment_id']})"])


# ── describe: the description, rewritten in the Markdown subset ──────────────

def cmd_describe(creds, args):
    """Replace one issue's description from a file (the Markdown subset: headings, bullets, numbered lists, bold,
    code, a --- fold). Dry run prints the current text and the new text rendered; --apply writes. Links the
    original author posted must be carried into the new text by the caller — the atom does not merge."""
    text = _read_text(args)
    if not text.strip():
        sys.exit("describe: empty text")
    key = extract_key(args.target)
    f = _issue(creds, key, "summary,description")
    before = body_text(f.get("description"))
    adf = markdown_to_adf(text)
    after = body_text(adf)
    r = {"key": key, "dry_run": not args.apply, "changed": False, "chars_before": len(before), "chars_after": len(after)}
    if _norm(before) == _norm(after):
        _emit(args, r, [f"{key}: description already reads so"]); return
    lost = [l for l in re.findall(r"https?://\S+", before) if l.rstrip(".,)") not in after]
    if not args.apply:
        lines = [f"DRY RUN — describe {key}  {f.get('summary','')}", "  was:", "    " + before.replace("\n", "\n    "), "  now:", "    " + after.replace("\n", "\n    ")]
        if lost:
            lines.append(f"  ! links in the current description not in the new one: {', '.join(lost)}")
        lines.append("pass --apply to write")
        _emit(args, dict(r, links_dropped=lost), lines); return
    if lost and not args.allow_dropped_links:
        _emit(args, dict(r, error="links dropped", links_dropped=lost), [f"{key}: the new text drops {len(lost)} link(s) the description carries — keep them, or pass --allow-dropped-links"]); sys.exit(2)
    _request(creds, f"/rest/api/3/issue/{key}", payload={"fields": {"description": adf}}, method="PUT")
    r["changed"] = True
    _emit(args, r, [f"{key}: description replaced ({len(after)} chars)"])


# ── close: one ticket, one bundle, one confirm ────────────────────────────────

def _assign_to_me(creds, key, me, apply):
    """The owner reviews what is proposed for closing: the ticket moves to him, the previous assignee stays in the comment."""
    f = _issue(creds, key, "assignee")
    cur = (f.get("assignee") or {}).get("accountId")
    if cur == me:
        return {"key": key, "assign": "already you"}, [f"{key}: already assigned to you"]
    if not apply:
        return {"key": key, "assign": "to you", "dry_run": True}, [f"  DRY RUN — assign {key} to you for review (was {name_of(f.get('assignee'))})"]
    try:
        _request(creds, f"/rest/api/3/issue/{key}/assignee", payload={"accountId": me}, method="PUT")
    except Exception as e:  # the request helper raises on a non-2xx
        return {"key": key, "error": f"assign failed: {str(e)[:120]}"}, [f"{key}: assign failed: {str(e)[:120]}"]
    return {"key": key, "assign": "to you"}, [f"{key}: assigned to you for review"]


def cmd_close(creds, args):
    """The close proposal: Fixed In + labels + comment + flag:closing + the ticket assigned to the owner, shown as one dry
    run per ticket and applied in that order. No step moves the status: a terminal status is the owner's own click in
    Jira, so a close he does not know about cannot happen. Every step is idempotent; a re-run finishes what is missing."""
    text = _read_text(args)
    add = _fixed_in_args(args.fixed_in) if args.fixed_in else []
    labels = _split_csv(args.label)
    me = (api_get(creds, "/rest/api/3/myself") or {}).get("accountId")
    results, lines, failed = [], [], False
    for key in _keys(args.targets):
        f = _issue(creds, key, "summary,status,assignee,labels")
        assignee = f.get("assignee") or {}
        steps, out = [], [f"== {key}  {f.get('summary','')}  [{name_of(f.get('status'), 'name')}; proposed for closing → {CLOSING_FLAG}, assigned to you; assignee now {name_of(assignee)}]"]
        if terminal(name_of(f.get("status"), "name")):
            r = {"key": key, "error": f"already {name_of(f.get('status'), 'name')}: nothing to propose"}
            results.append(r); lines += out + [f"{key}: {r['error']}"]; failed = True
            continue
        if not text.strip() and not args.allow_no_comment:
            r = {"key": key, "error": "a close proposal carries a comment (where verified, build, why); pass --text/--from-file"}
            results.append(r); lines += out + [f"{key}: {r['error']}"]; failed = True
            continue
        plan = []
        if add:
            plan.append(("fixed_in", lambda k=key: _fixed_in_one(creds, k, add, args.apply)))
        # The close is a proposal: the evidence and the comment on the ticket, flag:closing on the board, and the ticket
        # assigned to the owner, who reviews it and clicks Done himself. No step here moves a status.
        plan.append(("labels", lambda k=key: _label_one(creds, k, labels + [CLOSING_FLAG], [], args.apply)))
        plan.append(("comment", lambda k=key: _comment_one(creds, k, text, args.apply, mention=not args.no_mention)))
        plan.append(("assign", lambda k=key: _assign_to_me(creds, k, me, args.apply)))
        for name, fn in plan:
            r, ls = fn()
            steps.append(dict(r, step=name)); out += ["  " + l.replace("\n", "\n  ") for l in ls]
            if "error" in r:
                failed = True
                if args.apply:
                    out.append(f"  stopped at {name}; the steps before it are done and a re-run skips them")
                break
        results.append({"key": key, "steps": steps}); lines += out
    if not args.apply and not failed:
        lines.append("pass --apply to write all of the above, in this order; the status itself is the owner's click in Jira")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)
    if failed:
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser(
        description="Jira capability: read, search, gated writes.")
    ap.add_argument("--env-file", help="file with JIRA_BASE_URL/EMAIL/TOKEN")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("read", help="print one issue (or --json for raw fields)")
    p.add_argument("target", help="issue key or browse URL")
    p.add_argument("--deep", action="store_true",
                   help="also print linked issues / subtasks / parent")
    p.add_argument("--no-comments", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("files", help="download an issue's attachments — a screenshot is the evidence")
    p.add_argument("target", help="issue key or browse URL")
    p.add_argument("--id", help="one attachment id, as printed by `read`")
    p.add_argument("--out", help="directory (default <runtime>/jira-files)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_files)

    p = sub.add_parser("jql", help="search; key/status/assignee/summary rows")
    p.add_argument("jql")
    p.add_argument("--limit", type=int, default=50, help="max rows; pages of 100 are followed up to this")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_jql)

    p = sub.add_parser(
        "assign", help="re-assign one issue — dry-run unless --apply")
    p.add_argument("target", help="issue key or browse URL")
    p.add_argument("--assignee", required=True, help="email, accountId, or me")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_assign)

    p = sub.add_parser(
        "create",
        help="create one parent-level issue — dry-run unless --apply")
    p.add_argument("--project", default="MH", help="project key (default MH)")
    p.add_argument("--type", default="Task",
                   help="issue type name (default Task; also Bug, Story)")
    p.add_argument("--summary", required=True,
                   help="title; a parent carries cross-layer scope, no token required")
    p.add_argument("--description",
                   help="Markdown subset: # headings, - and 1. lists, **bold**, `code`; "
                        "a --- line folds what follows into a collapsed block")
    p.add_argument("--assignee",
                   help="assignee email or accountId "
                        "(default: the token's own account)")
    p.add_argument("--apply", action="store_true",
                   help="actually create; without it, validate and report only")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser(
        "create-subtask",
        help="create one subtask under a parent — dry-run unless --apply")
    p.add_argument("--parent", required=True, help="parent issue key")
    p.add_argument("--summary", required=True,
                   help="'[Token] action' — token from the seven-layer vocabulary")
    p.add_argument("--description",
                   help="Markdown subset: # headings, - and 1. lists, **bold**, `code`; "
                        "a --- line folds what follows into a collapsed block")
    p.add_argument("--assignee",
                   help="assignee email or accountId "
                        "(default: the token's own account)")
    p.add_argument("--issuetype", default="Sub-task",
                   help="issue type name (default Sub-task; MH verified id 10124)")
    p.add_argument("--apply", action="store_true",
                   help="actually create; without it, validate and report only")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_create_subtask)

    p = sub.add_parser("comment", help="post one comment to one or more issues (Markdown subset: bold, code, bullets, numbered; @name mentions; a --- line folds the rest) — dry-run unless --apply; identical text is not re-posted; --edit <id> replaces one")
    p.add_argument("targets", nargs="+", help="issue keys or browse URLs")
    p.add_argument("--text", help="plain text; paragraphs become ADF paragraphs")
    p.add_argument("--from-file", help="read the text from a file instead")
    p.add_argument("--no-mention", action="store_true", help="leave @name as text (default: resolve through the roster, refuse what it cannot)")
    p.add_argument("--edit", metavar="COMMENT_ID", help="replace the body of an existing comment (one key): dry run shows was/now")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_comment)

    p = sub.add_parser("transition", help="move issues to a status by name — dry-run unless --apply; already there is a no-op; --path walks Backlog → In Progress → Review → Done hop by hop")
    p.add_argument("targets", nargs="+"); p.add_argument("--to", required=True, help='target status name, e.g. "In Progress", Review, Done')
    p.add_argument("--path", action="store_true", help="when no direct transition exists, walk the MH lifecycle one hop at a time (each hop notifies the assignee)")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_transition)

    p = sub.add_parser("label", help="add/remove labels — dry-run unless --apply; only the delta is written")
    p.add_argument("targets", nargs="+"); p.add_argument("--add", help="comma-separated"); p.add_argument("--remove", help="comma-separated")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("link", help="link two issues — dry-run unless --apply; an existing link of that type is a no-op")
    p.add_argument("target"); p.add_argument("other")
    p.add_argument("--type", required=True, help='link type or phrase: Relates · Blocks · "is blocked by" · Duplicate · Cloners · "contains" · "is contained in" · "implements"')
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("fixed-in", help="append entries to Fixed In — dry-run unless --apply; present entries are skipped, none removed")
    p.add_argument("targets", nargs="+", help="issue keys or browse URLs")
    p.add_argument("--add", help="'<slug>@<version>[; <slug>@<version> …]' in the release map's grammar")
    p.add_argument("--remove", help="entries to take out — only for a value that should never have been written")
    p.add_argument("--clear", action="store_true", help="empty the field — same rule as --remove")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fixed_in)

    p = sub.add_parser("attach", help="attach one file to an issue — dry-run names file and size; --apply uploads; a same-named attachment is a no-op")
    p.add_argument("target"); p.add_argument("file"); p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser("describe", help="replace an issue's description from a file in the Markdown subset — dry-run shows was/now and any link the new text drops; --apply writes")
    p.add_argument("target"); p.add_argument("--from-file", required=True); p.add_argument("--allow-dropped-links", action="store_true")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("close", help="propose a close: Fixed In + labels + comment + flag:closing + the ticket assigned to you; the status is your own click in Jira — dry-run unless --apply")
    p.add_argument("targets", nargs="+", help="issue keys or browse URLs")
    p.add_argument("--fixed-in", help="'<slug>@<version>[; …]' to append (release map grammar)")
    p.add_argument("--label", help="comma-separated labels to add, e.g. release:mh-2.0,release:mh-2.1")
    p.add_argument("--text", help="the closing comment; `@name` mentions resolve through the roster; a `---` line starts the collapsed technical part")
    p.add_argument("--from-file", help="read the comment from a file instead")
    p.add_argument("--allow-no-comment", action="store_true", help="propose without a comment (normally refused: the assignee and the reporter must see why)")
    p.add_argument("--no-mention", action="store_true")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_close)

    args = ap.parse_args()
    creds = load_env(args.env_file)
    args.func(creds, args)


if __name__ == "__main__":
    main()
