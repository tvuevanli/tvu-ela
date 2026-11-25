#!/usr/bin/env python3
"""The read-only mirror of <published>, kept as an Obsidian vault of its own (site.json `published_mirror`).

`ela publish mirror [--dry-run]` copies <published> one way into the mirror with rsync: content the published
directory no longer holds is removed, so the mirror never shows a file that was withdrawn. The mirror's own reading
state survives: `.obsidian/` (the reader's settings), `.trash/`, and the generated `Home.md` are excluded from the
copy and therefore from its deletes; `.git`, `.gitignore` and temporary files are never carried.

After the copy, `Home.md` is written at the mirror root: what the vault is, that it is read-only and overwritten,
and a link to every note grouped by folder, so the vault reads from one page. Links are relative Markdown links,
which Obsidian resolves inside this vault.

Every writer of <published> calls `after_publish` when it has written (`ela publish` and its subcommands, `ela
release next --write`, `ela teamreport write`), so the mirror is current after every publication, the runner's passes
included. Its outcome is one line on stderr and in <runtime>/publish-mirror.log; a mirror that fails never fails the
publication it follows.

Safety: the target must not be <published> itself, nor overlap the working vault (site.json `vault`), and it must be
missing, empty or an earlier mirror (its Home.md carries the marker below). Anything else is refused, because
`--delete` would remove what is there. Stdlib only.
"""
import datetime, os, re, subprocess, sys

MARKER = "generated-by: ela publish mirror"
HOME = "Home.md"
# carried never: the published tree's repository and temporary files; kept, never deleted: the reader's own state
EXCLUDES = [".git", ".gitignore", "*.tmp", ".*.tmp", "/.obsidian/", "/.trash/", "/" + HOME]


def _real(p):
    return os.path.realpath(os.path.expanduser(p)).rstrip("/") or "/"


def _inside(a, b):
    """a equals b or lies under it."""
    return a == b or a.startswith(b.rstrip("/") + "/")


def refusal(published, target, vault=None):
    """None when the mirror may be written into `target`, else the reason it may not."""
    if not target:
        return "site.json has no published_mirror"
    t, p = _real(target), _real(published)
    if t == "/" or t == _real("~"):
        return f"refused: {target} is not a mirror directory"
    if _inside(t, p) or _inside(p, t):
        return "refused: the mirror overlaps <published>"
    if vault and (_inside(t, _real(vault)) or _inside(_real(vault), t)):
        return "refused: the mirror overlaps the working vault"
    if os.path.exists(t) and not os.path.isdir(t):
        return f"refused: {target} is not a directory"
    if os.path.isdir(t):
        rest = [f for f in os.listdir(t) if f not in (".obsidian", ".trash")]
        home = os.path.join(t, HOME)
        if rest and not (os.path.isfile(home) and MARKER in open(home, encoding="utf-8", errors="replace").read(400)):
            return f"refused: {target} holds files and no mirror Home.md; --delete would remove them"
    return None


def _title(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if line.startswith("# "):
                    return line[2:].strip()
                if i > 40:
                    break
    except OSError:
        pass
    return os.path.splitext(os.path.basename(path))[0]


def _link(rel):
    return rel.replace("%", "%25").replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def home_text(root, now=None):
    """Home.md for the mirror at `root`, from what the mirror holds after the copy."""
    now = now or datetime.datetime.now().astimezone()
    tops, root_notes = {}, []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        rel_dir = os.path.relpath(dirpath, root)
        for f in sorted(files):
            if f.startswith("."):
                continue
            rel = f if rel_dir == "." else f"{rel_dir}/{f}"
            if rel_dir == ".":
                if f.endswith(".md") and f != HOME:
                    root_notes.append(rel)
                continue
            top = rel.split("/")[0]
            t = tops.setdefault(top, {"notes": {}, "data": 0})
            if f.endswith(".md"):
                t["notes"].setdefault(rel_dir, []).append(rel)
            else:
                t["data"] += 1
    L = ["---", MARKER, f"mirrored: {now.strftime('%Y-%m-%d %H:%M %Z').strip()}", "---", "",
         "# MediaHub published knowledge (read-only mirror)", "",
         "A copy of ela's published directory: the MediaHub knowledge, the service map, the lanes and the release "
         "data that Helm and the team's tools read. It is refreshed after every publication.", "",
         "> [!warning] Read-only",
         "> Every file here is overwritten by the next publication, and a file the publication no longer holds is "
         "removed. Edits made here are lost. A correction goes to the source, through ela, and arrives with the next "
         "publication. This vault's own settings (`.obsidian/`) are kept.", ""]
    if root_notes:
        L += ["## Start here", ""] + [f"- [{_title(os.path.join(root, r))}]({_link(r)})" for r in root_notes] + [""]
    if tops:
        L += ["## Folders", ""]
        for top in sorted(tops):
            t = tops[top]
            n = sum(len(v) for v in t["notes"].values())
            L.append(f"- [{top}/](#{top}) — {n} note(s)" + (f", {t['data']} data file(s)" if t["data"] else ""))
        L.append("")
    for top in sorted(tops):
        t = tops[top]
        L += [f"## {top}", ""]
        for d in sorted(t["notes"]):
            if d != top:
                L.append(f"**{d[len(top) + 1:]}/**")
            for r in sorted(t["notes"][d], key=lambda r: (os.path.basename(r) != "README.md", r)):
                L.append(f"- [{_title(os.path.join(root, r))}]({_link(r)})")
            L.append("")
        if t["data"]:
            L += [f"_{t['data']} data file(s) (json, yaml) beside these notes are read by machines, Helm among them; "
                  "Obsidian shows them in the file list only._", ""]
    return "\n".join(L).rstrip() + "\n"


def write_home(root, now=None):
    tmp = os.path.join(root, f".{HOME}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(home_text(root, now))
    os.replace(tmp, os.path.join(root, HOME))


def mirror(published, target, vault=None, dry_run=False):
    """One-way copy of `published` into `target`, then Home.md. → (ok, one-line outcome); never raises, never exits."""
    why = refusal(published, target, vault)
    if why:
        return False, "not mirrored: " + why
    if not os.path.isdir(published):
        return False, "not mirrored: <published> does not exist"
    argv = ["rsync", "-rlt", "--delete", "--modify-window=2", "-i"] + [f"--exclude={e}" for e in EXCLUDES] \
        + (["-n"] if dry_run else []) + [published.rstrip("/") + "/", target.rstrip("/") + "/"]
    try:
        if not dry_run:
            os.makedirs(target, exist_ok=True)
        r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"not mirrored: {str(e)[:160]}"
    if r.returncode != 0:
        return False, f"not mirrored: rsync {r.returncode}: {(r.stderr or '').strip()[-160:]}"
    lines = (r.stdout or "").splitlines()
    copied = [l[12:] for l in lines if re.match(r"^[<>c]f", l)]
    deleted = [l[len("*deleting   "):].strip() for l in lines if l.startswith("*deleting")]
    what = f"{len(copied)} file(s) copied, {len(deleted)} removed"
    if dry_run:
        shown = ", ".join((copied + [f"-{d}" for d in deleted])[:12])
        return True, f"DRY RUN — would mirror <published> to {target}: {what}" + (f" ({shown} …)" if shown else "")
    try:
        write_home(target)
    except OSError as e:
        return False, f"mirrored ({what}) but Home.md failed: {str(e)[:120]}"
    return True, f"mirrored <published> to {target}: {what}, Home.md written"


def after_publish(site, published=None, log_dir=None):
    """Called by every writer of <published> once it has written: mirror, one line on stderr and in the log.
    → the line, or None when no mirror is configured. ELA_PUBLISH_MIRROR overrides the target (tests); an empty
    value turns the mirror off."""
    override = os.environ.get("ELA_PUBLISH_MIRROR")
    target = site.get("published_mirror") if override is None else override
    if not target:
        return None
    if published and override is None and _real(published) != _real(site.get("published") or ""):
        return None                          # a writer pointed at another root (a test's tmp tree) is not the publication
    published = published or site.get("published") or ""
    ok, line = mirror(published, target, site.get("vault"))
    print(f"mirror: {line}", file=sys.stderr)
    log_dir = log_dir or site.get("runtime")
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "publish-mirror.log"), "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")
        except OSError:
            pass
    return line
