#!/usr/bin/env python3
"""tvukb — the media team's knowledge base (tvu-kb), called in its checkout and cited by revision.

    tvukb.py [--env-file F] find <words>          Jenkins catalogue: a module or image name → job, repo, branch, image
    tvukb.py card <project|image>                 the project's (and the image's) card, its dependencies at the end
    tvukb.py deps <project>                       source and library dependencies, and who uses it
    tvukb.py grep <regex>                         the cards searched
    tvukb.py image <image[:tag]>                  an image tag → the build and the module commits in it
    tvukb.py version <program> <version>          a program version → that build's repository list with commits
    tvukb.py sha <sha>                            the builds a commit went into
    tvukb.py svn <revision>                       the SVN-era build of a revision
    tvukb.py status                               the checkout's revision, its read time and whether it is fresh

Each answer is tvu-kb's own `bin/kb`, run in `<code>/media/tvu-kb/skills/tvu-kb`, headed by `tvu-kb@<sha>` and the
time the checkout was last brought to its origin; cite that line with the answer. The checkout is fetched and
fast-forwarded by `ela facts refresh` (source tvukb) once a pass; a read older than ELA_FACTS_MAX_AGE hours, or
--fresh, fetches it first. `kb src` is not offered: the source of a commit is read in ela's own checkout at that
commit (ela map), never in a third cache. Nothing tvu-kb says is stored here. The method — which subcommand for
which question, and how a card's age is judged — is the checkout's own skills/tvu-kb/SKILL.md.

--json: {rev, read_at, fresh, args, exit, output}. Exit codes: 0 ok · 2 usage · 3 no checkout · kb's own otherwise.
"""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "facts"))
import facts as F  # noqa: E402

SUBS = ("find", "card", "deps", "grep", "image", "version", "sha", "svn")
EX_USAGE, EX_NOCHECKOUT = 2, 3
TIMEOUT = 120


def skill_dir():
    return os.path.join(F.tvukb_checkout(), "skills", "tvu-kb")


def ensure_fresh(force):
    """(rev, read_at, fresh, note): the checkout as the last refresh left it, refreshed first when it is older than the
    facts age or `force`. A failed refresh is said and the checkout answers at the revision it has."""
    wm = F.watermark("tvukb")
    note = ""
    if force or not wm.get("at") or not F.fresh(wm.get("at")):
        try:
            note = F.refresh_tvukb(None, False)
        except SystemExit as e:
            F.set_gap("tvukb", str(e.code))
            note = f"tvukb: not refreshed — {e.code}"
        wm = F.watermark("tvukb")
    rev = wm.get("rev") or ""
    if not rev:
        r = subprocess.run(["git", "-C", F.tvukb_checkout(), "rev-parse", "HEAD"], capture_output=True, text=True)
        rev = r.stdout.strip()
    gap = (wm.get("gap") or {}).get("why") if isinstance(wm.get("gap"), dict) else wm.get("gap")
    return rev, wm.get("at"), bool(wm.get("at")) and F.fresh(wm.get("at")) and not gap, note or (f"tvukb: {gap}" if gap else "")


def head(rev, at, fresh):
    when = (at or "never")[:16].replace("T", " ")
    return f"tvu-kb@{rev[:12]} (fetched {when}{'' if fresh else ', NOT fresh'})"


def cmd_status(a):
    if not os.path.isdir(skill_dir()):
        print(f"no tvu-kb checkout at <code>/{'/'.join(F.TVUKB)}", file=sys.stderr); sys.exit(EX_NOCHECKOUT)
    rev, at, fresh, note = ensure_fresh(a.fresh)
    if note:
        print(note, file=sys.stderr)
    if a.json:
        print(json.dumps({"rev": rev, "read_at": at, "fresh": fresh, "skill": os.path.join(skill_dir(), "SKILL.md")})); return
    print(head(rev, at, fresh))
    print(f"method: {os.path.join(skill_dir(), 'SKILL.md')}")


def cmd_kb(a):
    kb = os.path.join(skill_dir(), "bin", "kb")
    if not os.path.isfile(kb):
        print(f"no tvu-kb checkout at <code>/{'/'.join(F.TVUKB)} (no skills/tvu-kb/bin/kb)", file=sys.stderr); sys.exit(EX_NOCHECKOUT)
    if not a.args and a.sub != "find":
        print(f"tvukb {a.sub}: needs an argument", file=sys.stderr); sys.exit(EX_USAGE)
    rev, at, fresh, note = ensure_fresh(a.fresh)
    if note:
        print(note, file=sys.stderr)
    try:
        r = subprocess.run(["bash", kb, a.sub, *a.args], cwd=skill_dir(), capture_output=True, text=True, timeout=TIMEOUT,
                           stdin=subprocess.DEVNULL)
        code, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        code, out = 124, f"kb {a.sub} took longer than {TIMEOUT}s and was stopped"
    if a.json:
        print(json.dumps({"rev": rev, "read_at": at, "fresh": fresh, "args": [a.sub, *a.args], "exit": code, "output": out},
                         ensure_ascii=False))
    else:
        print(head(rev, at, fresh))
        sys.stdout.write(out if out.endswith("\n") or not out else out + "\n")
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(description="tvu-kb, called in its checkout and cited by revision.")
    ap.add_argument("--env-file", help="accepted for the ela adapter; unused")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status", help="the checkout's revision and read time")
    p.add_argument("--fresh", action="store_true", help="fetch now"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)
    for s in SUBS:
        p = sub.add_parser(s, help=f"kb {s}")
        p.add_argument("args", nargs="*")
        p.add_argument("--fresh", action="store_true", help="fetch the checkout first, whatever its age")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=cmd_kb, sub=s)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
