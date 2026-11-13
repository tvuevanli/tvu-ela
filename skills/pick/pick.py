#!/usr/bin/env python3
"""pick — fields out of JSON, for a session that may not run an interpreter one-liner.

  ela <verb> --json | ela pick <path>… [options]      JSON on stdin
  ela pick <path>… --file F [options]                 a JSON file (or JSON lines: one list)

  no path          the shape of the document: each key, its type and size, a scalar's value, a list's item keys
  a path           dotted keys from the root: fields.assignee.displayName · a key with a dot: ["a.b"]
    [N] [-1]       one item of a list
    [A:B] [7:]     a run of items, each a row
    []             every item of a list, or every value of a dict, each a row
    **             every dict at any depth, each a row (find an object without knowing where it sits)
    @key           the key (or index) under which the row was found: lanes[].@key
  several paths    one line per row, the fields tab-separated; they share the first path's list, and a later
                   path that starts with a dot is read from the row: rows[].key .status .assignee.name
  --where K=V      keep the rows whose K is V; K!=V is not V; K~V contains V (case ignored); K is a path from
                   the row, `.` the row itself; the same K twice is either, different Ks are all; with no
                   [] in the path, the list the path names is filtered: --file actions.json --where n=3
  --count          the number of rows instead of the rows
  --shape          the shape of what the path names, instead of its value
  --max N          cut each field to N characters
  --json           the rows as JSON

A tab or a newline inside a field prints as a space. A dict or a list in a field prints as JSON, alone on
the line it is indented. Nothing is evaluated, nothing is written, and a file in the site directory or the
site's env file is refused. Exit 0 · 2 usage or not JSON · 3 the path names nothing or no row matches.
"""
import argparse, json, os, re, sys

EX_USAGE, EX_NOTFOUND = 2, 3
SITE_DIR = os.path.join("~", ".claude", "ela")


def site_paths():
    """(the site directory, the env file), both resolved; the env file may live outside the directory."""
    d = os.path.realpath(os.path.expanduser(SITE_DIR))
    env = os.environ.get("ELA_ENV_FILE") or ""
    try:
        with open(os.path.join(d, "site.json")) as fh:
            env = env or (json.load(fh).get("env") or "")
    except Exception:
        pass
    return d, os.path.realpath(os.path.expanduser(env or os.path.join(d, ".env")))


def refused(path):
    """Why this file is not read, or None. Resolved first, so a link or `..` into the site directory is refused too."""
    real = os.path.realpath(os.path.expanduser(path))
    d, env = site_paths()
    if real == env:
        return "the site's env file is not read"
    if real == d or real.startswith(d + os.sep):
        return "a file in the site directory is not read"
    return None


def die(msg, code=EX_USAGE):
    print(f"pick: {msg}", file=sys.stderr)
    sys.exit(code)


# ── paths ────────────────────────────────────────────────────────────────────────────────────────────────────
BRACKET = re.compile(r'\[(?:"((?:[^"\\]|\\.)*)"|(-?\d+)|(-?\d*):(-?\d*)|)\]')
ROWS = ("each", "slice", "deep")


def parse(expr):
    """A path as steps: ("key", k) · ("idx", n) · ("slice", a, b) · ("each",) · ("deep",) · ("keyname",)."""
    steps, i, n = [], 0, len(expr)
    while i < n:
        c = expr[i]
        if c == ".":
            i += 1
        elif c == "[":
            m = BRACKET.match(expr, i)
            if not m:
                die(f"cannot read {expr!r} at {expr[i:]!r}: [N], [A:B], [] or [\"key\"]")
            if m.group(1) is not None:
                steps.append(("key", re.sub(r"\\(.)", r"\1", m.group(1))))
            elif m.group(2) is not None:
                steps.append(("idx", int(m.group(2))))
            elif m.group(3) is not None:
                steps.append(("slice", int(m.group(3)) if m.group(3) else None, int(m.group(4)) if m.group(4) else None))
            else:
                steps.append(("each",))
            i = m.end()
        else:
            j = i
            while j < n and expr[j] not in ".[":
                j += 1
            word = expr[i:j]
            steps.append(("deep",) if word == "**" else ("each",) if word == "*" else ("keyname",) if word == "@key" else ("key", word))
            i = j
    return steps


def deep(value, key):
    if isinstance(value, dict):
        yield value, key
        for k, v in value.items():
            yield from deep(v, k)
    elif isinstance(value, list):
        for k, v in enumerate(value):
            yield from deep(v, k)


def step(nodes, s):
    """One step over (value, the key it was found under) nodes; a step that does not apply yields nothing."""
    out = []
    for v, k in nodes:
        if s[0] == "key":
            if isinstance(v, dict) and s[1] in v:
                out.append((v[s[1]], s[1]))
            elif isinstance(v, list) and re.fullmatch(r"-?\d+", s[1]) and -len(v) <= int(s[1]) < len(v):
                out.append((v[int(s[1])], int(s[1])))
        elif s[0] == "idx":
            if isinstance(v, list) and -len(v) <= s[1] < len(v):
                out.append((v[s[1]], s[1] % len(v)))
        elif s[0] == "slice":
            if isinstance(v, list):
                idx = range(len(v))[s[1]:s[2]]
                out += [(v[i], i) for i in idx]
        elif s[0] == "each":
            if isinstance(v, list):
                out += [(x, i) for i, x in enumerate(v)]
            elif isinstance(v, dict):
                out += [(x, i) for i, x in v.items()]
        elif s[0] == "deep":
            out += list(deep(v, k))
        elif s[0] == "keyname":
            if k is not None:
                out.append((k, k))
    return out


def walk(nodes, steps):
    for s in steps:
        nodes = step(nodes, s)
    return nodes


def show(steps):
    out = ""
    for s in steps:
        out += {"key": lambda: ("." if out else "") + s[1], "idx": lambda: f"[{s[1]}]", "each": lambda: "[]", "deep": lambda: ("." if out else "") + "**",
                "slice": lambda: f"[{'' if s[1] is None else s[1]}:{'' if s[2] is None else s[2]}]", "keyname": lambda: ".@key"}[s[0]]()
    return out or "the root"


def where_missing(doc, steps):
    """The first step that names nothing, with what is there instead: the hint a session needs to correct its path."""
    nodes = [(doc, None)]
    for i, s in enumerate(steps):
        nxt = step(nodes, s)
        if not nxt:
            here = nodes[0][0] if nodes else None
            have = ("keys there: " + ", ".join(list(here)[:30])) if isinstance(here, dict) else \
                   (f"a list of {len(here)} there: [] for its items, [N] for one") if isinstance(here, list) else f"a {kind(here)} there"
            return f"no {show([s]).lstrip('.')} under {show(steps[:i])}; {have}"
        nodes = nxt
    return "nothing there"


# ── output ───────────────────────────────────────────────────────────────────────────────────────────────────
def kind(v):
    return ("null" if v is None else "bool" if isinstance(v, bool) else "int" if isinstance(v, int) else "float" if isinstance(v, float)
            else "str" if isinstance(v, str) else f"list({len(v)})" if isinstance(v, list) else f"dict({len(v)})")


def text(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def cell(values, cut):
    s = ", ".join(re.sub(r"[\t\r\n]+", " ", text(v)) for v in values)
    return s if not cut or len(s) <= cut else s[:cut] + "…"


def item_keys(items):
    keys = []
    for x in items:
        if isinstance(x, dict):
            keys += [k for k in x if k not in keys]
    return keys


def about(v):
    """What a session looks for before it writes a path: a scalar's value, a dict's keys, a list's item keys."""
    if isinstance(v, dict):
        return ", ".join(list(v)[:20]) + (" …" if len(v) > 20 else "")
    if isinstance(v, list):
        kinds = sorted({re.sub(r"\(\d+\)", "", kind(x)) for x in v})
        keys = item_keys(v)
        return ("of " + "|".join(kinds) if kinds else "empty") + ((": " + ", ".join(keys[:20]) + (" …" if len(keys) > 20 else "")) if keys else "")
    return cell([v], 80)


def shape(v):
    if isinstance(v, dict):
        return [f"{k}\t{kind(x)}\t{about(x)}" for k, x in v.items()]
    return [f"{kind(v)}\t{about(v)}"]


# ── where ────────────────────────────────────────────────────────────────────────────────────────────────────
def conditions(specs):
    """--where K=V · K!=V · K~V, grouped: the same K and operator twice is either value."""
    groups = {}
    for spec in specs:
        m = re.match(r"(.*?)(!=|~|=)(.*)", spec, re.S)
        if not m:
            die(f"--where {spec!r}: K=V, K!=V or K~V")
        groups.setdefault((m.group(1), m.group(2)), []).append(m.group(3))
    return [(parse(k), op, vals) for (k, op), vals in groups.items()]


def keeps(row, conds):
    for steps, op, vals in conds:
        got = [text(v) for v, _ in walk([row], steps)]
        if op == "=" and not any(g in vals for g in got):
            return False
        if op == "!=" and any(g in vals for g in got):
            return False
        if op == "~" and not any(v.lower() in g.lower() for g in got for v in vals):
            return False
    return True


# ── main ─────────────────────────────────────────────────────────────────────────────────────────────────────
def load(path):
    if path:
        why = refused(path)
        if why:
            die(f"refused: {why}")
        try:
            with open(os.path.expanduser(path), encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError as e:
            die(f"cannot read the file: {e.strerror}", EX_NOTFOUND)
    else:
        if sys.stdin.isatty():
            die("no JSON on stdin and no --file; `ela pick --help`")
        raw = sys.stdin.read()
    try:
        return json.loads(raw)
    except ValueError as e:
        first = e
    try:                                             # JSON lines: one document per line, read as one list
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if rows:
            return rows
    except ValueError:
        pass
    # the position only, never the text: what was read may not be a document at all
    die(f"not JSON (line {getattr(first, 'lineno', '?')}, column {getattr(first, 'colno', '?')}); "
        "a verb prints JSON only with --json, and its notes go to stderr: drop 2>&1")


def main():
    ap = argparse.ArgumentParser(prog="ela pick", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", metavar="path")
    ap.add_argument("--file", "-f")
    ap.add_argument("--where", action="append", default=[], metavar="K=V")
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--shape", action="store_true")
    ap.add_argument("--max", type=int, default=0, metavar="N")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    doc = load(a.file)
    conds = conditions(a.where)
    if not a.paths and not (a.where or a.count or a.json):
        a.shape = True                                 # no path: the shape, never the whole document

    exprs = [parse(p) for p in (a.paths or [""])]
    first = exprs[0]
    last = max((i for i, s in enumerate(first) if s[0] in ROWS), default=-1)
    if last < 0 and (a.where or a.count) and len(exprs) == 1:
        first = exprs[0] = first + [("each",)]         # no [] written: the list the path names is the rows
        last = len(first) - 1
    if last >= 0:
        prefix = first[:last + 1]
    else:
        prefix = first[:-1] if any(p.startswith(".") for p in a.paths[1:]) else []
    tails = []
    for n, (p, steps) in enumerate(zip(a.paths or [""], exprs)):
        if n and p.startswith("."):
            tails.append(steps)
        elif steps[:len(prefix)] == prefix:
            tails.append(steps[len(prefix):])
        else:
            die(f"{p!r} does not go through {show(prefix)}, the rows of the first path; start it with a dot to read it "
                "from the row, or pick it in a call of its own")

    rows = [r for r in walk([(doc, None)], prefix) if keeps(r, conds)]
    if a.count:
        print(len(rows)); return
    lines = [[[v for v, _ in walk([r], t)] for t in tails] for r in rows]
    lines = [ln for ln in lines if any(ln)]
    if not lines:
        if not rows and walk([(doc, None)], prefix):
            die("no row matches --where", EX_NOTFOUND)
        die(where_missing(doc, first if not rows else prefix + next((t for t in tails), [])), EX_NOTFOUND)
    if a.shape:
        for ln in lines:
            for v in ln[0]:
                print("\n".join(shape(v)))
        return
    if a.json:
        flat = [ln[0][0] if len(ln[0]) == 1 else ln[0] for ln in lines] if len(tails) == 1 else \
               [[c[0] if len(c) == 1 else (c or None) for c in ln] for ln in lines]
        print(json.dumps(flat, ensure_ascii=False, indent=1)); return
    if len(lines) == 1 and len(tails) == 1 and len(lines[0][0]) == 1 and isinstance(lines[0][0][0], (dict, list)) and not a.max:
        print(json.dumps(lines[0][0][0], ensure_ascii=False, indent=1)); return
    for ln in lines:
        print("\t".join(cell(c, a.max) for c in ln))


if __name__ == "__main__":
    main()
