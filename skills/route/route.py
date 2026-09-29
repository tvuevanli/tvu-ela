#!/usr/bin/env python3
"""route — the facts a routing verdict needs, gathered deterministically. The verdict stays in the skill.

L1 capability, stdlib only. Read-only: the ticket through the jira capability (a subprocess), the rest from
`<published>` (site.json `published`): the signal-word tables of
`knowledge/products/mediahub/team/layer-classification.md`, `map/services.yaml`, and the roster under
`knowledge/people/`. Nothing here names a person or a layer of its own; every name in the output was read.

  route.py facts <KEY|url> [--json]   ticket · [Layer] token · ids · signal words and layer hits · services named
                                      in the text with their owners · who to ask first per candidate layer · gaps

Exit codes: 0 ok (gaps are reported, not fatal) · 2 usage · 3 ticket not found · 5 remote error (Jira unreadable).
"""
import argparse, json, os, re, subprocess, sys

EX_USAGE, EX_NOTFOUND, EX_REMOTE = 2, 3, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)
LAYERS_REL = os.path.join("knowledge", "products", "mediahub", "team", "layer-classification.md")
SERVICES_REL = os.path.join("map", "services.yaml")
PEOPLE_DIR_REL = os.path.join("knowledge", "people")

for cap in ("jira", "map", "team"):
    sys.path.insert(0, os.path.join(SKILLS, cap))
import jira as jr   # noqa: E402 — body_text and the layer vocabulary; the read itself is a subprocess
import map as mp    # noqa: E402 — the services.yaml reader
import team as tm   # noqa: E402 — the roster reader

IDS = {   # regexes only: a shape, never a lookup
    "graph": re.compile(r"(?<![0-9A-Za-z])[0-9A-HJKMNP-TV-Z]{26}(?![0-9A-Za-z])"),
    "process": re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{32}(?![0-9A-Za-z])"),
    "object": re.compile(r"(?<!\d)\d{19}(?!\d)"),
}
TOKEN = re.compile(r"\[(" + "|".join(re.escape(t[1:-1]) for t in jr.LAYER_TOKENS) + r")\]", re.I)
WORD_HEADS = ("signal", "word", "keyword", "term", "symptom")
LAYER_HEADS = ("layer",)


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        print("no ~/.claude/ela/site.json — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)


def env_file(a, s):
    return a.env_file or s.get("env") or os.path.expanduser("~/.claude/ela/.env")


# ── the ticket ───────────────────────────────────────────────────────────────

def read_ticket(key, env):
    """jira.py read --json as a subprocess → (issue, None) or (None, (exit code, reason))."""
    argv = [sys.executable, os.path.join(SKILLS, "jira", "jira.py"), "--env-file", env, "read", key, "--json"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return None, (EX_REMOTE, "jira read timed out")
    if r.returncode != 0:
        why = (r.stderr.strip().splitlines() or ["jira read failed"])[-1][:300]
        return None, (EX_NOTFOUND if "HTTP 404" in r.stderr else EX_REMOTE, why)
    try:
        return json.loads(r.stdout), None
    except ValueError:
        return None, (EX_REMOTE, "jira read returned no JSON")


def ticket_facts(issue):
    f = issue.get("fields") or {}
    name = lambda o, k="displayName": (o or {}).get(k) or ""
    parent = f.get("parent") or {}
    t = {"key": issue.get("key"), "url": issue.get("url"), "summary": f.get("summary") or "",
         "type": name(f.get("issuetype"), "name"), "status": name(f.get("status"), "name"),
         "assignee": name(f.get("assignee")), "labels": f.get("labels") or [],
         "parent": ({"key": parent.get("key"), "summary": (parent.get("fields") or {}).get("summary", "")}
                    if parent else None)}
    parts = [t["summary"], jr.body_text(f.get("description"))]
    parts += [jr.body_text(c.get("body")) for c in issue.get("comments") or []]
    return t, "\n".join(p for p in parts if p)


def find_ids(text):
    out = {}
    for kind, rx in IDS.items():
        seen = []
        for m in rx.findall(text):
            v = m.lower() if kind == "process" else m
            if kind == "graph" and not (re.search(r"\d", v) and re.search(r"[A-Z]", v)):
                continue            # 26 capitals or 26 digits is a word or a number, not a ULID
            if v not in seen:
                seen.append(v)
        out[kind] = seen
    return out


def occurs(word, text_lower):
    """Word-bounded for ASCII words, substring for anything else (CJK has no word boundary)."""
    w = word.lower()
    if re.fullmatch(r"[\x00-\x7f]+", w):
        return re.search(r"(?<![a-z0-9_])" + re.escape(w) + r"(?![a-z0-9_])", text_lower) is not None
    return w in text_lower


# ── published sources ────────────────────────────────────────────────────────

def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _clean(cell):
    return re.sub(r"[`*]", "", cell).strip()     # `_` stays: process_type-style names are signal words too


def _tables(lines):
    """Every markdown table → (heading above it, header cells lowercased, body rows as cell lists)."""
    out, heading, i = [], "", 0
    while i < len(lines):
        ln = lines[i]
        if re.match(r"#{1,3}\s", ln):
            heading = _clean(ln.lstrip("#"))
        elif ln.lstrip().startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", lines[i + 1]):
            head, body = [_clean(c).lower() for c in _cells(ln)], []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                body.append(_cells(lines[i])); i += 1
            out.append((heading, head, body))
            continue
        i += 1
    return out


def layer_vocabulary(tables):
    """The file's own `| layer | token |` table → [(layer name, token)]."""
    for _, head, body in tables:
        li = next((j for j, h in enumerate(head) if h == "layer"), None)
        ti = next((j for j, h in enumerate(head) if h == "token"), None)
        if li is not None and ti is not None:
            return [(_clean(c[li]), _clean(c[ti])) for c in body if max(li, ti) < len(c) and _clean(c[li])]
    return []


def heading_layer(heading, vocab):
    """A heading → the vocabulary layer whose name or token it contains, else the heading verbatim."""
    h = heading.lower()
    for name, token in vocab:
        keys = [name, token, token.strip("[]")]
        if any(k and k.lower() in h for k in keys):
            return name
    return heading


def signal_table(text):
    """Every markdown table with a word column → [(word, layer)], and whether any table was found at all.

    The layer is the row's layer column when the table has one; otherwise the heading above the table,
    normalised to the file's own `| layer | token |` vocabulary. A cell may carry several words
    (`a`, `b` · a / b); each is one signal. A table without a word column is skipped, whatever it holds."""
    tables = _tables(text.splitlines())
    vocab = layer_vocabulary(tables)
    rows, found = [], False
    for heading, head, body in tables:
        wi = next((j for j, h in enumerate(head) if any(k in h for k in WORD_HEADS)), None)
        li = next((j for j, h in enumerate(head) if any(k in h for k in LAYER_HEADS) and j != wi), None)
        if wi is None:
            continue
        found = True
        fixed = None if li is not None else heading_layer(heading, vocab)
        for c in body:
            if wi >= len(c) or (li is not None and li >= len(c)):
                continue
            layer = fixed if li is None else _clean(c[li])
            if not layer:
                continue
            for w in re.split(r"\s*(?:,|，|、|·|/|;)\s*", _clean(c[wi])):
                w = w.strip().strip('"“”')
                if len(w) >= 2:
                    rows.append((w, layer))
    return rows, found


def service_hits(svc, text_lower):
    """Every image, slug, GM name or process type from services.yaml that occurs in the text, with its owners."""
    out = []
    for image, d in svc.items():
        names = {("image", image)}
        for kind, key in (("slug", "slugs"), ("gm_name", "gm_names"), ("process_type", "process_types")):
            names |= {(kind, n) for n in d.get(key) or [] if isinstance(n, str)}
        for row in d.get("services") or []:
            for kind in ("slug", "gm_name", "process_type"):
                if isinstance(row.get(kind), str):
                    names.add((kind, row[kind]))
        for kind, n in sorted(names):
            if len(n) >= 3 and occurs(n, text_lower):
                out.append({"name": n, "kind": kind, "image": image, "owners": d.get("owners") or []})
    return out


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def ask_first(layers, people):
    """Candidate layer → the roster's first contacts for the area(s) that carry that layer's name."""
    areas = {}
    for p in people:
        for r in p["responsibilities"]:
            e = areas.setdefault(r.get("area") or "", {"first": [], "what": set()})
            e["what"].add(_norm(r.get("what")))
            if r.get("first_contact") is True:
                e["first"].append({"name": p["name"], "email": p["email"], "slack": p.get("slack", "")})
    out, missing = {}, []
    for layer in layers:
        n = _norm(layer)
        hit = {a: e for a, e in areas.items() if a and (_norm(a) == n or n in _norm(a) or n in e["what"])}
        if not hit:
            missing.append(layer); continue
        out[layer] = [{"area": a, "ask_first": e["first"]} for a, e in sorted(hit.items())]
    return out, missing


# ── facts ────────────────────────────────────────────────────────────────────

def cmd_facts(a):
    s = site()
    gaps = []
    issue, err = read_ticket(a.key, env_file(a, s))
    if err:
        code, why = err
        out = {"ticket": {"key": a.key}, "layer_token": None, "ids": {}, "signals": [], "layer_hits": {},
               "services": [], "ask_first": {}, "gaps": [f"ticket unreadable: {why}"]}
        if a.json:
            print(json.dumps(out, ensure_ascii=False))
        else:
            print(f"{a.key}: ticket unreadable — {why}", file=sys.stderr)
        sys.exit(code)
    ticket, text = ticket_facts(issue)
    low = text.lower()
    m = TOKEN.search(ticket["summary"])
    layer_token = next((t for t in jr.LAYER_TOKENS if m and t.lower() == f"[{m.group(1).lower()}]"), None)

    pub = s.get("published")
    if not pub:
        gaps.append("site.json has no `published` root: signal words, services and roster unread")
    signals, hits, services, first = [], {}, [], {}
    if pub:
        path = os.path.join(pub, LAYERS_REL)
        if not os.path.isfile(path):
            gaps.append(f"missing <published>/{LAYERS_REL}")
        else:
            table, found = signal_table(mp.read(path))
            if not found:
                gaps.append(f"<published>/{LAYERS_REL}: no signal-word table found")
            for w, layer in table:
                if occurs(w, low) and {"word": w, "layer": layer} not in signals:
                    signals.append({"word": w, "layer": layer})
                    hits[layer] = hits.get(layer, 0) + 1
        path = os.path.join(pub, SERVICES_REL)
        if not os.path.isfile(path):
            gaps.append(f"missing <published>/{SERVICES_REL}")
        else:
            services = service_hits(mp.services(mp.read(path)), low)
        people_yaml = os.path.join(pub, tm.PEOPLE_REL)
        if not (os.path.isfile(people_yaml) and os.path.isfile(os.path.join(pub, tm.RESP_REL))):
            gaps.append(f"missing roster under <published>/{PEOPLE_DIR_REL} (people.yaml + responsibilities.yaml)")
        else:
            candidates = list(dict.fromkeys(([layer_token.strip("[]")] if layer_token else [])
                                            + sorted(hits, key=lambda k: -hits[k])))
            _, people = tm.read_roster(pub)
            first, unmatched = ask_first(candidates, people)
            gaps += [f"no roster area carries layer {l!r}" for l in unmatched]

    out = {"ticket": ticket, "layer_token": layer_token, "ids": find_ids(text), "signals": signals,
           "layer_hits": dict(sorted(hits.items(), key=lambda kv: -kv[1])), "services": services,
           "ask_first": first, "gaps": gaps}
    if a.json:
        print(json.dumps(out, ensure_ascii=False)); return
    t = ticket
    print(f"{t['key']}  {t['summary']}")
    print(f"  {t['type']} · {t['status']} · assignee {t['assignee'] or '—'}"
          + (f" · parent {t['parent']['key']}" if t["parent"] else "")
          + (f" · labels {', '.join(t['labels'])}" if t["labels"] else ""))
    print(f"  layer token  {layer_token or '—'}")
    for kind, vs in out["ids"].items():
        if vs:
            print(f"  {kind + ' ids':<12} {', '.join(vs)}")
    print(f"\n{'LAYER':<12} {'HITS':>4}  WORDS")
    for layer, n in out["layer_hits"].items():
        print(f"{layer:<12} {n:>4}  {', '.join(x['word'] for x in signals if x['layer'] == layer)}")
    if services:
        print(f"\n{'SERVICE NAME':<28} {'KIND':<13} {'IMAGE':<24} OWNERS")
        for x in services:
            print(f"{x['name']:<28} {x['kind']:<13} {x['image']:<24} {', '.join(x['owners']) or '?'}")
    if first:
        print(f"\n{'LAYER':<12} {'AREA':<20} ASK FIRST")
        for layer, rows in first.items():
            for r in rows:
                print(f"{layer:<12} {r['area']:<20} {', '.join(p['name'] for p in r['ask_first']) or '—'}")
    for g in gaps:
        print(f"gap: {g}")


def main():
    ap = argparse.ArgumentParser(description="The facts a routing verdict needs, read-only.")
    ap.add_argument("--env-file", help="credential file for the jira read (default: site.json `env`)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("facts", help="ticket, ids, signal words, services, who to ask first, gaps")
    p.add_argument("key", help="a ticket key or Jira URL"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"facts": cmd_facts}[a.cmd](a)


if __name__ == "__main__":
    main()
