#!/usr/bin/env python3
"""Read a Jira issue (and optionally its related issues) read-only.

Mirrors slack-read: the capability is shareable, the credentials are site
state resolved from the environment or an env file. Stdlib only.

Usage:
    jiraread.py MH-3454
    jiraread.py https://tvunetworks.atlassian.net/browse/MH-3454
    jiraread.py MH-3454 --deep          # also print linked/subtask bodies
    jiraread.py --jql 'project=MH AND text ~ "CSC"'
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


def api_get(creds, path, params=None):
    url = creds["JIRA_BASE_URL"] + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = base64.b64encode(
        f'{creds["JIRA_EMAIL"]}:{creds["JIRA_TOKEN"]}'.encode()
    ).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        sys.exit(f"jira {path} failed: HTTP {exc.code} {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"jira {path} failed: {exc}")


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


# ── Rendering ────────────────────────────────────────────────────────────────

def name_of(obj, key="displayName"):
    return (obj or {}).get(key) or "—"


def short_date(s):
    return (s or "")[:16].replace("T", " ")


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
        cdata = api_get(creds, f"/rest/api/3/issue/{key}/comment",
                        {"maxResults": 100, "orderBy": "created"})
        cs = cdata.get("comments") or []
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


def run_jql(creds, jql, limit):
    data = api_get(creds, "/rest/api/3/search/jql", {
        "jql": jql,
        "maxResults": limit,
        "fields": "summary,status,assignee,issuetype,updated",
    })
    issues = data.get("issues") or []
    print(f"# {len(issues)} issue(s) for: {jql}\n")
    for i in issues:
        f = i.get("fields") or {}
        print(f"{i.get('key'):<10} [{name_of(f.get('status'), 'name'):<12}] "
              f"{name_of(f.get('assignee')):<16} {f.get('summary', '')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="issue key or browse URL")
    ap.add_argument("--env-file")
    ap.add_argument("--jql", help="run a JQL search instead of reading one issue")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--deep", action="store_true",
                    help="also print linked issues / subtasks / parent")
    ap.add_argument("--no-comments", action="store_true")
    args = ap.parse_args()

    creds = load_env(args.env_file)

    if args.jql:
        run_jql(creds, args.jql, args.limit)
        return
    if not args.target:
        ap.error("give an issue key/URL, or --jql")

    m = re.search(r"([A-Z][A-Z0-9]+-\d+)", args.target.upper())
    if not m:
        sys.exit(f"cannot find an issue key in {args.target!r}")
    print_issue(creds, m.group(1), deep=args.deep,
                comments=not args.no_comments)


if __name__ == "__main__":
    main()
