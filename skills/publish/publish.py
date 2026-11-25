#!/usr/bin/env python3
"""Publish — render an elak source into the published directory machines read, and record the row in elak's manifest.

  all [--json]              everything below, then <published>/MANIFEST.md (what this directory holds, from where, when)
  catalogue [--json]        <elak>/map/services.yaml → <published>/knowledge/products/mediahub/services.md
  map [--json]              <elak>/map/*.yaml + README.md → <published>/map/ (addresses replaced by placeholders)
  pins [--json]             <elak>/blueprint/releases.yaml → <published>/blueprint/releases.yaml, the official bundle
                            per release line (ela ADR 0012), so Helm and the other machines read the owner's pin
  doc <rel> [--reader …]    <elak>/knowledge/<rel> → <published>/knowledge/<rel>, the elak document verbatim through `redact`
  lanes [--sync] [--json]   <reports>/lanes/ (lanes.md, test-list-*, dev-list-*) → <published>/lanes/, for Helm: pages
                            (with the newest <runtime>/runner/versions-<date>.json, the desk's lane versions, one copy kept);
                            each json gains a `label` beside every `lane`, its display label, and lanes/README.md says so
                            ela generates, not elak sources, so no manifest row; through `redact`, and a file the
                            content guard's rules flag (a credential, a quoted sentence) is refused with its line;
                            --sync then carries lanes/ alone to `published_remote` (typing it is the confirm); a sync
                            that fails is a line, never a failed publication
  list                      every manifest row and whether its source changed since (exit 1 when a republish is due)
  check [--json]            the release guard over the versioned part (knowledge/platform, knowledge/products, map/):
                            refuses the owner's word or name as a source, a quotation attributed to a person, and the
                            content guard's credential and quoted-sentence rules (exit 1, with the lines)
  release [--apply] [--json]  the team's versioned release (elak decisions/2026-11-25-published-knowledge-is-a-
                            versioned-release.md): whether one is due, what it would commit, the guard's verdict;
                            --apply commits it in <published>, recording elak's HEAD; it never pushes
  mirror [--dry-run]        <published> → site.json `published_mirror`, a read-only Obsidian vault of its own, one way
                            (withdrawn files removed; the vault's .obsidian/ kept), with a generated Home.md (mirror.py).
                            Every subcommand that writes <published> runs it afterwards, as do `ela release next --write`
                            and `ela teamreport write`; its outcome is one line, never a failed publication

The published directory is a subset of elak's own tree — the same paths, elak's names, no per-reader
directories. Readers (Helm's context packs, the remote ela) point at these paths.

A publication is written, not exported (elak map/README.md): the document opens by saying what it is,
carries every limit the source states where the reader sees it, and names its source and dates. Nothing
under <published> is edited by hand; a change is made in elak and published again. Stdlib only.
Roots come from site.json: `elak` and `published`. Every source is read from elak's last commit: a source whose
working copy differs from HEAD stops the publication unless --dirty, and the manifest's published-on date is the
source's commit date. Exit codes: 0 ok · 2 usage (an uncommitted source included) · 5 write failed.
"""
import argparse, datetime, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from addresses import IPV4, is_address   # noqa: E402 — one address rule, shared with hooks/content-guard.sh
import mirror as M                       # noqa: E402 — the read-only Obsidian mirror of <published>

EX_USAGE, EX_WRITE = 2, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        print("no ~/.claude/ela/site.json — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)


def roots():
    s = site()
    rec, pub = s.get("elak") or s.get("records"), s.get("published")   # old key accepted until /ela:setup renames it
    if not rec or not pub:
        print("site.json needs `elak` and `published` (the generated directory) — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)
    if s.get("site") == "remote":
        print("this is a remote site: publications are generated at the office and carried by the deploy", file=sys.stderr); sys.exit(EX_USAGE)
    return rec, pub


# ── the source is elak's last commit ──────────────────────────────────────────
# elak is committed on the owner's word, and publishing is how far that word reaches: what machines read is the output
# of a commit, never a half-edited tree. Every source is read from a snapshot of HEAD; a source whose working copy
# differs from HEAD stops the publication (one line naming the files) unless --dirty says the tree is meant.

DIRTY = {"on": False}               # --dirty: read the working tree, as before
_SNAP = {}


def git(records, *args):
    import subprocess
    r = subprocess.run(["git", "-C", records, *args], capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode(errors="replace").strip()[:200] or f"git {args[0]} failed")
    return r.stdout


def source_root(records):
    """The tree publication reads: elak's HEAD unpacked into a temporary directory, or elak itself with --dirty."""
    if DIRTY["on"]:
        return records
    if records not in _SNAP:
        import atexit, io, shutil, tarfile, tempfile
        d = tempfile.mkdtemp(prefix="elak-head-")
        atexit.register(shutil.rmtree, d, True)
        try:
            tarfile.open(fileobj=io.BytesIO(git(records, "archive", "--format=tar", "HEAD"))).extractall(d)
        except (RuntimeError, tarfile.TarError) as e:
            print(f"cannot read elak's HEAD: {e}", file=sys.stderr); sys.exit(EX_USAGE)
        _SNAP[records] = d
    return _SNAP[records]


def require_committed(records, rels):
    """Stop when a source to publish differs from HEAD (edited, staged or untracked) and --dirty was not given."""
    if DIRTY["on"] or not rels:
        return
    try:
        out = git(records, "status", "--porcelain", "--untracked-files=all", "--", *rels).decode()
    except RuntimeError as e:
        print(f"cannot read elak's status: {e}", file=sys.stderr); sys.exit(EX_USAGE)
    dirty = sorted({l[3:].strip() for l in out.splitlines() if l.strip()})
    if dirty:
        print(f"publish: not committed in elak: {', '.join(dirty)} — commit them first (or --dirty to publish the tree)", file=sys.stderr)
        sys.exit(EX_USAGE)


def source_date(records, rel):
    """The date the source was committed: the manifest's published-on row says which commit the copy is."""
    if DIRTY["on"]:
        return datetime.date.today().isoformat()
    try:
        return git(records, "log", "-1", "--format=%cs", "HEAD", "--", rel.split(" ")[0]).decode().strip() or datetime.date.today().isoformat()
    except RuntimeError:
        return datetime.date.today().isoformat()


# ── services.yaml, the subset of YAML it uses ─────────────────────────────────

def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        inner = v[1:-1]
        return inner.replace("''", "'") if v[0] == "'" else inner.replace('\\"', '"')
    return v


def read_front_matter(path):
    """→ the top-level scalars of a document's own YAML front matter, {} when the file has none."""
    fm = {}
    with open(path, encoding="utf-8") as fh:
        if fh.readline().rstrip("\n") != "---":
            return fm
        for raw in fh:
            line = raw.rstrip("\n")
            if line == "---":
                return fm
            key, sep, val = line.partition(":")
            if sep and key and not key[0].isspace() and not key.startswith(("-", "#")):
                fm[key.strip()] = _scalar(val)
    return fm                                        # unterminated front matter: what was read, the caller checks


def read_services(path):
    """→ (header: dict of top-level scalars, images: {name: {owners, slugs, gm_names, process_types, services, repos, note}})."""
    header, images, cur, repo, in_images = {}, {}, None, None, False
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, _, val = line.partition(":")
            if key == "images":
                in_images = True; continue
            in_images = False
            header[key] = _scalar(val); continue
        if not in_images:
            continue
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            cur = images.setdefault(m.group(1), {"owners": [], "slugs": [], "gm_names": [], "process_types": [], "services": [], "repos": [], "note": ""}); repo = None; continue
        if cur is None:
            continue
        m = re.match(r"^    (owners|slugs|gm_names|process_types): (.+)$", line)
        if m:
            try: cur[m.group(1)] = json.loads(m.group(2))
            except ValueError: cur[m.group(1)] = [_scalar(m.group(2))]
            continue
        m = re.match(r"^    note: (.+)$", line)
        if m:
            cur["note"] = _scalar(m.group(1)); continue
        m = re.match(r"^      - (\{.*\})\s*(#.*)?$", line)
        if m:
            try: cur["services"].append(json.loads(m.group(1)))
            except ValueError: pass
            continue
        m = re.match(r"^      - gitlab: (.+)$", line)
        if m:
            repo = {"gitlab": _scalar(m.group(1)), "role": ""}; cur["repos"].append(repo); continue
        m = re.match(r"^        role: (.+)$", line)
        if m and repo is not None:
            repo["role"] = _scalar(m.group(1)); continue
    return header, images


# ── the document ──────────────────────────────────────────────────────────────

def render_catalogue(header, images, today):
    n_services = sum(len(i["services"]) for i in images.values())
    out = [
        "---",
        f"verified: '{header.get('verified', '')}'",
        f"source: elak map/services.yaml (verified {header.get('verified', '?')}), published by ela on {today}",
        "generated: true — do not edit; change elak map/services.yaml and run `ela publish catalogue`",
        "path: knowledge/products/mediahub/services.md (elak's tree; the published directory is its subset)",
        "---",
        "",
        "# MediaHub media docker services — the catalogue",
        "",
        f"What runs as a media docker in MediaHub: {len(images)} docker images carrying {n_services} GM services. For each image: "
        "who owns it, the GM services it registers (the `mds-` slug, the name GM registers, GM's service id, the J2N "
        "process type, the MQTT topic, deployment status) and where its code lives (GitLab group paths). Helm's context "
        "packs read this file; ela's map is its source.",
        "",
        "## What this document can and cannot say",
        "",
        f"- Source of the table: {header.get('source', '(unstated)')}",
        f"- {header.get('note', '')}" if header.get("note") else "",
        f"- Architecture: {header.get('architecture', '')}" if header.get("architecture") else "",
        "- A repo marked *candidate* or *not yet read* was located by name in the GitLab group listing and has not been read; "
        "a slug with service id `TBD` is registered only, not deployed.",
        "",
        "## Every service, one line",
        "",
        "| slug | GM name | service id | process type | image | owner | status |",
        "|---|---|---|---|---|---|---|",
    ]
    for img in sorted(images):
        i = images[img]
        for s in i["services"]:
            out.append(f"| `{s.get('slug','')}` | {s.get('gm_name','')} | `{s.get('service_id','')}` | `{s.get('process_type','')}` | `{img}` | {', '.join(i['owners']) or '?'} | {s.get('status','')} |")
    out += ["", "## By image", ""]
    for img in sorted(images):
        i = images[img]
        out.append(f"### `{img}`")
        out.append("")
        out.append(f"Owner: {', '.join(i['owners']) or 'unknown'} · process types: {', '.join('`' + p + '`' for p in i['process_types']) or '—'}")
        if i["note"]:
            out.append(f"Note: {i['note']}")
        out.append("")
        if i["services"]:
            out.append("| slug | GM name | service id | MQTT topic | status |")
            out.append("|---|---|---|---|---|")
            for s in i["services"]:
                out.append(f"| `{s.get('slug','')}` | {s.get('gm_name','')} | `{s.get('service_id','')}` | `{s.get('mqtt_topic','')}` | {s.get('status','')} |")
            out.append("")
        if i["repos"]:
            out.append("Code:")
            for r in i["repos"]:
                out.append(f"- `{r['gitlab']}`" + (f" — {r['role']}" if r["role"] else ""))
        else:
            out.append("Code: no repository known — see elak map/absent.yaml.")
        out.append("")
    out += ["---", "", f"Generated by ela `publish catalogue` on {today} from elak `map/services.yaml` (verified {header.get('verified', '?')}). "
            "The manifest row is in elak `map/published-machines.md`.", ""]
    return "\n".join(x for x in out if x is not None)


# ── the manifest row ──────────────────────────────────────────────────────────

def update_manifest(records, source_rel, dest_rel, today, verified, reader):
    path = os.path.join(records, "map", "published-machines.md")
    text = open(path, encoding="utf-8").read()
    row = f"| `{source_rel}` | `<published>/{dest_rel}` | {today} | {verified} | {reader} |"
    lines = text.splitlines()
    out, replaced, in_table = [], False, False
    for ln in lines:
        if ln.startswith("| source | published file |"):
            in_table = True; out.append(ln); continue
        if in_table and ln.startswith("|---"):
            out.append(ln); continue
        if in_table and ln.startswith("|"):
            if ln.startswith("| — |") or f"`{source_rel}`" in ln:
                if not replaced:
                    out.append(row); replaced = True
                continue
            cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 5 and not os.path.exists(os.path.join(records, cells[0].split(" ")[0])):
                continue                                      # a source that no longer exists has no row
            out.append(ln); continue
        if in_table and not ln.startswith("|"):
            if not replaced:
                out.append(row); replaced = True
            in_table = False
        out.append(ln)
    if not replaced:
        out.append(row)
    open(path, "w", encoding="utf-8").write("\n".join(out) + ("\n" if text.endswith("\n") else ""))
    return path, row


def manifest_rows(records):
    """elak's publication manifest → one list of cells per row: source · published file · generated · verified · reader.

    The one place the manifest is read: what is published, and therefore what a reader may be holding open,
    is answered from these rows and never from a second list kept beside them."""
    path = os.path.join(records, "map", "published-machines.md")
    rows = []
    for ln in open(path, encoding="utf-8"):
        if not ln.startswith("| `"):
            continue
        cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 5:                 # the "First content" table has three cells; only manifest rows are rows
            rows.append(cells)
    return rows


def published_paths(records, published):
    """Every path under <published> the manifest records as published, absolute — files and the directories
    that hold them. A row's published file may name a directory and its contents,
    `<published>/knowledge/people/ (people.yaml, responsibilities.yaml, roster.md)`; both forms are returned."""
    paths = set()
    for cells in manifest_rows(records):
        head, _, listed = cells[1].replace("<published>/", "").partition(" (")
        base = os.path.join(published, *head.strip().rstrip("/").split("/"))
        paths.add(base)
        paths.update(os.path.join(base, n.strip()) for n in listed.rstrip(")").split(",") if n.strip())
    return paths


def holds_published(path, protected):
    """→ whether `path` is, or contains, something the manifest records as published."""
    prefix = os.path.join(path, "")
    return any(p == path or p.startswith(prefix) for p in protected)


def cmd_catalogue(a):
    records, published = roots()
    require_committed(records, ["map/services.yaml"])
    src = os.path.join(source_root(records), "map", "services.yaml")
    header, images = read_services(src)
    if not images:
        print(f"{src}: no images parsed", file=sys.stderr); sys.exit(EX_USAGE)
    today = source_date(records, "map/services.yaml")
    dest_rel = "knowledge/products/mediahub/services.md"
    dest = os.path.join(published, dest_rel)
    doc = render_catalogue(header, images, today)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"; open(tmp, "w", encoding="utf-8").write(doc); os.replace(tmp, dest)
    except OSError as e:
        print(f"cannot write {dest}: {e}", file=sys.stderr); sys.exit(EX_WRITE)
    mpath, row = update_manifest(records, "map/services.yaml", dest_rel, today, header.get("verified", "?"),
                                 "Helm context pack `service_catalog` (once Helm's knowledge root points at <published>/knowledge)")
    write_published_manifest(records, published)
    n = sum(len(i["services"]) for i in images.values())
    if a.json:
        print(json.dumps({"source": src, "destination": dest, "images": len(images), "services": n, "verified": header.get("verified"), "published": today, "manifest": mpath}, ensure_ascii=False)); return
    print(f"published {dest_rel}\n  {len(images)} images · {n} services · source verified {header.get('verified')} · published {today}\n  manifest row → {mpath}\n  {row}")


# ── the roster: knowledge/people/{people,responsibilities}.yaml → roster.md + both yamls as they are ────

def render_team_map(header, people, today):
    """One identity block per CORE person, in the shape Helm's roster parser already reads —
    `**Name** — <responsibility>`, `- Email:`, `- Slack:`, `- Jira accountId:`.

    Related people are rendered as a table and never as an identity block: Helm parses a bolded
    `**Name** — …` line as an internal member, invents an ownership area from the nearest heading and
    logs `[roster] NO COLOR` on every lookup — strictly worse than leaving them table-only
    (helm knowledge/mediahub/team/team-map.md § External Cross-Team Owners)."""
    core = [p for p in people if p["scope"] == "core"]
    related = [p for p in people if p["scope"] != "core"]
    areas = []
    for p in core:
        if p["area"] not in areas:
            areas.append(p["area"])
    out = [
        "---", f"verified: '{header.get('verified', '?')}'", f"published: '{today}'",
        "source: generated by `ela publish roster` from elak knowledge/people/people.yaml + responsibilities.yaml — edit the source, publish again",
        "---", "", "# MediaHub Roster", "",
        "What this is: who is on MediaHub and how each person is identified. The only place a person's identity "
        "(email, Slack id, Jira account) is asserted. Every email and Slack id was read first-hand from Slack "
        "`users.list`; Jira ids were confirmed against ticket history. "
        f"Source verified {header.get('verified', '?')}; published {today}.", "",
        "No rank is recorded here: no title, no seniority, no reporting line. MediaHub responsibility is "
        "de-facto and TVU has no matching titles, so a level would be invented rather than read "
        "(elak `blueprint/decisions/2026-09-04-roster-schema-identity-and-responsibilities.md`). Where an area has a de-facto lead, it "
        "appears as **ask first** on that area, which is per person-and-area and is not comparable across areas.", "",
        "**Rule.** A person not listed here is unknown: look them up first-hand and add them to the source; never compose an "
        "address from a name (elak `blueprint/principles.md` P6).", "",
    ]
    if header.get("note"):
        out += [f"Note: {header['note']}", ""]
    for area in areas:
        out += [f"## {area}", ""]
        for p in [x for x in core if x["area"] == area]:
            first = next((r for r in p["responsibilities"] if r.get("first_contact") is True), None)
            out.append(f"**{p['name']}** — {(first or p['responsibilities'][0])['what'].split(' — ')[0].split('. ')[0]}")
            single = len(p["responsibilities"]) == 1
            for r in p["responsibilities"]:
                mark = " (ask first about this area)" if r.get("first_contact") is True else ""
                if single and not mark and not r["owns"]:
                    continue                                  # the header already says it; a repeated bullet reads as a second responsibility
                out.append(f"- {r['scope']}/{r['area']}{mark}: {r['what']}" if not single else f"- {r['scope']}/{r['area']}{mark}")
                if r["owns"]:
                    out.append(f"  - owns: {', '.join(r['owns'])}")
            if p.get("review_means"):
                out.append(f"- A Review-status ticket here reads as: {p['review_means']}")
            out.append(f"- Email: {p['email']}")
            out.append(f"- Slack: user ID `{p['slack']}`")
            if p.get("jira") and p.get("jira_name"):
                out.append(f"- Jira: `{p['jira_name']}` — accountId `{p['jira']}`")
            elif p.get("jira"):
                out.append(f"- Jira accountId: `{p['jira']}`")
            else:
                out.append("- Jira accountId: not recorded — look it up before assigning")
            out.append("")
    out += ["## Related — not on the MediaHub team", "",
            "Everyone here has a business relationship with MediaHub (they own a service MH depends on or "
            "integrates, or have a say in MH product decisions) and none of them may be assigned MediaHub work: "
            "tag or loop them, the MH-side area lead stays the driver.", "",
            "| Person | Area | Responsibility | Email | Slack | Jira |", "|---|---|---|---|---|---|"]
    for p in related:
        what = " · ".join(r["what"] for r in p["responsibilities"])
        out.append(f"| {p['name']} | {', '.join(p['areas'])} | {what} | {p['email']} | `{p['slack']}` | "
                   f"{('`' + p['jira'] + '`') if p['jira'] else 'not recorded'} |")
    out.append("")
    return "\n".join(out)


# the artefacts the roster was published as before it moved, per directory: exact names, never a whole tree,
# because a retired directory goes on holding published documents (knowledge/products/mediahub/team/ holds the
# layer rules) and every reader reads <published> live.
STALE_ROSTER_ARTEFACTS = (
    ("knowledge/people", ("team-map.md",)),                                       # Helm's filename for the roster, until 2026-09-03
    ("knowledge/products/mediahub/team", ("roster.md", "roster.yaml", "team-map.md")),   # the roster's own location, until 2026-09-04
)


def prune_stale(published, protected):
    """Remove the named stale artefacts under <published>, and a directory only once it is left empty.

    A cleanup may delete only what it knows to be stale. A path the manifest records as published is refused
    whatever its name: readers were told they may read it, and removing one takes a file out from under a
    running reader. → the paths removed."""
    removed = []
    for rel_dir, names in STALE_ROSTER_ARTEFACTS:
        d = os.path.join(published, *rel_dir.split("/"))
        if not os.path.isdir(d):
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p) and not holds_published(p, protected):
                os.remove(p); removed.append(p)
        if not os.listdir(d):
            os.rmdir(d); removed.append(d)
    return removed


def cmd_roster(a):
    import shutil
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "team"))
    import team  # noqa: E402 — the roster reader, same plugin
    records, published = roots()
    src_rel = "knowledge/people/ (people.yaml, responsibilities.yaml)"
    require_committed(records, ["knowledge/people/people.yaml", "knowledge/people/responsibilities.yaml"])
    src = os.path.join(source_root(records), "knowledge", "people")
    header, people = team.read_roster(source_root(records))
    if not people:
        print(f"{src}: no people parsed", file=sys.stderr); sys.exit(EX_USAGE)
    today = source_date(records, "knowledge/people")
    dest_dir = os.path.join(published, "knowledge", "people")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        for f in ("people.yaml", "responsibilities.yaml"):
            shutil.copyfile(os.path.join(src, f), os.path.join(dest_dir, f))
        tmp = os.path.join(dest_dir, "roster.md.tmp")
        open(tmp, "w", encoding="utf-8").write(render_team_map(header, people, today))
        os.replace(tmp, os.path.join(dest_dir, "roster.md"))
        prune_stale(published, published_paths(records, published))
    except OSError as e:
        print(f"cannot write {dest_dir}: {e}", file=sys.stderr); sys.exit(EX_WRITE)
    mpath, row = update_manifest(records, src_rel, "knowledge/people/ (people.yaml, responsibilities.yaml, roster.md)", today,
                                 header.get("verified", "?"), "Helm `known_emails()` (published-only file, no Helm copy to shadow); `ela who` on Helm Akamai")
    write_published_manifest(records, published)
    if a.json:
        print(json.dumps({"source": src, "destination": dest_dir, "people": len(people), "verified": header.get("verified"), "published": today, "manifest": mpath}, ensure_ascii=False)); return
    print(f"published knowledge/people/ (people.yaml, responsibilities.yaml, roster.md)\n  {len(people)} people · source verified {header.get('verified')} · published {today}\n  manifest row → {mpath}\n  {row}")


TAILNET = re.compile(r"\b[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b")


def redact(text):
    """The published tree is read inside the company but outside this machine: an address is replaced by
    a placeholder, a tailnet name likewise. What counts as an address (a version number does not) is
    addresses.is_address, the rule the commit-time content guard applies too."""
    return TAILNET.sub("<tailnet>", IPV4.sub(lambda m: "<ip>" if is_address(text, m) else m.group(0), text))


def map_files(src_dir):
    return sorted(f for f in os.listdir(src_dir) if f.endswith(".yaml") or f == "README.md")


def cmd_map(a):
    """The machine-readable map — services · absent · release · apis · dependencies and the README — copied
    through `redact`: the file shape is unchanged, addresses are not carried."""
    records, published = roots()
    require_committed(records, [f"map/{f}" for f in map_files(os.path.join(records, "map"))])
    src_dir, dst_dir = os.path.join(source_root(records), "map"), os.path.join(published, "map")
    os.makedirs(dst_dir, exist_ok=True)
    names, redacted = map_files(src_dir), 0
    for f in names:
        text = open(os.path.join(src_dir, f), encoding="utf-8").read()
        out = redact(text)
        redacted += out.count("<ip>") + out.count("<tailnet>") - text.count("<ip>") - text.count("<tailnet>")
        tmp = os.path.join(dst_dir, f + ".tmp"); open(tmp, "w", encoding="utf-8").write(out); os.replace(tmp, os.path.join(dst_dir, f))
    protected = published_paths(records, published)
    for stale in sorted(set(os.listdir(dst_dir)) - set(names)):   # a source that no longer exists is not kept downstream
        p = os.path.join(dst_dir, stale)                          # scoped to map/, whose every file this verb writes
        if os.path.isfile(p) and not holds_published(p, protected):
            os.remove(p)
    today = source_date(records, "map")
    ver = next((l.split(":", 1)[1].strip().strip("'") for l in open(os.path.join(src_dir, "services.yaml")) if l.startswith("verified:")), "?")
    update_manifest(records, "map/", "map/", today, ver, "ela's read verbs (site.json `map` points here), the remote ela, Helm `release_map`")
    write_published_manifest(records, published)
    if a.json:
        print(json.dumps({"files": names, "destination": dst_dir, "published": today, "redacted": redacted})); return
    print(f"published map/ ({', '.join(names)}) → {dst_dir}" + (f"  · {redacted} address(es) replaced by placeholders" if redacted else ""))


# ── the official bundle per release line (ADR 0012) ───────────────────────────

PINS_REL = "blueprint/releases.yaml"


def cmd_pins(a):
    """The owner's release pins, copied through `redact`; a line not pinned is simply absent. No source, nothing to do."""
    records, published = roots()
    if os.path.isfile(os.path.join(records, PINS_REL)):
        require_committed(records, [PINS_REL])
    src, dst = os.path.join(source_root(records), PINS_REL), os.path.join(published, PINS_REL)
    if not os.path.isfile(src):
        msg = f"no {PINS_REL} in elak: no line is held; prod follows the newest official bundle (ADR 0013)"
        print(json.dumps({"published": None, "why": msg}) if a.json else msg); return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"; open(tmp, "w", encoding="utf-8").write(redact(open(src, encoding="utf-8").read())); os.replace(tmp, dst)
    today = source_date(records, PINS_REL)
    update_manifest(records, PINS_REL, PINS_REL, today, today, "ela matrix and ela changes on machines without elak; Helm's official bundle")
    write_published_manifest(records, published)
    print(json.dumps({"destination": dst, "published": today}) if a.json else f"published {PINS_REL} → {dst}")


# ── a written document from elak's knowledge tree ─────────────────────────────

DOC_READER = ("Helm context packs once the rel is adopted (config_loader.PUBLISHED_ADOPTED_RELS); the remote ela")
DOC_ROW = re.compile(r"^knowledge/\S+\.md$")


def publish_doc(records, published, rel, reader, today):
    """One prose document, elak's `knowledge/<rel>` → the same path under <published>, through `redact`.

    The published file is the elak source verbatim, front matter included: the reader must see the
    document's own `verified:` and `source:`, and nothing but an address is rewritten on the way."""
    require_committed(records, [f"knowledge/{rel}"])
    src = os.path.join(source_root(records), "knowledge", rel)
    today = source_date(records, f"knowledge/{rel}")
    if not os.path.isfile(src):
        print(f"no such document: {src}", file=sys.stderr); sys.exit(EX_USAGE)
    text = open(src, encoding="utf-8").read()
    fm = read_front_matter(src)
    if not fm.get("verified") or not fm.get("source"):
        print(f"{src}: no front matter carrying both `verified:` and `source:` — every document in elak's "
              "knowledge tree carries both (elak knowledge/README.md). Add them in elak, then publish.",
              file=sys.stderr); sys.exit(EX_USAGE)
    out = redact(text)
    dest_rel = f"knowledge/{rel}"
    dest = os.path.join(published, dest_rel)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"; open(tmp, "w", encoding="utf-8").write(out); os.replace(tmp, dest)
    except OSError as e:
        print(f"cannot write {dest}: {e}", file=sys.stderr); sys.exit(EX_WRITE)
    redacted = out.count("<ip>") + out.count("<tailnet>") - text.count("<ip>") - text.count("<tailnet>")
    mpath, row = update_manifest(records, dest_rel, dest_rel, today, fm["verified"], reader)
    return {"source": src, "destination": dest, "rel": dest_rel, "verified": fm["verified"],
            "published": today, "redacted": redacted, "manifest": mpath, "row": row}


def doc_rows(records):
    """The manifest's document rows → [(rel relative to knowledge/, the reader recorded for it)].

    A row is a document when its source is a single `.md` file under `knowledge/`; the roster's row names
    the `knowledge/people/` directory and is published by `roster`, not here."""
    return [(c[0][len("knowledge/"):], c[4]) for c in manifest_rows(records) if DOC_ROW.match(c[0])]


def cmd_doc(a):
    records, published = roots()
    r = publish_doc(records, published, a.rel.strip("/"), a.reader, datetime.date.today().isoformat())
    write_published_manifest(records, published)
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    print(f"published {r['rel']}\n  source verified {r['verified']} · published {r['published']}"
          + (f" · {r['redacted']} address(es) replaced by placeholders" if r["redacted"] else "")
          + f"\n  manifest row → {r['manifest']}\n  {r['row']}")


# ── the lanes' pages: generated by ela, read by Helm ─────────────────────────

LANE_PAGE = re.compile(r"^(lanes\.md|(?:test|dev)-list-[\w.-]+\.(?:md|json))$")
GUARD = [(re.compile(r"xox[abpe]-[A-Za-z0-9-]{10,}"), "Slack token"), (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
         (re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_\-]{12,}"), "credential assignment"),
         (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{24,}"), "bearer token"),
         (re.compile(r"[\"“«「『]([^\"”»」』\n]{0,80}[\u4e00-\u9fff][^\"”»」』\n]{0,80})[\"”»」』]"), "a quoted CJK sentence")]


def guard_flags(text, name="", facts=()):
    """The content guard's rules a published page must pass (hooks/content-guard.sh): a credential anywhere, a quoted
    sentence of eight or more CJK characters. A `.json` file's quotes are syntax, so there the quoted-sentence rule reads
    its decoded string values and names the key path; a json that does not parse is read as text. A quotation that is
    part of one of `facts` (the Jira titles the lists carry) is a field with a source, not a person's words, and passes.
    → [(line number or key path, why, line)]."""
    values = None
    if name.endswith(".json"):
        try:
            values = list(json_strings(json.loads(text)))
        except ValueError:
            pass
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for rx, why in GUARD:
            if values is not None and why == QUOTED:
                continue
            m = rx.search(line)
            if m and quoted_cjk_ok(why, m) and not (why == QUOTED and is_fact(m, facts)):
                out.append((n, why, line.strip()[:100]))
    for path, v in values or []:
        rx, why = GUARD[-1]
        for line in v.splitlines():
            m = rx.search(line)
            if m and quoted_cjk_ok(why, m) and not is_fact(m, facts):
                out.append((path, why, line.strip()[:100]))
    return out


QUOTED = "a quoted CJK sentence"
QUOTE_CUT = "(quoted text left out)"


def is_fact(m, facts):
    """True when the quotation `m` matched sits inside one of `facts` — a Jira field the page cites."""
    return any(m.group(0) in f for f in facts)


def lane_titles(src, names):
    """Every `title` value in the lanes' json files: the Jira summaries the lists and the lanes page carry."""
    out = set()
    for f in names:
        if not f.endswith(".json"):
            continue
        try:
            doc = json.load(open(os.path.join(src, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out |= {v for path, v in json_strings(doc) if path.endswith(".title") and isinstance(v, str)}
    return out


def cut_quotes(text, name, facts):
    """`text` with every flagged quotation replaced by QUOTE_CUT, credentials untouched → (text, cut count). A json
    file is cut in its decoded values and dumped again in the list writer's form (indent 1, CJK kept)."""
    rx = GUARD[-1][0]
    n = [0]

    def cut(s):
        def one(m):
            if quoted_cjk_ok(QUOTED, m) and not is_fact(m, facts):
                n[0] += 1
                return QUOTE_CUT
            return m.group(0)
        return rx.sub(one, s)
    if name.endswith(".json"):
        try:
            doc = json.loads(text)
        except ValueError:
            doc = None
        if doc is not None:
            def walk(v):
                if isinstance(v, str):
                    return cut(v)
                if isinstance(v, dict):
                    return {k: walk(x) for k, x in v.items()}
                if isinstance(v, list):
                    return [walk(x) for x in v]
                return v
            out = walk(doc)
            return (json.dumps(out, ensure_ascii=False, indent=1) + "\n" if n[0] else text), n[0]
    return "\n".join(cut(line) for line in text.split("\n")), n[0]


def quoted_cjk_ok(why, m):
    """True when a match counts: any credential, or a quotation holding eight or more CJK characters."""
    return why != QUOTED or len(re.findall(r"[\u4e00-\u9fff]", m.group(1))) >= 8


def json_strings(v, path="$"):
    """Every string value in a decoded json document → (key path, value)."""
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from json_strings(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from json_strings(x, f"{path}[{i}]")


LANES_README = """# lanes/

Generated by `ela publish lanes` from the owner's reports; regenerated on every publish, never edited.

| file | what |
|---|---|
| `lanes.md` | the lanes across the release lines, the vault's `releases/lanes.md` |
| `test-list-<lane>.json`, `.md` | what QA verifies on a lane, ranked |
| `dev-list-<line>.json`, `.md` | what is in development for a release line |
| `versions-<date>.json` | the desk's last read of every lane's service versions, one dated copy |

## `label`

Every object in these json files that carries a `lane` (the lane's token, such as `daily-wed`, `qa-cn3`,
`prod-2-china`) carries a `label` beside it: the lane's display label, MediaHub's name first with the UR / J2N
environment in brackets where the map names one, such as `daily-wed (UR test2)`, `prod-3 (UR/J2N Prod 3)`,
`CN Prod2 (UR/J2N cn2)`, or MediaHub's name alone, such as `QA-AWS3`. A reader shows `label` verbatim and never
composes one from `lane` or `shown`: the MediaHub side knows the lanes by these names, and a UR environment alone or a
file token in brackets misnames them. `lane` stays the key to match on; `shown` in a test list is the release mails'
own wording for the lane, kept as read. The label is derived in one place, ela `skills/release/line.py` `lane_label`.
"""


def lane_label_of():
    """release line.py's lane_label, the one derivation of a lane's display label; None when it cannot be loaded."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "release"))
        import line as LP                                 # noqa: E402
        return LP.lane_label
    except Exception:                                      # noqa: BLE001 — a page without labels beats no page
        return None


def with_labels(text, name, label):
    """`text` with a `label` after every `lane` in a json document — the document itself and each object in its
    top-level lists — in the list writer's form (indent 1, CJK kept); unchanged when nothing is added or it is no json."""
    if not name.endswith(".json") or label is None:
        return text
    try:
        doc = json.loads(text)
    except ValueError:
        return text
    added = [0]

    def one(o):
        if not isinstance(o, dict) or not isinstance(o.get("lane"), str) or not o["lane"]:
            return o
        out = {}
        for k, v in o.items():
            if k == "label":
                continue
            out[k] = v
            if k == "lane":
                out["label"] = label(v)
        added[0] += out["label"] != o.get("label")
        return out
    if isinstance(doc, dict):
        doc = one(doc)
        doc = {k: [one(x) for x in v] if isinstance(v, list) else v for k, v in doc.items()}
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n" if added[0] else text


def cmd_lanes(a):
    """The lanes page and the test and dev lists, copied through `redact` into <published>/lanes/. A Jira title is a
    fact and passes the guard; any other quoted sentence is cut out and the file published with the cut reported; a file
    that carries a credential is refused, the published copy left as it was. Only a credential exits non-zero: one row's
    words never fail the pass."""
    s = site()
    src = os.path.join(s.get("reports") or os.path.join(s.get("projects", ""), "reports"), "lanes")
    _, published = roots()
    dst = os.path.join(published, "lanes")
    names = sorted(f for f in os.listdir(src) if LANE_PAGE.match(f)) if os.path.isdir(src) else []
    facts = lane_titles(src, names)
    label = lane_label_of()
    done, refused, cut = [], [], []
    for f in names:
        text = with_labels(redact(open(os.path.join(src, f), encoding="utf-8").read()), f, label)
        flags = guard_flags(text, f, facts)
        if any(why != QUOTED for _, why, _ in flags):
            refused.append({"file": f, "flags": [f"{n}: {why}: {line}" for n, why, line in flags[:5]]}); continue
        if flags:
            text, k = cut_quotes(text, f, facts)
            cut.append({"file": f, "cut": k, "rows": [f"{n}: {line}" for n, _, line in flags[:5]]})
        os.makedirs(dst, exist_ok=True)
        tmp = os.path.join(dst, f + ".tmp"); open(tmp, "w", encoding="utf-8").write(text); os.replace(tmp, os.path.join(dst, f))
        done.append(f)
    versions = publish_versions(s, dst, label)
    if done:
        tmp = os.path.join(dst, "README.md.tmp"); open(tmp, "w", encoding="utf-8").write(LANES_README)
        os.replace(tmp, os.path.join(dst, "README.md"))
    synced = None
    if a.sync:
        synced = sync_lanes(dst)
    if a.json:
        print(json.dumps({"destination": dst, "published": done, "versions": versions, "refused": refused, "cut": cut,
                          "synced": synced}, ensure_ascii=False))
    else:
        print(f"published lanes/ ({', '.join(done) or 'nothing'}) → {dst}")
        print(f"versions: {versions}")
        for c in cut:
            print(f"published {c['file']} with {c['cut']} quotation(s) left out:\n  " + "\n  ".join(c["rows"]))
        for r in refused:
            print(f"refused {r['file']}:\n  " + "\n  ".join(r["flags"]))
        if synced is not None:
            print(f"remote: {synced}")
    if refused:
        sys.exit(EX_USAGE)


VERSIONS_FILE = re.compile(r"^versions-\d{4}-\d{2}-\d{2}\.json$")


def publish_versions(s, dst, label=None):
    """The newest `<runtime>/runner/versions-<date>.json` (written by `ela changes`) → <published>/lanes/, the one dated copy
    kept, so a host with no desk — Helm Akamai — reads the QA lanes the desk recorded from QA's mails (the QA host
    refuses the tvutest account since 2026-11-04; release SKILL.md, two hosts). Through `redact`; a file the guard flags
    for a credential is not published. → a one-line outcome, never an exit: the lane pages are the publication."""
    runner = os.path.join(s.get("runtime") or "", "runner")
    names = sorted(f for f in os.listdir(runner) if VERSIONS_FILE.match(f)) if os.path.isdir(runner) else []
    if not names:
        return "not published: no versions-<date>.json under <runtime>/runner"
    name = names[-1]
    text = with_labels(redact(open(os.path.join(runner, name), encoding="utf-8").read()), name, label)
    if any(why != QUOTED for _, why, _ in guard_flags(text, name)):
        return f"not published: {name} carries what the guard refuses"
    try:
        json.loads(text)
    except ValueError:
        return f"not published: {name} is not JSON after redaction"
    os.makedirs(dst, exist_ok=True)
    tmp = os.path.join(dst, name + ".tmp"); open(tmp, "w", encoding="utf-8").write(text); os.replace(tmp, os.path.join(dst, name))
    for old in os.listdir(dst):
        if VERSIONS_FILE.match(old) and old != name:
            os.remove(os.path.join(dst, old))
    return f"published {name}"


def sync_lanes(dst):
    """rsync <published>/lanes/ to `published_remote`/lanes/; → a one-line outcome, never an exit."""
    return sync_dir(dst, "lanes")


def sync_dir(src, rel, target=None):
    """rsync one generated directory of <published> (`src`, already redacted and guarded where it was written) to
    `published_remote`/<rel>/, its stale files removed there; nothing else of the remote tree is touched. `target`: the
    remote root instead of site.json's (tests). → a one-line outcome, never an exit."""
    import subprocess
    target = target or site().get("published_remote")
    if not target:
        return "not synced: site.json has no published_remote"
    argv = ["rsync", "-az", "--delete", "--exclude", ".git", src.rstrip("/") + "/", target.rstrip("/") + f"/{rel}/"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"not synced: {str(e)[:160]}"
    return f"synced {rel}/ to <published_remote>" if r.returncode == 0 else f"not synced: rsync {r.returncode}: {(r.stderr or '').strip()[-160:]}"


def write_published_manifest(records, published):
    """<published>/MANIFEST.md — what this directory holds, generated from elak's manifest so the remote can tell what it has."""
    src = os.path.join(records, "map", "published-machines.md")
    rows = [ln for ln in open(src, encoding="utf-8") if ln.startswith("| `")]
    rows = [r for r in rows if len(r.strip().strip("|").split("|")) >= 5]
    today = datetime.date.today().isoformat()
    text = ["# What this directory is", "",
            "The colleague tier of ela's knowledge: everything a colleague may be shown, generated from ela's private knowledge "
            "base (elak) with the same paths and names. Helm, ela in Slack and mediahub-bot read it. Nothing in it is edited by "
            "hand; a change is made in elak and published again (`ela publish all`).", "",
            f"Generated {today}. Rows: source in elak · published path here · published on · source's `verified:` then · reader.", "",
            "| source | published file | generated | source verified at publication | read by |", "|---|---|---|---|---|"] + [r.rstrip("\n") for r in rows]
    open(os.path.join(published, "MANIFEST.md"), "w", encoding="utf-8").write("\n".join(text) + "\n")
    write_release_files(published)


# ── the team's versioned release (elak decisions/2026-11-25-published-knowledge-is-a-versioned-release.md) ──

RELEASE_SCOPE = ("knowledge/platform", "knowledge/products", "map")
RELEASE_SHA = re.compile(r"^elak: ([0-9a-f]{7,40})$", re.M)
RELEASE_README = """# MediaHub knowledge — the team's release

Facts about MediaHub and the platform it runs on, as ela reads them first-hand: the code, Jira, the services' own
records. Each commit here is one release, built from one commit of ela's private knowledge base (`elak:` in the
commit message) and made on the product owner's signal.

| path | holds |
|---|---|
| `knowledge/products/` | MediaHub itself: services, the release map's reading, Jira conventions, architecture |
| `knowledge/platform/` | what MediaHub runs on: unified resources, media, gateway, observability, LinuxR |
| `map/` | generated facts: services → owners → repos, release components, API projects, dependencies |

Every document carries `verified:` (when it was last checked against its source) and `source:` (where to check it).
A document is facts and knowledge only: no one's decisions, plans or opinions, and no one's quoted words; a source
is a ticket, a thread, a commit or a file. Addresses are replaced by placeholders.

Nothing here is edited by hand. A correction goes to the product owner, or to ela in Slack; it is made at the source
and arrives in the next release. Paths are stable: Helm and mediahub-bot read them.
"""


def write_release_files(published):
    """README.md and .gitignore at the root of <published>: the colleague's first page, and the scope git sees. Generated
    here because nothing under <published> is written by hand (the location guard blocks it)."""
    ignore = ["# generated by ela publish: only the release scope is versioned; the rest is the colleague tier, rsynced",
              "/*", "!/README.md", "!/.gitignore", "!/map/", "!/knowledge/", "/knowledge/*"] + \
             [f"!/{p}/" for p in RELEASE_SCOPE if p.startswith("knowledge/")] + ["*.tmp", ".*.tmp"]
    for name, body in (("README.md", RELEASE_README), (".gitignore", "\n".join(ignore) + "\n")):
        tmp = os.path.join(published, name + ".tmp")
        open(tmp, "w", encoding="utf-8").write(body); os.replace(tmp, os.path.join(published, name))


def owner_first_name(records):
    """The owner's first name, from elak's git identity: read on the machine, never written in a tracked file."""
    import subprocess
    r = subprocess.run(["git", "-C", records, "config", "user.name"], capture_output=True, text=True)
    return (r.stdout.split() or [""])[0]


OWNER_SOURCE = re.compile(r"(?i)\b(?:product\s+|mediahub\s+)?owner'{0,2}s\s+(?:own\s+)?(?:word|ruling|reading|instruction|opinion|view|plan)\b")
ATTRIBUTED_QUOTE = re.compile(r"[\"“][^\"”\n]{12,}[\"”]\s*\((?:[A-Z][a-z]+)[ ,]")


def release_flags(text, name, first):
    """The release guard's lines for one file → [(line, why, text)]: the content guard's rules (`guard_flags`, Jira
    titles in json passing as facts), plus the owner's word or name cited and a quotation attributed to a person."""
    out = [f for f in guard_flags(text, name)
           if not (name.endswith(".yaml") and f[1] == QUOTED)]   # a yaml file's quotes are syntax: a label, a title
    # a quotation attributed to a person, in prose, is caught by ATTRIBUTED_QUOTE below
    by_name = re.compile(rf"\b{re.escape(first)}\b") if first else None
    for n, line in enumerate(text.splitlines(), 1):
        for rx, why in ((OWNER_SOURCE, "the owner's word as a source"), (by_name, "the owner by name"),
                        (ATTRIBUTED_QUOTE, "a quotation attributed to a person")):
            if rx and rx.search(line):
                out.append((n, why, line.strip()[:100]))
    return out


def release_files(published):
    """Every file in the release scope, relative to <published>, temporaries left out."""
    out = []
    for top in RELEASE_SCOPE:
        for d, _, files in os.walk(os.path.join(published, top)):
            out += [os.path.relpath(os.path.join(d, f), published) for f in files if not f.endswith(".tmp")]
    return sorted(out)


def run_check(records, published):
    first = owner_first_name(records)
    flags = []
    for rel in release_files(published):
        try:
            text = open(os.path.join(published, rel), encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        flags += [(rel, n, why, line) for n, why, line in release_flags(text, rel, first)]
    return flags


def cmd_check(a):
    records, published = roots()
    flags = run_check(records, published)
    if a.json:
        print(json.dumps([{"file": f, "line": n, "why": w, "text": t} for f, n, w, t in flags], ensure_ascii=False))
    else:
        for f, n, w, t in flags:
            print(f"{f}:{n}: {w}: {t}")
        print(f"{len(flags)} line(s) refused" if flags else f"release guard: clean ({len(release_files(published))} files)")
    sys.exit(1 if flags else 0)


def last_release(published):
    """The elak commit the last release recorded, or None (no repository, no commit yet)."""
    import subprocess
    r = subprocess.run(["git", "-C", published, "log", "-1", "--format=%B"], capture_output=True, text=True)
    m = RELEASE_SHA.search(r.stdout) if r.returncode == 0 else None
    return m.group(1) if m else None


def cmd_release(a):
    """Due · what would change · the guard. A release is due when elak changed in a source of the release scope since
    the recorded commit; files the runner writes are outside the scope and never make one due."""
    import subprocess
    records, published = roots()
    if not os.path.isdir(os.path.join(published, ".git")):
        print(f"{published} is not a git repository: `git init` there first", file=sys.stderr); sys.exit(EX_USAGE)
    write_release_files(published)
    head = git(records, "rev-parse", "HEAD").decode().strip()
    last = last_release(published)
    if last:
        changed = git(records, "diff", "--name-only", last, "HEAD", "--", *RELEASE_SCOPE).decode().split()
    else:
        changed = None
    st = subprocess.run(["git", "-C", published, "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True).stdout.splitlines()
    flags = run_check(records, published)
    due = last is None or bool(changed)
    report = {"elak_head": head[:12], "last_release": last, "due": due, "elak_changed": changed,
              "would_commit": len(st), "refused": len(flags)}
    if a.json and not a.apply:
        print(json.dumps(report)); return
    print(f"elak HEAD {head[:12]} · last release {last[:12] if last else 'none'} · "
          + ("due" if due else "not due") + (f" ({len(changed)} source file(s) changed)" if changed else ""))
    print(f"  {len(st)} path(s) would be committed in <published>; release guard: "
          + (f"{len(flags)} line(s) refused — `ela publish check`" if flags else "clean"))
    if not a.apply:
        print("dry run — `ela publish release --apply` commits, on the owner's signal; nothing is pushed"); return
    if flags:
        print("refused: the release guard flags lines; fix them in elak and publish again", file=sys.stderr); sys.exit(1)
    if not st:
        print("nothing to commit"); return
    subprocess.run(["git", "-C", published, "add", "-A"], check=True)
    msg = f"release: knowledge and map from elak {head[:12]}\n\nelak: {head}\n"
    r = subprocess.run(["git", "-C", published, "commit", "-q", "-m", msg], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"commit failed: {(r.stderr or r.stdout).strip()[-300:]}", file=sys.stderr); sys.exit(EX_WRITE)
    print(f"committed the release in <published> (elak {head[:12]}); not pushed")


def cmd_all(a):
    records, published = roots()
    require_committed(records, [f"map/{f}" for f in map_files(os.path.join(records, "map"))] + ["knowledge/people/people.yaml",
                      "knowledge/people/responsibilities.yaml"] + [f"knowledge/{rel}" for rel, _ in doc_rows(records)]
                      + ([PINS_REL] if os.path.isfile(os.path.join(records, PINS_REL)) else []))   # all or nothing
    cmd_map(argparse.Namespace(json=False)); cmd_catalogue(argparse.Namespace(json=False)); cmd_roster(argparse.Namespace(json=False))
    cmd_pins(argparse.Namespace(json=False))
    today = datetime.date.today().isoformat()
    for rel, reader in doc_rows(records):            # every document already published stays published
        r = publish_doc(records, published, rel, reader, today)
        print(f"published {r['rel']}\n  source verified {r['verified']} · published {r['published']}")
    write_published_manifest(records, published)
    stale = os.path.join(published, "helm")           # the per-reader directory, until 2026-09-03
    if os.path.isdir(stale):
        if holds_published(stale, published_paths(records, published)):
            print("kept helm/: the manifest records a published file under it — publish it elsewhere first")
        else:
            import shutil; shutil.rmtree(stale); print("removed the old per-reader directory helm/")
    print(f"MANIFEST.md written → {os.path.join(published, 'MANIFEST.md')}")
    print("remote copy: `ela publish sync` (dry run) then `--apply` — the remote reads this directory and nothing else carries it")


def cmd_sync(a):
    """Carry <published> to Helm Akamai, named by site.json `published_remote` (`user@host:/path`, never a tracked
    file) with rsync — dry run unless --apply. Publication is the only exit from elak (principle P2), so publication
    owns the remote copy: a deploy of Helm cannot carry a directory outside its repository, and the published tree
    changes when something is published, not when Helm deploys."""
    import subprocess
    records, published = roots()
    target = site().get("published_remote")
    if not target:
        print("site.json has no `published_remote` (user@host:/path) — nothing to sync to", file=sys.stderr); sys.exit(2)
    argv = ["rsync", "-az", "--delete", "--exclude", ".git"] + ([] if a.apply else ["-n", "-v"]) + [published.rstrip("/") + "/", target.rstrip("/") + "/"]
    shown = " ".join(argv).replace(target, "<published_remote>")
    print(("syncing: " if a.apply else "DRY RUN — ") + shown)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    out = (r.stdout or "").strip().splitlines()
    if r.returncode != 0:
        print(f"rsync failed ({r.returncode}): {(r.stderr or '').strip()[-300:]}", file=sys.stderr); sys.exit(5)
    if not a.apply:
        files = [l for l in out if l and not l.startswith(("sending", "sent", "total", "./"))]
        print(f"  {len(files)} path(s) would change" + (": " + ", ".join(files[:12]) + (" …" if len(files) > 12 else "") if files else ""))
        print("pass --apply to sync")
    else:
        print(f"  synced to <published_remote>")


def cmd_list(a):
    """Every manifest row, and whether the published copy still matches its source — by content for the
    map files and the written documents (after redaction), by modification time for the rendered
    catalogue and roster, which are generated and so never equal their source."""
    records, published = roots()
    drifted = 0
    for cells in manifest_rows(records):
        src_rel, dest_rel = cells[0], cells[1].replace("<published>/", "")
        drift = ""
        if src_rel == "map/":
            src_dir, dst_dir = os.path.join(source_root(records), "map"), os.path.join(published, "map")
            changed = [f for f in map_files(src_dir)
                       if not os.path.isfile(os.path.join(dst_dir, f))
                       or redact(open(os.path.join(src_dir, f), encoding="utf-8").read()) != open(os.path.join(dst_dir, f), encoding="utf-8").read()]
            if changed:
                drift = f"  ← differs: {', '.join(changed)}: republish"
        elif DOC_ROW.match(src_rel) or src_rel == PINS_REL:
            src, dst = os.path.join(source_root(records), src_rel), os.path.join(published, dest_rel)
            try:
                if not os.path.isfile(dst) or redact(open(src, encoding="utf-8").read()) != open(dst, encoding="utf-8").read():
                    drift = "  ← the published file differs from the elak source: republish"
            except OSError:
                drift = "  ← source or destination missing"
        else:
            srcs = [os.path.join(records, src_rel.split(" ")[0])]
            if os.path.isdir(srcs[0]):
                srcs = [os.path.join(srcs[0], f) for f in os.listdir(srcs[0])]
            dest = os.path.join(published, dest_rel.split(" ")[0])
            dests = [os.path.join(dest, f) for f in os.listdir(dest)] if os.path.isdir(dest) else [dest]
            try:
                newest_src = max(os.path.getmtime(x) for x in srcs)
                oldest_dst = min(os.path.getmtime(x) for x in dests)
                if newest_src > oldest_dst:
                    drift = "  ← source changed after publication: republish"
            except (OSError, ValueError):
                drift = "  ← source or destination missing"
        drifted += bool(drift)
        print(f"{cells[0]:<24} → {cells[1]:<70} published {cells[2]}  (source verified {cells[3]}){drift}")
    if drifted:
        sys.exit(1)


def cmd_mirror(a):
    """<published> → `published_mirror` now; --dry-run lists what would change. Exit 5 when the mirror was refused or failed."""
    s = site()
    _, published = roots()
    ok, line = M.mirror(published, os.environ.get("ELA_PUBLISH_MIRROR", s.get("published_mirror")), s.get("vault"), dry_run=a.dry_run)
    print(line)
    if not ok:
        sys.exit(EX_WRITE)


WRITES_PUBLISHED = ("catalogue", "map", "roster", "doc", "pins", "all", "lanes")   # and `release --apply`


def main():
    ap = argparse.ArgumentParser(description="Publish elak sources into the published directory.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("catalogue"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("map"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("roster"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("doc", help="publish one written document from elak's knowledge tree")
    p.add_argument("rel", help="path relative to <elak>/knowledge/, e.g. products/mediahub/team/layer-classification.md")
    p.add_argument("--reader", default=DOC_READER, help="who reads it, for the manifest row")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("pins"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("all"); p.add_argument("--json", action="store_true")
    sub.add_parser("list")
    p = sub.add_parser("lanes", help="the lanes page and the test and dev lists → <published>/lanes/, for Helm")
    p.add_argument("--sync", action="store_true", help="then carry lanes/ alone to published_remote")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("check", help="the release guard over the versioned part of <published> (exit 1 when it refuses a line)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("release", help="the team's versioned release: due, what it commits, the guard — dry run unless --apply")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("sync", help="rsync <published> to site.json `published_remote` — dry run unless --apply")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("mirror", help="<published> → site.json `published_mirror`, the read-only Obsidian vault")
    p.add_argument("--dry-run", action="store_true")
    for name, sp in sub.choices.items():
        if name in ("catalogue", "map", "roster", "doc", "pins", "all", "list"):
            sp.add_argument("--dirty", action="store_true", help="read elak's working tree instead of its last commit")
    a = ap.parse_args()
    DIRTY["on"] = bool(getattr(a, "dirty", False))
    # an unattended session (ELA_NO_APPLY=1) reads and dry-runs only; the owner's word applies a write
    if os.environ.get("ELA_NO_APPLY") and getattr(a, "apply", False):
        print("refused: --apply inside an unattended session (ELA_NO_APPLY)", file=sys.stderr); sys.exit(2)
    run = {"catalogue": cmd_catalogue, "map": cmd_map, "roster": cmd_roster, "doc": cmd_doc, "pins": cmd_pins, "all": cmd_all,
           "list": cmd_list, "sync": cmd_sync, "lanes": cmd_lanes, "check": cmd_check, "release": cmd_release,
           "mirror": cmd_mirror}[a.cmd]
    if a.cmd not in WRITES_PUBLISHED and not (a.cmd == "release" and a.apply):
        run(a); return
    try:
        run(a)
    except SystemExit as e:                  # a refusal before writing leaves <published> as it was, so no mirror;
        if e.code in (None, 0) or (a.cmd == "lanes" and e.code == EX_USAGE):   # lanes exits 2 with its other pages written
            M.after_publish(site())
        raise
    M.after_publish(site())


if __name__ == "__main__":
    main()
