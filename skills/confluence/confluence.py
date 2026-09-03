#!/usr/bin/env python3
"""Confluence (the web team's wiki) — read-only. L1: subcommands, --json, exit codes, stdlib only.

  spaces                      every space the token can see (key · name · type)
  tree   <SPACE>              the page tree of a space, indented, with ids and last editor/date
  search <text> [--space K]   full-text search (CQL text~), newest first
  read   <id|url>             one page as plain text (storage XHTML flattened; tables as rows; macros as their text)
  children <id>               direct child pages

Config: site.json services.confluence.url · CONFLUENCE_TOKEN (a personal access token) from the env or the env file.
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, html, json, os, re, signal, sys, urllib.error, urllib.parse, urllib.request
from html.parser import HTMLParser

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in filter(None, [env_file, os.environ.get("ELA_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].rstrip("\n")
        except OSError:
            continue
    return None


class Wiki:
    def __init__(self, env_file):
        try:
            self.base = json.load(open(SITE))["services"]["confluence"]["url"].rstrip("/")
        except Exception:
            print("site.json services.confluence.url is not set — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)
        self.tok = env_value("CONFLUENCE_TOKEN", env_file)
        if not self.tok:
            print("no CONFLUENCE_TOKEN in the env file — run /ela:setup", file=sys.stderr); sys.exit(EX_AUTH)

    def get(self, path, **params):
        url = f"{self.base}/rest/api/{path}" + (("?" + urllib.parse.urlencode(params)) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.tok}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"confluence: HTTP {e.code} — the PAT is invalid, expired or lacks access", file=sys.stderr); sys.exit(EX_AUTH)
            if e.code == 404:
                return None
            print(f"confluence: HTTP {e.code} on {path}", file=sys.stderr); sys.exit(EX_REMOTE)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"confluence: unreachable ({e}) — office network only", file=sys.stderr); sys.exit(EX_REMOTE)

    def paged(self, path, **params):
        start, out = 0, []
        while True:
            d = self.get(path, start=start, **params)
            if not d:
                break
            out += d.get("results", [])
            if not d.get("_links", {}).get("next") or not d.get("results"):
                break
            start += d.get("limit") or len(d["results"])
        return out


# ── storage XHTML → text ──────────────────────────────────────────────────────

class Flatten(HTMLParser):
    BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br", "ac:layout-cell", "ac:layout-section",
             "ac:task", "ac:rich-text-body", "table", "ul", "ol", "pre", "blockquote"}
    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.cell = False; self.row = []; self.skip = 0; self.heading = ""
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("ac:parameter",) and a.get("ac:name") in ("title",):
            self.heading = "param"; return
        if tag in ("ac:parameter", "ri:page", "ri:attachment", "ri:user", "ac:task-id", "ac:task-status", "ac:macro-id"):
            self.skip += 1; return
        if tag in ("td", "th"):
            self.cell = True; self.row.append("")
        elif tag == "tr":
            self.row = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "ac:structured-macro":
            name = a.get("ac:name", "")
            if name in ("code", "noformat"): self.out.append("\n```\n")
            elif name not in ("toc", "children", "recently-updated", "livesearch", "pagetree"): self.out.append(f"\n[{name}] ")
        elif tag in ("ri:url", "a"):
            href = a.get("ri:value") or a.get("href")
            if href: self.out.append(f" <{href}> ")
        elif tag in self.BLOCK:
            self.out.append("\n")
    def handle_endtag(self, tag):
        if tag in ("ac:parameter",) and self.heading:
            self.heading = ""; return
        if tag in ("ac:parameter", "ri:page", "ri:attachment", "ri:user", "ac:task-id", "ac:task-status", "ac:macro-id"):
            self.skip = max(0, self.skip - 1); return
        if tag in ("td", "th"):
            self.cell = False
        elif tag == "tr":
            self.out.append("\n| " + " | ".join(c.strip().replace("\n", " ") for c in self.row) + " |")
        elif tag == "ac:structured-macro" and self.out and self.out[-1].startswith("\n```"):
            pass
        elif tag == "ac:plain-text-body":
            self.out.append("\n```\n")
        elif tag in self.BLOCK:
            self.out.append("\n")
    def handle_data(self, data):
        if self.skip: return
        if self.heading == "param":
            self.out.append(f"**{data.strip()}** "); return
        if self.cell:
            self.row[-1] += data
        else:
            self.out.append(data)
    def text(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t]+\n", "\n", t); t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def to_text(storage):
    f = Flatten(); f.feed(storage); return f.text()


def page_id(ref, w):
    m = re.search(r"pageId=(\d+)", ref) or re.fullmatch(r"(\d+)", ref.strip())
    if m:
        return m.group(1)
    m = re.search(r"/display/([^/]+)/([^?#]+)", ref)      # /display/SPACE/Title
    if m:
        d = w.get("content", spaceKey=m.group(1), title=urllib.parse.unquote(m.group(2)).replace("+", " "))
        if d and d.get("results"):
            return d["results"][0]["id"]
    print(f"{ref}: not a page id or a Confluence page URL", file=sys.stderr); sys.exit(EX_USAGE)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_spaces(w, a):
    rows = [{"key": s["key"], "name": s["name"], "type": s.get("type")} for s in w.paged("space", limit=100)]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    for r in sorted(rows, key=lambda r: (r["type"] != "global", r["name"].lower())):
        print(f"{r['key']:<18} {r['name']:<40} {r['type']}")


def cmd_tree(w, a):
    pages = w.paged("content", spaceKey=a.space, type="page", limit=200, expand="ancestors,version")
    if not pages:
        print(f"space {a.space}: no pages or no access", file=sys.stderr); sys.exit(EX_NOTFOUND)
    rows = [{"id": p["id"], "title": p["title"], "depth": len(p.get("ancestors") or []), "parent": (p.get("ancestors") or [{}])[-1].get("id"),
             "updated": p["version"]["when"][:10], "by": (p["version"].get("by") or {}).get("displayName", "")} for p in pages]
    # order as a tree: children after their parent
    by_parent = {}
    for r in rows: by_parent.setdefault(r["parent"] if r["depth"] else None, []).append(r)
    def walk(pid, acc):
        for r in by_parent.get(pid, []):
            acc.append(r); walk(r["id"], acc)
    ordered = []; walk(None, ordered)
    ordered += [r for r in rows if r not in ordered]
    if a.json:
        print(json.dumps(ordered, ensure_ascii=False)); return
    print(f"# {a.space}  {len(rows)} pages  ({w.base}/pages/viewpage.action?pageId=<id>)")
    for r in ordered:
        print(f"{'  ' * r['depth']}{r['title']}  [{r['id']}]  {r['updated']} {r['by']}")


def cmd_search(w, a):
    cql = f'text ~ "{a.text}" and type = page' + (f' and space = "{a.space}"' if a.space else "") + " order by lastmodified desc"
    d = w.get("content/search", cql=cql, limit=a.limit, expand="version,space")
    hits = (d or {}).get("results", [])
    if not hits:
        print(f"no pages match {a.text!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    rows = [{"id": h["id"], "title": h["title"], "space": (h.get("space") or {}).get("key", ""), "updated": h["version"]["when"][:10],
             "url": f"{w.base}/pages/viewpage.action?pageId={h['id']}"} for h in hits]
    if a.json:
        print(json.dumps({"total": (d or {}).get("totalSize"), "results": rows}, ensure_ascii=False)); return
    print(f"# {len(rows)} of {(d or {}).get('totalSize')} pages match {a.text!r}")
    for r in rows:
        print(f"{r['space']:<12} {r['updated']}  {r['title']}  [{r['id']}]")


def cmd_read(w, a):
    pid = page_id(a.ref, w)
    p = w.get(f"content/{pid}", expand="body.storage,version,space,ancestors")
    if not p:
        print(f"page {pid}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    text = to_text(p["body"]["storage"]["value"])
    crumbs = " / ".join(x["title"] for x in p.get("ancestors") or [])
    meta = {"id": pid, "title": p["title"], "space": p["space"]["key"], "path": crumbs, "updated": p["version"]["when"][:19],
            "by": (p["version"].get("by") or {}).get("displayName", ""), "version": p["version"]["number"],
            "url": f"{w.base}/pages/viewpage.action?pageId={pid}"}
    if a.json:
        print(json.dumps(dict(meta, text=text), ensure_ascii=False)); return
    if a.raw:
        print(p["body"]["storage"]["value"]); return
    print(f"# {meta['title']}\n{meta['space']} / {crumbs}  ·  v{meta['version']} {meta['updated']} {meta['by']}\n{meta['url']}\n")
    print(text)


def cmd_children(w, a):
    d = w.get(f"content/{a.id}/child/page", limit=200, expand="version")
    rows = [{"id": c["id"], "title": c["title"], "updated": c["version"]["when"][:10]} for c in (d or {}).get("results", [])]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    for r in rows:
        print(f"{r['title']}  [{r['id']}]  {r['updated']}")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Confluence, read-only.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("spaces"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("tree"); p.add_argument("space"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("search"); p.add_argument("text"); p.add_argument("--space"); p.add_argument("--limit", type=int, default=20); p.add_argument("--json", action="store_true")
    p = sub.add_parser("read"); p.add_argument("ref"); p.add_argument("--json", action="store_true"); p.add_argument("--raw", action="store_true")
    p = sub.add_parser("children"); p.add_argument("id"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    w = Wiki(a.env_file)
    {"spaces": cmd_spaces, "tree": cmd_tree, "search": cmd_search, "read": cmd_read, "children": cmd_children}[a.cmd](w, a)


if __name__ == "__main__":
    main()
