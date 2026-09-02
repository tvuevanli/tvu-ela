#!/usr/bin/env python3
"""Map capability — where code is, what is missing, and how to get it. L1: subcommands, --json, stdlib only.

  find     <name>                  a repo, image or process type → local path(s), or where it can be cloned from
  services [--image X | --type T]  the service table: image → process types → owners → repos (map/services.yaml)
  probe    <gitlab-path> [...]     does ssh://git@10.12.23.181:22222/<path>.git exist? refs count (the API lists only public projects)
  clone    <gitlab-path> [--into DIR]   clone from the LAN GitLab into the mds layout (source → mds/imatrix or mds/standalone, AI → mds/ai, shells → mds/reference/shells)
  missing                          absent.yaml entries that have a clone URL or a probe-able name

Reads ~/.claude/ela/site.json for `map` (host.yaml · absent.yaml · services.yaml) and `projects`.
Never writes the map: `clone` changes disk, and /ela:map re-surveys disk into the map.
Exit codes: 0 ok · 2 usage · 3 not found · 5 remote error.
"""
import argparse, json, os, re, signal, subprocess, sys

EX_USAGE, EX_NOTFOUND, EX_REMOTE = 2, 3, 5
GITLAB_SSH = "ssh://git@10.12.23.181:22222"


def site():
    try:
        return json.load(open(os.path.expanduser("~/.claude/ela/site.json")))
    except Exception:
        print("no ~/.claude/ela/site.json — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)


def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


# Minimal YAML readers for the three files the map skill writes (flat, predictable shapes).
def host_repos(text):
    out = []
    for m in re.finditer(r"^- name: (.+)\n((?:  [^\n]*\n)+)", text, re.M):
        body = m.group(2)
        f = lambda k: (re.search(rf"^  {k}: (.+)$", body, re.M) or [None, ""])[1].strip()
        out.append({"name": m.group(1).strip(), "area": f("area"), "path": f("path"), "remote": f("remote"),
                    "branch": f("branch"), "governance": f("governance"), "owner": f("owner"),
                    "mirror_of": f("mirror_of"), "authoritative": f("authoritative") == "true"})
    return out


def absent_entries(text):
    out = []
    for m in re.finditer(r"^- name: (.+)\n((?:  [^\n]*\n)+)", text, re.M):
        body = m.group(2)
        f = lambda k: (re.search(rf"^  {k}: (.+)$", body, re.M) or [None, ""])[1].strip()
        out.append({"name": m.group(1).strip(), "declared_by": f("declared_by"), "owner": f("owner"),
                    "location": f("location"), "why": f("why_it_matters")})
    return out


def services(text):
    out, cur, repo = {}, None, None
    for line in text.splitlines():
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            cur = out.setdefault(m.group(1), {"owners": [], "process_types": [], "repos": []}); repo = None; continue
        if cur is None:
            continue
        m = re.match(r"^    owners: (.+)$", line)
        if m: cur["owners"] = json.loads(m.group(1)); continue
        m = re.match(r"^    process_types: (.+)$", line)
        if m: cur["process_types"] = json.loads(m.group(1)); continue
        m = re.match(r"^      - gitlab: (.+)$", line)
        if m: repo = {"gitlab": m.group(1).strip()}; cur["repos"].append(repo); continue
        m = re.match(r"^        (path|role): (.+)$", line)
        if m and repo is not None: repo[m.group(1)] = m.group(2).strip()
    return out


class Map:
    def __init__(self):
        s = site()
        self.dir = s.get("map", ""); self.projects = s.get("projects", os.path.expanduser("~/projects"))
        self.repos = host_repos(read(os.path.join(self.dir, "host.yaml")))
        self.absent = absent_entries(read(os.path.join(self.dir, "absent.yaml")))
        self.services = services(read(os.path.join(self.dir, "services.yaml")))


def norm(x):
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def cmd_find(mp, a):
    q = norm(a.name)
    hits = {"repos": [], "images": [], "process_types": [], "absent": []}
    for r in mp.repos:
        if q in norm(r["name"]) or q in norm(os.path.basename(r["remote"].rstrip("/"))):
            hits["repos"].append(r)
    for img, d in mp.services.items():
        if q in norm(img):
            hits["images"].append(dict(image=img, **d))
            continue  # the image row already lists its types and code
        for pt in d["process_types"]:
            if q in norm(pt):
                hits["process_types"].append({"process_type": pt, "image": img, "owners": d["owners"], "repos": d["repos"]})
    for e in mp.absent:
        if q in norm(e["name"]):
            hits["absent"].append(e)
    if not any(hits.values()):
        print(f"{a.name}: not in host.yaml, services.yaml or absent.yaml — try `probe media/{a.name}`", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if a.json:
        print(json.dumps(hits, ensure_ascii=False)); return
    for r in hits["repos"]:
        tag = " (mirror of %s)" % r["mirror_of"] if r["mirror_of"] else (" (authoritative)" if r["authoritative"] else "")
        print(f"repo   {r['name']:<28} {r['path']}  [{r['area']} · {r['governance']} · {r['owner'] or 'owner ?'}]{tag}")
    for i in hits["images"]:
        print(f"image  {i['image']:<28} owners {', '.join(i['owners']) or '?'}; types {', '.join(i['process_types'][:8])}{' …' if len(i['process_types'])>8 else ''}")
        for rp in i["repos"]:
            print(f"         {rp['gitlab']:<40} {rp.get('path','')}  {rp.get('role','')}")
        if not i["repos"]:
            print("         no repo known — see absent")
    for p in hits["process_types"]:
        print(f"type   {p['process_type']:<28} image {p['image']}; owners {', '.join(p['owners']) or '?'}; code " + (", ".join(r.get('path','') for r in p['repos']) or "unknown"))
    for e in hits["absent"]:
        print(f"absent {e['name']:<28} owner {e['owner'] or '?'}; {e['location'][:90]}")


def cmd_services(mp, a):
    rows = []
    for img, d in sorted(mp.services.items()):
        if a.image and norm(a.image) != norm(img):
            continue
        if a.type and not any(norm(a.type) == norm(t) for t in d["process_types"]):
            continue
        rows.append(dict(image=img, **d))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    for r in rows:
        code = ", ".join(x.get("path", "").replace(mp.projects + "/", "") for x in r["repos"]) or "—"
        print(f"{r['image']:<20} {', '.join(r['owners']) or '?':<20} {len(r['process_types']):>2} types  {code}")


def ls_remote(path):
    url = f"{GITLAB_SSH}/{path}.git"
    try:
        r = subprocess.run(["git", "ls-remote", "--heads", "--tags", url], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return url, None
    refs = [l for l in r.stdout.splitlines() if "\t" in l]
    return url, (len(refs) if r.returncode == 0 and refs else 0)


def cmd_probe(mp, a):
    out = []
    for p in a.paths:
        url, n = ls_remote(p)
        out.append({"path": p, "url": url, "refs": n, "exists": bool(n)})
        print(f"{'ok  ' if n else 'no  '} {p:<45} {n if n is not None else 'timeout'} refs")
    if a.json:
        print(json.dumps(out))


def placement(mp, path):
    """The mds layout rule (mds/README.md): imatrix product sources flat under imatrix/, AI group under ai/,
    a media/<name> that duplicates an imatrix source is a CI shell → reference/shells/, else standalone/."""
    name = path.split("/")[-1]
    mds = os.path.join(mp.projects, "mds")
    if path.startswith("media/imatrix/prj/"):
        return os.path.join(mds, "imatrix", name)
    if path.startswith("media/AI/"):
        return os.path.join(mds, "ai", name)
    if os.path.isdir(os.path.join(mds, "imatrix", name)) or any(r["remote"].endswith(f"/media/imatrix/prj/{name}.git") for r in mp.repos):
        return os.path.join(mds, "reference", "shells", name)
    return os.path.join(mds, "standalone", name)


def cmd_clone(mp, a):
    dest = a.into or placement(mp, a.path)
    url = f"{GITLAB_SSH}/{a.path}.git"
    for r in mp.repos:
        if r["remote"].lower() == url.lower():
            print(f"already on disk: {r['path']}"); return
    if os.path.exists(dest):
        print(f"{dest} exists — refusing to clone over it", file=sys.stderr); sys.exit(EX_USAGE)
    _, n = ls_remote(a.path)
    if not n:
        print(f"{a.path}: nothing answers at {url}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if a.dry_run:
        print(f"DRY RUN — git clone {url} {dest}  ({n} refs)"); return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    r = subprocess.run(["git", "clone", "-q", url, dest], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip()[:300], file=sys.stderr); sys.exit(EX_REMOTE)
    print(f"cloned {a.path} -> {dest}   (run /ela:map to record it)")


def cmd_missing(mp, a):
    rows = [e for e in mp.absent]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    for e in rows:
        print(f"{e['name']:<28} {e['owner'] or '?':<16} {e['location'][:80]}")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="ela map — where code is and how to get it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find"); p.add_argument("name"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("services"); p.add_argument("--image"); p.add_argument("--type"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("probe"); p.add_argument("paths", nargs="+"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("clone"); p.add_argument("path", help="GitLab path, e.g. media/mediabox"); p.add_argument("--into"); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("missing"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    mp = Map()
    {"find": cmd_find, "services": cmd_services, "probe": cmd_probe, "clone": cmd_clone, "missing": cmd_missing}[a.cmd](mp, a)


if __name__ == "__main__":
    main()
