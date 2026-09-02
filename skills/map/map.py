#!/usr/bin/env python3
"""Map capability — where code is, what is missing, how to get it, and where to work on it.
L1: subcommands, --json, stdlib only.

Layout rule (site.json): every checkout that is not Evan's lives under <code>/<alias>/<remote path>.
The alias is a function of (host, group) — media · web · mx · lr/rx · lr/receiver · github/<org>.
Hosts and aliases live only in ~/.claude/ela/site.json — no address is written in any tracked file.
No judgment, no categories. Machine state (what is on disk, branch, dirty) is a CACHE, never
knowledge: `survey` writes ~/.claude/ela/map/host.json; the knowledge base keeps only what cannot be
derived — services.yaml (image → repos → owners) and absent.yaml.

  survey                            scan <code>, <work>, <lab> and Evan's repos → the cache (seconds)
  find     <name>                   repo · docker image · process type → paths, owners, or where to clone from
  services [--image X | --type T]   the service table
  where    <alias>/<path>           the directory a remote path maps to (no network)
  probe    <alias>/<path> …         does the remote exist? (ssh ls-remote; the media GitLab's API lists only public projects)
  clone    <alias>/<path> [--dry-run]   clone into its place; imatrix sibling links kept
  sync     <name|dir> [--ref R]     fetch; report branch, ahead/behind, dirty; optionally check out a ref (code/ only, clean only)
  worktree <name|dir> <KEY> [--base origin/<branch>]   branch evan/<key>; lives in <work>/<KEY>/<repo>, or beside the repo when a team stack requires it (then <work>/<KEY>/<repo> is a symlink)
  coverage                          is the code we usually need on disk? per docker image and per alias
  missing                           absent.yaml, one line each

Exit codes: 0 ok · 2 usage · 3 not found · 4 refused (dirty / not under code/) · 5 remote error.
"""
import argparse, json, os, re, shutil, signal, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

EX_USAGE, EX_NOTFOUND, EX_REFUSED, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
CACHE = os.path.expanduser("~/.claude/ela/map/host.json")


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        print("no ~/.claude/ela/site.json — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)


def git(path, *args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


# ── remotes ↔ places ─────────────────────────────────────────────────────────

def parse_remote(url, hosts=None):
    """→ (host key, path). Host keys come from site.json `hosts` (a url and the names it matches)."""
    m = (re.match(r"ssh://git@([\w.-]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
         or re.match(r"git@([\w.-]+):(.+?)(?:\.git)?/?$", url)
         or re.match(r"https?://([\w.-]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url))
    if not m:
        return None, None
    name, path = m.group(1), m.group(2)
    for key, h in (hosts or {}).items():
        if name == key or name in h.get("matches", []) or name in h.get("url", ""):
            return key, path
    return name, path


DEFAULT_ALIASES = {  # no addresses here — hosts are named; their urls live in site.json `hosts`
    "media": {"host": "gitlab-media", "group": "media"},
    "web": {"host": "gitlab-web", "group": "webteam"},
    "mx": {"host": "gitlab-web", "group": "mx"},
    "lr/rx": {"host": "gitlab-web", "group": "rx"},
    "lr/receiver": {"host": "gitlab-web", "group": "receiver"},
    "github": {"host": "github", "group": "*"},
}
DEFAULT_DIR_NAMES = {"web/mediahub-admin-frontend": "web/mediahub-admin-front"}   # mediahub-agent's registry names it


class Layout:
    """Everything derives from `projects` unless site.json overrides it; `hosts` is the one thing
    that must be filled in by hand (addresses are machine/site facts, never tracked)."""
    def __init__(self, s):
        self.projects = s.get("projects") or sys.exit("site.json has no `projects` root — run /ela:setup")
        self.code = s.get("code") or os.path.join(self.projects, "code")
        self.work = s.get("work") or os.path.join(self.projects, "work")
        self.lab = s.get("lab") or os.path.join(self.projects, "lab")
        self.hosts = s.get("hosts", {})
        if "github" not in self.hosts:
            self.hosts["github"] = {"url": "git@github.com", "matches": ["github.com"]}
        self.aliases = s.get("aliases") or DEFAULT_ALIASES
        self.dir_names = s.get("dir_names") or DEFAULT_DIR_NAMES
        self.stacks = s.get("stacks") or {"web": os.path.join(self.code, "web", "mediahub-agent")}
        self.mine = [os.path.join(self.projects, x) for x in ("ela", "ela-knowledge", "helm")]
        self.by_group = {(a["host"], a["group"]): alias for alias, a in self.aliases.items()}

    def alias_for(self, host, path):
        group, _, rest = path.partition("/")
        if (host, "*") in self.by_group:
            return self.by_group[(host, "*")], path  # github: <org>/<repo>
        alias = self.by_group.get((host, group))
        return (alias, rest) if alias else (None, rest)

    def place(self, url):
        """remote url → absolute directory under <code>, or None when the (host, group) has no alias."""
        host, path = parse_remote(url, self.hosts)
        if not host:
            return None
        alias, rest = self.alias_for(host, path)
        if not alias:
            return None
        rel = self.dir_names.get(f"{alias}/{rest}", f"{alias}/{rest}")
        return os.path.join(self.code, rel)

    def alias_path(self, ref):
        """'media/imatrix/prj/x' | 'web/x' | 'github/org/x' → (remote url, directory)."""
        alias = next((a for a in sorted(self.aliases, key=len, reverse=True) if ref == a or ref.startswith(a + "/")), None)
        if not alias:
            return None, None
        rest = ref[len(alias):].lstrip("/")
        a = self.aliases[alias]
        base = self.hosts.get(a["host"], {}).get("url", a["host"])
        if a["group"] == "*":
            url = f"{base}:{rest}.git" if not base.startswith("ssh://") else f"{base}/{rest}.git"
        elif base.startswith("ssh://"):
            url = f"{base}/{a['group']}/{rest}.git"
        else:
            url = f"{base}:{a['group']}/{rest}.git"
        rel = self.dir_names.get(f"{alias}/{rest}", f"{alias}/{rest}")
        return url, os.path.join(self.code, rel)


# ── survey → cache ───────────────────────────────────────────────────────────

def find_repos(roots, max_depth=6):
    out = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base_depth = root.rstrip("/").count("/")
        for dirpath, dirnames, _ in os.walk(root):
            if os.path.islink(dirpath):
                dirnames[:] = []; continue
            if ".git" in dirnames or os.path.isfile(os.path.join(dirpath, ".git")):
                out.append(dirpath); dirnames[:] = []; continue
            if dirpath.count("/") - base_depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
    return out


def describe(path):
    _, remote, _ = git(path, "remote", "get-url", "origin")
    _, branch, _ = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    _, status, _ = git(path, "status", "--porcelain")
    _, last, _ = git(path, "log", "-1", "--format=%h %ad %an", "--date=short")
    _, wt, _ = git(path, "worktree", "list", "--porcelain")
    worktrees = [l.split(" ", 1)[1] for l in wt.splitlines() if l.startswith("worktree ") and l.split(" ", 1)[1] != path]
    federate = [f for f in ("CLAUDE.md", ".claude", "AGENTS.md", "openspec") if os.path.exists(os.path.join(path, f))]
    return {"path": path, "name": os.path.basename(path), "remote": remote, "branch": branch,
            "dirty": len([l for l in status.splitlines() if l.strip()]), "last_commit": last,
            "worktrees": worktrees, "federate": federate}


def cmd_survey(lay, a):
    roots = [lay.code, lay.work, lay.lab, *lay.mine]
    paths = find_repos(roots)
    with ThreadPoolExecutor(max_workers=8) as ex:
        repos = list(ex.map(describe, paths))
    for r in repos:
        mine = any(r["path"] == m or r["path"].startswith(m + "/") for m in lay.mine)
        r["place"] = None if mine else (lay.place(r["remote"]) if r["remote"] else None)
        r["in_place"] = True if mine else ((r["place"] == r["path"]) if r["place"] else None)
        r["governance"] = "team-stack" if any(r["path"].startswith(lay.code + "/" + k + "/") for k in lay.stacks) else ("repo-local" if r["federate"] else "bare")
    cache = {"surveyed": time.strftime("%Y-%m-%d %H:%M"), "roots": roots, "repos": repos}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=1)
    misplaced = [r for r in repos if r["in_place"] is False]
    unaliased = [r for r in repos if r["remote"] and r["place"] is None and not r["path"].startswith(tuple(lay.mine)) and not r["path"].startswith(lay.lab or "\0")]
    if a.json:
        print(json.dumps({"surveyed": cache["surveyed"], "repos": len(repos), "misplaced": [r["path"] for r in misplaced], "unaliased": [(r["path"], r["remote"]) for r in unaliased]})); return
    print(f"{len(repos)} repos surveyed → {CACHE}")
    for r in misplaced:
        print(f"  misplaced  {r['path']}  →  {r['place']}")
    for r in unaliased:
        print(f"  no alias   {r['path']}  ({r['remote']})")
    dirty = [r for r in repos if r["dirty"] and r["path"].startswith(lay.code or "\0")]
    for r in dirty:
        print(f"  dirty      {r['path']}  ({r['dirty']} files) — code/ checkouts should stay clean; work belongs in work/")


def cache(lay):
    if not os.path.isfile(CACHE) or time.time() - os.path.getmtime(CACHE) > 86400:
        class A: json = True
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_survey(lay, A())
    return json.load(open(CACHE))


# ── knowledge readers (flat yaml written by ela) ─────────────────────────────

def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def services(text):
    out, cur, repo = {}, None, None
    for line in text.splitlines():
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            cur = out.setdefault(m.group(1), {"owners": [], "process_types": [], "slugs": [], "gm_names": [], "repos": []}); repo = None; continue
        if cur is None:
            continue
        for key in ("owners", "process_types", "slugs", "gm_names"):
            m = re.match(rf"^    {key}: (.+)$", line)
            if m:
                try: cur[key] = json.loads(m.group(1))
                except ValueError: pass
        m = re.match(r"^      - gitlab: (.+)$", line)
        if m: repo = {"gitlab": m.group(1).strip()}; cur["repos"].append(repo); continue
        m = re.match(r"^        (role): (.+)$", line)
        if m and repo is not None: repo[m.group(1)] = m.group(2).strip()
    return out


def absent_entries(text):
    out = []
    for m in re.finditer(r"^- name: (.+)\n((?:  [^\n]*\n)+)", text, re.M):
        body = m.group(2)
        f = lambda k: (re.search(rf"^  {k}: (.+)$", body, re.M) or [None, ""])[1].strip()
        out.append({"name": m.group(1).strip(), "owner": f("owner"), "location": f("location"), "why": f("why_it_matters")})
    return out


def gitlab_to_dir(lay, gl):
    """'media/imatrix/prj/x' (a media-group path as written in services.yaml) → directory."""
    _, d = lay.alias_path(gl)
    return d


def norm(x):
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_find(lay, a):
    q = norm(a.name)
    s = site(); mapdir = s.get("map", "")
    svc = services(read(os.path.join(mapdir, "services.yaml")))
    absent = absent_entries(read(os.path.join(mapdir, "absent.yaml")))
    repos = cache(lay)["repos"]
    hits = {"repos": [], "images": [], "process_types": [], "slugs": [], "gm_names": [], "absent": []}
    for r in repos:
        if q in norm(r["name"]) or (r["remote"] and q in norm(os.path.basename(r["remote"]))):
            hits["repos"].append(r)
    for img, d in svc.items():
        rows = [dict(rp, path=gitlab_to_dir(lay, rp["gitlab"]), on_disk=os.path.isdir(gitlab_to_dir(lay, rp["gitlab"]) or "\0")) for rp in d["repos"]]
        if q in norm(img):
            hits["images"].append(dict(image=img, **{k: v for k, v in d.items() if k != "repos"}, repos=rows)); continue
        for pt in d["process_types"]:
            if q in norm(pt):
                hits["process_types"].append({"process_type": pt, "image": img, "owners": d["owners"], "repos": rows})
        for key, kind in (("slugs", "slugs"), ("gm_names", "gm_names")):
            for name in d[key]:
                if q in norm(name):
                    hits[kind].append({"name": name, "image": img, "owners": d["owners"], "repos": rows})
    for e in absent:
        if q in norm(e["name"]):
            hits["absent"].append(e)
    if not any(hits.values()):
        print(f"{a.name}: no repo, image, process type, slug or GM name matches; not in absent.yaml — try `probe media/{a.name}`", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if a.json:
        print(json.dumps(hits, ensure_ascii=False)); return
    for r in hits["repos"]:
        flag = "" if r["in_place"] in (True, None) else f"  (misplaced → {r['place']})"
        print(f"repo   {r['name']:<28} {r['path']}  [{r['branch']} · {r['governance']} · dirty {r['dirty']}]{flag}")
    for i in hits["images"]:
        print(f"image  {i['image']:<28} owners {', '.join(i['owners']) or '?'}; slugs {', '.join(i['slugs'][:4])}{' …' if len(i['slugs'])>4 else ''}; GM names {len(i['gm_names'])}")
        for rp in i["repos"]:
            print(f"         {rp['gitlab']:<38} {(rp['path'] or '?'):<58} {'on disk' if rp['on_disk'] else 'NOT cloned'}  {rp.get('role','')}")
        if not i["repos"]:
            print("         no repo known — see absent")
    for p in hits["process_types"]:
        print(f"type   {p['process_type']:<28} image {p['image']}; owners {', '.join(p['owners']) or '?'}; " + ("; ".join(f"{r['gitlab']} ({'on disk' if r['on_disk'] else 'not cloned'})" for r in p['repos']) or "code unknown"))
    for kind, label in (("slugs", "slug"), ("gm_names", "gm")):
        for h in hits[kind]:
            code = "; ".join(f"{r['gitlab']} ({'on disk' if r['on_disk'] else 'not cloned'})" for r in h["repos"]) or "code unknown"
            print(f"{label:<6} {h['name'][:28]:<28} image {h['image']}; owners {', '.join(h['owners']) or '?'}; {code}")
    for e in hits["absent"]:
        print(f"absent {e['name']:<28} owner {e['owner'] or '?'}; {e['location'][:100]}")


def cmd_services(lay, a):
    svc = services(read(os.path.join(site().get("map", ""), "services.yaml")))
    rows = []
    for img, d in sorted(svc.items()):
        if a.image and norm(a.image) != norm(img): continue
        if a.type and not any(norm(a.type) == norm(t) for t in d["process_types"]): continue
        rows.append(dict(image=img, **d))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    for r in rows:
        code = ", ".join(("" if os.path.isdir(gitlab_to_dir(lay, x["gitlab"]) or "\0") else "✗ ") + x["gitlab"] for x in r["repos"]) or "—"
        print(f"{r['image']:<20} {', '.join(r['owners']) or '?':<18} slugs {len(r['slugs']):>2}  {code}")


def cmd_where(lay, a):
    url, d = lay.alias_path(a.ref)
    if not url:
        # not an alias/path — a repo name: answer from the survey cache, one line per checkout
        q = norm(a.ref)
        hits = [r for r in cache(lay)["repos"] if norm(r["name"]) == q or (r["remote"] and norm(os.path.basename(r["remote"]).removesuffix(".git")) == q)]
        if not hits:
            # a service: image name, Helm slug or GM name → the repos its code lives in
            svc = services(read(os.path.join(site().get("map", ""), "services.yaml")))
            for img, d in svc.items():
                if q == norm(img) or any(q == norm(x) for x in d["slugs"] + d["gm_names"] + d["process_types"]):
                    rows = [dict(rp, dir=gitlab_to_dir(lay, rp["gitlab"])) for rp in d["repos"]]
                    if a.json:
                        print(json.dumps({"image": img, "owners": d["owners"], "repos": [dict(r, on_disk=os.path.isdir(r["dir"] or "\0")) for r in rows]})); return
                    print(f"image {img}  owners {', '.join(d['owners']) or '?'}")
                    for r in rows:
                        print(f"{(r['dir'] or '?'):<60} {'on disk' if os.path.isdir(r['dir'] or chr(0)) else 'not cloned'}  {r.get('role','')}")
                    if not rows:
                        print("no repo known — `ela find` shows the absent entry")
                    return
            print(f"{a.ref}: no alias, checkout, image, slug or GM name matches (aliases: {', '.join(lay.aliases)}; try `ela find {a.ref}`)", file=sys.stderr); sys.exit(EX_NOTFOUND)
        if a.json:
            print(json.dumps([{"name": r["name"], "dir": r["path"], "remote": r["remote"], "branch": r.get("branch")} for r in hits])); return
        for r in hits:
            print(f"{r['path']}  [{r.get('branch','?')}]  ← {r['remote'] or 'no remote'}")
        return
    print(json.dumps({"remote": url, "dir": d, "on_disk": os.path.isdir(d)}) if a.json else f"{d}  {'on disk' if os.path.isdir(d) else 'not cloned'}  ← {url}")


def ls_remote(url):
    code, out, err = git("/", "ls-remote", "--heads", "--tags", url, timeout=40)
    return len([l for l in out.splitlines() if "\t" in l]) if code == 0 else (None if code == 124 else 0)


def cmd_probe(lay, a):
    out = []
    for ref in a.refs:
        url, d = lay.alias_path(ref)
        if not url:
            print(f"no   {ref:<45} no alias", file=sys.stderr); continue
        n = ls_remote(url)
        out.append({"ref": ref, "remote": url, "refs": n, "exists": bool(n), "dir": d, "on_disk": os.path.isdir(d)})
        print(f"{'ok  ' if n else 'no  '} {ref:<45} {n if n is not None else 'timeout'} refs   {'on disk' if os.path.isdir(d) else ''}")
    if a.json:
        print(json.dumps(out))


IMATRIX_SIBLINGS = ("libshmmedia", "libtvulive", "libplayercontrolwrapper")  # remote media/<lib>, but imatrix sources refer to ../<lib>


def cmd_clone(lay, a):
    url, dest = lay.alias_path(a.ref)
    if not url:
        print(f"{a.ref}: no alias matches", file=sys.stderr); sys.exit(EX_USAGE)
    if os.path.exists(dest):
        print(f"already on disk: {dest}"); return
    n = ls_remote(url)
    if not n:
        print(f"{a.ref}: nothing answers at {url}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if a.dry_run:
        print(f"DRY RUN — git clone {url} {dest}  ({n} refs)"); return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    code, _, err = git("/", "clone", "-q", url, dest, timeout=1800)
    if code != 0:
        print(err[:300], file=sys.stderr); sys.exit(EX_REMOTE)
    name = os.path.basename(dest)
    prj = os.path.join(lay.code, "media", "imatrix", "prj")
    if a.ref.startswith("media/") and name in IMATRIX_SIBLINGS and os.path.isdir(prj) and not os.path.exists(os.path.join(prj, name)):
        os.symlink(f"../../{name}", os.path.join(prj, name))
    print(f"cloned {a.ref} -> {dest}")
    class A: json = True
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        cmd_survey(lay, A())


def resolve_dir(lay, name):
    if os.path.isdir(name):
        return os.path.abspath(name)
    repos = cache(lay)["repos"]
    hits = [r for r in repos if norm(r["name"]) == norm(name)]
    if len(hits) == 1:
        return hits[0]["path"]
    if not hits:
        url, d = lay.alias_path(name)
        if d and os.path.isdir(d):
            return d
        print(f"{name}: not on disk", file=sys.stderr); sys.exit(EX_NOTFOUND)
    print(f"{name} is ambiguous: " + ", ".join(h["path"] for h in hits) + " — pass a path or alias/path", file=sys.stderr); sys.exit(EX_USAGE)


def cmd_sync(lay, a):
    d = resolve_dir(lay, a.target)
    code, _, err = git(d, "fetch", "--all", "--tags", "--prune", timeout=300)
    if code != 0:
        print(f"fetch failed: {err[:200]}", file=sys.stderr)
    _, branch, _ = git(d, "rev-parse", "--abbrev-ref", "HEAD")
    _, status, _ = git(d, "status", "--porcelain")
    dirty = len([l for l in status.splitlines() if l.strip()])
    _, ab, _ = git(d, "rev-list", "--left-right", "--count", f"{branch}...@{{u}}") if branch != "HEAD" else (0, "", "")
    ahead, behind = (ab.split() + ["?", "?"])[:2] if ab else ("?", "?")
    _, last, _ = git(d, "log", "-1", "--format=%h %ad %s", "--date=short")
    _, tags, _ = git(d, "tag", "--sort=-creatordate")
    r = {"dir": d, "branch": branch, "ahead": ahead, "behind": behind, "dirty": dirty, "head": last, "recent_tags": tags.splitlines()[:8], "checked_out": None}
    if a.ref:
        if not d.startswith(lay.code + "/"):
            print("refusing to check out a ref outside code/ — work happens in work/", file=sys.stderr); sys.exit(EX_REFUSED)
        if dirty:
            print(f"refusing: {d} has {dirty} uncommitted files (code/ must stay clean)", file=sys.stderr); sys.exit(EX_REFUSED)
        code, _, err = git(d, "checkout", "-q", a.ref)
        if code != 0:
            print(f"checkout {a.ref} failed: {err[:200]}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        _, r["branch"], _ = git(d, "rev-parse", "--abbrev-ref", "HEAD"); r["checked_out"] = a.ref
        _, r["head"], _ = git(d, "log", "-1", "--format=%h %ad %s", "--date=short")
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    print(f"{d}\n  branch {r['branch']}  ahead {ahead}  behind {behind}  dirty {dirty}\n  head   {r['head']}")
    if r["recent_tags"]:
        print(f"  tags   {' '.join(r['recent_tags'])}")
    if r["checked_out"]:
        print(f"  checked out {r['checked_out']}")


def cmd_worktree(lay, a):
    """One task, one place to look: <work>/<KEY>/<repo>. Where a team stack owns the area (site.json
    `stacks`), the worktree lives physically where the stack's tooling expects it — beside the repo as
    <repo>-<key-lower> (mediahub-agent lists worktrees under its workspace root from `git worktree
    list`, so a symlink there would not do) — and <work>/<KEY>/<repo> is a symlink to it."""
    d = resolve_dir(lay, a.target)
    name, key = os.path.basename(d), a.key.upper()
    branch = f"evan/{key.lower()}"
    stack_alias = next((al for al in lay.stacks if d.startswith(os.path.join(lay.code, al) + "/")), None)
    physical = os.path.join(os.path.dirname(d), f"{name}-{key.lower()}") if stack_alias else os.path.join(lay.work, key, name)
    view = os.path.join(lay.work, key, name)
    if os.path.exists(physical) or os.path.lexists(view):
        print(f"exists: {physical if os.path.exists(physical) else view}"); return
    base = a.base
    if not base:
        _, b, _ = git(d, "rev-parse", "--abbrev-ref", "HEAD"); base = f"origin/{b}" if b != "HEAD" else "HEAD"
    git(d, "fetch", "-q", "origin", timeout=300)
    os.makedirs(os.path.dirname(physical), exist_ok=True); os.makedirs(os.path.dirname(view), exist_ok=True)
    code, out, err = git(d, "worktree", "add", "-b", branch, physical, base)
    if code != 0:
        code, out, err = git(d, "worktree", "add", physical, branch)  # branch already exists
        if code != 0:
            print(err[:300], file=sys.stderr); sys.exit(EX_REMOTE)
    if physical != view:
        os.symlink(physical, view)
    r = {"worktree": physical, "view": view, "branch": branch, "base": base, "stack": lay.stacks.get(stack_alias) if stack_alias else None}
    print(json.dumps(r) if a.json else f"worktree {physical}  (branch {branch} from {base})" + (f"\nwork view {view} -> {physical}  [stack: {r['stack']}]" if physical != view else ""))


def cmd_coverage(lay, a):
    """Is the code we usually need on disk? Per docker image: module source present · only the mediabox
    host + adapter present (module core not located) · no repo known. Then the app layer and the R
    team groups by count. This is the list to read before asking "do we have the code for X"."""
    svc = services(read(os.path.join(site().get("map", ""), "services.yaml")))
    have = lambda gl: os.path.isdir(gitlab_to_dir(lay, gl) or "\0")
    full, adapter_only, none = [], [], []
    for img, d in sorted(svc.items()):
        if not d["repos"]:
            none.append((img, d)); continue
        module = [r for r in d["repos"] if r["gitlab"] not in ("media/mediabox", "media/mediaboxPlugins")]
        if module and all(have(r["gitlab"]) for r in module):
            full.append((img, d, module))
        elif module and not all(have(r["gitlab"]) for r in module):
            adapter_only.append((img, d, [r["gitlab"] for r in module if not have(r["gitlab"])]))
        else:
            adapter_only.append((img, d, ["module core not located — only the adapter (mediaboxPlugins) and the host (mediabox) are on disk"]))
    repos = cache(lay)["repos"]
    by_alias = {}
    for r in repos:
        if r["path"].startswith(lay.code + "/"):
            alias = r["path"][len(lay.code) + 1:].split("/")[0]
            by_alias[alias] = by_alias.get(alias, 0) + 1
    if a.json:
        print(json.dumps({"module_source_on_disk": [i for i, _, _ in full], "adapter_only": {i: m for i, _, m in adapter_only},
                          "no_repo": {i: d["owners"] for i, d in none}, "checkouts_by_alias": by_alias}, ensure_ascii=False)); return
    print(f"docker images {len(svc)}: module source on disk {len(full)} · adapter/host only {len(adapter_only)} · no repo known {len(none)}\n")
    print("== module source on disk")
    for img, d, module in full:
        print(f"  {img:<20} {', '.join(d['owners']) or '?':<10} {'; '.join(r['gitlab'] for r in module)}")
    print("\n== only mediabox + adapter on disk — the module's own code was not found")
    for img, d, missing in adapter_only:
        print(f"  {img:<20} {', '.join(d['owners']) or '?':<10} {'; '.join(missing)}")
    print("\n== no repo known (owner is the way in)")
    for img, d in none:
        print(f"  {img:<20} {', '.join(d['owners']) or '?':<10} slugs {', '.join(d['slugs'])}")
    print("\n== checkouts under code/ by alias: " + ", ".join(f"{k} {v}" for k, v in sorted(by_alias.items())))


def cmd_missing(lay, a):
    rows = absent_entries(read(os.path.join(site().get("map", ""), "absent.yaml")))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    for e in rows:
        print(f"{e['name']:<32} {e['owner'] or '?':<16} {e['location'][:90]}")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="ela map — where code is, how to get it, where to work on it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("survey"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("find"); p.add_argument("name"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("services"); p.add_argument("--image"); p.add_argument("--type"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("where"); p.add_argument("ref"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("probe"); p.add_argument("refs", nargs="+"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("clone"); p.add_argument("ref", help="alias/path, e.g. media/mediabox, web/mx-service, github/tvunetworks-com/tvu-csc"); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("sync"); p.add_argument("target", help="repo name, directory, or alias/path"); p.add_argument("--ref"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("worktree"); p.add_argument("target"); p.add_argument("key", help="task key, e.g. MH-3568"); p.add_argument("--base"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("coverage", help="is the code we usually need on disk? per docker image and per alias"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("missing"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    lay = Layout(site())
    {"survey": cmd_survey, "find": cmd_find, "services": cmd_services, "where": cmd_where, "probe": cmd_probe,
     "clone": cmd_clone, "sync": cmd_sync, "worktree": cmd_worktree, "coverage": cmd_coverage, "missing": cmd_missing}[a.cmd](lay, a)


if __name__ == "__main__":
    main()
