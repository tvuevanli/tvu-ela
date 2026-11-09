#!/usr/bin/env python3
"""Deploy prerequisites and branch state of a promotion: what must happen around the deploy, what is not built yet,
which branches tied to the release's tickets are not merged and whether they would merge.

  prereqs.py <report.json> [--fetch] [--json]      from a saved promote report (its delta and tickets)

Why: on 2026-11-09 a DDL (MH-3891: a column and an index on the encoding-profile table, on two databases) surfaced
only when the owner asked; release-branch commits after the promoted build were unseen; a review follow-up branch
(MH-3961) conflicted with another ticket's fix (MH-3966) and nobody had tried the merge. All of it is on disk.

1. **Deploy-time items** — every line of the release's tickets (description and comments) and of the docs and SQL
   files the range changes in each repo (agent-rule files and proposals skipped), matched against closed vocabularies:
   `ddl` (an ALTER/CREATE/DROP statement naming a table, ADD COLUMN/INDEX, 建表, 加字段), `config` (a key = value beside
   a release word: deploy, prod, 上线, 配置中心), `one-off` (a backfill, a script or call run once), `release-todo` (发版待办,
   上线前置, deploy order). A negated line (no DDL, 无 DDL, 不需配置) is never an item. Each item is
   cited (ticket and comment author/date, or repo:path:line); nothing is inferred from a status.
2. **Unbuilt release commits** — per service, `git log <promoted build sha>..origin/<its build branch>` (non-merge):
   the commits a next build would carry that the target will not get from this one.
3. **Unmerged branches** — remote branches whose name carries a release ticket key, not contained in the build
   branch: commits ahead, the tip's date and author, `git merge-tree --write-tree` against the build branch (clean or
   the conflicting files), and the same dry run between every two such branches of one repo.
The checkouts are read as last fetched (the fetch time is printed); `--fetch` runs `git fetch origin` first (a read).
Nothing is merged, pushed or written anywhere.
"""
import argparse, datetime, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "release"))
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}-\d{2,6}\b")

NEGATED = re.compile(r"(?i)(\bno\b|\bwithout\b|" + "|".join(["无", "不需", "没有", "零"]) + r")\s*(新\s*)?(DDL|config|配置|表结构|key)")
RELEASE_CTX = re.compile(r"(?i)(deploy|release|prod\b|config[- ]?server|must|before|after|" +
                         "|".join(["上线", "发版", "配置中心", "需要", "必须", "前置", "部署"]) + ")")
VOCAB = {
    "ddl": re.compile(r"(?i)\b(alter\s+table\s+\w+|create\s+table\s+\w+|drop\s+(table|index|column)\s+\w+|add\s+(column|index)\s+\w+|truncate\s+table)|" +
                      "|".join(["建表", "改表结构"])),
    "one-off": re.compile(r"(?i)(backfill\w*|run (it )?once|migration script)|" + "|".join(["执行一次", "调用一次", "迁移脚本", "刷数据", "回填脚本"])),
    "config": re.compile(r"(?i)\b[a-z][\w-]*(\.[\w-]+){1,}\s*[=:]\s*[\w\"'/{]"),
    "release-todo": re.compile(r"(?i)(deploy(ment)? (note|order|step)s?)|" + "|".join(["发版待办", "上线前置", "部署注意", "发版注意", "部署顺序", "上线前"])),
}
NEEDS_CONTEXT = {"config"}                     # a key=value line is an item only beside release words
SKIP_FILES = re.compile(r"(^|/)(CLAUDE|AGENTS|README)\.md$|(^|/)\.claude/|openspec/")
DOC_GLOBS = ("*.md", "*.sql", "docs/*", "doc/*", "sql/*", "*.yml", "*.yaml", "*.properties")


def run(argv, timeout=60):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def git(path, *args, timeout=60):
    return run(["git", "-C", path, *args], timeout)


def repo_path(repo):
    import release as R  # noqa: E402
    code = R.site().get("code") or ""
    dn = R.site().get("dir_names") or {}
    for cand in (dn.get(repo), repo):
        if cand and os.path.isdir(os.path.join(code, cand, ".git")):
            return os.path.join(code, cand)
    return None


def scan(text, where):
    out = []
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if not s or len(s) > 400:
            continue
        if NEGATED.search(s):
            continue
        for cat, rx in VOCAB.items():
            if rx.search(s) and (cat not in NEEDS_CONTEXT or RELEASE_CTX.search(s)):
                item = {"category": cat, "line": s[:240], "where": where if isinstance(where, str) else where(i)}
                if cat == "release-todo":                 # the list under a 发版待办 line is the item (the databases)
                    detail = []
                    for nxt in lines[i:i + 8]:
                        t = nxt.strip()
                        if not t and detail:
                            break
                        if re.match(r"^([-*•]|\d+[.)、]|\|)", t):
                            detail.append(t[:160])
                    item["detail"] = detail
                out.append(item)
                break
    return out


def ticket_items(tickets):
    out = []
    for t in (tickets or {}).get("tickets") or []:
        if not t.get("exists"):
            continue
        out += [dict(x, key=t["key"]) for x in scan(t.get("description") or "", f"{t['key']} description")]
        for c in t.get("comments") or []:
            out += [dict(x, key=t["key"]) for x in scan(c.get("text") or "", f"{t['key']} comment {c.get('who')} {c.get('when')}")]
    return out


def doc_items(delta, keys=()):
    """Items from the docs the range changes. A doc is the release's when it names one of the release's tickets or
    carries a release-todo line; items from other docs (analyses, atlases) are kept with release_doc False."""
    out = []
    kset = set(keys)
    for s in (delta or {}).get("services") or []:
        path = repo_path(s.get("repo") or "")
        fb, tb = (s.get("from_build") or {}).get("sha"), (s.get("to_build") or {}).get("sha")
        if not path or not fb or not tb:
            continue
        rc, names, _ = git(path, "diff", "--name-only", tb, fb, "--", *DOC_GLOBS)
        for f in names.split():
            if SKIP_FILES.search(f):
                continue                          # agent rules and proposals describe how to work, not this deploy
            rc, body, _ = git(path, "show", f"{fb}:{f}")
            if rc == 0:
                found = scan(body, lambda i, f=f, r=s["repo"]: f"{r}:{f}:{i}")
                named = sorted(set(KEY_RE.findall(body + " " + f.upper().replace("MH", "MH-", 1) if False else body)) & kset)
                release_doc = bool(named) or any(x["category"] == "release-todo" for x in found)
                out += [dict(x, repo=s["repo"], service=s["service"], release_doc=release_doc, keys=named) for x in found]
    return out


def fetch_time(path):
    for f in ("FETCH_HEAD",):
        p = os.path.join(path, ".git", f)
        if os.path.exists(p):
            return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
    return None


def unbuilt(delta, fetch=False):
    out = []
    for s in (delta or {}).get("services") or []:
        path = repo_path(s.get("repo") or "")
        fb = s.get("from_build") or {}
        if not path or not fb.get("sha") or not fb.get("branch"):
            out.append({"service": s["service"], "repo": s.get("repo"), "error": "no checkout or no build sha/branch"})
            continue
        if fetch:
            git(path, "fetch", "--quiet", "origin", timeout=180)
        ref = f"origin/{fb['branch']}"
        rc, log, err = git(path, "log", "--no-merges", "--format=%h%x09%ad%x09%an%x09%s", "--date=short", f"{fb['sha']}..{ref}")
        commits = [dict(zip(("sha", "date", "author", "subject"), l.split("\t", 3))) for l in log.splitlines() if l.strip()]
        out.append({"service": s["service"], "repo": s.get("repo"), "branch": ref, "build": fb.get("version"),
                    "build_sha": fb["sha"][:8], "fetched": fetch_time(path), "commits": commits,
                    "error": err.strip()[:200] if rc else None})
    return out


def merge_tree(path, a, b):
    rc, out, err = git(path, "merge-tree", "--write-tree", "--name-only", "--no-messages", a, b, timeout=120)
    if rc == 0:
        return {"clean": True, "conflicts": []}
    if rc == 1:
        files = [l for l in out.splitlines()[1:] if l.strip()]
        return {"clean": False, "conflicts": files}
    return {"clean": None, "error": (err or out).strip()[:200]}


def branches(delta, keys):
    """Remote branches named after a release ticket, not in the service's build branch, each dry-run merged."""
    out = []
    kre = {k: re.compile(re.escape(k).replace(r"\-", "[-_]?"), re.I) for k in keys}
    seen = set()
    for s in (delta or {}).get("services") or []:
        path = repo_path(s.get("repo") or "")
        fb = s.get("from_build") or {}
        if not path or not fb.get("branch") or path in seen:
            continue
        seen.add(path)
        base = f"origin/{fb['branch']}"
        rc, refs, _ = git(path, "for-each-ref", "refs/remotes/origin", "--format=%(refname:short)")
        mine = []
        for ref in refs.split():
            hit = [k for k, rx in kre.items() if rx.search(ref)]
            if not hit or ref == base:
                continue
            if git(path, "merge-base", "--is-ancestor", ref, base)[0] == 0:
                continue                                   # merged already
            rc, n, _ = git(path, "rev-list", "--count", f"{base}..{ref}")
            rc2, tip, _ = git(path, "log", "-1", "--format=%h%x09%ad%x09%an%x09%s", "--date=short", ref)
            sha, date, author, subject = (tip.strip().split("\t", 3) + ["", "", "", ""])[:4]
            mine.append({"repo": s["repo"], "service": s["service"], "branch": ref, "keys": hit, "ahead": int(n.strip() or 0),
                         "tip": sha, "date": date, "author": author, "subject": subject[:100],
                         "against_release": merge_tree(path, base, ref), "with_others": []})
        for i, a in enumerate(mine):
            for b in mine[i + 1:]:
                m = merge_tree(path, a["branch"], b["branch"])
                if m.get("clean") is False:
                    a["with_others"].append({"branch": b["branch"], **m})
                    b["with_others"].append({"branch": a["branch"], **m})
        out += mine
    return out


def collect(report, fetch=False):
    keys = sorted({t["key"] for t in (report.get("tickets") or {}).get("tickets") or [] if t.get("exists")})
    return {"items": ticket_items(report.get("tickets")) + doc_items(report.get("delta"), keys),
            "unbuilt": unbuilt(report.get("delta"), fetch), "branches": branches(report.get("delta"), keys)}


def render(p):
    L = []
    by, other = {}, 0
    for it in p["items"]:
        if it.get("release_doc") is False:
            other += 1
            continue
        by.setdefault(it["category"], []).append(it)
    for cat in ("ddl", "one-off", "config", "release-todo"):
        for it in by.get(cat, [])[:12]:
            L.append(f"- [{cat}] {it['line'][:160]} — {it['where']}")
            for d in it.get("detail") or []:
                L.append(f"    {d}")
    if other:
        L.append(f"- ({other} more matching line(s) in changed docs that name no release ticket: analyses, not deploy steps)")
    for u in p["unbuilt"]:
        if u.get("commits"):
            L.append(f"- [unbuilt] {u['service']}: {len(u['commits'])} commit(s) on {u['branch']} after build {u['build']} "
                     f"(fetched {u['fetched']}): " + "; ".join(f"{c['sha']} {c['subject'][:60]}" for c in u["commits"][:5]))
    for b in p["branches"]:
        m = b["against_release"]
        st = "merges clean" if m.get("clean") else ("conflicts: " + ", ".join(m.get("conflicts") or [])[:120] if m.get("clean") is False else "merge not tried: " + str(m.get("error")))
        L.append(f"- [branch] {b['repo']} {b['branch']} ({', '.join(b['keys'])}; {b['ahead']} ahead, {b['author']} {b['date']}) {st}"
                 + "".join(f"; conflicts with {o['branch']} in {', '.join(o['conflicts'])[:100]}" for o in b["with_others"]))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report"); ap.add_argument("--fetch", action="store_true"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = collect(json.load(open(a.report)), a.fetch)
    print(json.dumps(p, ensure_ascii=False, indent=1) if a.json else render(p))


if __name__ == "__main__":
    main()
