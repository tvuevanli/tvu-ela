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
    jira.py transition MH-1 [MH-2 …] --to Review  [--terminal] [--apply]   # looked up by target status; a terminal one needs --terminal
    jira.py label MH-1 [MH-2 …] --add a,b --remove c           [--apply]   # only the delta is written
    jira.py link MH-1 MH-2 --type Blocks|"is blocked by"|Relates [--apply]  # existing link of that type is a no-op
    jira.py unlink MH-1 --id <link id> [--apply]               # the reverse atoms: each applied write records its
    jira.py comment-delete MH-1 --id <comment id> [--apply]    # before-state and its undo in <reports>/ela/acts.jsonl;
    jira.py assign MH-1 --assignee <prior>|none [--apply]      # Fixed In and labels reverse through --remove
    jira.py fixed-in MH-1 [MH-2 …] --add 'slug@1.2.3; slug2@4.5.6' [--apply]  # append-only; present entries skipped
    jira.py priority MH-1 [MH-2 …] --to High [--why "rule"] [--apply]   # raises; never lowers one a person set
    jira.py due MH-1 [MH-2 …] --date 2026-11-04 [--why "rule"] [--apply]  # sets a missing date; never moves one
    jira.py version create|release <name> [--release-date D] [--project MH] [--apply]
    jira.py version set MH-1 [MH-2 …] --name <name> [--apply]   # Fix Version, additive

Writes are dry-run by default; --apply performs the create. Safety gates
(title token vocabulary, duplicate detection) live here and cannot be
bypassed by any caller. Confirmation UX belongs to the caller.

Exit codes: 0 ok (including idempotent "already exists"), 1 API/transport
error, 2 validation error.
"""
import argparse
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "facts"))
try:
    import facts as F  # noqa: E402 — the fact store: `read`, `changes` and the standing queries serve from it
except ImportError:                                     # a copied script without the store reads live
    F = None

ENV_KEYS = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_TOKEN")
SHORT_TTL_H = 0.5          # a key read with no sweep after it is served again this long: one read per key per pass
OWNER_TTL_H = 24           # the owner-name JQL runs once a day

# Closed vocabulary — one token, one owning layer. A title that does not start
# with exactly one of these is invalid; no caller may create it.
# [UR] is UR in the broad sense, J2N included (the owner's word, 2026-11-10; it replaced [J2N]).
LAYER_TOKENS = ("[Infra]", "[UR]", "[Media]", "[App]", "[UI]", "[QA]", "[Design]")

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


def write_who():
    """Who made a write and on whose word, from the environment the caller set: the session's name (or its Claude id),
    the runner's job, the drafted action or batch applied, and the word (a tick, `apply N`, an answer). A field
    nobody set stays null; the links index then says unknown rather than guessing."""
    e = os.environ
    session = e.get("ELA_SESSION_NAME") or (f"claude:{e['CLAUDE_CODE_SESSION_ID'][:8]}" if e.get("CLAUDE_CODE_SESSION_ID") else None)
    word = e.get("ELA_WORD") or ("the owner in the session" if session and not e.get("ELA_NO_APPLY") else None)
    return {"session": session, "job": e.get("ELA_RUNNER_JOB") or None, "action": e.get("ELA_ACTION") or None, "word": word}


def ela_dir():
    """<reports>/ela, where the write log and the acts live; ELA_REPORTS overrides the site's reports root (tests)."""
    if os.environ.get("ELA_REPORTS"):
        return os.path.join(os.environ["ELA_REPORTS"], "ela")
    site = json.load(open(os.path.expanduser("~/.claude/ela/site.json")))
    return os.path.join(site.get("reports") or os.path.join(site.get("projects") or "", "reports"), "ela")


def undo_argv(*argv):
    """A reverse atom as the argv `ela jira …` takes, without --apply: an undo is a dry run until its own word."""
    return ["ela", "jira", *[str(a) for a in argv]]


def record_act(key, verb, before, undo, after=None):
    """One applied write's before-state and the reverse atom that restores it, kept with the act: <reports>/ela/
    acts.jsonl. The act is the caller's (ELA_ACT: a dry batch's write, a reconcile batch's command) and its class
    (ELA_CLASS); `ela dry undo <act>` runs the undo. Never fatal: the write has happened either way."""
    try:
        d = ela_dir()
        os.makedirs(d, exist_ok=True)
        row = {"at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "act": os.environ.get("ELA_ACT") or None,
               "class": os.environ.get("ELA_CLASS") or None, "key": key, "verb": verb, "before": before, "after": after,
               "undo": undo, **write_who()}
        with open(os.path.join(d, "acts.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def acts_rows():
    """Every recorded act row, oldest first; [] when there is none."""
    out = []
    try:
        for line in open(os.path.join(ela_dir(), "acts.jsonl"), encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except (OSError, ValueError):
        pass
    return out


def log_write(system, method, path, ok=True):
    """One line per applied write, so the owner's brief can say what ela did: Jira and Slack record ela's writes
    under the owner's own account, indistinguishable from his clicks. <reports>/ela/writes.jsonl; never fatal."""
    try:
        d = ela_dir()
        os.makedirs(d, exist_ok=True)
        key = (re.search(r"/issue/([A-Z][A-Z0-9]+-\d+)", path) or [None, None])[1]
        verb = next((a for a in sys.argv[1:] if not a.startswith("-") and not os.path.exists(a)), "")
        named = [a for a in sys.argv[1:] if re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", a) and a != key]
        row = {"at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "system": system, "verb": verb,
               "key": key or (named.pop(0) if named else None), "keys": named or None, "method": method, "path": path,
               "ok": ok, "unattended": bool(os.environ.get("ELA_NO_APPLY")), **write_who()}
        with open(os.path.join(d, "writes.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _request(creds, path, params=None, payload=None, method="GET"):
    if method != "GET":
        r = _request_raw(creds, path, params, payload, method)
        log_write("jira", method, path)
        return r
    return _request_raw(creds, path, params, payload, method)


def _request_raw(creds, path, params=None, payload=None, method="GET"):
    if F:
        F.trace("jira", f"{method} {path}")
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
        # `@First Last`: the rest of the display name typed after the token is the same person, not more text
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
    """A comment: the Markdown subset (bold, code, links, bullets, numbered lists, headings) above and inside the
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


# Code comes first, so a URL inside backticks stays code; a [text](url) link comes before a bare URL, so its
# target is not linkified a second time.
MARK_RX = re.compile(r"`(?P<code>[^`]+)`|\*\*(?P<bold>[^*]+)\*\*"
                     r"|\[(?P<label>[^\]]+)\]\((?P<href>https?://[^\s)]+)\)|(?P<url>https?://[^\s<>`]+)")
URL_RX = re.compile(r"https?://[^\s<>`]+")
HEADING_RX = re.compile(r"^(#{1,3})\s+(.*)$")
BULLET_RX = re.compile(r"^[-*]\s+(.*)$")
NUMBERED_RX = re.compile(r"^\d+\.\s+(.*)$")


def _url_end(url):
    """A bare URL without the sentence punctuation that follows it; a closing parenthesis stays only when the
    URL opened one."""
    while url and (url[-1] in ".,;:!?'\"" or (url[-1] == ")" and url.count(")") > url.count("("))):
        url = url[:-1]
    return url


def _text(text, marks=None):
    return {"type": "text", "text": text, "marks": marks} if marks else {"type": "text", "text": text}


def _linked(text, marks=None):
    """Plain text with each bare http(s) URL as a link mark whose text is the URL; `marks` apply to every node."""
    nodes, pos = [], 0
    for m in URL_RX.finditer(text):
        url = _url_end(m.group(0))
        if not url.split("://", 1)[1]:
            continue
        if m.start() > pos:
            nodes.append(_text(text[pos:m.start()], marks))
        nodes.append(_text(url, (marks or []) + [{"type": "link", "attrs": {"href": url}}]))
        pos = m.start() + len(url)
    if pos < len(text):
        nodes.append(_text(text[pos:], marks))
    return nodes


def _marked(line):
    """`**bold**`, `` `code` ``, `[text](https://url)` and a bare http(s) URL as ADF marks; everything else is
    plain text. A URL inside code stays code."""
    nodes, pos = [], 0
    for m in MARK_RX.finditer(line):
        if m.start() > pos:
            nodes.extend(_linked(line[pos:m.start()]))
        if m.group("code") is not None:
            nodes.append(_text(m.group("code"), [{"type": "code"}]))
        elif m.group("bold") is not None:
            nodes.extend(_linked(m.group("bold"), [{"type": "strong"}]))
        elif m.group("href") is not None:
            nodes.append(_text(m.group("label"), [{"type": "link", "attrs": {"href": m.group("href")}}]))
        else:
            nodes.extend(_linked(m.group("url")))
        pos = m.end()
    if pos < len(line):
        nodes.extend(_linked(line[pos:]))
    return nodes or [{"type": "text", "text": line}]


def _md_blocks(lines):
    blocks, lst, code = [], None, None
    for line in lines:
        s = line.strip()
        if code is not None:
            if s.startswith("```"):
                blocks.append(code); code = None
            else:
                code["content"][0]["text"] += ("\n" if code["content"][0]["text"] else "") + line
            continue
        if s.startswith("```"):
            lst, lang = None, s[3:].strip()
            code = {"type": "codeBlock", "attrs": {"language": lang} if lang else {}, "content": [{"type": "text", "text": ""}]}
            continue
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
    if code is not None:
        blocks.append(code)
    return blocks


def markdown_to_adf(text):
    """A ticket description in a Markdown subset → ADF: `#`..`###` headings, `- `/`* ` bullets, `1. ` numbered
    lists, `**bold**`, `` `code` ``, `[text](https://url)` and bare http(s) URLs as links (not inside code),
    ``` fenced code blocks. A line of three or more dashes folds everything after it into a collapsed
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



# ── the description standard: what ela creates is held to one shape per issue type ──────────────
# Recorded in elak knowledge/products/mediahub/jira/conventions.md § Description standard. Of 944 open MH tickets
# on 2026-10-23, 23 stated what done means; a ticket without a criterion cannot be verified or closed by evidence,
# which is the board's debt. A heading is a `#`..`###` line or a line that is only bold text, above the fold.
CRITERION = ("Done when", "QA verification")
STANDARD = {
    "Bug": ("Problem", "Steps to reproduce", CRITERION),
    "Sub-task": ("Scope", CRITERION),
    "*": ("Goal", "Scope", CRITERION),
}
_HEAD_RX = re.compile(r"^\s*(?:#{1,3}\s+(.+?)|\*\*(.+?)\*\*:?)\s*$")


def description_standard(issuetype, text):
    """The sections the issue type requires that the text lacks, and the warnings (language). Empty lists: standard."""
    want = STANDARD.get(issuetype) or STANDARD["*"]
    heads = set()
    for line in (text or "").splitlines():
        if DETAIL_RX.match(line.strip()):
            break
        m = _HEAD_RX.match(line)
        if m:
            heads.add((m.group(1) or m.group(2)).strip().rstrip(":").lower())
    missing = []
    for w in want:
        names = w if isinstance(w, tuple) else (w,)
        if not any(n.lower() in heads for n in names):
            missing.append(" or ".join(names))
    warnings = []
    first = next((l for l in (text or "").splitlines() if l.strip()), "")
    if re.search(r"[一-鿿]", first):
        warnings.append("English first: a bilingual description puts the English sections first and a `### 中文` section after them")
    return missing, warnings


def _standard_gate(args, issuetype, result):
    """Dry run: report the check. --apply: refuse a nonstandard description unless --nonstandard says why."""
    missing, warnings = description_standard(issuetype, args.description or "")
    result["standard_missing"], result["standard_warnings"] = missing, warnings
    lines = [f"  standard   {'ok' if not missing else 'missing: ' + ', '.join(missing)}"] + [f"  note       {w}" for w in warnings]
    if args.apply and missing and not getattr(args, "nonstandard", None):
        print("\n".join(lines), file=sys.stderr)
        print(f"refused: a {issuetype} ela creates carries {', '.join(missing)} (elak jira conventions § Description standard); "
              "add the sections, or pass --nonstandard '<reason>'", file=sys.stderr)
        sys.exit(2)
    return lines

def cmd_projects(creds, args):
    """Every project key the account can see — the allow-list for recognising a ticket key in free text — and its lead.
    Served from the store for a day: the list changes rarely and every key-recognising reader asks for it."""
    path = os.path.join(F.store_dir("jira"), "projects.json") if F else None
    doc = F.read_json(path) if path else None
    if doc and not args.fresh and not F.forced_fresh() and F.fresh(doc.get("at"), OWNER_TTL_H):
        F.served("jira", doc["at"], "projects")
        keys = doc["projects"]
        if args.json:
            print(json.dumps({"count": len(keys), "projects": keys, "read_at": doc["at"]}, ensure_ascii=False)); return
        for p in keys:
            print(f"{p['key']:<12} {p['name']}")
        return
    keys, start = [], 0
    while True:
        d = api_get(creds, "/rest/api/3/project/search", {"startAt": start, "maxResults": 100, "expand": "lead"})
        keys += [{"key": p.get("key"), "name": p.get("name"), "lead": name_of(p.get("lead")) if p.get("lead") else None}
                 for p in d.get("values") or []]
        if d.get("isLast", True) or not d.get("values"):
            break
        start += len(d["values"])
    if path:
        F.write_json(path, {"at": F.now_iso(), "projects": keys})
    if args.json:
        print(json.dumps({"count": len(keys), "projects": keys}, ensure_ascii=False)); return
    for p in keys:
        print(f"{p['key']:<12} {p['name']}")


# ── changes: what moved on each ticket in a window (read-only) ───────────────
# The fields a reader acts on; edits to anything else are counted, not listed.
CHANGE_FIELDS = {"status", "priority", "assignee", "labels", "Fixed In", "issuetype", "resolution", "Link", "Parent", "Sprint"}


# the sweep's fields: what `changes` renders, plus what `recent` reads off the same issues (reporter, labels, due,
# the description and Fixed In), so one read per window serves both
SWEEP_FIELDS = ("summary,status,assignee,reporter,priority,issuetype,parent,comment,created,updated,labels,duedate,"
                "description,resolution,resolutiondate," + FIXED_IN_FIELD)


def since_cutoff(since):
    """A JQL relative date (-1d, -72h) or 'YYYY-MM-DD HH:MM' (machine local) as an aware UTC cutoff."""
    if since.startswith("-"):
        n = int(re.sub(r"\D", "", since) or 1); unit = since[-1]
        delta = {"d": datetime.timedelta(days=n), "h": datetime.timedelta(hours=n), "w": datetime.timedelta(weeks=n)}.get(unit, datetime.timedelta(days=n))
        return datetime.datetime.now(datetime.timezone.utc) - delta
    return datetime.datetime.fromisoformat(since).astimezone(datetime.timezone.utc)


def updated_iso(ts):
    """A Jira stamp (2026-11-02T09:41:12.345+0800) as an aware ISO string, comparable as text; '' when unreadable."""
    try:
        t = datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc) - \
            datetime.timedelta(minutes=int(ts[-4:-2]) * 60 + int(ts[-2:])) * (1 if ts[-5] == "+" else -1)
        return t.isoformat(timespec="seconds")
    except (TypeError, ValueError, IndexError):
        return ""


def search_changed(creds, project, since, limit=400, fields=SWEEP_FIELDS):
    """The raw issues of a project updated since `since`, changelog expanded, newest update first."""
    jql = f'project = {project} AND updated >= "{since}" ORDER BY updated DESC' if not since.startswith("-") \
        else f"project = {project} AND updated >= {since} ORDER BY updated DESC"
    issues, token = [], None
    while len(issues) < limit:
        p = {"jql": jql, "maxResults": min(100, limit - len(issues)), "expand": "changelog", "fields": fields}
        if token:
            p["nextPageToken"] = token
        d = api_get(creds, "/rest/api/3/search/jql", p)
        issues += d.get("issues") or []
        token = d.get("nextPageToken")
        if not token or d.get("isLast"):
            break
    return issues


def sweep_issue(i, read_at):
    """A raw search issue as the store keeps it: Jira's shape (key, fields, changelog) plus a top-level `comments`
    list (id, created, author, body) and the read time, so a reader needs no knowledge of the search payload."""
    f = i.get("fields") or {}
    return {"key": i.get("key"), "id": i.get("id"), "read_at": read_at, "fields": f, "changelog": i.get("changelog") or {},
            "comments": list(((f.get("comment") or {}).get("comments")) or [])}


def stored_changed(project=None, cutoff=None):
    """The store's changed issues (facts/jira/changes.json) for a project, updated at or after the cutoff, newest
    first; None when the store does not cover the window (no sweep, a stale one, or a horizon after the cutoff)."""
    if not F or F.forced_fresh():
        return None
    wm = F.watermark("jira")
    if not wm.get("at") or not F.fresh(wm["at"]):
        return None
    if project and project not in (wm.get("projects") or []):
        return None
    horizon = F.parse_iso(wm.get("horizon"))
    if cutoff is not None and (horizon is None or horizon > cutoff + datetime.timedelta(minutes=1)):
        return None
    out = []
    for i in F.read_json(os.path.join(F.store_dir("jira"), "changes.json"), []) or []:
        k = i.get("key") or ""
        if project and not k.startswith(project + "-"):
            continue
        upd = updated_iso(((i.get("fields") or {}).get("updated")) or "")
        if cutoff is not None and upd and upd < cutoff.isoformat(timespec="seconds"):
            continue
        out.append(i)
    out.sort(key=lambda i: updated_iso(((i.get("fields") or {}).get("updated")) or ""), reverse=True)
    return {"at": wm["at"], "issues": out}


def changes_rows(issues, cutoff):
    """The `changes` rows from raw issues: the changelog items and comments inside the window."""
    def inside(ts):
        try:
            return datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc) - \
                datetime.timedelta(minutes=int(ts[-4:-2]) * 60 + int(ts[-2:])) * (1 if ts[-5] == "+" else -1) >= cutoff
        except (ValueError, IndexError):
            return True
    rows = []
    for i in issues:
        f = i.get("fields") or {}
        events, other = [], 0
        for h in (i.get("changelog") or {}).get("histories") or []:
            if not inside(h.get("created", "")):
                continue
            who = name_of(h.get("author"))
            for it in h.get("items") or []:
                if it.get("field") in CHANGE_FIELDS:
                    events.append({"at": h.get("created"), "by": who, "field": it.get("field"),
                                   "from": it.get("fromString"), "to": it.get("toString")})
                else:
                    other += 1
        comments = [{"at": c.get("created"), "by": name_of(c.get("author")), "text": re.sub(r"\s+", " ", body_text(c.get("body")))[:300]}
                    for c in ((f.get("comment") or {}).get("comments") or []) if inside(c.get("created", ""))]
        created = inside(f.get("created", ""))
        if not (events or comments or created or other):
            continue
        rows.append({"key": i.get("key"), "summary": f.get("summary", ""), "status": name_of(f.get("status"), "name"),
                     "assignee": name_of(f.get("assignee")), "priority": name_of(f.get("priority"), "name"),
                     "type": name_of(f.get("issuetype"), "name"), "parent": (f.get("parent") or {}).get("key"),
                     "created_in_window": created, "events": events, "comments": comments, "other_edits": other})
    return rows


def cmd_changes(creds, args):
    """Tickets updated since --since (a JQL relative date such as -1d, or YYYY-MM-DD HH:MM), each with the changelog
    items and comments inside the window: who moved what, when. Feeds the brief's yesterday section. Served from the
    store's sweep when it covers the window (`ela facts refresh`); --fresh reads Jira now."""
    cutoff = since_cutoff(args.since)
    stored = None if getattr(args, "fresh", False) else stored_changed(args.project, cutoff)
    if stored is not None:
        issues, read_at = stored["issues"][: args.limit], stored["at"]
        F.served("jira", read_at, f"changes {args.project} since {args.since}")
    else:
        issues, read_at = search_changed(creds, args.project, args.since, args.limit), datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    rows = changes_rows(issues, cutoff)
    if args.json:
        print(json.dumps({"since": args.since, "cutoff": cutoff.isoformat(timespec="seconds"), "count": len(rows), "issues": rows,
                          "read_at": read_at}, ensure_ascii=False)); return
    print(f"# {len(rows)} issue(s) changed since {args.since}\n")
    for r in rows:
        ev = "; ".join(f"{e['field']}: {e['from'] or '—'} → {e['to'] or '—'} ({e['by']})" for e in r["events"])
        print(f"{r['key']:<10} [{r['status']:<12}] {r['summary'][:70]}")
        if r["created_in_window"]:
            print("           created")
        if ev:
            print(f"           {ev}")
        for c in r["comments"]:
            print(f"           comment by {c['by']}: {c['text'][:120]}")


# ── Rendering ────────────────────────────────────────────────────────────────

def name_of(obj, key="displayName"):
    return (obj or {}).get(key) or "—"


def short_date(s):
    return (s or "")[:16].replace("T", " ")


def fetch_comments(creds, key):
    cdata = api_get(creds, f"/rest/api/3/issue/{key}/comment",
                    {"maxResults": 100, "orderBy": "created"})
    return cdata.get("comments") or []


_CHANGED = {}
def _changed_updated(key):
    """The `updated` the store's last sweep saw for a key, or None when the sweep did not list it."""
    if "doc" not in _CHANGED:
        _CHANGED["doc"] = {i.get("key"): i for i in (F.read_json(os.path.join(F.store_dir("jira"), "changes.json"), []) or [])}
    rec = _CHANGED["doc"].get(key) or {}
    return updated_iso(((rec.get("fields") or {}).get("updated")) or "") or None


def cache_holds(key, cached):
    """Whether a cached issue read still stands: the store's sweep ran after the read and does not say the key moved;
    with no sweep since the read, the short TTL (one read per key per pass)."""
    if not F or F.forced_fresh() or not cached:
        return False
    read_at = cached.get("read_at")
    moved = _changed_updated(key)
    if moved and moved > str(cached.get("updated") or ""):
        return False
    wm = F.watermark("jira")
    swept = F.parse_iso(wm.get("at"))
    if swept and F.fresh(wm["at"]) and key.split("-")[0] in (wm.get("projects") or []) and F.parse_iso(read_at) and swept >= F.parse_iso(read_at):
        return True
    return F.fresh(read_at, SHORT_TTL_H)


def issue_doc(creds, key, comments=True, fresh=False):
    """One issue as `read --json` prints it: {key, url, fields, comments, updated, read_at}. Served from the store's key
    cache (facts/jira/issues/<KEY>.json) while the sweep says the issue has not moved; a live read writes through."""
    path = os.path.join(F.store_dir("jira", "issues"), f"{key}.json") if F else None
    cached = F.read_json(path) if path else None
    if cached and not fresh and cache_holds(key, cached) and (cached.get("has_comments") or not comments):
        F.served("jira", cached.get("read_at"), key)
        return cached
    data = api_get(creds, f"/rest/api/3/issue/{key}", {"fields": "*all"})
    f = data.get("fields") or {}
    doc = {"key": data.get("key"), "url": f"{creds['JIRA_BASE_URL']}/browse/{data.get('key')}", "fields": f,
           "updated": updated_iso(f.get("updated") or ""), "read_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "has_comments": bool(comments)}
    if comments:
        doc["comments"] = fetch_comments(creds, key)
    if path:
        F.write_json(path, doc)
    return doc


def print_issue(creds, key, deep=False, comments=True, seen=None, fresh=False):
    seen = seen if seen is not None else set()
    if key in seen:
        return
    seen.add(key)

    data = issue_doc(creds, key, comments=comments, fresh=fresh)
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
        cs = data.get("comments") or []
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
                print_issue(creds, k, deep=False, comments=comments, seen=seen, fresh=fresh)


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
        doc = issue_doc(creds, key, comments=not args.no_comments, fresh=args.fresh)
        out = {"key": doc.get("key"), "url": doc.get("url"), "fields": doc.get("fields") or {}}
        if not args.no_comments:
            out["comments"] = doc.get("comments") or []
        out["read_at"] = doc.get("read_at")
        print(json.dumps(out, ensure_ascii=False))
        return
    print_issue(creds, key, deep=args.deep, comments=not args.no_comments, fresh=args.fresh)


# ── the standing queries: run once per refresh, served to the verbs that ask the same JQL ─────────────
OWNER_JQL = "assignee = currentUser() ORDER BY updated DESC"
STANDING = {"incidents": "project = MH AND parent = MH-2342 AND statusCategory != Done ORDER BY updated ASC"}
STANDING_LIMIT = 300


def search_rows(creds, jql, limit):
    """`jql` rows as the verb prints them with --json; pages of 100 followed to `limit`."""
    issues, token = [], None
    while len(issues) < limit:
        params = {
            "jql": jql,
            "maxResults": min(100, limit - len(issues)),
            "fields": "summary,status,assignee,reporter,issuetype,priority,labels,parent,subtasks,created,updated,duedate",
        }
        if token:
            params["nextPageToken"] = token
        data = api_get(creds, "/rest/api/3/search/jql", params)
        issues += data.get("issues") or []
        token = data.get("nextPageToken")
        if not token or data.get("isLast"):
            break
    return issues


def standing_queries(creds):
    """The incidents umbrella's open children, and the owner's Jira name (once a day), kept in the store."""
    if not F:
        return
    d = F.store_dir("jira", "queries")
    for name, jql in STANDING.items():
        F.write_json(os.path.join(d, f"{name}.json"), {"jql": jql, "limit": STANDING_LIMIT, "at": F.now_iso(),
                                                       "issues": search_rows(creds, jql, STANDING_LIMIT)})
    owner = F.read_json(os.path.join(F.store_dir("jira"), "owner.json"), {}) or {}
    if not F.fresh(owner.get("at"), OWNER_TTL_H):
        F.write_json(os.path.join(F.store_dir("jira"), "owner.json"), {"jql": OWNER_JQL, "limit": 1, "at": F.now_iso(),
                                                                       "issues": search_rows(creds, OWNER_JQL, 1)})


def _jql_path(q, limit):
    import hashlib
    return os.path.join(F.store_dir("jira", "queries"), f"jql-{hashlib.sha1(f'{q}|{limit}'.encode()).hexdigest()[:16]}.json")


def stored_query(jql, limit):
    """A standing query's rows from the store when its read is fresh and deep enough; any other JQL for the short TTL
    after its last read (the same search is asked several times in one pass); None otherwise."""
    if not F or F.forced_fresh():
        return None
    q = " ".join(jql.split())
    doc = F.read_json(_jql_path(q, limit))
    if doc and F.fresh(doc.get("at"), SHORT_TTL_H):
        return doc
    if q == OWNER_JQL and limit == 1:
        doc = F.read_json(os.path.join(F.store_dir("jira"), "owner.json"))
        return doc if doc and F.fresh(doc.get("at"), OWNER_TTL_H) else None
    for name, standing in STANDING.items():
        if q == standing:
            doc = F.read_json(os.path.join(F.store_dir("jira", "queries"), f"{name}.json"))
            if doc and F.fresh(doc.get("at")) and (limit <= doc.get("limit", 0) or len(doc.get("issues") or []) < doc.get("limit", 0)):
                return doc
    return None


def cmd_jql(creds, args):
    stored = None if args.fresh else stored_query(args.jql, args.limit)
    if stored is not None:
        issues, read_at = (stored.get("issues") or [])[: args.limit], stored.get("at")
        F.served("jira", read_at, "jql (standing query)")
    else:
        issues, read_at = search_rows(creds, args.jql, args.limit), datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        if F and " ".join(args.jql.split()) == OWNER_JQL and args.limit == 1:   # the owner-name query: once a day
            F.write_json(os.path.join(F.store_dir("jira"), "owner.json"), {"jql": OWNER_JQL, "limit": 1, "at": read_at, "issues": issues})
        elif F:                                                                  # any other search: once per pass
            F.write_json(_jql_path(" ".join(args.jql.split()), args.limit), {"jql": args.jql, "limit": args.limit, "at": read_at, "issues": issues})
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
            "due": (i.get("fields") or {}).get("duedate"),
        } for i in issues]
        print(json.dumps({"jql": args.jql, "count": len(rows), "issues": rows, "read_at": read_at},
                         ensure_ascii=False))
        return
    print(f"# {len(issues)} issue(s) for: {args.jql}\n")
    for i in issues:
        f = i.get("fields") or {}
        print(f"{i.get('key'):<10} [{name_of(f.get('status'), 'name'):<12}] "
              f"{name_of(f.get('assignee')):<16} {f.get('summary', '')}")


# ── find: a ticket named by what it is about ─────────────────────────────────
# A reference like "the 异步api ticket" rarely shares a word with the summary it means; the ticket it came from names
# the endpoint or identifier the other one uses. So find searches the caller's words and the source's vocabulary,
# and ranks: a caller's word weighs most, a key the source itself names adds.
ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_IDENT = re.compile(r"(?<![\w{])[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+(?![\w}])")
_PATH = re.compile(r"(?:https?://[^\s<>()`'\"]+|(?<![\w.])/[A-Za-z0-9_.{}\-/]+)")
FIND_WEIGHTS = {"phrase": 3, "term": 1, "about": 2, "named": 2, "owner": 1, "project": 1}


def _noise(piece):
    """An id, hex, version or templated piece: not vocabulary."""
    p = piece.lower()
    return (not p or "{" in p or "}" in p or len(re.findall(r"\d", p)) >= 3
            or re.fullmatch(r"v?\d+(?:\.\d+)*", p) is not None
            or (re.fullmatch(r"[0-9a-f]+", p) is not None and re.search(r"\d", p) is not None))


def context_terms(text, cap=10):
    """The source's own vocabulary: hyphen/underscore identifiers and the last literal segment of each URL path,
    lower-cased, ids/hex/versions/templated pieces and issue keys dropped, length ≥ 6, most frequent first."""
    text = text or ""
    counts, first = {}, {}
    def add(t):
        t = t.lower().strip("-_.")
        if len(t) < 6 or ISSUE_KEY.fullmatch(t.upper()) or any(_noise(p) for p in re.split(r"[-_]", t)):
            return
        counts[t] = counts.get(t, 0) + 1
        first.setdefault(t, len(first))
    for m in _PATH.finditer(text):
        path = m.group(0).split("?")[0].split("#")[0]
        if "://" in path:                                   # the host is not vocabulary
            path = path.split("://", 1)[1].partition("/")[2]
        segs = [s for s in path.split("/") if s]
        while segs and "{" in segs[-1]:                     # /graphs/{graphId} names "graphs"
            segs.pop()
        if len(segs) > 1 and not _noise(segs[-1]):          # a permalink ending in an id names nothing
            add(segs[-1])
    for m in _IDENT.finditer(text):
        add(m.group(0))
    return sorted(counts, key=lambda t: (-counts[t], first[t]))[:cap]


def mentioned_keys(text, own=None):
    """Issue keys the source text names, in order, without its own."""
    out = []
    for k in ISSUE_KEY.findall(text or ""):
        if k != own and k not in out:
            out.append(k)
    return out


def bridged_terms(text, phrases, terms):
    """{term: [phrase, ...]} for each source term written on the same line as a caller's word: the source translating
    the caller's word into its own vocabulary ("异步接口 `POST /api/v2.0/graph-submissions`")."""
    out = {}
    for line in (text or "").lower().splitlines():
        said = [p for p in phrases if p.lower() in line]
        for t in terms if said else []:
            if t in line:
                out.setdefault(t, [])
                out[t] += [p for p in said if p not in out[t]]
    return out


def _flat(s):
    return " ".join(re.sub(r"[-_]", " ", (s or "").lower()).split())


def rank_found(hits, mentioned, owner=None, project=None, bridges=None):
    """hits: {key: {"issue": search row, "phrases": [...], "terms": [...]}}. Score: caller's word ×3, source term ×1
    (×3 when bridged to a caller's word), its summary carries one +2, named by the source +2, the owner's own ticket +1,
    the source's project +1; each row carries `why`."""
    w, rows, bridges = FIND_WEIGHTS, [], bridges or {}
    for key, h in hits.items():
        f = (h.get("issue") or {}).get("fields") or {}
        phrases, terms = list(h.get("phrases") or []), list(h.get("terms") or [])
        score = w["phrase"] * len(phrases) + sum(w["phrase"] if t in bridges else w["term"] for t in terms)
        why = []
        if phrases:
            why.append("your words: " + ", ".join(phrases))
        if terms:
            why.append("source terms: " + ", ".join(t + (f" (≈{'/'.join(bridges[t])})" if t in bridges else "")
                                                     for t in terms))
        about = [x for x in phrases + terms if _flat(x) and _flat(x) in _flat(f.get("summary"))]
        if about:
            score += w["about"]; why.append("summary carries " + ", ".join(about))
        if key in (mentioned or []):
            score += w["named"]; why.append("named by the source")
        if owner and ((f.get("assignee") or {}).get("accountId") == owner):
            score += w["owner"]; why.append("yours")
        if project and key.split("-")[0] == project:
            score += w["project"]; why.append(f"in {project}")
        rows.append({"key": key, "score": score, "status": name_of(f.get("status"), "name"),
                     "assignee": name_of(f.get("assignee")), "summary": f.get("summary", ""), "why": why})
    return sorted(rows, key=lambda r: (-r["score"], r["key"]))


def _jql_str(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _text_search(creds, words, per, project=None):
    """One `text ~` search; an identifier is searched as a phrase. A term Jira rejects is skipped, not fatal."""
    q = f'"\\"{_jql_str(words)}\\""' if re.search(r"[-_]", words) else f'"{_jql_str(words)}"'
    jql = (f'project = "{_jql_str(project)}" AND ' if project else "") + f"text ~ {q} ORDER BY updated DESC"
    try:
        return search_rows(creds, jql, per)
    except SystemExit as exc:
        print(f"# skipped {words!r}: {exc}", file=sys.stderr)
        return []


def cmd_find(creds, args):
    phrases = [p for p in (args.phrases or []) if p.strip()]
    near = extract_key(args.near) if args.near else None
    if not phrases and not near:
        sys.exit("find needs words, --near KEY, or both")
    terms, mentioned, src_project, bridges = [], [], None, {}
    if near:
        doc = issue_doc(creds, near, comments=True, fresh=args.fresh)
        f = doc.get("fields") or {}
        text = "\n".join([f.get("summary") or "", body_text(f.get("description"))]
                         + [body_text(c.get("body")) for c in doc.get("comments") or []])
        terms = [t for t in context_terms(text) if t not in [p.lower() for p in phrases]]
        mentioned = mentioned_keys(text, near)
        bridges = bridged_terms(text, phrases, terms)
        src_project = near.split("-")[0]
    hits = {}
    def hit(issue, kind, word):
        k = issue.get("key")
        if not k or k == near:
            return
        h = hits.setdefault(k, {"issue": issue, "phrases": [], "terms": []})
        if word not in h[kind]:
            h[kind].append(word)
    for p in phrases:
        for i in _text_search(creds, p, args.per, args.project):
            hit(i, "phrases", p)
    for t in terms:
        for i in _text_search(creds, t, args.per, args.project):
            hit(i, "terms", t)
    missing = [k for k in mentioned if k not in hits]
    if missing:
        try:
            for i in search_rows(creds, f"key in ({', '.join(missing)})", len(missing)):
                hits.setdefault(i.get("key"), {"issue": i, "phrases": [], "terms": []})
        except SystemExit as exc:
            print(f"# named keys unread: {exc}", file=sys.stderr)
    owner = (api_get(creds, "/rest/api/3/myself") or {}).get("accountId")
    found = rank_found(hits, mentioned, owner, src_project, bridges)[: args.limit]
    if args.json:
        print(json.dumps({"phrases": phrases, "near": near, "terms": terms, "bridges": bridges, "mentioned": mentioned,
                          "found": found}, ensure_ascii=False))
        return
    tried = phrases + terms
    print(f"# find {' '.join(phrases)}" + (f" --near {near}" if near else ""))
    if terms:
        print(f"# source terms: {', '.join(terms)}")
    if bridges:
        print("# the source says your words as: " + ", ".join(f"{'/'.join(v)} → {t}" for t, v in bridges.items()))
    if mentioned:
        print(f"# named by the source: {', '.join(mentioned)}")
    print()
    if not found:
        print(f"nothing found for: {', '.join(tried) or '(no terms)'} — try the other language's word, "
              "or the endpoint/identifier the ticket would use")
        sys.exit(1)
    for r in found:
        print(f"{r['key']:<10} {r['score']:>3} [{r['status']}] {r['assignee']}  {r['summary']}")
        print(f"{'':<14} why: {'; '.join(r['why'])}")


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
    """Email or accountId → accountId; without either, the token's own account; `none` unassigns (an undo's
    reverse of an assignment to a ticket that had nobody)."""
    if who and who.lower() == "none":
        return None, "Unassigned"
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
              "before": {"assignee": cur.get("accountId"), "name": cur.get("displayName")},
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
    result["undo"] = undo_argv("assign", key, "--assignee", cur.get("accountId") or "none")
    record_act(key, "assign", result["before"], result["undo"], {"assignee": account_id})
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
    std = _standard_gate(args, args.type, result)

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
            print("\n".join(std))
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
    std = _standard_gate(args, "Sub-task", result)

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
            print("\n".join(std))
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
    if resp.get("id"):
        r["undo"] = undo_argv("comment-delete", key, "--id", resp["id"])
        record_act(key, "comment", {"comment": None}, r["undo"], {"comment": str(resp["id"])})
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
# A terminal status is the owner's own decision. ela proposes a close (Fixed In, comment, flag:closing, the ticket
# assigned to him) and performs the transition only on his explicit word, which the caller states with --terminal —
# so a close he does not know about cannot happen (conventions.md section Clean-up rules, 2026-10-21; the opt-in
# added 2026-10-22, MH-3645).
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


def _transition_one(creds, key, to, apply, path=False, terminal_ok=False):
    """Move one issue to `to`. Direct when Jira offers it; with `path`, along STATUS_PATH hop by hop. Stops, without
    writing, at a hop that needs a field, and at Review → Done while the assignee is in the product area — that is
    the product sign-off the status spec describes, and it is theirs to give. A terminal `to` is refused unless
    `terminal_ok`, the caller's statement that the owner named that status himself."""
    f = _issue(creds, key, "summary,status,assignee")
    cur = name_of(f.get("status"), "name")
    r = {"key": key, "from": cur, "to": to, "dry_run": not apply, "changed": False, "walked": []}
    if _norm(cur) == _norm(to):
        return r, [f"{key}: already {cur}"]
    if terminal(to) and not terminal_ok:
        r["error"] = f"{to} is a terminal status: refused unless the owner names it himself (pass --terminal) — otherwise propose it with `close` (the ticket is assigned to the owner for his decision)"
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
        note = "" if len(hops) == 1 else f"\n  (up to {len(hops)} hops, looked up live; it stops as soon as Jira offers {to}; the assignee is notified at every hop)"
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
        r, ls = _transition_one(creds, key, args.to, args.apply, path=args.path, terminal_ok=args.terminal)
        results.append(r); lines += ls
    if not args.apply and any("hops" in r and not r["changed"] for r in results):
        lines.append("pass --apply to transition")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)
    if any("error" in r for r in results):
        sys.exit(2)


# ── the label vocabulary: the values ela may write (elak map/jira-labels.yaml, read through the published map) ──
OPEN_NAMESPACES = ("release:", "pending-svc:")    # their values follow the release lines and the slug registry


def vocabulary():
    """{namespace: set of values} for the closed label namespaces, and {bare label: what it became}; None when the
    published map holds no vocabulary (then nothing is checked, and the dry run says so)."""
    try:
        site = json.load(open(os.path.expanduser("~/.claude/ela/site.json")))
        path = os.path.join(site.get("map") or "", "jira-labels.yaml")
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "release"))
        from release import _yaml_subset
        d = _yaml_subset(open(path, encoding="utf-8").read()) or {}
    except Exception:
        return None
    closed, bare = {}, {}
    for n in d.get("namespaces") or []:
        if n.get("prefix") == "bare":
            bare = {str(v.get("value")): (v.get("to") or v.get("action") or "retire") for v in n.get("values") or []}
        elif n.get("kind") == "label":
            closed[n["prefix"] + ":"] = {str(v.get("value")) for v in n.get("values") or [] if v.get("action") != "retire"}
    return {"closed": closed, "bare": bare}


def label_problems(labels, vocab):
    """Why each label may not be written: outside a closed namespace's values, a retired or renamed bare label, or a
    namespace the owner ruled out (customer: is the summary's [Account] bracket; feature is the component)."""
    out = []
    for x in labels:
        pre = x.split(":", 1)[0] + ":" if ":" in x else None
        if pre in OPEN_NAMESPACES:
            continue
        if pre == "customer:":
            out.append(f"{x}: no customer label; the customer is the summary's leading [Account] bracket")
        elif pre == "feat:":
            out.append(f"{x}: the feature is the ticket's component, not a label")
        elif pre in vocab["closed"]:
            if x not in vocab["closed"][pre]:
                out.append(f"{x}: not a {pre} value; the values: {', '.join(sorted(vocab['closed'][pre]))}")
        elif pre is None and x in vocab["bare"]:
            out.append(f"{x}: retired" + (f"; use {vocab['bare'][x]}" if vocab["bare"][x] not in ("retire", "rename") else ""))
        else:
            out.append(f"{x}: not in the vocabulary")
    return out


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
    # the reverse takes out exactly what was added and puts back what was taken, so a label someone else set since stays
    r["undo"] = undo_argv("label", key, *(["--remove", ",".join(to_add)] if to_add else []),
                          *(["--add", ",".join(to_rem), "--nonstandard", "restoring the labels before an act"] if to_rem else []))
    record_act(key, "label", {"labels": cur}, r["undo"], {"labels": [x for x in cur if x not in to_rem] + to_add})
    return r, [f"{key}: labels " + " ".join((["+" + x for x in to_add] + ["-" + x for x in to_rem]))]


# ── priority, due date and Fix Version: the fields the engineering rules keep true ──────────────────────

PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")


def _human_set(creds, key, field):
    """Whether a person (not an app or an automation) ever changed `field` on the issue: its changelog, newest first."""
    start, out = 0, False
    while True:
        page = api_get(creds, f"/rest/api/3/issue/{key}/changelog", {"startAt": start, "maxResults": 100})
        for h in page.get("values") or []:
            if (h.get("author") or {}).get("accountType") == "app":
                continue
            if any((i.get("field") or "").lower() == field for i in h.get("items") or []):
                out = True
        start += len(page.get("values") or [])
        if page.get("isLast", True) or not page.get("values"):
            return out


def _rule_comment(creds, key, text, apply):
    if text:
        _comment_one(creds, key, text, apply, mention=False)


def cmd_priority(creds, args):
    """Set the priority by rule. Raising is always allowed; lowering is refused when a person ever set the priority
    by hand (the changelog says so), since a rule never overrides that word. --why posts the rule as a comment."""
    want = next((p for p in PRIORITIES if p.lower() == args.to.lower()), None)
    if not want:
        sys.exit(f"priority: one of {', '.join(PRIORITIES)}")
    results, lines = [], []
    for key in _keys(args.targets):
        f = _issue(creds, key, "summary,priority")
        cur = (f.get("priority") or {}).get("name")
        r = {"key": key, "from": cur, "to": want, "dry_run": not args.apply, "changed": False}
        if cur == want:
            lines.append(f"{key}: priority already {want}"); results.append(r); continue
        lower = cur in PRIORITIES and PRIORITIES.index(want) > PRIORITIES.index(cur)
        if lower and _human_set(creds, key, "priority"):
            r["refused"] = "a person set this priority; a rule never lowers it"
            lines.append(f"{key}: refused — {cur} was set by a person; a rule only raises"); results.append(r); continue
        if not args.apply:
            lines.append(f"DRY RUN — {key}  {f.get('summary', '')}\n  priority {cur} → {want}" + (f"\n  comment: {args.why}" if args.why else ""))
            results.append(r); continue
        _request(creds, f"/rest/api/3/issue/{key}", payload={"fields": {"priority": {"name": want}}}, method="PUT")
        _rule_comment(creds, key, args.why, True)
        r["changed"] = True; results.append(r); lines.append(f"{key}: priority {cur} → {want}")
    if not args.apply and any(not r["changed"] and not r.get("refused") and r["from"] != r["to"] for r in results):
        lines.append("pass --apply to change the priority")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


def cmd_due(creds, args):
    """Set a missing due date by rule. A date already there is a person's commitment (or an earlier rule's, which a
    person may have kept): it is never moved; the same date is a no-op. --why posts the rule as a comment."""
    try:
        datetime.date.fromisoformat(args.date)
    except ValueError:
        sys.exit("due: --date YYYY-MM-DD")
    results, lines = [], []
    for key in _keys(args.targets):
        f = _issue(creds, key, "summary,duedate")
        cur = f.get("duedate")
        r = {"key": key, "from": cur, "to": args.date, "dry_run": not args.apply, "changed": False}
        if cur == args.date:
            lines.append(f"{key}: due already {cur}")
        elif cur:
            r["refused"] = "a due date is set; a rule never moves it"
            lines.append(f"{key}: refused — due {cur} is set; a rule never moves a date")
        elif not args.apply:
            lines.append(f"DRY RUN — {key}  {f.get('summary', '')}\n  due — → {args.date}" + (f"\n  comment: {args.why}" if args.why else ""))
        else:
            _request(creds, f"/rest/api/3/issue/{key}", payload={"fields": {"duedate": args.date}}, method="PUT")
            _rule_comment(creds, key, args.why, True)
            r["changed"] = True; lines.append(f"{key}: due → {args.date}")
        results.append(r)
    if not args.apply and any(not r["from"] for r in results):
        lines.append("pass --apply to set the due date")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


def _versions(creds, project):
    return api_get(creds, f"/rest/api/3/project/{project}/versions") or []


def cmd_version(creds, args):
    """Fix Versions, one atom: create (a no-op when the name exists), release (a no-op when released), set (adds the
    version to each issue's Fix Version; never removes one)."""
    vs = {v.get("name"): v for v in _versions(creds, args.project)}
    if args.act in ("create", "release"):
        if len(args.names) != 1:
            sys.exit(f"version {args.act}: one name")
        name = args.names[0]
        v = vs.get(name)
        if args.act == "create":
            r = {"name": name, "exists": bool(v), "dry_run": not args.apply, "created": False}
            if v:
                _emit(args, r, [f"version {name}: already exists"]); return
            if not args.apply:
                _emit(args, r, [f"DRY RUN — create version {name} in {args.project}" + (f", release date {args.release_date}" if args.release_date else ""),
                                "pass --apply to create"]); return
            pid = api_get(creds, f"/rest/api/3/project/{args.project}").get("id")
            body = {"name": name, "projectId": int(pid)}
            if args.release_date:
                body["releaseDate"] = args.release_date
            api_post(creds, "/rest/api/3/version", body)
            r["created"] = True
            _emit(args, r, [f"version {name}: created"]); return
        if not v:
            sys.exit(f"version release: no version {name!r} in {args.project}")
        r = {"name": name, "released": bool(v.get("released")), "dry_run": not args.apply, "changed": False}
        if v.get("released"):
            _emit(args, r, [f"version {name}: already released"]); return
        date = args.release_date or v.get("releaseDate") or datetime.date.today().isoformat()
        if not args.apply:
            _emit(args, r, [f"DRY RUN — release version {name}, date {date}", "pass --apply to release"]); return
        _request(creds, f"/rest/api/3/version/{v['id']}", payload={"released": True, "releaseDate": date}, method="PUT")
        r["changed"] = True
        _emit(args, r, [f"version {name}: released {date}"]); return
    if not args.name or args.name not in vs:
        sys.exit(f"version set: --name must be an existing version of {args.project} (create it first)")
    results, lines = [], []
    for key in _keys(args.names):
        f = _issue(creds, key, "summary,fixVersions")
        cur = [x.get("name") for x in f.get("fixVersions") or []]
        r = {"key": key, "fix_versions": cur, "add": args.name, "dry_run": not args.apply, "changed": False}
        if args.name in cur:
            lines.append(f"{key}: Fix Version already has {args.name}")
        elif not args.apply:
            lines.append(f"DRY RUN — {key}  {f.get('summary', '')}\n  Fix Version {', '.join(cur) or '(none)'} + {args.name}")
        else:
            _request(creds, f"/rest/api/3/issue/{key}", payload={"update": {"fixVersions": [{"add": {"name": args.name}}]}}, method="PUT")
            r["changed"] = True; lines.append(f"{key}: Fix Version + {args.name}")
        results.append(r)
    if not args.apply and any(args.name not in r["fix_versions"] for r in results):
        lines.append("pass --apply to add the Fix Version")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


def _split_csv(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def cmd_label(creds, args):
    """Add and/or remove labels. Idempotent: only the actual delta is written. An added label must be in the
    vocabulary (elak map/jira-labels.yaml); removing is always allowed. --nonstandard REASON overrides once."""
    add, rem = _split_csv(args.add), _split_csv(args.remove)
    if not add and not rem:
        sys.exit("label: nothing to do — pass --add and/or --remove")
    vocab = vocabulary()
    problems = label_problems(add, vocab) if vocab else []
    if problems:
        print("label vocabulary:\n  " + "\n  ".join(problems), file=sys.stderr)
        if args.apply and not getattr(args, "nonstandard", None):
            sys.exit("label: refused — fix the values, or pass --nonstandard '<reason>'")
    elif vocab is None:
        print("label vocabulary: not found in the published map; values not checked", file=sys.stderr)
    results, lines = [], []
    for key in _keys(args.targets):
        r, ls = _label_one(creds, key, add, rem, args.apply)
        results.append(r); lines += ls
    if not args.apply and any(r["add"] or r["remove"] for r in results):
        lines.append("pass --apply to change labels")
    _emit(args, {"results": results} if len(results) > 1 else results[0], lines)


def _link_types(creds):
    return api_get(creds, "/rest/api/3/issueLinkType").get("issueLinkTypes") or []


def resolve_link(types, phrase):
    """'blocks' | 'is blocked by' | 'contains' | 'is contained in' | a type name → (type, direction). The phrase
    decides the direction for every type: 'outward' means <key> <outward phrase> <other>, 'inward' the reverse. A
    phrase is matched before a type name, so a name that happens to equal one side's phrase cannot flip it."""
    for t in types:
        if _norm(phrase) == _norm(t["outward"]):
            return t, "outward"
        if _norm(phrase) == _norm(t["inward"]):
            return t, "inward"
    for t in types:
        if _norm(phrase) == _norm(t["name"]):
            return t, "outward"
    return None, None


def link_plan(t, direction, key, other):
    """What one link writes and how Jira will show it. Jira's POST /issueLink reads 'inwardIssue <outward phrase>
    outwardIssue' (the reverse of the issuelinks a GET returns, where an outwardIssue entry on X reads 'X <outward>
    Y'): so <key> <outward> <other> posts key as inwardIssue. `reads` is the sentence on <key>, `target_reads` the
    same link as <other> shows it."""
    src, dst = (key, other) if direction == "outward" else (other, key)     # src <outward> dst
    phrase = t["outward"] if direction == "outward" else t["inward"]
    back = t["inward"] if direction == "outward" else t["outward"]
    return {"payload": {"type": {"name": t["name"]}, "inwardIssue": {"key": src}, "outwardIssue": {"key": dst}},
            "reads": f"{key} {phrase} {other}", "target_reads": f"{other} {back} {key}"}


def link_exists(links, t, direction, other):
    """The existing link of type t joining <key> to <other> in that direction, from <key>'s issuelinks (GET form)."""
    for l in links or []:
        if (l.get("type") or {}).get("name") != t["name"]:
            continue
        o = (l.get("outwardIssue") or {}).get("key"); i = (l.get("inwardIssue") or {}).get("key")
        if (direction == "outward" and o == other) or (direction == "inward" and i == other):
            return l
    return None


def cmd_link(creds, args):
    """Link <key> to <other>: '<key> <phrase> <other>'. Idempotent per (type, pair, direction)."""
    key, other = extract_key(args.target), extract_key(args.other)
    types = _link_types(creds)
    t, direction = resolve_link(types, args.type)
    if not t:
        names = ", ".join(f"{x['name']} ({x['outward']} / {x['inward']})" for x in types
                          if "WBSGantt" not in x["name"] or x["outward"] == "contains")
        sys.exit(f"link: unknown type or phrase {args.type!r}; use one of: {names}")
    f = _issue(creds, key, "summary,issuelinks")
    exists = link_exists(f.get("issuelinks"), t, direction, other)
    plan = link_plan(t, direction, key, other)
    r = {"key": key, "other": other, "type": t["name"], "reads": plan["reads"], "target_reads": plan["target_reads"],
         "dry_run": not args.apply, "created": False, "existing_link_id": (exists or {}).get("id")}
    if exists:
        _emit(args, r, [f"{plan['reads']}: link already exists"]); return
    if not args.apply:
        _emit(args, r, [f"DRY RUN — {plan['reads']}  ({t['name']})",
                        f"  on {other} Jira will show: {plan['target_reads']}", "pass --apply to link"]); return
    api_post(creds, "/rest/api/3/issueLink", plan["payload"])
    after = link_exists(_issue(creds, key, "issuelinks").get("issuelinks"), t, direction, other)
    r["created"] = True
    if not after:                                       # read back: a reversed link is named, never reported as done
        r["created"] = False; r["error"] = "the link Jira holds does not read as asked; check both issues"
        _emit(args, r, [f"WRONG — Jira does not show {plan['reads']}; check {key} and {other}"]); sys.exit(1)
    r["link_id"] = after.get("id")
    if r["link_id"]:
        r["undo"] = undo_argv("unlink", key, "--id", r["link_id"])
        record_act(key, "link", {"link": None, "reads": plan["reads"]}, r["undo"], {"link": str(r["link_id"])})
    _emit(args, r, [f"linked: {plan['reads']} (on {other}: {plan['target_reads']})"])


# ── the reverse atoms: what undoes an act, each a dry run until --apply ───────────────────────

def cmd_unlink(creds, args):
    """Remove one issue link by its id, from the issue it joins: the reverse of `link`. The dry run reads the link as
    Jira shows it on <key>; a link already gone is a no-op; an id that does not join <key> is refused."""
    key = extract_key(args.target)
    f = _issue(creds, key, "summary,issuelinks")
    l = next((x for x in f.get("issuelinks") or [] if str(x.get("id")) == str(args.id)), None)
    r = {"key": key, "id": str(args.id), "dry_run": not args.apply, "removed": False}
    if l is None:
        _emit(args, r, [f"{key}: no link {args.id} — already gone"]); return
    t = l.get("type") or {}
    o = l.get("outwardIssue") or l.get("inwardIssue") or {}
    reads = f"{key} {t.get('outward') if l.get('outwardIssue') else t.get('inward')} {o.get('key')}"
    r.update(reads=reads, other=o.get("key"), type=t.get("name"))
    if not args.apply:
        _emit(args, r, [f"DRY RUN — unlink {reads}  ({t.get('name')}, id {args.id})", "pass --apply to unlink"]); return
    _request(creds, f"/rest/api/3/issueLink/{args.id}", method="DELETE")
    r["removed"] = True
    _emit(args, r, [f"unlinked: {reads}"])


def own_comment(cid):
    """Whether ela posted comment `cid`: an act on record names it. A comment the owner typed himself, under the same
    account, is never deleted by ela."""
    return any(str((a.get("after") or {}).get("comment")) == str(cid) for a in acts_rows() if a.get("verb") == "comment")


def cmd_comment_delete(creds, args):
    """Delete one comment ela posted (an act on record names it, and this account wrote it): the reverse of a comment.
    Anyone else's comment, and his own typed under the same account, is refused. Already gone is a no-op."""
    key = extract_key(args.target)
    c = next((x for x in fetch_comments(creds, key) if str(x.get("id")) == str(args.id)), None)
    r = {"key": key, "id": str(args.id), "dry_run": not args.apply, "removed": False}
    if c is None:
        _emit(args, r, [f"{key}: no comment {args.id} — already gone"]); return
    me = _request(creds, "/rest/api/3/myself") or {}
    if (c.get("author") or {}).get("accountId") != me.get("accountId"):
        sys.exit(f"comment-delete: refused — comment {args.id} on {key} is {name_of(c.get('author'))}'s, not this account's")
    if not own_comment(args.id):
        sys.exit(f"comment-delete: refused — no act on record posted comment {args.id}; ela deletes only its own comments")
    text = body_text(c.get("body"))
    r["text"] = text
    if not args.apply:
        _emit(args, r, [f"DRY RUN — delete comment {args.id} on {key} ({(c.get('created') or '')[:16]}):",
                        "  " + text.replace("\n", "\n  "), "pass --apply to delete"]); return
    _request(creds, f"/rest/api/3/issue/{key}/comment/{args.id}", method="DELETE")
    r["removed"] = True
    _emit(args, r, [f"{key}: comment {args.id} deleted"])


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
    if new and not gone:                                  # an append's reverse takes out exactly the entries it added
        r["undo"] = undo_argv("fixed-in", key, "--remove", "; ".join(new))
    elif gone and not new:                                # a removal's reverse appends them again
        r["undo"] = undo_argv("fixed-in", key, "--add", "; ".join(gone))
    if r.get("undo"):
        record_act(key, "fixed-in", {"fixed_in": r["current"]}, r["undo"], {"fixed_in": r["value"]})
    return r, [f"{key}: Fixed In = {r['value']}"]


def _fixed_in_vocabulary():
    """(known slugs, docker resolver) from the fixed-in skill, which reads the published map; None when it cannot load."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "fixedin"))
        import fixedin as F
        return F.known_slugs(), F.resolve_docker
    except Exception:  # noqa: BLE001 — no map: the grammar alone still applies
        return None


def fixed_in_problem(entry, known=None, resolve_docker=None):
    """Why `entry` breaks the release map's Fixed In grammar (map/release.yaml fixed_in), or None.
    A docker entry is `mds-<slug>@<image>:<tag>` with the image mandatory; a SaaS entry is `<slug>@<version>` with a
    slug the map knows. An image name in the slug's place passes the shape check (MH-3829, 2026-11-02), so the slug is
    checked against the map and the docker form is suggested from the image index."""
    if not FIXED_IN_ENTRY.match(entry):
        return "not <slug>@<version>"
    slug, ver = entry.split("@", 1)
    if slug.startswith("mds-") and ":" not in ver:
        return "a docker entry is mds-<slug>@<image>:<tag>; the image is missing"
    if ":" in ver and not slug.startswith("mds-"):
        return "an <image>:<tag> version belongs to an mds- slug"
    if known is not None and slug not in known:
        hint = resolve_docker(f"{slug}:{ver}") if resolve_docker else []
        if hint:
            return "a docker image is not a slug; write " + " or ".join(f"{s}@{t}" for s, t in hint)
        return "slug not in the release map"
    return None


def _fixed_in_args(text):
    """The entries to add, each checked against the map's grammar; `--remove` is not checked, so a grandfathered or
    wrong entry can always be taken out."""
    add = fixed_in_entries(text)
    if not add:
        sys.exit("fixed-in: entries must be <slug>@<version>; none given")
    vocab = _fixed_in_vocabulary()
    known, resolver = vocab if vocab else (None, None)
    bad = [(e, p) for e in add if (p := fixed_in_problem(e, known, resolver))]
    if bad:
        sys.exit("fixed-in: refused\n" + "\n".join(f"  {e}: {p}" for e, p in bad))
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
    replace = bool(getattr(args, "replace", False))
    if dup and not replace:
        _emit(args, r, [f"{key}: {name} is already attached (id {dup.get('id')}, {short_date(dup.get('created'))}) — skipped (--replace deletes it and uploads this file)"]); return
    if not args.apply:
        _emit(args, r, [f"DRY RUN — attach {name} ({size} bytes) to {key}  {f.get('summary','')}"
                        + (f"; replaces attachment id {dup.get('id')} ({dup.get('size')} bytes, {short_date(dup.get('created'))}), which is deleted first" if dup else ""), "pass --apply to upload"]); return
    if dup:
        # --replace: a corrected record under the same name (the comment names the file) — the old copy goes first,
        # so the issue never shows two files of one name (MH-3722, 2026-10-22: a PDF printed without its screenshots).
        _request(creds, f"/rest/api/3/attachment/{dup.get('id')}", method="DELETE"); r["replaced"] = dup.get("id")
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
    log_write("jira", "POST", f"/rest/api/3/issue/{key}/attachments")
    r["uploaded"], r["attachment_id"] = True, (out[0].get("id") if out else None)
    _emit(args, r, [f"{key}: attached {name} (id {r['attachment_id']})" + (f", replacing id {r['replaced']}" if r.get("replaced") else "")])


def cmd_detach(creds, args):
    """Remove one attachment from one issue — the dry run names it; --apply deletes. Only an attachment uploaded by
    this token's own account (ela writes as the owner), so a reporter's evidence is never removed. Already gone is a
    no-op. Added 2026-11-10: a superseded copy of a report (MH-3983 carried the .md and the .pdf of one report)."""
    key = extract_key(args.target)
    f = _issue(creds, key, "summary,attachment")
    att = next((a for a in f.get("attachment") or [] if str(a.get("id")) == str(args.id)), None)
    r = {"key": key, "id": str(args.id), "dry_run": not args.apply, "removed": False}
    if att is None:
        _emit(args, r, [f"{key}: no attachment id {args.id} — nothing to remove"]); return
    me = _request(creds, "/rest/api/3/myself") or {}
    if (att.get("author") or {}).get("accountId") != me.get("accountId"):
        sys.exit(f"detach: refused — attachment {args.id} ({att.get('filename')}) was uploaded by "
                 f"{(att.get('author') or {}).get('displayName', '?')}, not by this account; it is theirs to remove")
    r["file"] = att.get("filename")
    if not args.apply:
        _emit(args, r, [f"DRY RUN — remove {att.get('filename')} (id {args.id}, {att.get('size')} bytes, "
                        f"{short_date(att.get('created'))}) from {key}  {f.get('summary','')}", "pass --apply to remove"]); return
    _request(creds, f"/rest/api/3/attachment/{args.id}", method="DELETE")
    r["removed"] = True
    _emit(args, r, [f"{key}: removed {att.get('filename')} (id {args.id})"])


# ── describe: the description, rewritten in the Markdown subset ──────────────

def cmd_retitle(creds, args):
    """Replace one issue's summary. Dry run prints was / now; --apply writes; the same summary is a no-op. A
    sub-task's title still carries exactly one layer token, the rule create-subtask enforces."""
    title = args.summary.strip()
    if not title:
        sys.exit("retitle: empty summary")
    key = extract_key(args.target)
    f = _issue(creds, key, "summary,issuetype")
    before = f.get("summary") or ""
    err = validate_summary(title) if (f.get("issuetype") or {}).get("subtask") else None
    if err:
        sys.exit(f"retitle: {err}")
    r = {"key": key, "dry_run": not args.apply, "changed": False, "from": before, "to": title}
    if before.strip() == title:
        _emit(args, r, [f"{key}: summary already reads so"]); return
    if not args.apply:
        _emit(args, r, [f"DRY RUN — retitle {key}", f"  was  {before}", f"  now  {title}", "pass --apply to write"]); return
    _request(creds, f"/rest/api/3/issue/{key}", payload={"fields": {"summary": title}}, method="PUT")
    r["changed"] = True
    _emit(args, r, [f"{key}: summary replaced"])


def cmd_describe(creds, args):
    """Replace one issue's description from a file (the Markdown subset: headings, bullets, numbered lists, bold,
    code, links, a --- fold). Dry run prints the current text and the new text rendered; --apply writes. Links the
    original author posted must be carried into the new text by the caller — the atom does not merge."""
    text = _read_text(args)
    if not text.strip():
        sys.exit("describe: empty text")
    key = extract_key(args.target)
    f = _issue(creds, key, "summary,description,issuetype")
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
        missing, _ = description_standard(((f.get("issuetype") or {}).get("name")) or "Task", text)
        if missing:
            lines.append(f"  standard   missing: {', '.join(missing)} (information only: a rewrite keeps the author's shape)")
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
    if getattr(args, "terminal", False) and len(_keys(args.targets)) > 1:
        print("refused: a close the owner names is one ticket per confirm; name the tickets one at a time", file=sys.stderr); sys.exit(2)
    for key in _keys(args.targets):
        f = _issue(creds, key, "summary,status,assignee,labels")
        assignee = f.get("assignee") or {}
        named = bool(getattr(args, "terminal", False))
        how = (f"closing to {args.to} on your word" if named else f"proposed for closing → {CLOSING_FLAG}, assigned to you")
        steps, out = [], [f"== {key}  {f.get('summary','')}  [{name_of(f.get('status'), 'name')}; {how}; assignee now {name_of(assignee)}]"]
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
        # When the owner named this close himself (--terminal, one ticket per confirm), the bundle performs it: the
        # evidence and the comment, then the transition, and no flag or reassignment, which exist only for a proposal.
        plan.append(("labels", lambda k=key: _label_one(creds, k, labels + ([] if named else [CLOSING_FLAG]), [], args.apply)))
        plan.append(("comment", lambda k=key: _comment_one(creds, k, text, args.apply, mention=not args.no_mention)))
        if named:
            plan.append(("transition", lambda k=key: _transition_one(creds, k, args.to, args.apply, path=True, terminal_ok=True)))
        else:
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
        lines.append("pass --apply to write all of the above, in this order"
                     + ("" if getattr(args, "terminal", False) else "; the status itself is the owner's click in Jira"))
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
    p.add_argument("--fresh", action="store_true", help="read Jira now instead of the store's copy")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("files", help="download an issue's attachments — a screenshot is the evidence")
    p.add_argument("target", help="issue key or browse URL")
    p.add_argument("--id", help="one attachment id, as printed by `read`")
    p.add_argument("--out", help="directory (default <runtime>/jira-files)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_files)

    p = sub.add_parser("projects", help="every project key the account can see (read-only)")
    p.add_argument("--fresh", action="store_true", help="read Jira now instead of the store's list")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("changes", help="tickets changed since a time, each with its status/priority/assignee/label/"
                                         "Fixed In moves and the comments in the window — read-only")
    p.add_argument("--since", default="-1d", help="JQL relative date (-1d, -72h) or 'YYYY-MM-DD HH:MM' (default -1d)")
    p.add_argument("--project", default="MH"); p.add_argument("--limit", type=int, default=400)
    p.add_argument("--fresh", action="store_true", help="read Jira now instead of the store's sweep")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_changes)

    p = sub.add_parser("jql", help="search; key/status/assignee/summary rows")
    p.add_argument("jql")
    p.add_argument("--limit", type=int, default=50, help="max rows; pages of 100 are followed up to this")
    p.add_argument("--fresh", action="store_true", help="a standing query: read Jira now instead of the store")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_jql)

    p = sub.add_parser("find", help="a ticket named by what it is about: the words, and --near the ticket the "
                                    "reference came from (its endpoints, identifiers, named keys); ranked — read-only")
    p.add_argument("phrases", nargs="*", metavar="PHRASE", help="the caller's words, both languages (异步 async)")
    p.add_argument("--near", metavar="KEY", help="the ticket the reference came from; its vocabulary is searched too")
    p.add_argument("--project", help="restrict every search to one project")
    p.add_argument("--per", type=int, default=20, help="rows read per search (default 20)")
    p.add_argument("--limit", type=int, default=10, help="rows printed (default 10)")
    p.add_argument("--fresh", action="store_true", help="read the --near ticket now instead of the store's copy")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser(
        "assign", help="re-assign one issue — dry-run unless --apply")
    p.add_argument("target", help="issue key or browse URL")
    p.add_argument("--assignee", required=True, help="email, accountId, me, or none (unassign)")
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
                   help="Markdown subset: # headings, - and 1. lists, **bold**, `code`, [text](url), bare URLs; "
                        "a --- line folds what follows into a collapsed block")
    p.add_argument("--assignee",
                   help="assignee email or accountId "
                        "(default: the token's own account)")
    p.add_argument("--apply", action="store_true",
                   help="actually create; without it, validate and report only")
    p.add_argument("--json", action="store_true")
    p.add_argument("--nonstandard", metavar="REASON",
                   help="create although the description lacks the sections its type requires; the reason is printed")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser(
        "create-subtask",
        help="create one subtask under a parent — dry-run unless --apply")
    p.add_argument("--parent", required=True, help="parent issue key")
    p.add_argument("--summary", required=True,
                   help="'[Token] action' — token from the seven-layer vocabulary")
    p.add_argument("--description",
                   help="Markdown subset: # headings, - and 1. lists, **bold**, `code`, [text](url), bare URLs; "
                        "a --- line folds what follows into a collapsed block")
    p.add_argument("--assignee",
                   help="assignee email or accountId "
                        "(default: the token's own account)")
    p.add_argument("--issuetype", default="Sub-task",
                   help="issue type name (default Sub-task; MH verified id 10124)")
    p.add_argument("--apply", action="store_true",
                   help="actually create; without it, validate and report only")
    p.add_argument("--json", action="store_true")
    p.add_argument("--nonstandard", metavar="REASON",
                   help="create although the description lacks the sections its type requires; the reason is printed")
    p.set_defaults(func=cmd_create_subtask)

    p = sub.add_parser("comment", help="post one comment to one or more issues (Markdown subset: bold, code, links, bullets, numbered; @name mentions; a --- line folds the rest) — dry-run unless --apply; identical text is not re-posted; --edit <id> replaces one")
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
    p.add_argument("--terminal", action="store_true", help="allow a terminal status (Done, Cancelled, Failed, Closed Ambigous): the owner named it himself; without it such a target is refused")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_transition)

    p = sub.add_parser("label", help="add/remove labels — dry-run unless --apply; only the delta is written")
    p.add_argument("targets", nargs="+"); p.add_argument("--add", help="comma-separated"); p.add_argument("--remove", help="comma-separated")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.add_argument("--nonstandard", metavar="REASON", help="write a label outside the vocabulary, once, saying why")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("priority", help="set the priority by rule — dry-run unless --apply; raises always, never lowers one a person set")
    p.add_argument("targets", nargs="+"); p.add_argument("--to", required=True, help="Highest · High · Medium · Low · Lowest")
    p.add_argument("--why", help="the rule, posted as a comment with the change")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_priority)

    p = sub.add_parser("due", help="set a missing due date by rule — dry-run unless --apply; never moves a date already set")
    p.add_argument("targets", nargs="+"); p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--why", help="the rule, posted as a comment with the change")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_due)

    p = sub.add_parser("version", help="Fix Versions: create · release · set (additive) — dry-run unless --apply")
    p.add_argument("act", choices=("create", "release", "set"))
    p.add_argument("names", nargs="+", help="create/release: the version name · set: issue keys")
    p.add_argument("--name", help="set: the version to add"); p.add_argument("--release-date", help="YYYY-MM-DD")
    p.add_argument("--project", default="MH")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("link", help="link two issues — dry-run unless --apply; an existing link of that type is a no-op")
    p.add_argument("target"); p.add_argument("other")
    p.add_argument("--type", required=True, help='link type or phrase: Relates · Blocks · "is blocked by" · Duplicate · Cloners · "contains" · "is contained in" · "implements"')
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("unlink", help="remove one link by id (the reverse of link) — dry-run unless --apply; already gone is a no-op")
    p.add_argument("target"); p.add_argument("--id", required=True, help="the link id, as the act recorded it")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_unlink)

    p = sub.add_parser("comment-delete", help="delete one comment ela posted (an act on record names it) — dry-run unless --apply; anyone else's is refused")
    p.add_argument("target"); p.add_argument("--id", required=True, help="the comment id, as the act recorded it")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_comment_delete)

    p = sub.add_parser("fixed-in", help="append entries to Fixed In — dry-run unless --apply; present entries are skipped, none removed")
    p.add_argument("targets", nargs="+", help="issue keys or browse URLs")
    p.add_argument("--add", help="'<slug>@<version>[; <slug>@<version> …]' in the release map's grammar")
    p.add_argument("--remove", help="entries to take out — only for a value that should never have been written")
    p.add_argument("--clear", action="store_true", help="empty the field — same rule as --remove")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fixed_in)

    p = sub.add_parser("attach", help="attach one file to an issue — dry-run names file and size; --apply uploads; a same-named attachment is a no-op")
    p.add_argument("--replace", action="store_true", help="a same-named attachment is deleted first, then this file uploaded (default: same name = no-op)")
    p.add_argument("target"); p.add_argument("file"); p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_attach)
    p = sub.add_parser("detach", help="remove one attachment this account uploaded — dry-run names it; --apply deletes; already gone is a no-op")
    p.add_argument("target"); p.add_argument("--id", required=True); p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_detach)

    p = sub.add_parser("describe", help="replace an issue's description from a file in the Markdown subset — dry-run shows was/now and any link the new text drops; --apply writes")
    p.add_argument("target"); p.add_argument("--from-file", required=True); p.add_argument("--allow-dropped-links", action="store_true")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("retitle", help="replace an issue's summary — dry-run shows was/now; --apply writes; the same summary is a no-op")
    p.add_argument("target"); p.add_argument("--summary", required=True)
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_retitle)

    p = sub.add_parser("close", help="propose a close: Fixed In + labels + comment + flag:closing + the ticket assigned to you; the status is your own click in Jira — dry-run unless --apply")
    p.add_argument("targets", nargs="+", help="issue keys or browse URLs")
    p.add_argument("--fixed-in", help="'<slug>@<version>[; …]' to append (release map grammar)")
    p.add_argument("--label", help="comma-separated labels to add, e.g. release:mh-2.0,release:mh-2.1")
    p.add_argument("--text", help="the closing comment; `@name` mentions resolve through the roster; a `---` line starts the collapsed technical part")
    p.add_argument("--from-file", help="read the comment from a file instead")
    p.add_argument("--allow-no-comment", action="store_true", help="propose without a comment (normally refused: the assignee and the reporter must see why)")
    p.add_argument("--no-mention", action="store_true")
    p.add_argument("--terminal", action="store_true", help="the owner named this close himself: perform it (evidence, comment, then the "
                   "transition to --to), one ticket per confirm; without it the close stays a proposal")
    p.add_argument("--to", default="Done", help="the terminal status with --terminal (default Done; Cancelled, Failed, Closed Ambigous)")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_close)

    args = ap.parse_args()
    # An unattended session (ela-runner's headless job, ELA_NO_APPLY=1) may read and dry-run, never write:
    # the owner's word for a write is given in the Slack thread and executed by the runner, not by a model.
    if os.environ.get("ELA_NO_APPLY") and getattr(args, "apply", False):
        print("refused: --apply inside an unattended session (ELA_NO_APPLY); the dry run above is the answer, the owner's word applies it", file=sys.stderr); sys.exit(2)
    creds = load_env(args.env_file)
    args.func(creds, args)


if __name__ == "__main__":
    main()
