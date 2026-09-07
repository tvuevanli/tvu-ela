#!/usr/bin/env python3
"""ela runtime — the disposable working directory, by contract deletable when no task is open.

  runtime status            each top-level entry with its size and age; open worktrees under work/
  runtime clean [--work]    delete every entry except work/; --work also removes closed worktrees
                            (a worktree whose branch is merged or whose directory has no changes)

Reads <runtime> from ~/.claude/ela/site.json. Never touches elak, the site directory or any checkout under <code>.
"""
import json, os, shutil, subprocess, sys, time

SITE = os.path.expanduser("~/.claude/ela/site.json")


def site():
    return json.load(open(SITE))


def size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def age(path):
    days = (time.time() - os.path.getmtime(path)) / 86400
    return f"{days:.0f}d"


def worktrees(work):
    out = []
    if not os.path.isdir(work):
        return out
    for key in sorted(os.listdir(work)):
        kdir = os.path.join(work, key)
        if not os.path.isdir(kdir):
            continue
        for repo in sorted(os.listdir(kdir)):
            wt = os.path.join(kdir, repo)
            if not os.path.isdir(wt):
                continue
            dirty = subprocess.run(["git", "-C", wt, "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
            branch = subprocess.run(["git", "-C", wt, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
            out.append({"key": key, "repo": repo, "path": wt, "branch": branch, "dirty": bool(dirty)})
    return out


def cmd_status(a):
    s = site()
    rt = s.get("runtime") or os.path.join(s["projects"], ".ela")
    work = s.get("work") or os.path.join(rt, "work")
    rows = []
    for name in sorted(os.listdir(rt)) if os.path.isdir(rt) else []:
        p = os.path.join(rt, name)
        rows.append({"entry": name, "size": size(p) if os.path.isdir(p) else os.path.getsize(p), "age": age(p)})
    wts = worktrees(work)
    if a.json:
        print(json.dumps({"runtime": rt, "entries": rows, "worktrees": wts}, indent=2)); return
    print(f"runtime {rt}")
    for r in rows:
        print(f"  {r['entry']:<16} {human(r['size']):>7}  {r['age']:>5}")
    if wts:
        print("worktrees:")
        for w in wts:
            print(f"  {w['key']}/{w['repo']:<24} {w['branch']:<40} {'dirty' if w['dirty'] else 'clean'}")
    else:
        print("no open worktrees")


def cmd_clean(a):
    s = site()
    rt = s.get("runtime") or os.path.join(s["projects"], ".ela")
    work = s.get("work") or os.path.join(rt, "work")
    removed = []
    for name in sorted(os.listdir(rt)) if os.path.isdir(rt) else []:
        p = os.path.join(rt, name)
        if os.path.realpath(p) == os.path.realpath(work):
            continue
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        removed.append(name)
    if a.work:
        for w in worktrees(work):
            if w["dirty"]:
                print(f"kept {w['key']}/{w['repo']} — uncommitted changes", file=sys.stderr); continue
            repo = subprocess.run(["git", "-C", w["path"], "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip()
            subprocess.run(["git", "-C", w["path"], "worktree", "remove", "--force", w["path"]], capture_output=True)
            if os.path.isdir(w["path"]):
                shutil.rmtree(w["path"])
            removed.append(f"work/{w['key']}/{w['repo']}")
            kdir = os.path.dirname(w["path"])
            if os.path.isdir(kdir) and not os.listdir(kdir):
                os.rmdir(kdir)
    print(json.dumps({"removed": removed}) if a.json else ("removed: " + (", ".join(removed) or "nothing")))


def main():
    import argparse
    p = argparse.ArgumentParser(prog="ela runtime", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("status"); q.add_argument("--json", action="store_true")
    q = sub.add_parser("clean"); q.add_argument("--work", action="store_true"); q.add_argument("--json", action="store_true")
    a = p.parse_args()
    {"status": cmd_status, "clean": cmd_clean}[a.cmd](a)


if __name__ == "__main__":
    main()
