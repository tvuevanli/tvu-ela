#!/usr/bin/env python3
"""Publish — render an elak source into the published directory machines read, and record the row in elak's manifest.

  all [--json]              everything below, then <published>/MANIFEST.md (what this directory holds, from where, when)
  catalogue [--json]        <records>/map/services.yaml → <published>/knowledge/products/mediahub/services.md
  map [--json]              <records>/map/*.yaml + README.md → <published>/map/ (machine-readable, copied as they are)
  list                      what the manifest says has been published, and whether the source moved since

The published directory is a subset of elak's own tree — the same paths, elak's names, no per-reader
directories. Readers (Helm's context packs, the remote ela) point at these paths.

A publication is written, not exported (elak publish/README.md): the document opens by saying what it is,
carries every limit the source states where the reader sees it, and names its source and dates. Nothing
under <published> is edited by hand; a change is made in elak and published again. Stdlib only.
Roots come from site.json: `records` (elak) and `published`. Exit codes: 0 ok · 2 usage · 5 write failed.
"""
import argparse, datetime, json, os, re, sys

EX_USAGE, EX_WRITE = 2, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        print("no ~/.claude/ela/site.json — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)


def roots():
    s = site()
    rec, pub = s.get("records"), s.get("published")
    if not rec or not pub:
        print("site.json needs `records` (elak) and `published` (the generated directory) — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)
    if s.get("site") == "remote":
        print("this is a remote site: publications are generated at the office and carried by the deploy", file=sys.stderr); sys.exit(EX_USAGE)
    return rec, pub


# ── services.yaml, the subset of YAML it uses ─────────────────────────────────

def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        inner = v[1:-1]
        return inner.replace("''", "'") if v[0] == "'" else inner.replace('\\"', '"')
    return v


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
        "who owns it, the GM services it registers (Evan's `mds-` slug, the name GM registers, GM's service id, the J2N "
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
            "The manifest row is in elak `publish/published.md`.", ""]
    return "\n".join(x for x in out if x is not None)


# ── the manifest row ──────────────────────────────────────────────────────────

def update_manifest(records, source_rel, dest_rel, today, verified, reader):
    path = os.path.join(records, "publish", "published.md")
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


def cmd_catalogue(a):
    records, published = roots()
    src = os.path.join(records, "map", "services.yaml")
    header, images = read_services(src)
    if not images:
        print(f"{src}: no images parsed", file=sys.stderr); sys.exit(EX_USAGE)
    today = datetime.date.today().isoformat()
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
        "**No rank is recorded here** — no title, no seniority, no reporting line. MediaHub responsibility is "
        "de-facto and TVU has no matching titles, so a level would be invented rather than read "
        "(decision `2026-09-04-people-carry-responsibilities-not-rank`). Where an area has a de-facto lead, it "
        "appears as **ask first** on that area, which is per person-and-area and is not comparable across areas.", "",
        "**Rule.** A person not listed here is unknown: look them up first-hand and add them to the source; never compose an "
        "address from a name (decision `2026-09-03-people-identified-by-the-roster-never-guessed`).", "",
    ]
    if header.get("note"):
        out += [f"Note: {header['note']}", ""]
    for area in areas:
        out += [f"## {area}", ""]
        for p in [x for x in core if x["area"] == area]:
            first = next((r for r in p["responsibilities"] if r.get("first_contact") is True), None)
            out.append(f"**{p['name']}** — {(first or p['responsibilities'][0])['what'].split(' — ')[0].split('. ')[0]}")
            for r in p["responsibilities"]:
                mark = " (ask first about this area)" if r.get("first_contact") is True else ""
                out.append(f"- {r['scope']}/{r['area']}{mark}: {r['what']}")
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


def cmd_roster(a):
    import shutil
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "team"))
    import team  # noqa: E402 — the roster reader, same plugin
    records, published = roots()
    src_rel = "knowledge/people/ (people.yaml, responsibilities.yaml)"
    src = os.path.join(records, "knowledge", "people")
    header, people = team.read_roster(records)
    if not people:
        print(f"{src}: no people parsed", file=sys.stderr); sys.exit(EX_USAGE)
    today = datetime.date.today().isoformat()
    dest_dir = os.path.join(published, "knowledge", "people")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        for f in ("people.yaml", "responsibilities.yaml"):
            shutil.copyfile(os.path.join(src, f), os.path.join(dest_dir, f))
        tmp = os.path.join(dest_dir, "roster.md.tmp")
        open(tmp, "w", encoding="utf-8").write(render_team_map(header, people, today))
        os.replace(tmp, os.path.join(dest_dir, "roster.md"))
        for stale in (os.path.join(dest_dir, "team-map.md"),                                  # Helm's filename, until 2026-09-03
                      os.path.join(published, "knowledge", "products", "mediahub", "team")):   # the old roster location, until 2026-09-04
            if os.path.isdir(stale):
                shutil.rmtree(stale)
            elif os.path.exists(stale):
                os.remove(stale)
    except OSError as e:
        print(f"cannot write {dest_dir}: {e}", file=sys.stderr); sys.exit(EX_WRITE)
    mpath, row = update_manifest(records, src_rel, "knowledge/people/ (people.yaml, responsibilities.yaml, roster.md)", today,
                                 header.get("verified", "?"), "Helm `known_emails()` (published-only file, no Helm copy to shadow); `ela who` on the remote site")
    if a.json:
        print(json.dumps({"source": src, "destination": dest_dir, "people": len(people), "verified": header.get("verified"), "published": today, "manifest": mpath}, ensure_ascii=False)); return
    print(f"published knowledge/people/ (people.yaml, responsibilities.yaml, roster.md)\n  {len(people)} people · source verified {header.get('verified')} · published {today}\n  manifest row → {mpath}\n  {row}")


def cmd_map(a):
    """The machine-readable map, copied as it is: services · absent · release · apis and the README."""
    import shutil
    records, published = roots()
    src_dir, dst_dir = os.path.join(records, "map"), os.path.join(published, "map")
    os.makedirs(dst_dir, exist_ok=True)
    names = sorted(f for f in os.listdir(src_dir) if f.endswith(".yaml") or f == "README.md")
    for f in names:
        shutil.copyfile(os.path.join(src_dir, f), os.path.join(dst_dir, f))
    today = datetime.date.today().isoformat()
    ver = next((l.split(":", 1)[1].strip().strip("'") for l in open(os.path.join(src_dir, "services.yaml")) if l.startswith("verified:")), "?")
    update_manifest(records, "map/", "map/", today, ver, "the remote ela (`records`/`map` roots) and Helm's pipeline drift check")
    if a.json:
        print(json.dumps({"files": names, "destination": dst_dir, "published": today})); return
    print(f"published map/ ({', '.join(names)}) → {dst_dir}")


def write_published_manifest(records, published):
    """<published>/MANIFEST.md — what this directory holds, generated from elak's manifest so the remote can tell what it has."""
    src = os.path.join(records, "publish", "published.md")
    rows = [ln for ln in open(src, encoding="utf-8") if ln.startswith("| `")]
    rows = [r for r in rows if len(r.strip().strip("|").split("|")) >= 5]
    today = datetime.date.today().isoformat()
    text = ["# What this directory is", "",
            "A generated subset of elak, Evan's knowledge base — the same paths and names as elak's own tree, published for machines to read: "
            "Helm's knowledge root and the remote ela point here. Nothing in it is edited by hand; a change is made in elak and published again "
            "(`ela publish all`). The remote receives it by rsync with Helm's deploy.", "",
            f"Generated {today}. Rows: source in elak · published path here · published on · source's `verified:` then · reader.", "",
            "| source | published file | generated | source verified at publication | read by |", "|---|---|---|---|---|"] + [r.rstrip("\n") for r in rows]
    open(os.path.join(published, "MANIFEST.md"), "w", encoding="utf-8").write("\n".join(text) + "\n")


def cmd_all(a):
    records, published = roots()
    cmd_map(argparse.Namespace(json=False)); cmd_catalogue(argparse.Namespace(json=False)); cmd_roster(argparse.Namespace(json=False))
    write_published_manifest(records, published)
    stale = os.path.join(published, "helm")
    if os.path.isdir(stale):
        import shutil; shutil.rmtree(stale); print("removed the old per-reader directory helm/")
    print(f"MANIFEST.md written → {os.path.join(published, 'MANIFEST.md')}")


def cmd_list(a):
    records, published = roots()
    path = os.path.join(records, "publish", "published.md")
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("| `"):
            cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
            if len(cells) < 5:          # the "First content" table has three cells; only manifest rows are listed
                continue
            src = os.path.join(records, cells[0]); now = ""
            if os.path.isdir(src):                       # a directory source (map/) carries its date on services.yaml
                src = os.path.join(src, "services.yaml")
            try:
                now = next((l.split(":", 1)[1].strip().strip("'") for l in open(src) if l.startswith("verified:")), "")
            except OSError:
                now = "(source missing)"
            drift = "" if now == cells[3] else f"  ← source now verified {now}: republish"
            print(f"{cells[0]:<24} → {cells[1]:<70} published {cells[2]}  (source verified {cells[3]}){drift}")


def main():
    ap = argparse.ArgumentParser(description="Publish elak sources into the published directory.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("catalogue"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("map"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("roster"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("all"); p.add_argument("--json", action="store_true")
    sub.add_parser("list")
    a = ap.parse_args()
    {"catalogue": cmd_catalogue, "map": cmd_map, "roster": cmd_roster, "all": cmd_all, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
