#!/usr/bin/env python3
"""Read and write documents in the TVU knowledge base (Outline).

The capability is shareable; the credentials are site state resolved from the environment or an
env file. Stdlib only.

Usage:
    kb.py search 'srt listener'
    kb.py read https://kb.tvunetworks.com/doc/design-audio-remapping-0aa0ItyDui
    kb.py tree                                  # collections
    kb.py tree 'MediaHub & UR'                  # document tree of a collection
    kb.py write '[DESIGN] Foo' --collection 'MediaHub & UR' --file foo.md          # dry run
    kb.py write '[DESIGN] Foo' --collection 'MediaHub & UR' --file foo.md --apply  # writes
    kb.py update <doc> --file foo.md            # replace body (dry run without --apply)
    kb.py update <doc> --append --file note.md  # append to body

Writes are dry-run by default: write/update/delete print what would happen and exit 0; nothing
reaches Outline until --apply is passed, and --apply follows Evan's word.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://kb.tvunetworks.com"
ENV_KEYS = ("OUTLINE_URL", "OUTLINE_TOKEN")


# ── credentials ───────────────────────────────────────────────────────────────

def load_env(env_file):
    """Resolve credentials: process env wins, then the env file."""
    creds = {k: os.environ.get(k) for k in ENV_KEYS}
    path = env_file or os.environ.get("OUTLINE_ENV_FILE") or os.environ.get("ELA_ENV_FILE")
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
    if not creds.get("OUTLINE_URL"):
        creds["OUTLINE_URL"] = DEFAULT_URL
    if not creds.get("OUTLINE_TOKEN"):
        sys.exit(
            "missing OUTLINE_TOKEN.\n"
            "Set it in the environment, or pass --env-file / $OUTLINE_ENV_FILE."
        )
    creds["OUTLINE_URL"] = creds["OUTLINE_URL"].rstrip("/")
    return creds


def api(creds, method, payload):
    url = f"{creds['OUTLINE_URL']}/api/{method}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {creds['OUTLINE_TOKEN']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        try:
            detail = json.loads(detail).get("message", detail)
        except ValueError:
            pass
        sys.exit(f"outline {method} failed: HTTP {exc.code} {detail}")
    except urllib.error.URLError as exc:
        sys.exit(f"outline {method} failed: {exc}")


# ── identifier / lookup helpers ───────────────────────────────────────────────

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def doc_id(ref):
    """Accept a UUID, a urlId slug, or any /doc/<slug> URL."""
    ref = ref.strip()
    if ref.startswith("http"):
        path = urllib.parse.urlparse(ref).path
        ref = path.rstrip("/").split("/")[-1]
    return urllib.parse.unquote(ref)


def collections(creds):
    """Every collection the token can see."""
    out, offset = [], 0
    while True:
        page = api(creds, "collections.list", {"limit": 100, "offset": offset})
        out.extend(page["data"])
        if len(page["data"]) < 100:
            return out
        offset += 100


def resolve_collection(creds, ref):
    """Match a collection by UUID, exact name, or unique case-insensitive prefix."""
    if UUID_RE.match(ref):
        return ref, ref
    cols = collections(creds)
    exact = [c for c in cols if c["name"] == ref]
    loose = [c for c in cols if c["name"].lower().startswith(ref.lower())]
    hits = exact or loose
    if not hits:
        names = ", ".join(repr(c["name"]) for c in cols)
        sys.exit(f"no collection matching {ref!r}. Available: {names}")
    if len(hits) > 1:
        names = ", ".join(repr(c["name"]) for c in hits)
        sys.exit(f"{ref!r} is ambiguous: {names}")
    return hits[0]["id"], hits[0]["name"]


# ── rendering ─────────────────────────────────────────────────────────────────

def strip_tags(text):
    return re.sub(r"</?b>", "", text or "")


def doc_header(creds, doc):
    icon = doc.get("icon")
    lines = [
        f"# {icon + ' ' if icon else ''}{doc['title']}",
        f"url:       {creds['OUTLINE_URL']}{doc.get('url','')}",
        f"id:        {doc['id']}",
    ]
    if doc.get("collectionId"):
        lines.append(f"collection: {doc['collectionId']}")
    if doc.get("parentDocumentId"):
        lines.append(f"parent:    {doc['parentDocumentId']}")
    lines.append(
        f"updated:   {doc.get('updatedAt','?')}"
        f"  by {(doc.get('updatedBy') or {}).get('name','?')}"
    )
    lines.append(
        f"created:   {doc.get('createdAt','?')}"
        f"  by {(doc.get('createdBy') or {}).get('name','?')}"
    )
    if not doc.get("publishedAt"):
        lines.append("state:     DRAFT (unpublished — visible only to its author)")
    if doc.get("archivedAt"):
        lines.append(f"state:     ARCHIVED {doc['archivedAt']}")
    if doc.get("deletedAt"):
        lines.append(f"state:     TRASHED {doc['deletedAt']}")
    return "\n".join(lines)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_search(creds, args):
    payload = {"query": args.query, "limit": args.limit}
    if args.collection:
        payload["collectionId"] = resolve_collection(creds, args.collection)[0]
    res = api(creds, "documents.search", payload)
    if args.json:
        print(json.dumps(res["data"], indent=2, ensure_ascii=False))
        return
    hits = res["data"]
    if not hits:
        print(f"no documents matching {args.query!r}")
        return
    for hit in hits:
        doc = hit["document"]
        print(f"\n{doc['title']}")
        print(f"  {creds['OUTLINE_URL']}{doc.get('url','')}")
        print(f"  updated {doc.get('updatedAt','?')[:10]}  id {doc['id']}")
        ctx = " ".join(strip_tags(hit.get("context")).split())
        if ctx:
            print(f"  … {ctx[:300]}")
    print(f"\n{len(hits)} of {res.get('pagination',{}).get('total','?')} matches")


def cmd_read(creds, args):
    doc = api(creds, "documents.info", {"id": doc_id(args.doc)})["data"]
    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return
    print(doc_header(creds, doc))
    print("\n" + "─" * 76 + "\n")
    print(doc.get("text") or "(empty)")
    if args.children:
        kids = api(creds, "documents.list", {
            "parentDocumentId": doc["id"], "limit": 100,
        })["data"]
        for kid in kids:
            print("\n" + "═" * 76 + "\n")
            print(doc_header(creds, kid))
            print("\n" + "─" * 76 + "\n")
            print(kid.get("text") or "(empty)")


def cmd_tree(creds, args):
    if not args.collection:
        for col in collections(creds):
            print(f"{col.get('permission') or 'private':10} {col['name']}")
            print(f"{'':10} id {col['id']}")
        return
    cid, name = resolve_collection(creds, args.collection)
    print(f"{name}  ({cid})\n")
    nodes = api(creds, "collections.documents", {"id": cid})["data"]

    def walk(items, depth):
        for item in items:
            slug = item["url"].rstrip("/").split("/")[-1]
            print(f"{'  ' * depth}- {item['title']}   [{slug}]")
            walk(item.get("children") or [], depth + 1)

    walk(nodes, 0)


def read_body(args):
    """Body text from --text or --file; None when neither was given.

    Stdin is read only for an explicit `--file -`. There is deliberately no
    implicit stdin fallback: a caller with an idle pipe would block forever, and
    an empty read must never be mistaken for "blank the document".
    """
    if args.text is not None:
        return args.text
    if args.file == "-":
        return sys.stdin.read()
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            sys.exit(f"cannot read {args.file}: {exc}")
    return None


def cmd_write(creds, args):
    body = read_body(args)
    if body is None:
        sys.exit("no body: pass --file <path>, --file - (stdin), or --text")
    payload = {
        "title": args.title,
        "text": body,
        "publish": not args.draft,
    }
    if args.parent:
        parent = api(creds, "documents.info", {"id": doc_id(args.parent)})["data"]
        payload["parentDocumentId"] = parent["id"]
        payload["collectionId"] = parent["collectionId"]
        target = f"under {parent['title']!r}"
    elif args.collection:
        cid, name = resolve_collection(creds, args.collection)
        payload["collectionId"] = cid
        target = f"in collection {name!r}"
    else:
        sys.exit("pass --collection <name> or --parent <doc> to say where it goes")
    if args.icon:
        payload["icon"] = args.icon
    if not args.apply:
        print(f"DRY RUN — would create {args.title!r} {target}, "
              f"{'draft' if args.draft else 'published'}, {len(body)} chars")
        print("\n" + "─" * 76 + "\n" + body)
        print("\npass --apply to create it")
        return
    doc = api(creds, "documents.create", payload)["data"]
    print(f"created {'draft' if args.draft else 'published'} {target}")
    print(f"{doc['title']}\n{creds['OUTLINE_URL']}{doc.get('url','')}\nid {doc['id']}")


def cmd_update(creds, args):
    doc = api(creds, "documents.info", {"id": doc_id(args.doc)})["data"]
    body = read_body(args)
    if body is None and not args.title and not args.icon:
        sys.exit("nothing to change: pass --file/--text, --title, or --icon")
    payload = {"id": doc["id"]}
    if body is not None:
        payload["text"] = body
        if args.append:
            payload["append"] = True
    if args.title:
        payload["title"] = args.title
    if args.icon:
        payload["icon"] = args.icon
    if args.publish:
        payload["publish"] = True
    if body is None:
        verb = "retitle" if args.title else "update"
    else:
        verb = "append to" if args.append else "replace body of"
    if not args.apply:
        old = doc.get("text") or ""
        sizes = ("" if body is None else
                 f" ({len(old)} chars now, {len(body)} chars incoming)")
        print(f"DRY RUN — would {verb} {doc['title']!r}{sizes}")
        print(f"{creds['OUTLINE_URL']}{doc.get('url','')}")
        if body is not None:
            print("\n" + "─" * 76 + "\n" + body)
        print("\npass --apply to send it")
        return
    new = api(creds, "documents.update", payload)["data"]
    print(f"updated ({verb.replace(' of', '')}) — revision {new.get('revision')}")
    print(f"{new['title']}\n{creds['OUTLINE_URL']}{new.get('url','')}")


def cmd_delete(creds, args):
    doc = api(creds, "documents.info", {"id": doc_id(args.doc)})["data"]
    if not args.apply:
        print(f"DRY RUN — would move {doc['title']!r} to trash "
              f"({creds['OUTLINE_URL']}{doc.get('url','')})\npass --apply to do it")
        return
    api(creds, "documents.delete", {"id": doc["id"]})
    print(f"moved {doc['title']!r} to trash (restorable in Outline for 30 days)")


# ── cli ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env-file", help="file with OUTLINE_TOKEN=... lines")
    p.add_argument("--json", action="store_true", help="raw API JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="full-text search")
    s.add_argument("query")
    s.add_argument("--collection", help="restrict to one collection")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("read", help="print a document as markdown")
    s.add_argument("doc", help="URL, urlId slug, or UUID")
    s.add_argument("--children", action="store_true", help="also print child docs")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("tree", help="list collections, or one collection's docs")
    s.add_argument("collection", nargs="?")
    s.set_defaults(fn=cmd_tree)

    def body_args(sp):
        sp.add_argument("--file", help="markdown body file, or - for stdin")
        sp.add_argument("--text", help="markdown body inline")
        sp.add_argument("--icon", help="emoji icon")
        sp.add_argument("--apply", action="store_true",
                        help="actually send it; without this the command is a dry run")
        sp.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)  # legacy no-op: dry run is the default

    s = sub.add_parser("write", help="create a new document")
    s.add_argument("title")
    s.add_argument("--collection", help="target collection (name or UUID)")
    s.add_argument("--parent", help="nest under this document")
    s.add_argument("--draft", action="store_true",
                   help="leave unpublished (visible only to you)")
    body_args(s)
    s.set_defaults(fn=cmd_write)

    s = sub.add_parser("update", help="edit an existing document")
    s.add_argument("doc", help="URL, urlId slug, or UUID")
    s.add_argument("--append", action="store_true",
                   help="append instead of replacing the body")
    s.add_argument("--title", help="new title")
    s.add_argument("--publish", action="store_true", help="publish a draft")
    body_args(s)
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("delete", help="move a document to trash")
    s.add_argument("doc")
    s.add_argument("--apply", action="store_true", help="actually trash it; default is a dry run")
    s.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_delete)

    args = p.parse_args()
    args.fn(load_env(args.env_file), args)


if __name__ == "__main__":
    main()
