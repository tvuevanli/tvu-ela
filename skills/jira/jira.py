#!/usr/bin/env python3
"""Jira capability — read, search, and gated writes. Stdlib only.

This is an L1 atomic capability: deterministic, no LLM, callable by anything
(a Claude session via the skill, Helm ops via subprocess, a future MCP server).
Credentials are site state resolved from the environment or an env file.

Usage:
    jira.py read MH-3454 [--deep] [--no-comments] [--json]
    jira.py read https://tvunetworks.atlassian.net/browse/MH-3454
    jira.py jql 'project=MH AND text ~ "CSC"' [--limit 50] [--json]
    jira.py create-subtask --parent MH-3513 --summary '[App] ...' \
            [--description TEXT] [--assignee EMAIL|ACCOUNTID] [--apply] [--json]
    jira.py comment MH-1 [MH-2 …] --text '…' | --from-file f   [--apply]   # identical text is never re-posted
    jira.py transition MH-1 [MH-2 …] --to Review               [--apply]   # transition looked up by target status
    jira.py label MH-1 [MH-2 …] --add a,b --remove c           [--apply]   # only the delta is written
    jira.py link MH-1 MH-2 --type Blocks|"is blocked by"|Relates [--apply]  # existing link of that type is a no-op

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

ENV_KEYS = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_TOKEN")

# Closed vocabulary — one token, one owning layer. A title that does not start
# with exactly one of these is invalid; no caller may create it.
LAYER_TOKENS = ("[Infra]", "[J2N]", "[Media]", "[App]", "[UI]", "[QA]", "[Design]")


def load_env(env_file):
    """Resolve credentials: process env wins, then the env file."""
    creds = {k: os.environ.get(k) for k in ENV_KEYS}
    path = env_file or os.environ.get("JIRA_ENV_FILE")
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


def text_to_adf(text):
    """Plain text → minimal ADF: one paragraph per non-empty line."""
    paras = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        for line in text.splitlines() if line.strip()
    ]
    return {"type": "doc", "version": 1,
            "content": paras or [{"type": "paragraph"}]}


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
            print(f"  {a.get('filename')}  ({a.get('size')} B, "
                  f"{short_date(a.get('created'))}, {name_of(a.get('author'))})")

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
    if not who:
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
        fields["description"] = text_to_adf(args.description)
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
        fields["description"] = text_to_adf(args.description)
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


def cmd_comment(creds, args):
    """Post one comment to one or more issues. Idempotent on identical text."""
    text = args.text
    if args.from_file:
        with open(args.from_file, encoding="utf-8") as fh:
            text = fh.read().rstrip("\n")
    if not (text or "").strip():
        sys.exit("comment: empty text")
    results, lines = [], []
    for key in _keys(args.targets):
        existing = fetch_comments(creds, key)
        dup = next((c for c in existing if _norm(body_text(c.get("body"))) == _norm(text)), None)
        r = {"key": key, "dry_run": not args.apply, "posted": False,
             "duplicate_of": (dup or {}).get("id"), "chars": len(text)}
        if dup:
            lines.append(f"{key}: identical comment already posted ({(dup.get('created') or '')[:16]}) — skipped")
        elif not args.apply:
            lines += [f"DRY RUN — comment on {key} ({len(text)} chars):", "  " + text.replace("\n", "\n  ")]
        else:
            resp = api_post(creds, f"/rest/api/3/issue/{key}/comment", {"body": text_to_adf(text)})
            r["posted"], r["comment_id"] = True, resp.get("id")
            lines.append(f"{key}: comment posted (id {resp.get('id')})")
        results.append(r)
    if not args.apply and any(not r["duplicate_of"] for r in results):
        lines.append("pass --apply to post")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


def cmd_transition(creds, args):
    """Move issues to a target status by name; the transition is looked up, never guessed."""
    results, lines = [], []
    for key in _keys(args.targets):
        f = _issue(creds, key, "summary,status")
        cur = name_of(f.get("status"), "name")
        r = {"key": key, "from": cur, "to": args.to, "dry_run": not args.apply, "changed": False}
        if _norm(cur) == _norm(args.to):
            lines.append(f"{key}: already {cur}")
            results.append(r); continue
        trans = api_get(creds, f"/rest/api/3/issue/{key}/transitions").get("transitions") or []
        hit = next((t for t in trans if _norm((t.get("to") or {}).get("name")) == _norm(args.to)), None)
        if not hit:
            opts = ", ".join(sorted({(t.get("to") or {}).get("name", "?") for t in trans}))
            r["error"] = f"no transition from {cur} to {args.to}; available: {opts}"
            lines.append(f"{key}: {r['error']}")
            results.append(r); continue
        r["transition"] = hit.get("name")
        if not args.apply:
            lines.append(f"DRY RUN — {key}  {f.get('summary','')}\n  status  {cur} -> {args.to}  (transition '{hit.get('name')}')")
        else:
            api_post(creds, f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": hit["id"]}})
            r["changed"] = True
            lines.append(f"{key}: {cur} -> {args.to}")
        results.append(r)
    if not args.apply and any(not r["changed"] and "error" not in r and _norm(r["from"]) != _norm(r["to"]) for r in results):
        lines.append("pass --apply to transition")
    if any("error" in r for r in results) and not args.json:
        sys.exit(2) if all("error" in r for r in results) else None
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


def cmd_label(creds, args):
    """Add and/or remove labels. Idempotent: only the actual delta is written."""
    add = [x.strip() for x in (args.add or "").split(",") if x.strip()]
    rem = [x.strip() for x in (args.remove or "").split(",") if x.strip()]
    if not add and not rem:
        sys.exit("label: nothing to do — pass --add and/or --remove")
    results, lines = [], []
    for key in _keys(args.targets):
        f = _issue(creds, key, "summary,labels")
        cur = f.get("labels") or []
        to_add = [x for x in add if x not in cur]
        to_rem = [x for x in rem if x in cur]
        r = {"key": key, "labels": cur, "add": to_add, "remove": to_rem, "dry_run": not args.apply, "changed": False}
        if not to_add and not to_rem:
            lines.append(f"{key}: labels already as requested ({' '.join(cur) or 'none'})")
        elif not args.apply:
            lines.append(f"DRY RUN — {key}  {f.get('summary','')}\n  labels  {' '.join(cur) or '(none)'}"
                         + (f"\n  + {' '.join(to_add)}" if to_add else "") + (f"\n  - {' '.join(to_rem)}" if to_rem else ""))
        else:
            ops = [{"add": x} for x in to_add] + [{"remove": x} for x in to_rem]
            _request(creds, f"/rest/api/3/issue/{key}", payload={"update": {"labels": ops}}, method="PUT")
            r["changed"] = True
            lines.append(f"{key}: labels " + " ".join((["+" + x for x in to_add] + ["-" + x for x in to_rem])))
        results.append(r)
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

    p = sub.add_parser("jql", help="search; key/status/assignee/summary rows")
    p.add_argument("jql")
    p.add_argument("--limit", type=int, default=50, help="max rows; pages of 100 are followed up to this")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_jql)

    p = sub.add_parser(
        "assign", help="re-assign one issue — dry-run unless --apply")
    p.add_argument("target", help="issue key or browse URL")
    p.add_argument("--assignee", required=True, help="email or accountId")
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
    p.add_argument("--description", help="plain text; rendered as ADF paragraphs")
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
    p.add_argument("--description", help="plain text; rendered as ADF paragraphs")
    p.add_argument("--assignee",
                   help="assignee email or accountId "
                        "(default: the token's own account)")
    p.add_argument("--issuetype", default="Sub-task",
                   help="issue type name (default Sub-task; MH verified id 10124)")
    p.add_argument("--apply", action="store_true",
                   help="actually create; without it, validate and report only")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_create_subtask)

    p = sub.add_parser("comment", help="post one comment to one or more issues — dry-run unless --apply; identical text is not re-posted")
    p.add_argument("targets", nargs="+", help="issue keys or browse URLs")
    p.add_argument("--text", help="plain text; paragraphs become ADF paragraphs")
    p.add_argument("--from-file", help="read the text from a file instead")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_comment)

    p = sub.add_parser("transition", help="move issues to a status by name — dry-run unless --apply; already there is a no-op")
    p.add_argument("targets", nargs="+"); p.add_argument("--to", required=True, help='target status name, e.g. "In Progress", Review, Done')
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

    args = ap.parse_args()
    creds = load_env(args.env_file)
    args.func(creds, args)


if __name__ == "__main__":
    main()
