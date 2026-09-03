#!/usr/bin/env python3
"""Reports for Evan — markdown sources rendered to self-contained HTML pages, published as private claude.ai artifacts.

  list                 the reports in <reports>/ with their artifact URLs (from <reports>/README.md)
  build [name…]        render <reports>/<name>.md → <reports>/out/<name>.html (all when no name given)

Sources live in site.json `reports` (default <projects>/reports), one markdown file per report with front matter
(title · as_of · sources). Not knowledge — a reading surface, regenerated at will. A Claude session publishes
the HTML with the Artifact tool (same file path → same URL); a `/ela:reports` run rewrites the text first.
Markdown subset: # headings · paragraphs · - lists · | tables | · ``` fences (```mermaid → a native diagram) ·
**bold** *italic* `code` [text](url). Stdlib only.
"""
import argparse, html, json, os, re, sys

SITE = os.path.expanduser("~/.claude/ela/site.json")


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        return {}


def reports_dir():
    s = site()
    return s.get("reports") or os.path.join(s.get("projects", os.path.expanduser("~/projects")), "reports")


# ── markdown subset ───────────────────────────────────────────────────────────

def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)
    return t


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        text = text[m.end():]
    return meta, text


def render_body(md):
    out, lines, i = [], md.splitlines(), 0
    para = []
    def flush():
        if para:
            out.append("<p>" + inline(" ".join(x.strip() for x in para)) + "</p>"); para.clear()
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            flush(); lang = ln[3:].strip(); i += 1; buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            if lang == "mermaid":
                # a literal \n inside a mermaid label is a line break for the reader — mermaid takes <br/>
                out.append('<div class="diagram"><pre class="mermaid">' + html.escape("\n".join(buf).replace("\\n", "<br/>"), quote=False) + "</pre></div>")
            else:
                out.append("<pre><code>" + html.escape("\n".join(buf), quote=False) + "</code></pre>")
            continue
        m = re.match(r"^(#{1,4}) (.+)$", ln)
        if m:
            flush(); lvl = len(m.group(1)); txt = m.group(2)
            slug = re.sub(r"[^a-z0-9]+", "-", txt.lower()).strip("-")
            out.append(f'<h{lvl} id="{slug}">{inline(txt)}</h{lvl}>'); i += 1; continue
        if ln.startswith("|"):
            flush(); rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i]); i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\|[\s:|-]+\|$", r)]
            if cells:
                head, body = cells[0], cells[1:]
                out.append('<div class="table"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                           + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table></div>")
            continue
        m = re.match(r"^(\s*)([-*]|\d+\.) (.+)$", ln)
        if m:
            flush(); ordered = m.group(2)[0].isdigit(); items = []
            while i < len(lines) and (mm := re.match(r"^(\s*)([-*]|\d+\.) (.+)$", lines[i])):
                item = [mm.group(3)]; i += 1
                while i < len(lines) and lines[i].startswith("  ") and not re.match(r"^\s*([-*]|\d+\.) ", lines[i]):
                    item.append(lines[i].strip()); i += 1
                items.append(" ".join(item))
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>"); continue
        if not ln.strip():
            flush(); i += 1; continue
        para.append(ln); i += 1
    flush()
    return "\n".join(out)


STYLE = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{--ground:#f4f6f8;--surface:#ffffff;--ink:#18222d;--muted:#5c6b7a;--rule:#d7dde3;--accent:#0f766e;--accent-ink:#ffffff;--amber:#b45309;--code:#eef2f5;--link:#0b5f5a}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--ground:#0f151b;--surface:#161e26;--ink:#e6ebf0;--muted:#93a1ae;--rule:#2a353f;--accent:#2dd4bf;--accent-ink:#0b1216;--amber:#f59e0b;--code:#1c2630;--link:#5eead4}}
:root[data-theme="dark"]{--ground:#0f151b;--surface:#161e26;--ink:#e6ebf0;--muted:#93a1ae;--rule:#2a353f;--accent:#2dd4bf;--accent-ink:#0b1216;--amber:#f59e0b;--code:#1c2630;--link:#5eead4}
body{background:var(--ground);color:var(--ink);font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;font-size:16px;line-height:1.55;margin:0}
.bar{position:sticky;top:0;z-index:2;background:var(--surface);border-bottom:1px solid var(--rule);padding:12px 24px;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
.bar .name{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;font-size:18px;letter-spacing:.01em}
.bar .eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.bar .asof{margin-left:auto;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
main{max-width:78ch;margin:0 auto;padding:32px 24px 80px}
.meta{font-size:13px;color:var(--muted);border-left:3px solid var(--accent);padding:6px 12px;margin:0 0 28px;line-height:1.45}
h1{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;font-size:34px;line-height:1.15;letter-spacing:-.01em;margin:0 0 16px;text-wrap:balance}
h2{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;font-size:22px;margin:40px 0 12px;padding-top:16px;border-top:1px solid var(--rule);text-wrap:balance}
h3{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;font-size:17px;margin:24px 0 8px}
p{margin:0 0 14px}
ul,ol{margin:0 0 14px;padding-left:22px}li{margin:4px 0}
a{color:var(--link);text-decoration-thickness:1px;text-underline-offset:2px}a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.88em;background:var(--code);padding:1px 5px;border-radius:3px}
pre{background:var(--code);border:1px solid var(--rule);border-radius:4px;padding:12px 14px;overflow-x:auto;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13px;line-height:1.5;margin:0 0 16px}
pre code{background:none;padding:0;font-size:inherit}
.table{overflow-x:auto;margin:0 0 18px;border:1px solid var(--rule);border-radius:4px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;text-align:left;font-size:12.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);border-bottom:1px solid var(--rule);padding:9px 12px;white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid var(--rule);vertical-align:top}tbody tr:last-child td{border-bottom:none}
td strong{color:var(--accent)}
.diagram{background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:16px;margin:0 0 18px;overflow-x:auto}
.diagram pre.mermaid{background:none;border:none;padding:0;margin:0;font-family:"IBM Plex Mono",ui-monospace,monospace}
strong{font-weight:600}
@media (prefers-reduced-motion: reduce){*{scroll-behavior:auto}}
</style>
"""


def render(md_path):
    meta, body = front_matter(open(md_path, encoding="utf-8").read())
    title = meta.get("title") or os.path.splitext(os.path.basename(md_path))[0]
    inner = render_body(body)
    inner = re.sub(r"^<h1 [^>]*>.*?</h1>\n?", "", inner, count=1)   # the bar and the page heading carry the title
    sources = inline(meta.get("sources", ""))
    page = f"""<title>{html.escape(title)}</title>
{STYLE}
<header class="bar"><span class="eyebrow">ela · report</span><span class="name">{html.escape(title)}</span><span class="asof">as of {html.escape(meta.get('as_of', ''))}</span></header>
<main>
<h1>{html.escape(title)}</h1>
<div class="meta"><strong>Sources:</strong> {sources}<br><strong>As of</strong> {html.escape(meta.get('as_of', ''))} · regenerated by <code>/ela:reports</code>; a reading surface, not knowledge</div>
{inner}
</main>
"""
    return title, page


def cmd_build(a):
    d = reports_dir(); out = os.path.join(d, "out"); os.makedirs(out, exist_ok=True)
    names = a.names or sorted(os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith(".md") and f != "README.md")
    for n in names:
        src = os.path.join(d, n + ".md")
        if not os.path.isfile(src):
            print(f"{src}: no such report", file=sys.stderr); sys.exit(2)
        title, page = render(src)
        dst = os.path.join(out, n + ".html"); open(dst, "w", encoding="utf-8").write(page)
        print(f"{n:<20} {title!r:<36} → {dst}")


def cmd_list(a):
    d = reports_dir(); idx = os.path.join(d, "README.md")
    urls = {}
    if os.path.isfile(idx):
        for m in re.finditer(r"^\|\s*`?([\w-]+)`?\s*\|\s*([^|]*?)\s*\|\s*(https?://\S+)", open(idx).read(), re.M):
            urls[m.group(1)] = (m.group(2), m.group(3))
    for f in sorted(os.listdir(d)):
        if f.endswith(".md") and f != "README.md":
            n = f[:-3]; meta, _ = front_matter(open(os.path.join(d, f)).read())
            t, u = urls.get(n, ("", "(not published yet)"))
            print(f"{n:<20} as of {meta.get('as_of', '?'):<11} {meta.get('title', ''):<32} {u}")


def main():
    ap = argparse.ArgumentParser(description="Evan's reports: markdown → HTML for artifacts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("names", nargs="*")
    sub.add_parser("list")
    a = ap.parse_args()
    {"build": cmd_build, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
