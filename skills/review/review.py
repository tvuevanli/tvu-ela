#!/usr/bin/env python3
"""ela's own output, reviewed: the workflow is judged on the pages ela writes, not on the owner noticing.

    review.py lint PAGE [--actions F] [--date D] [--json]

lint checks one page mechanically (a morning page, Changes, the lanes page, the board): every ticket key is a link,
every Do line is a box and none is a bare verb for him, every `apply N` has its action and its box, a count equals
the day's counts object, a key is an item once, a service is named by slug, a front-matter status is in the closed
set, and a bundle name is one the reads held. Exit 1 with one line per failure; `ela page-check` runs it.

Reads files only; nothing is posted or ticked.
"""
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "brief"))
import brief as B  # noqa: E402  — the apply-N check and front matter, read the page-check way
sys.path.insert(0, os.path.join(HERE, "..", "vault"))
import vault as V  # noqa: E402  — the closed status set and the key pattern the vault links

SITE = os.path.expanduser("~/.claude/ela/site.json")
CODE_SPAN = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)
LINKED = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+|\[\[[^\]]*\]\]")
ITEM_RX = re.compile(r"^###\s+\d+\.\s", re.M)
DO_RX = re.compile(r"^\s*[-*]\s+\*\*Do:\*\*\s*(.*)$")
BOX_RX = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
# a box he must still act on: a slash command, or a draft, list, lookup or question left for him to make
BARE_VERB_RX = re.compile(r"/ela:|^(?:draft|list|ask|run|check|look|read|find|write|go deep)\b", re.I)
VAGUE_SERVICE_RX = re.compile(r"\b(?:the|a)\s+(frontend|backend)\b(?!\s*[(:]?\s*[\w-]*\d)", re.I)
BUNDLE_RX = re.compile(r"\bmh\d+\.\d+@[a-z][\w-]*|\bMediaHub \d+\.\d+(?:\.\d+| rc\d+)(?: \([^)]*\))?")
# a count over another window or scope ("commits, 7 days", "8 commits on a branch") is not the day's
SCOPED = r"(?!,?\s*\d+\s+days|\s+(?:on|in|for|to|from|of|since|by|under)\b)"
# a count cited in prose or a heading, and the counts-object field it must equal; "(N · M as of" takes M
COUNT_PHRASES = (
    (re.compile(r"\b(\d+)\s+close-ready\b|\bclose-ready(?: tickets)?:?\s+(\d+)\b|Ready for a close proposal \((?:\d+ · )?(\d+)", re.I), "close_ready"),
    (re.compile(r"\b(\d+)\s+verified[- ]not[- ]fixed\b|Verified as not fixed \((?:\d+ · )?(\d+)", re.I), "verified_not_fixed"),
    (re.compile(r"\b(\d+)\s+(?:ela\s+)?jobs\b" + SCOPED, re.I), "jobs"),
    (re.compile(r"\b(\d+)\s+commits\b" + SCOPED, re.I), "commits"),
    (re.compile(r"\b(\d+)\s+tickets moved\b" + SCOPED, re.I), "tickets_moved"),
    (re.compile(r"\b(\d+)\s+builds\b" + SCOPED, re.I), "builds"),
)


def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def roots(s):
    p = s.get("projects", "")
    return s.get("reports") or os.path.join(p, "reports"), s.get("runtime") or os.path.join(p, ".ela"), s.get("vault")


def outside_code(text):
    """The page with code spans and fences blanked, line breaks kept so line numbers still hold."""
    return CODE_SPAN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def bare_keys(text, in_vault):
    """Ticket keys a reader sees as plain text. In the vault every key outside a link is bare; in a <reports> source
    the vault links keys on render, except inside code spans, which it leaves as written."""
    out = []
    if in_vault:
        plain = LINKED.sub(lambda m: " " * len(m.group(0)), outside_code(text))
        out = [m.group(1) for m in V.KEY_RX.finditer(plain)]
    else:
        for m in CODE_SPAN.finditer(text):
            out += [k.group(1) for k in V.KEY_RX.finditer(m.group(0)) if not m.group(0).startswith("```")]
    return sorted({k for k in out if not B.NOT_KEYS.match(k)})


def items(text):
    """The numbered items (`### N. …`): (heading line, facts line, body) each."""
    starts = [m.start() for m in ITEM_RX.finditer(text)]
    out = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        nxt = re.search(r"^##\s", text[s + 3:end], re.M)
        body = text[s:s + 3 + nxt.start()] if nxt else text[s:end]
        lines = body.splitlines()
        out.append((lines[0], lines[1] if len(lines) > 1 else "", body))
    return out


def do_lines(body):
    """The lines under an item's **Do:**: (line, text of a box or None)."""
    out, on = [], False
    for line in body.splitlines():
        m = DO_RX.match(line)
        if m:
            on = True
            if m.group(1).strip():
                out.append((line, None))
            continue
        if on:
            if not line.strip() or line.startswith("#"):
                break
            b = BOX_RX.match(line)
            out.append((line, b.group(1) if b else None))
    return out


def lint(text, actions=None, counts=None, bundles=None, in_vault=False, brief=False):
    """One line per failure, empty when the page passes. `actions` the day's drafted writes (None: not checked),
    `counts` the day's counts object, `bundles` every bundle name the reads held (None: not checked)."""
    fails = []
    for k in bare_keys(text, in_vault):
        fails.append(f"{k}: a ticket key that is not a link")
    if actions is not None:
        orphan, unboxed = B.page_check(text, actions)
        fails += [f"apply {n}: no such action in the actions file" for n in orphan]
        fails += [f"apply {n}: named without its box on the page" for n in unboxed]
    seen = {}
    for head, facts, body in items(text):
        title = head.lstrip("#").strip()
        for line, box in do_lines(body):
            if box is None:
                fails.append(f"{title[:50]}: a Do line without a box: {line.strip()[:60]}")
            elif BARE_VERB_RX.search(box.strip()) and not B.APPLY_RX.search(box):
                fails.append(f"{title[:50]}: a Do line left for him to do: {box.strip()[:60]}")
        for k in set(B.keys_in(head + "\n" + facts)):
            seen.setdefault(k, []).append(title.split(".")[0])
    for k, where in sorted(seen.items()):
        if len(where) > 1:
            fails.append(f"{k}: an item {len(where)} times (items {', '.join(where)})")
    plain = outside_code(text)
    for m in VAGUE_SERVICE_RX.finditer(plain):
        line = plain[:m.start()].count("\n") + 1
        fails.append(f"line {line}: \"{m.group(0)}\": name the service by its slug")
    status = B.front_matter(text).get("status")
    if status not in (None, "") and status not in V.STATUSES:
        fails.append(f"status {status!r}: not in the closed set ({', '.join(V.STATUSES)})")
    if counts:
        for rx, field in COUNT_PHRASES:
            if field not in counts:
                continue
            for m in rx.finditer(plain):
                n = int(next(g for g in m.groups() if g))
                if n != counts[field]:
                    fails.append(f"{field}: the page says {n}, the day's counts say {counts[field]}")
    if bundles is not None:
        for name in sorted({m.group(0) for m in BUNDLE_RX.finditer(plain)}):
            if name not in bundles and not name.startswith("MediaHub "):
                fails.append(f"{name}: a bundle no read of the last 14 days holds")
    return list(dict.fromkeys(fails))


def page_date(path, text):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path)) or re.search(r"(\d{4}-\d{2}-\d{2})", text[:400])
    return m.group(1) if m else None


def day_counts(runtime, date):
    try:
        return json.load(open(os.path.join(runtime, "runner", f"{date}-changes.json"), encoding="utf-8")).get("counts") or {}
    except (OSError, ValueError):
        return None


def read_bundles(runtime):
    """Every bundle name the daily reads held: the changes files' new bundles and the matrix rows they wrote."""
    names = set()
    for f in sorted(glob.glob(os.path.join(runtime, "runner", "*-changes.json")))[-14:]:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names |= {str(b.get("name")) for b in d.get("bundles") or [] if b.get("name")}
    return names


def context(path, text, actions_path=None, date=None):
    """What lint compares a page with, found from the page's name and date: (actions, counts, bundles, in_vault, brief)."""
    s = site()
    reports, runtime, vault = roots(s)
    date = date or page_date(path, text)
    brief = bool(re.search(r"-brief\.md$", path))
    if not actions_path and brief and date:
        actions_path = os.path.join(reports, "runner", f"{date}-actions.json")
    actions = None
    if actions_path:
        try:
            actions = json.load(open(actions_path, encoding="utf-8"))
        except OSError:
            actions = []
    counts = day_counts(runtime, date) if date else None
    bundles = read_bundles(runtime)
    in_vault = bool(vault) and os.path.realpath(path).startswith(os.path.realpath(vault) + os.sep)
    return actions, counts, bundles or None, in_vault, brief


def cmd_lint(args):
    try:
        text = open(args.page, encoding="utf-8").read()
    except OSError as e:
        print(f"lint: {e}", file=sys.stderr); sys.exit(2)
    try:
        actions, counts, bundles, in_vault, brief = context(args.page, text, args.actions, args.date)
    except ValueError as e:
        print(f"lint: {e}", file=sys.stderr); sys.exit(2)
    fails = lint(text, actions, counts, bundles, in_vault, brief)
    if args.json:
        print(json.dumps({"page": args.page, "failures": fails}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(fails))
    sys.exit(1 if fails else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint", help="mechanical checks on any page ela writes; exit 1 with one line per failure")
    p.add_argument("page")
    p.add_argument("--actions", help="the day's actions file (default <reports>/runner/<date>-actions.json for a brief page)")
    p.add_argument("--date", help="the page's day, YYYY-MM-DD (default: from its name or header)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lint)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
