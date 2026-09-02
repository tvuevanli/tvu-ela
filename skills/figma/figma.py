#!/usr/bin/env python3
"""Figma capability — read-only. Stdlib only.

L1 atomic CLI: deterministic, no LLM, callable by anything. Credentials are
site state resolved from the environment or an env file (FIGMA_TOKEN).

Usage:
    figma.py me
    figma.py file <url-or-key> [--depth N] [--json]
    figma.py node <url-with-node-id | key> [--id 12:34] [--json]
    figma.py comments <url-or-key> [--json]
    figma.py image <url-with-node-id | key> [--id 12:34] [--format png]
             [--scale 2] [--out DIR]

Accepts full figma.com URLs (file/design/board/proto); a `node-id=12-34`
query parameter is understood as node id 12:34. Read-only by design: every
call is a GET; `image` renders via Figma's export endpoint and can download
the result, it never modifies the document.

Exit codes: 0 ok, 1 API/transport error, 2 usage error.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.figma.com"
ENV_KEYS = ("FIGMA_TOKEN",)


def load_env(env_file):
    creds = {k: os.environ.get(k) for k in ENV_KEYS}
    path = env_file or os.environ.get("FIGMA_ENV_FILE") or os.environ.get("ELA_ENV_FILE")
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
    if not creds.get("FIGMA_TOKEN"):
        sys.exit("missing FIGMA_TOKEN — set it in the environment, "
                 "or pass --env-file / $FIGMA_ENV_FILE (run /ela:setup).")
    return creds


def api_get(creds, path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "X-Figma-Token": creds["FIGMA_TOKEN"],
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        sys.exit(f"figma {path} failed: HTTP {exc.code} {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"figma {path} failed: {exc}")


def parse_target(target):
    """URL or bare key → (file_key, node_id or None). node-id=12-34 → 12:34."""
    m = re.search(r"figma\.com/(?:file|design|board|proto)/([A-Za-z0-9]+)",
                  target)
    if m:
        key = m.group(1)
        node = None
        q = urllib.parse.urlparse(target).query
        nid = (urllib.parse.parse_qs(q).get("node-id") or [None])[0]
        if nid:
            node = nid.replace("-", ":")
        return key, node
    if re.fullmatch(r"[A-Za-z0-9]{10,}", target):
        return target, None
    sys.exit(f"cannot find a Figma file key in {target!r}")


def node_id_of(args):
    key, url_node = parse_target(args.target)
    node = args.id or url_node
    if not node:
        print("no node id: pass --id 12:34 or a URL with node-id=", file=sys.stderr)
        sys.exit(2)
    return key, node.replace("-", ":")


# ── rendering ────────────────────────────────────────────────────────────────

def walk(node, depth, max_depth, out):
    name = node.get("name", "")
    ntype = node.get("type", "")
    line = f"{'  ' * depth}{node.get('id', ''):<12} {ntype:<18} {name}"
    if ntype == "TEXT" and node.get("characters"):
        chars = " ".join(node["characters"].split())
        line += f'  "{chars[:80]}"'
    out.append(line)
    if depth < max_depth:
        for c in node.get("children") or []:
            walk(c, depth + 1, max_depth, out)


def collect_text(node, acc):
    if node.get("type") == "TEXT" and node.get("characters"):
        acc.append(node["characters"])
    for c in node.get("children") or []:
        collect_text(c, acc)


# ── subcommands ──────────────────────────────────────────────────────────────

def cmd_me(creds, args):
    d = api_get(creds, "/v1/me")
    print(f"ok  {d.get('handle')}  {d.get('email')}")


def cmd_file(creds, args):
    key, _ = parse_target(args.target)
    d = api_get(creds, f"/v1/files/{key}", {"depth": args.depth})
    if args.json:
        print(json.dumps(d, ensure_ascii=False))
        return
    print(f"{d.get('name')}   (key {key})")
    print(f"lastModified {d.get('lastModified')}   version {d.get('version')}")
    doc = d.get("document") or {}
    out = []
    for page in doc.get("children") or []:
        walk(page, 0, args.depth - 1, out)
    print("\n".join(out))
    print(f"\n(depth {args.depth} — deeper: --depth N, one node: "
          f"figma.py node <url> --id <id>)")


def cmd_node(creds, args):
    key, node = node_id_of(args)
    d = api_get(creds, f"/v1/files/{key}/nodes", {"ids": node})
    entry = (d.get("nodes") or {}).get(node)
    if not entry:
        sys.exit(f"node {node} not found in {key}")
    doc = entry.get("document") or {}
    if args.json:
        print(json.dumps(entry, ensure_ascii=False))
        return
    out = []
    walk(doc, 0, args.depth, out)
    print("\n".join(out))
    texts = []
    collect_text(doc, texts)
    if texts:
        print(f"\n--- text content ({len(texts)}) ---")
        for t in texts:
            print(f"  {' '.join(t.split())[:160]}")


def cmd_comments(creds, args):
    key, _ = parse_target(args.target)
    d = api_get(creds, f"/v1/files/{key}/comments")
    comments = d.get("comments") or []
    if args.json:
        print(json.dumps(d, ensure_ascii=False))
        return
    print(f"# {len(comments)} comment(s) on {key}\n")
    for c in comments:
        who = (c.get("user") or {}).get("handle", "?")
        when = (c.get("created_at") or "")[:16].replace("T", " ")
        mark = "resolved" if c.get("resolved_at") else "open"
        reply = f" ↳ reply to {c['parent_id']}" if c.get("parent_id") else ""
        print(f"[{when}] {who} ({mark}){reply}")
        print(f"  {c.get('message', '')}\n")


def cmd_image(creds, args):
    key, node = node_id_of(args)
    d = api_get(creds, f"/v1/images/{key}", {
        "ids": node, "format": args.format, "scale": args.scale,
    })
    if d.get("err"):
        sys.exit(f"figma image render failed: {d['err']}")
    url = (d.get("images") or {}).get(node)
    if not url:
        sys.exit(f"no image rendered for node {node}")
    if not args.out:
        print(url)
        return
    os.makedirs(args.out, exist_ok=True)
    dest = os.path.join(args.out,
                        f"{key}-{node.replace(':', '-')}.{args.format}")
    with urllib.request.urlopen(url, timeout=120) as resp, \
            open(dest, "wb") as fh:
        fh.write(resp.read())
    print(dest)


def main():
    ap = argparse.ArgumentParser(description="Figma capability, read-only.")
    ap.add_argument("--env-file", help="file with FIGMA_TOKEN")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("me", help="probe the token (who am I)")
    p.set_defaults(func=cmd_me)

    p = sub.add_parser("file", help="file summary: pages and frames tree")
    p.add_argument("target", help="figma.com URL or file key")
    p.add_argument("--depth", type=int, default=2,
                   help="tree depth fetched (default 2: pages + top frames)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_file)

    p = sub.add_parser("node", help="one node's subtree + its text content")
    p.add_argument("target", help="URL (node-id honoured) or file key")
    p.add_argument("--id", help="node id, 12:34 or 12-34")
    p.add_argument("--depth", type=int, default=6,
                   help="printed tree depth (default 6)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_node)

    p = sub.add_parser("comments", help="all comments on a file")
    p.add_argument("target", help="figma.com URL or file key")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_comments)

    p = sub.add_parser("image", help="render a node; prints the URL or saves")
    p.add_argument("target", help="URL (node-id honoured) or file key")
    p.add_argument("--id", help="node id, 12:34 or 12-34")
    p.add_argument("--format", default="png",
                   choices=["png", "jpg", "svg", "pdf"])
    p.add_argument("--scale", type=float, default=2)
    p.add_argument("--out", help="download into this directory")
    p.set_defaults(func=cmd_image)

    args = ap.parse_args()
    creds = load_env(args.env_file)
    args.func(creds, args)


if __name__ == "__main__":
    main()
