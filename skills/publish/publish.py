#!/usr/bin/env python3
"""Publish — render an elak source into the published directory machines read, and record the row in elak's manifest.

  catalogue [--json]        <records>/map/services.yaml → <published>/helm/knowledge/mediahub/services/docker-service-map.md
                            and a manifest row in <records>/publish/helm-runtime.md
  list                      what the manifest says has been published, and whether the source moved since

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
            "The manifest row is in elak `publish/helm-runtime.md`.", ""]
    return "\n".join(x for x in out if x is not None)


# ── the manifest row ──────────────────────────────────────────────────────────

def update_manifest(records, source_rel, dest_rel, today, verified, reader):
    path = os.path.join(records, "publish", "helm-runtime.md")
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
    dest_rel = "helm/knowledge/mediahub/services/docker-service-map.md"
    dest = os.path.join(published, dest_rel)
    doc = render_catalogue(header, images, today)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"; open(tmp, "w", encoding="utf-8").write(doc); os.replace(tmp, dest)
    except OSError as e:
        print(f"cannot write {dest}: {e}", file=sys.stderr); sys.exit(EX_WRITE)
    mpath, row = update_manifest(records, "map/services.yaml", dest_rel, today, header.get("verified", "?"),
                                 "Helm context pack `service_catalog` / pipeline drift check (once Helm's knowledge root points at <published>)")
    n = sum(len(i["services"]) for i in images.values())
    if a.json:
        print(json.dumps({"source": src, "destination": dest, "images": len(images), "services": n, "verified": header.get("verified"), "published": today, "manifest": mpath}, ensure_ascii=False)); return
    print(f"published {dest_rel}\n  {len(images)} images · {n} services · source verified {header.get('verified')} · published {today}\n  manifest row → {mpath}\n  {row}")


def cmd_list(a):
    records, published = roots()
    path = os.path.join(records, "publish", "helm-runtime.md")
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("| `"):
            cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
            if len(cells) < 5:          # the "First content" table has three cells; only manifest rows are listed
                continue
            src = os.path.join(records, cells[0]); now = ""
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
    sub.add_parser("list")
    a = ap.parse_args()
    {"catalogue": cmd_catalogue, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
