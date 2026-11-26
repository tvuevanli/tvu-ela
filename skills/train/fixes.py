#!/usr/bin/env python3
"""The fixes on their way: each train row as the deploy sees it — what changed, the test QA failed in QA's own words,
the verdict with its source, the row's impact on its next move and what happens next. Stdlib only; a module of the
train verb (`ela train`), read by the line page (release line.py) and today.md (vault.py).

    fixes.py --help    this text; the verbs are `ela train --line L [--write]` and `ela train --answer ID LETTER`

Impact, one scale (vault ela/2026-11-26-plan-fixes-followed-to-prod-one-home-per-fact.md, phase 2), judged under the
hiding bar (vault ela/2026-11-26-plan-ela-runs-on-its-own-asks-teach-it.md): a wrong "does not block" hides a risk,
so it is ela's only on a mechanical proof read first-hand, and every test fails closed.

    blocks          first-hand evidence: an open incident naming the key on a prod lane; a fail on daily or prod
                    after a pass on QA; an earlier pass on QA that a later build fails; QA's own verdict "not fixed"
                    (the main behaviour does not work); QA's own words that the fix brought a regression
    does not block  every test below holds:
                    1. each failed case is put out of the fix by proof, not by QA's tone: its line names a split
                       ticket, QA's own words put it out of scope, or it names a follow-up fix with a QA pass on a build
                       that travels with the move (a lane's config switch is a proof too, but no config is read yet,
                       so it never holds); a fail with no case named fails this test
                    2. the incidents were read and none names the key
                    3. the cell's history holds no earlier pass on QA or a prod lane
                    4. no ruling of the owner's of the same kind says blocks
    your call       anything else: an ask on today.md with ela's leaning and its reason, drafted; the owner answers
                    right or wrong, and the ruling is kept with its kind in <reports>/train/rulings.jsonl, cited as a
                    precedent for the next case of that kind (never standing in for a proof)
    not yet verified  arrived on QA, no word on the build it rides (an earlier build's fail is named)
    ready           QA passed, or the fix passed QA before the lane's list began

A row at prod is not on its way, unless a prod lane fails it or an incident names it. Impact orders rows; it never
hides one: a "does not block" is a visible line with its reason, never folded into a count.
"""
import datetime, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "promote"))
import qajira as QJ  # noqa: E402  — QA's verdict in Jira: counts, failed cases, splits, links

JIRA_URL = "https://tvunetworks.atlassian.net/browse/"
GROUPS = ("blocks", "your-call", "unverified", "no-block", "ready")
GROUP_TITLE = {"blocks": "Blocks", "your-call": "Your call", "unverified": "Not yet verified", "no-block": "Does not block",
               "ready": "Ready"}
CRITERIA = ("case-split", "case-follow-up", "case-out-of-scope", "partial", "fail", "report-only")   # the closed list of a kind's second half
REGRESSED_W = re.compile(r"(?i)" + "|".join([r"引入回归", r"出现回归", r"回归失败", r"\bregressed\b", r"introduc\w*\s+(?:a\s+)?regression"]))
MAIN_OK_W = re.compile(r"(?i)" + "|".join([r"主功能通过", r"主场景修复生效", r"main (?:function|fix|scenario)\w* (?:works|passe?s?)"]))
OUT_OF_SCOPE_W = re.compile(r"(?i)" + "|".join([r"不在本单范围", r"非本单范围", r"不属于本单", r"本单不覆盖", r"out of (?:this ticket's )?scope"]))
RULINGS = ("train", "rulings.jsonl")
ROW_CASE_CHARS, ROW_WORDS = 48, 9
OPEN_MAX = 6                    # a long group (not yet verified, does not block) shows this many, the rest folded


def anchor(key_or_id):
    """The row's block id on the line page: `fix-mh-4097`; lowercase so the linker never reads it as a key."""
    return "fix-" + re.sub(r"[^a-z0-9-]+", "-", str(key_or_id).lower()).strip("-")


def short(text, n):
    t = " ".join(str(text or "").split()).replace("|", "/")
    return t if len(t) <= n else t[:n - 1].rstrip(" ,;:，；：") + "…"


def words(text, n=ROW_WORDS):
    w = " ".join(str(text or "").split()).replace("|", "/").split(" ")
    return " ".join(w[:n]) + (" …" if len(w) > n else "")


# ── what QA said ───────────────────────────────────────────────────────────────────────────────────────

def qa_word(issue, qa, key):
    """QA's latest result comment on the ticket, compact: {verdict, head, counts, when, who, url, failed, splits, links};
    None when no QA person wrote one."""
    if not issue:
        return None
    v = QJ.verdict_of(issue, qa, key)
    lt = v.get("latest")
    if not lt:
        return {"verdict": "none", "links": v.get("links") or []}
    return {"verdict": v["verdict"], "head": lt.get("head"), "counts": lt.get("counts"), "when": lt.get("when"), "who": lt.get("who"),
            "url": f"{JIRA_URL}{key}?focusedCommentId={lt['id']}" if lt.get("id") else f"{JIRA_URL}{key}",
            "failed": [dict(c, keys=[k for k in c.get("keys") or [] if k != key]) for c in lt.get("failed") or []],
            "open_points": lt.get("open_points") or [], "splits": lt.get("splits") or [], "links": v.get("links") or []}


def report_line(reports, key, key_verdicts):
    """QA's own line on the key in the newest QA report mail that judges it: {at, build, verdict, line}, or None."""
    for r in sorted(reports or [], key=lambda x: x.get("at") or "", reverse=True):
        got = key_verdicts(r.get("text") or "", key)
        if got:
            v, seg = got[-1]
            return {"at": (r.get("at") or "")[:16], "build": r.get("build"), "verdict": v, "line": seg}
    return None


# ── the judgment ───────────────────────────────────────────────────────────────────────────────────────

def lane_of(lanes, role):
    return next((l["lane"] for l in lanes if l["role"] == role), None)


def shown_of(lanes, lane):
    return next((l["shown"] for l in lanes if l["lane"] == lane), lane)


def move_of(row, lanes):
    """The row's next move as (from lane, to lane), or None when it has none (at prod, or no arrival)."""
    order = [lane_of(lanes, r) for r in ("qa", "daily", "prod")]
    pos = {"qa": 0, "daily": 1}.get(row.get("position"))
    if pos is None or not order[pos] or not order[pos + 1]:
        return None
    return order[pos], order[pos + 1]


def build_no(text):
    m = re.search(r"(\d+)\s*$", str(text or ""))
    return int(m.group(1)) if m else None


def kind_of(row, criterion):
    """A ruling's kind: the row's layer and a criterion from the closed list."""
    assert criterion in CRITERIA, criterion
    return f"{row.get('layer') or '—'}:{criterion}"


def sig_of(row, qa_cell, word):
    """What a ruling answers: the verdict, the build and the failed cases. A new build or a new case asks again."""
    bits = [row.get("key") or row.get("id"), (qa_cell or {}).get("verdict"), (qa_cell or {}).get("version"),
            ",".join(sorted(c.get("case") or c.get("text", "")[:30] for c in (word or {}).get("failed") or []))]
    return hashlib.sha256("|".join(str(b) for b in bits).encode()).hexdigest()[:12]


def case_proof(case, row, word, by_key, qa_lane, moving_build):
    """Why one failed case is outside the fix, proven, or None. Proofs: a split ticket the case or the comment names
    (a Jira link of a split type, or a key QA's split words name); QA's own words putting it out of scope; a follow-up
    fix the case names with a QA pass on a build no newer than the one that moves."""
    splits = set(word.get("splits") or []) | {l["key"] for l in word.get("links") or [] if l.get("split")}
    for k in case.get("keys") or []:
        if k in splits:
            return ("case-split", f"{case.get('case') or 'the case'} split to {k}")
    if OUT_OF_SCOPE_W.search(case.get("text") or ""):
        return ("case-out-of-scope", f"QA put {case.get('case') or 'the case'} out of this ticket's scope")
    for k in case.get("keys") or []:
        other = by_key.get(k)
        c = ((other or {}).get("cells") or {}).get(qa_lane) or {}
        b = build_no(c.get("arrived"))
        if c.get("verdict") == "pass" and b is not None and (moving_build is None or b <= moving_build):
            return ("case-follow-up", f"{case.get('case') or 'the case'}'s follow-up {k} passed QA on build {b}")
    return None


def incident_names(key, incidents):
    return [i.get("key") for i in incidents or [] if key and key in re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b",
                                                                          f"{i.get('summary') or ''} {' '.join(i.get('labels') or [])}")]


def judge(row, lanes, by_key, incidents, rulings=()):
    """The row's impact on its next move: {group, reason, kind, leaning, lean_reason, proofs, failed_tests, sig, next,
    move}. `incidents` is None when the incidents lane was not read (test 2 then fails)."""
    qa_lane = lane_of(lanes, "qa")
    cells = row.get("cells") or {}
    qa_cell = cells.get(qa_lane) or {}
    word = row.get("qa_word") or {}
    move = move_of(row, lanes)
    out = {"move": list(move) if move else None, "sig": sig_of(row, qa_cell, word), "proofs": [], "failed_tests": [],
           "kind": None, "leaning": None, "lean_reason": None}
    key = row.get("key")

    def done(group, reason, nxt):
        return dict(out, group=group, reason=reason, next=nxt)

    for l in lanes:                                        # first-hand: an incident, a fail on daily or prod
        c = cells.get(l["lane"]) or {}
        if c.get("verdict") == "incident":
            return done("blocks", f"{c.get('source')} on {l['shown']}", "the incident's owner answers it")
        if l["role"] in ("daily", "prod", "cn") and c.get("verdict") == "fail":
            return done("blocks", f"fails on {l['shown']} ({c.get('source')})", "a fix, then QA again")
    if row.get("position") == "prod" or not move:
        return done("arrived", "on prod", None)
    if row.get("regression"):
        return done("blocks", row.get("priority_reason") or "a regression", "a fix, then QA again")
    hist = qa_cell.get("history") or []
    v = qa_cell.get("verdict")
    if v == "fail":
        last_fail = max((h.get("at") or "" for h in hist if h["verdict"] == "fail"), default="9")
        passed = [h for h in hist if h["verdict"] == "pass" and (h.get("at") or "")[:10] < last_fail[:10]]   # a pass the same day is a conflict, not a regression
        if passed:
            return done("blocks", f"passed QA on {passed[-1]['version']}, fails on {qa_cell.get('version')}", "a fix, then QA again")
        if word.get("verdict") == "fail":
            return done("blocks", "QA: not fixed" + case_list(word), "a fix, then QA again")
        if REGRESSED_W.search(word.get("head") or ""):
            return done("blocks", "QA: the fix brought a regression" + case_list(word), "a fix, then QA again")
        return firm_or_ask(row, lanes, by_key, incidents, rulings, out, word, qa_cell, move)
    if not qa_cell.get("arrived"):                         # the fix passed QA before the lane's list began
        return done("ready", "passed QA before the list began", f"moves with {shown_of(lanes, move[0])} → {shown_of(lanes, move[1])}")
    if v in ("pass", "n/a"):
        return done("ready", "QA passed" if v == "pass" else "QA: not testable on QA", f"moves with {shown_of(lanes, move[0])} → {shown_of(lanes, move[1])}")
    earlier = [h for h in hist if h["verdict"] == "fail"]
    reason = (f"failed {earlier[-1]['version']}" + case_list(word) + f"; build {qa_cell.get('arrived')} waits for QA") if earlier \
        else f"build {qa_cell.get('arrived')} waits for QA"
    return done("unverified", reason, f"QA's word on build {qa_cell.get('arrived')}")


def case_list(word, n=3):
    cs = [c.get("case") or "a case" for c in (word or {}).get("failed") or []]
    return f" ({', '.join(cs[:n])}{', …' if len(cs) > n else ''})" if cs else ""


def firm_or_ask(row, lanes, by_key, incidents, rulings, out, word, qa_cell, move):
    """A QA fail that is neither a plain "not fixed" nor a regression: "does not block" when every test holds, else
    your call with ela's leaning and its reason."""
    key, qa_lane = row.get("key"), lane_of(lanes, "qa")
    failed, proofs, tests = word.get("failed") or [], [], []
    moving = build_no(((row.get("cells") or {}).get(qa_lane) or {}).get("arrived"))
    if word.get("verdict") == "pass":
        criterion = "fail"
        tests.append(f"QA's Jira comment of {str(word.get('when'))[5:10]} says pass, a later QA word says fail")
    elif not word.get("head"):
        criterion = "report-only"
        tests.append("QA named no case in Jira: the failing case is not read")
    elif not failed:
        criterion = "partial" if word.get("verdict") == "partial" else "fail"
        tests.append("QA's comment names no failed case")
    else:
        crit = []
        for c in failed:
            p = case_proof(c, row, word, by_key, qa_lane, moving)
            if p:
                crit.append(p[0]); proofs.append(p[1])
            else:
                follow = [k for k in c.get("keys") or [] if k != key]
                tests.append(f"{c.get('case') or 'a case'}: " + (f"follow-up {follow[0]} has no QA pass on a build that moves" if follow
                                                                  else "nothing puts it outside the fix"))
        criterion = crit[0] if crit and not tests and len(set(crit)) == 1 else ("partial" if word.get("verdict") == "partial" else "fail")
    if incidents is None:
        tests.append("the incidents were not read")
    elif incident_names(key, incidents):
        tests.append(f"incident {incident_names(key, incidents)[0]} names it")
    if any(h["verdict"] == "pass" for l in lanes if l["role"] in ("qa", "prod", "cn")
           for h in ((row.get("cells") or {}).get(l["lane"]) or {}).get("history") or []):
        tests.append("an earlier pass is on record")
    kind = kind_of(row, criterion)
    same = [r for r in rulings or () if r.get("kind") == kind]
    if any(r.get("ruled") == "blocks" for r in same):
        tests.append(f"your ruling on {next(r['key'] for r in same if r.get('ruled') == 'blocks')} of the same kind says blocks")
    mine = next((r for r in reversed(list(rulings or ())) if r.get("key") == key and r.get("sig") == out["sig"]), None)
    base = dict(out, kind=kind, proofs=proofs, failed_tests=tests)
    if mine:                                               # his ruling on this very case: his word, cited
        return dict(base, group="blocks" if mine["ruled"] == "blocks" else "no-block",
                    reason=f"your ruling {mine['at'][5:10]}" + (f": {mine['cause']}" if mine.get("cause") else ""),
                    next="a fix, then QA again" if mine["ruled"] == "blocks" else f"moves with {shown_of(lanes, move[0])} → {shown_of(lanes, move[1])}")
    if not tests:
        return dict(base, group="no-block", reason="; ".join(proofs), next=f"moves with {shown_of(lanes, move[0])} → {shown_of(lanes, move[1])}")
    main_ok = bool(MAIN_OK_W.search(word.get("head") or ""))
    leaning = "does not block" if main_ok and (proofs or failed) else "blocks"
    c = (word.get("counts") or {})
    said = f"QA: main fix works ({c.get('pass', 0)} Pass + {c.get('fail', 0)} Fail)" if main_ok else \
        f"QA failed it on {qa_cell.get('version') or 'its build'}"
    why = "; ".join([said] + proofs + tests[:2])
    prec = [r for r in same if r.get("ruled")]
    if prec:
        why += f"; like your ruling on {prec[-1]['key']} ({prec[-1]['at'][5:10]}): {prec[-1]['ruled']}"
    return dict(base, group="your-call", reason="not proven: " + "; ".join(tests[:2]), leaning=leaning, lean_reason=why,
                next=f"your ruling on today.md, or `ela train answer impact:{key} A|B`")


# ── the train's rows, enriched ─────────────────────────────────────────────────────────────────────────

def enrich(rows, lanes, issues, reports, qa, incidents, rulings=(), key_verdicts=None):
    """Each row gains `qa_word` (QA's latest Jira result), `qa_report` (QA's own report line, the QA lane's mails) and
    `impact` (judge). `lanes` as the train lists them ([{role, lane, shown}]); `reports` the QA lane's report mails."""
    by_key = {}
    for r in rows:
        for k in [r.get("key"), *(r.get("also") or [])]:
            if k:
                by_key.setdefault(k, r)
    for r in rows:
        k = r.get("key")
        r["qa_word"] = qa_word((issues or {}).get(k), qa, k) if k else None
        r["qa_report"] = report_line(reports, k, key_verdicts) if k and key_verdicts else None
    for r in rows:
        r["impact"] = judge(r, lanes, by_key, incidents, rulings)
    return rows


# ── the line page's block ──────────────────────────────────────────────────────────────────────────────

def verdict_text(row, qa_lane):
    """The verdict with its source as a link: QA's Jira comment, else QA's report mail by its date."""
    c = ((row.get("cells") or {}).get(qa_lane) or {})
    word, rep = row.get("qa_word") or {}, row.get("qa_report") or {}
    v = c.get("verdict") or "untested"
    if v == "untested":
        last = next((h for h in reversed(c.get("history") or []) if h["verdict"] in ("pass", "fail")), None)
        return f"untested on build {c.get('arrived')}" + (f" (was {last['verdict']} on {last['version']})" if last else "")
    mark = {"pass": "✓", "fail": "❌", "n/a": "n/a", "incident": "⚠"}.get(v, v)
    src = f"[QA {str(word['when'])[5:10]}]({word['url']})" if word.get("url") and word.get("verdict") not in (None, "none") \
        else f"QA report {str(rep.get('at') or c.get('at') or '')[5:10]}".rstrip()
    ver = c.get("version") or (f"build {c.get('arrived')}" if c.get("arrived") else "")
    return f"{mark} {v} {ver} · {src}".replace("  ", " ")


def test_text(row):
    word, rep = row.get("qa_word") or {}, row.get("qa_report") or {}
    failed = word.get("failed") or []
    if failed:
        c = failed[0]
        more = f" +{len(failed) - 1}" if len(failed) > 1 else ""
        return f"{c.get('case') + ' ' if c.get('case') else ''}{short(c.get('text'), ROW_CASE_CHARS)}{more}"
    if rep.get("verdict") == "fail" and rep.get("line"):
        return short(rep["line"], ROW_CASE_CHARS)
    return None


def row_line(row, qa_lane):
    """One row as one visible line, with its block id so today.md and the morning page can link it."""
    imp = row.get("impact") or {}
    head = f"{'◇ ' if row.get('qa_only') else ''}{row.get('key') or 'no ticket'} {words(row.get('title'), ROW_WORDS)}"
    bits = [head]
    change = (row.get("change") or "").split(":", 1)[-1].strip()
    if change and short(change, 40).lower() not in (row.get("title") or "").lower():
        bits.append(f"change: {words(change, 7)}")
    t = test_text(row)
    if t:
        bits.append(f"test: {t}")
    bits.append(verdict_text(row, qa_lane))
    label = {"blocks": "blocks", "your-call": "your call", "no-block": "does not block", "unverified": "not yet verified"}.get(imp.get("group"), imp.get("group"))
    if imp.get("group") == "your-call":
        bits.append(f"**{label}**, ela leans *{imp.get('leaning')}*: {imp.get('reason')}")
    else:
        bits.append(f"**{label}**: {imp.get('reason')}")
    if imp.get("next"):
        bits.append(f"next: {imp['next']}")
    return "- " + " · ".join(bits) + f" ^{anchor(row.get('key') or row.get('id'))}"


def block(train, open_max=OPEN_MAX):
    """`## Fixes on their way` for the line page: blocks · your call · not yet verified · does not block, one line a
    row (blocks and your call never folded; a long group shows `open_max`, the rest folded), then Ready as a count.
    [] when the train has no row on its way."""
    lanes = train.get("lanes") or []
    qa_lane = lane_of(lanes, "qa")
    rows = [r for r in train.get("rows") or [] if (r.get("impact") or {}).get("group") in GROUPS]
    if not train.get("rows"):
        return []
    at = str(train.get("at") or "")
    L = ["## Fixes on their way", "",
         f"*From the train of {at[5:10]} {at[11:16]}: each fix by what it does to its next move. A row is never hidden; "
         f"`ela train --line {train.get('line')}` has every lane's cell.*", ""]
    if not rows:
        return L + ["Nothing is on its way: every fix in the window is on prod or has not reached QA.", ""]
    order = {"P1": 0, "P2": 1, "P3": 2}
    for g in GROUPS[:-1]:
        mine = sorted((r for r in rows if r["impact"]["group"] == g), key=lambda r: (order.get(r.get("priority"), 3), r.get("key") or r["id"]))
        if not mine:
            continue
        lines = [row_line(r, qa_lane) for r in mine]
        L.append(f"**{GROUP_TITLE[g]} · {len(mine)}**")
        L.append("")
        if g in ("blocks", "your-call") or len(lines) <= open_max:
            L += lines
        else:
            L += lines[:open_max] + ["", f"> [!note]- {len(lines) - open_max} more not yet verified" if g == "unverified"
                                     else f"> [!note]- {len(lines) - open_max} more"] + ["> " + l for l in lines[open_max:]]
        L.append("")
    ready = [r for r in rows if r["impact"]["group"] == "ready"]
    if ready:
        by_move = {}
        for r in ready:
            m = r["impact"].get("move") or ["", ""]
            by_move.setdefault(f"{shown_of(lanes, m[0])} → {shown_of(lanes, m[1])}", []).append(r)
        L.append("**Ready:** " + " · ".join(f"{len(v)} for {k}" for k, v in by_move.items()))
        L += ["", "> [!note]- Ready, by key"] + [f"> - {k}: " + ", ".join(r.get("key") or "no ticket" for r in v) for k, v in by_move.items()] + [""]
    return L


# ── today.md ───────────────────────────────────────────────────────────────────────────────────────────

def changed_since(row, since):
    """The newest word on any of the row's cells after `since` (ISO), or None."""
    words_ = [h for c in (row.get("cells") or {}).values() for h in c.get("history") or [] if (h.get("at") or "") > (since or "")[:16]]
    return max(words_, key=lambda h: h.get("at") or "", default=None)


def since_lines(trains, since, page_of, n=5):
    """today.md's "Since you last looked": at most n lines, each a fix whose verdict changed since he last looked,
    linking its row on its line page — blocks, then your call, does not block, not yet verified; a passes-only rest as
    one count line. `trains` [train]; `page_of(line)` the line page's path without .md."""
    rank = {g: i for i, g in enumerate(GROUPS)}
    got = []
    for t in trains or []:
        for r in t.get("rows") or []:
            imp = r.get("impact") or {}
            h = changed_since(r, since) if since else None
            if not h or imp.get("group") not in GROUPS:
                continue
            got.append((rank[imp["group"]], h.get("at") or "", t, r, h))
    got.sort(key=lambda x: (x[0], x[1]))
    shown = [x for x in got if x[2] is not None and x[0] < rank["ready"]]
    passed = [x for x in got if x[0] == rank["ready"]]
    out = []
    for _, _, t, r, h in shown[: n - (1 if passed else 0)]:
        imp = r["impact"]
        label = {"blocks": "blocks", "your-call": "your call", "no-block": "does not block", "unverified": "not yet verified"}[imp["group"]]
        what = f"{h['verdict']} on {h.get('version') or 'its build'}"
        told = f"your call, ela leans {imp.get('leaning')}" if imp["group"] == "your-call" else f"{label}: {words(imp.get('reason'), 14)}"
        out.append(f"- {r.get('key') or 'a no-ticket fix'} {what} — {told} → "
                   f"[[{page_of(t['line'])}#^{anchor(r.get('key') or r['id'])}|its row]]")
    rest = shown[n - (1 if passed else 0):]
    if passed or rest:
        lines_ = sorted({t["line"] for _, _, t, _, _ in passed + rest})
        out.append(f"- {len(passed)} more passed QA" + (f", {len(rest)} more changed" if rest else "") + " → "
                   + " · ".join(f"[[{page_of(l)}#Fixes on their way|the {l} line]]" for l in lines_))
    return out[:n]


def asks(trains, page_of):
    """Each your-call row as a today.md ask: one line of question, ela's leaning as A with its reason, the other way as
    B; the letter is recorded by `answer`. [{id, text, whole, options, sig, link}]; the vault's ask cap applies."""
    out = []
    for t in trains or []:
        for r in t.get("rows") or []:
            imp = r.get("impact") or {}
            if imp.get("group") != "your-call" or not r.get("key"):
                continue
            mv = imp.get("move") or ["", ""]
            lanes = t.get("lanes") or []
            other = "blocks" if imp["leaning"] == "does not block" else "does not block"
            aid = f"impact:{r['key']}"
            out.append({"id": aid, "whole": True, "sig": imp["sig"], "kind": imp.get("kind"),
                        "text": f"Ruling: does {r['key']}'s QA fail block {shown_of(lanes, mv[0])} → {shown_of(lanes, mv[1])}? "
                                f"ela leans {imp['leaning']}: {short(imp.get('lean_reason'), 220)}",
                        "link": f"{page_of(t['line'])}#^{anchor(r['key'])}",
                        "options": [{"letter": "A", "text": f"right: {imp['leaning']}", "does": f"ela train answer {aid} A", "recommended": True},
                                    {"letter": "B", "text": f"wrong: it {other}; say why under the ask", "does": f"ela train answer {aid} B",
                                     "recommended": False}]})
    return out


# ── the owner's rulings ────────────────────────────────────────────────────────────────────────────────

def rulings_path(reports):
    return os.path.join(reports or "", *RULINGS)


def read_rulings(reports):
    out = []
    try:
        for l in open(rulings_path(reports), encoding="utf-8"):
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def answer(reports, aid, letter, train, why=None, now=None):
    """His letter on a your-call ask, kept with its kind: A agrees with ela's leaning, B rules the other way; `why` is
    his cause, recorded as "waiting for a cause" when absent. Raises KeyError when the train holds no such ask,
    ValueError for a letter other than A or B. → the ruling row."""
    letter = str(letter).upper()
    if letter not in ("A", "B"):
        raise ValueError(letter)
    key = aid.split(":", 1)[-1]
    row = next((r for r in (train or {}).get("rows") or [] if r.get("key") == key and (r.get("impact") or {}).get("group") == "your-call"), None)
    if not row:
        raise KeyError(aid)
    imp = row["impact"]
    ruled = imp["leaning"] if letter == "A" else ("blocks" if imp["leaning"] == "does not block" else "does not block")
    rec = {"at": (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds"), "id": aid, "key": key,
           "line": (train or {}).get("line"), "kind": imp.get("kind"), "sig": imp.get("sig"), "leaning": imp["leaning"],
           "lean_reason": imp.get("lean_reason"), "letter": letter, "ruled": ruled, "cause": why or None,
           "corpus": "admitted" if why or letter == "A" else "waiting for a cause"}
    p = rulings_path(reports)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


if __name__ == "__main__":
    print(__doc__)
