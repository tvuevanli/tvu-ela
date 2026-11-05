#!/usr/bin/env python3
"""Docker service candidates: for every docker image QA has reported on, whether its version can move to a lane.

    docker.py [--env-file F] [--days 21]              the candidates as Markdown
    docker.py … --json                                 the candidates
    docker.py … --image tvu_live_transmit              one image only
    docker.py … --write                                keep them as <reports>/docker/candidates.json
    docker.py … --page                                 also write <reports>/lanes/docker.md (the vault places it)
    docker.py --morning                                the morning page's lines, from the written result; no reads

A docker service is released by its developer in a mail whose subject names the image
(`docker.tvunetworks.com/<group>/<image>:<version>`) and reported on by QA in a "Summary/Daily Test Report" mail
naming the same image. Lanes take a docker version through a GM bundle, so a lane's version is the tag its newest
bundle carries (prod: the line's official bundle, as pinned). For each image and its newest reported version this
joins:
  - QA's own conclusion, quoted from the summary report (never re-derived), and the signal ela reads in it:
    `positive` (建议发布 / no regression introduced by this version / 不阻塞), `negative` (不建议 / 暂缓 / 放行卡点 /
    阻断), or `unclear`;
  - each ticket the report names, with its Jira status and priority, and the report's own blocking column (是/否);
  - a breaking-change sentence (破坏性变更 / breaking), which another layer must absorb;
  - the version each followed line's QA, daily and prod lanes carry, and the versions a move would skip;
  - a newer release of the same image still under test.
The verdict is ela's reading of those facts, each part cited: `ready` · `ready-with-questions` · `not-ready` ·
`under-test` (released, no summary report yet) · `read-the-report` (QA's words did not say). A daily lane behind a
ready version gets the dry-run bundle command for the owner; QA lanes are QA's to move, so they get a question instead;
prod moves through the line's promotion (/ela:promote), never from here.
Read-only: mail, Jira and GM bundles are read; nothing is created. Writes only under <reports>.
Exit codes: 0 ok · 2 usage (--image with --write or --page) · 5 the mails could not be read.
"""
import argparse, datetime, email.utils, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
for d in ("brief", "release"):
    sys.path.insert(0, os.path.join(SKILLS, d))
import brief as B  # noqa: E402  — run_json, lane_bundles, followed_lines, mail_time, the mail/jira/release scripts
import release as R  # noqa: E402  — the published map: lines and their lanes; the bundle time

EX_USAGE, EX_REMOTE = 2, 5
MAIL, JIRA, RELEASE, PROMOTE = B.MAIL, B.JIRA, B.RELEASE, os.path.join(SKILLS, "promote", "promote.py")
REG = r"docker\.tvunetworks\.(?:com|cn)/[\w.-]+/"
VER = r"v?\d+(?:\.\d+)+(?:[a-z]+\d+)?(?:-[a-z]+)?"
IMAGE_RX = re.compile(r"(?:" + REG + r")([\w.-]*[a-z][\w.-]*):(" + VER + r")", re.I)
AND_RX = re.compile(r"&\s*([\w.-]*[a-z][\w.-]*):(" + VER + r")", re.I)
REPORT_RX = re.compile(r"test\s+report", re.I)
SUMMARY_RX = re.compile(r"\bsummary\b", re.I)
REPLY_RX = re.compile(r"^\s*(re|fw|fwd)\s*:", re.I)
KEY_RX = re.compile(r"\bMH-\d+\b")
POSITIVE = ("建议发布", "可以发布", "同意发布", "没有发现本版引入", "未发现本版引入", "没有本版引入", "未发现功能缺陷",
            "不阻塞", "结论：通过", "结论: 通过", "冒烟测试通过", "recommend release", "no regression")
NEGATIVE = ("不建议", "暂缓", "放行卡点", "阻断级", "不能发布", "不可发布", "无法放行", "do not release", "blocks the release")
PASS_MARKS, FAIL_MARKS = ("通过验证", "通过", "PASS"), ("不通过", "未通过", "FAIL")
MARK_RX = re.compile(r"\*\s*(" + "|".join(PASS_MARKS + FAIL_MARKS) + r")[^*\n]{0,16}\*"   # *PASS* · *通过* · *未通过*
                     r"|--\s*(" + "|".join(m for m in PASS_MARKS + FAIL_MARKS if not m.isascii()) + r")\b")   # -- 通过验证
CONCLUSION_MARKS =("结论", "验收意见", "Conclusion", "测试结论", "Test Result")
BREAKING_RX = re.compile(r"[^。\n]{0,80}(?:破坏性变更|breaking change)[^。\n]{0,80}", re.I)
SEVERITY_RX = re.compile(r"(?:Highest|High|Medium|Low|高|中|低)\S{0,12}\s+(是|否)")
ROLES = ("qa", "daily", "prod")
JIRA_BROWSE = "https://tvunetworks.atlassian.net/browse/"


def now():
    return datetime.datetime.now().astimezone()


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "")))


def same(a, b):
    return vtuple(a) == vtuple(b)


def who(addr):
    return email.utils.parseaddr(addr or "")[0] or addr


# ── mails ────────────────────────────────────────────────────────────────────────────────────────────
def images_in(subject):
    """Every (image, version) a subject names: the full paths, then a bare `name:version` after an `&`
    ("…/shm_agora:1.0.6 & audio_card_capture:1.0.6"), which shares the first one's registry."""
    out = [(m.group(1), m.group(2)) for m in IMAGE_RX.finditer(subject)]
    if out:
        out += [(m.group(1), m.group(2)) for m in AND_RX.finditer(subject) if (m.group(1), m.group(2)) not in out]
    return out


def mail_search(env, query, limit=100):
    return B.run_json(["python3", MAIL, *env, "search", query, "--limit", str(limit), "--json"], timeout=300).get("messages") or []


def collect_mails(env, days):
    """{image: {version: {"release": mail|None, "summary": [mails], "daily": [mails]}}} over the window. A reply names its
    thread's image, not a new event, and is skipped."""
    after = (now() - datetime.timedelta(days=days)).strftime("%Y/%m/%d")
    seen, msgs = set(), []
    for q in (f'subject:("test report") after:{after}', f"subject:(docker.tvunetworks.com OR docker.tvunetworks.cn) after:{after}"):
        for m in mail_search(env, q):
            if m["id"] not in seen:
                seen.add(m["id"]); msgs.append(m)
    out = {}
    for m in msgs:
        subj = m.get("subject") or ""
        if REPLY_RX.match(subj):
            continue
        m["at"] = (B.mail_time(m.get("date")) or "")[:16].replace("T", " ")
        for image, ver in images_in(subj):
            vs = out.setdefault(image, {})
            key = next((k for k in vs if same(k, ver)), ver)   # v1.0.19 and 1.0.19 are one version
            cell = vs.setdefault(key, {"release": None, "summary": [], "daily": []})
            if REPORT_RX.search(subj):
                cell["summary" if SUMMARY_RX.search(subj) else "daily"].append(m)
            elif not cell["release"] or m["at"] < cell["release"]["at"]:
                cell["release"] = m
    return out


# ── QA's words ──────────────────────────────────────────────────────────────────────────────────────
def clean(text):
    return re.sub(r"<https?://[^>]+>", "", re.sub(r"[ \t\r]+", " ", text or "")).strip()


def conclusion(body):
    """QA's conclusion as written: the first bold sentence after a conclusion marker, else the marker's next line;
    with no marker, the first line carrying a release word."""
    text = clean(body)
    for mark in CONCLUSION_MARKS:
        i = text.find(mark)
        if i < 0:
            continue
        seg = text[i:i + 1200]
        bold = re.search(r"\*([^*]{12,400})\*", seg)          # a bold sentence may wrap across the mail's lines
        if bold:
            return re.sub(r"\s*\n\s*", "", bold.group(1)).strip()
        line = next((l.strip() for l in seg.split("\n")[1:] if len(l.strip()) > 14 and not re.search(r"[:：]\s*$", l)), "")
        if line:
            return line[:300]
    return next((l.strip()[:300] for l in text.split("\n") if any(w in l for w in POSITIVE + NEGATIVE)), "")


def marks(body):
    """The results QA marked item by item — `*PASS*`, `*通过*`, `-- 通过验证`, `*FAIL*`, `*未通过*` — as (pass, fail).
    Only a marked result counts: a FAIL inside an expected-behaviour sentence is not one."""
    words = [a or b for a, b in MARK_RX.findall(clean(body))]
    fail = sum(w in FAIL_MARKS for w in words)
    return len(words) - fail, fail


def signal(body, quote):
    """A negative word in the conclusion or the report's head wins: a report saying both names a blocker. With no
    release word, QA's item marks speak: every marked result a pass and none a fail reads as positive."""
    head = quote + "\n" + clean(body)[:4000]
    neg = next((w for w in NEGATIVE if w in head), None)
    if neg:
        return "negative", neg
    pos = next((w for w in POSITIVE if w in head), None)
    if pos:
        return "positive", pos
    p, f = marks(body)
    if f:
        return "negative", f"{f} item{'s' if f != 1 else ''} marked FAIL"
    if p >= 2:
        return "positive", f"{p} items marked PASS/通过, none FAIL"
    return "unclear", None


def ticket_rows(body):
    """Each MH key the report names, once, with the report's blocking column (是/否) when its row carries one."""
    text = clean(body)
    hits = list(KEY_RX.finditer(text))
    out = {}
    for n, m in enumerate(hits):
        key = m.group(0)
        end = min(hits[n + 1].start() if n + 1 < len(hits) else len(text), m.end() + 600)
        sev = SEVERITY_RX.search(text[m.end():end])
        blocking = {"是": "yes", "否": "no"}[sev.group(1)] if sev else None
        if key not in out or (blocking and not out[key]["blocking"]):
            out[key] = {"key": key, "blocking": blocking}
    return list(out.values())


def breaking(body):
    m = BREAKING_RX.search(clean(body))
    return m.group(0).strip(" ，,;；") if m else None


# ── lanes ───────────────────────────────────────────────────────────────────────────────────────────
def bundle_images(env, bundle, host, cache):
    """{image: [(GM name, tag)]} from a bundle's bill of materials; the image is the backend version's last segment."""
    bid = str(bundle["bundleId"])
    if bid not in cache:
        got = B.run_json(["python3", RELEASE, *env, "bundle", bid, "--host", host, "--json"], timeout=180)
        imgs = {}
        for s in got.get("services") or []:
            m = re.search(r"/([\w.-]+):([\w.+-]+)$", str(s.get("backendVersion") or ""))
            if m:
                imgs.setdefault(m.group(1), []).append((s.get("serviceName"), s.get("tagName") or m.group(2)))
        cache[bid] = imgs
    return cache[bid]


def read_lanes(env, gaps):
    """[{line, role, lane, host, bundle, images|None, error}] for each followed line's qa, daily and prod lanes."""
    lines, cache, out = R.rmap("lines") or {}, {}, []
    for line in B.followed_lines():
        cfg = lines.get(line) or {}
        if not cfg.get("bundle_line") or not cfg.get("lanes"):
            continue
        for role in ROLES:
            lane = cfg["lanes"].get(role)
            if not lane:
                continue
            host = "qa" if role == "qa" else "prod"
            row = {"line": line, "role": role, "lane": lane, "host": host, "bundle": None, "images": None, "error": None}
            try:
                got = B.lane_bundles(env, line, role, host, cfg)
                if got:
                    row["bundle"] = {"name": got[0].get("bundleName"), "id": str(got[0].get("bundleId")), "at": R.when(got[0].get("createTime"))}
                    row["images"] = bundle_images(env, got[0], host, cache)
                else:
                    row["error"] = "no bundle for this lane"
            except (B.LaneError, subprocess.TimeoutExpired, ValueError, KeyError) as e:
                why = str(e).split("{")[0].strip()[:120] or type(e).__name__
                row["error"] = "not readable: QA no longer admits ela's account" if host == "qa" else f"not readable: {why}"
            if row["error"]:
                gaps.append(f"{lane} ({line} {role}): {row['error']}")
            out.append(row)
    return out


def constraints(env, gaps):
    try:
        return B.run_json(["python3", PROMOTE, *env, "constraints", "--json"], timeout=120).get("active") or []
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
        gaps.append(f"standing constraints: {str(e)[:120]}")
        return []


# ── judgment over the facts ─────────────────────────────────────────────────────────────────────────
def lane_cell(lane, image, ver, versions):
    if lane["images"] is None:
        return {"state": "unread", "why": lane["error"]}
    tags = lane["images"].get(image)
    if not tags:
        return {"state": "absent"}
    have = sorted({t for _, t in tags}, key=vtuple)
    cell = {"gm": [g for g, _ in tags], "have": have}
    if not all(B.is_version(t) for t in have):           # a GM named tag ("Production2", "Monday") cannot be compared
        cell["state"] = "named"
        return cell
    low, high, want = vtuple(have[0]), vtuple(have[-1]), vtuple(ver)
    if all(same(t, ver) for t in have):
        cell["state"] = "at"
    elif low > want:
        cell["state"] = "ahead"
    elif high <= want:
        cell["state"] = "behind"
        cell["skips"] = [{"version": v, "reported": bool(c["summary"])} for v, c in sorted(versions.items(), key=lambda x: vtuple(x[0]))
                         if low < vtuple(v) < want]
    else:
        cell["state"] = "mixed"
    return cell


def is_open(ticket):
    return (ticket.get("status") or "").lower() not in ("done", "closed", "resolved")


def judge(image, versions, lanes, jira, pins):
    """One image → its candidate: the newest version with a summary report, else the newest released one."""
    order = sorted(versions, key=vtuple, reverse=True)
    reported = [v for v in order if versions[v]["summary"]]
    ver = reported[0] if reported else order[0]
    cell = versions[ver]
    c = {"image": image, "version": ver, "release": None, "report": None, "tickets": [], "questions": [], "risks": [],
         "lanes": [], "commands": [], "asks": []}
    if cell["release"]:
        r = cell["release"]
        c["release"] = {"id": r["id"], "at": r["at"], "by": who(r["from"]), "subject": r["subject"]}
    c["newer"] = [{"version": v, "released": (versions[v]["release"] or {}).get("at"), "daily_reports": len(versions[v]["daily"])}
                  for v in order if vtuple(v) > vtuple(ver)]
    if cell["summary"]:
        m = cell["summary"][0]
        body = m.get("body") or ""
        quote = re.sub(r"\s*<[^>\s]+@[^>\s]+>|\*", "", conclusion(body)).strip()
        sig, word = signal(body, quote)
        if word and " marked " in word:                   # the signal came from the item marks, not a release word,
            quote = f"QA's item marks: {word}"            # so the marks are QA's words here
        c["report"] = {"id": m["id"], "at": m["at"], "by": who(m["from"]), "subject": m["subject"],
                       "conclusion": quote, "signal": sig, "signal_word": word}
        for t in ticket_rows(body):
            j = jira.get(t["key"]) or {}
            c["tickets"].append(dict(t, summary=j.get("summary"), status=j.get("status"), priority=j.get("priority"), assignee=j.get("assignee")))
        b = breaking(body)
        if b:
            c["questions"].append(f"a breaking change another layer must absorb, in QA's words: «{b}» — does the target lane's app handle it?")
    elif cell["daily"]:
        d = cell["daily"][0]
        c["report"] = {"id": d["id"], "at": d["at"], "by": who(d["from"]), "subject": d["subject"], "signal": "in-progress", "conclusion": None}
    blocking = [t for t in c["tickets"] if t["blocking"] == "yes" and is_open(t)]
    high = [t for t in c["tickets"] if t["blocking"] != "yes" and is_open(t) and t.get("priority") in ("Highest", "High")]
    if high:
        c["risks"].append("open High tickets the report names as not blocking: " + ", ".join(t["key"] for t in high))
    if c["newer"]:
        c["questions"].append("a newer release has no summary report yet: " + ", ".join(f"{n['version']} (released {(n['released'] or '?')[:10]})" for n in c["newer"])
                              + " — move the reported one, or wait for the newer?")
    for p in pins:
        if image.lower() in json.dumps(p, ensure_ascii=False).lower():
            c["questions"].append(f"a standing constraint names this image: {p.get('what') or p.get('id') or json.dumps(p, ensure_ascii=False)[:120]}")
    sig = (c["report"] or {}).get("signal")
    if not cell["summary"]:
        c["verdict"] = "under-test"
    elif sig == "negative" or blocking:
        c["verdict"] = "not-ready"
        if blocking:
            c["risks"].insert(0, "QA marks as blocking the release: " + ", ".join(t["key"] for t in blocking))
    elif sig == "positive":
        c["verdict"] = "ready"
    else:
        c["verdict"] = "read-the-report"
    for lane in lanes:
        lc = dict(lane_cell(lane, image, ver, versions), line=lane["line"], role=lane["role"], lane=lane["lane"],
                  bundle=(lane["bundle"] or {}).get("name"))
        c["lanes"].append(lc)
        if lc["state"] != "behind" or not c["verdict"].startswith("ready"):
            continue
        unrep = [s["version"] for s in lc.get("skips") or [] if not s["reported"]]
        if unrep and lane["role"] != "prod":
            c["questions"].append(f"{lane['lane']} would also take {', '.join(unrep)}, which has no QA summary report")
        if lane["role"] == "qa":
            c["asks"].append(f"{lane['lane']} is QA's lane: ask the QA lead whether it should carry {image} {ver}")
        elif lane["role"] == "daily" and lc["bundle"]:
            sets = " ".join(f'--set "{g}={ver}"' for g in lc["gm"])
            c["commands"].append({"lane": lane["lane"], "line": lane["line"],
                                  "command": f"ela release create --from {lc['bundle']} {sets} --note \"{image} {ver}: QA summary report {c['report']['at'][:10]}\""})
    if c["verdict"] == "ready" and c["questions"]:
        c["verdict"] = "ready-with-questions"
    c["behind"] = sorted({l["lane"] for l in c["lanes"] if l["state"] == "behind" and l["role"] != "prod"})
    c["prod_behind"] = sorted({l["lane"] for l in c["lanes"] if l["state"] == "behind" and l["role"] == "prod"})
    c["rank"] = [{"ready": 0, "ready-with-questions": 1, "read-the-report": 2, "not-ready": 3, "under-test": 4}[c["verdict"]],
                 0 if c["behind"] else 1]
    return c


def collect(a, env):
    gaps = []
    try:
        images = collect_mails(env, a.days)
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
        print(f"mails not read: {str(e)[:200]}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    if a.image:
        images = {k: v for k, v in images.items() if B.norm(k) == B.norm(a.image)}
    for vs in images.values():
        for cell in vs.values():
            for part in ("summary", "daily"):
                cell[part].sort(key=lambda m: m["at"], reverse=True)
        reported = [v for v in vs if vs[v]["summary"]]
        if reported:                                        # the candidate's newest summary is the one read in full
            m = vs[max(reported, key=vtuple)]["summary"][0]
            try:
                m["body"] = B.run_json(["python3", MAIL, *env, "read", m["id"], "--json"], timeout=120).get("body") or ""
            except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
                gaps.append(f"report {m['id']}: {str(e)[:100]}")
    keys = sorted({k.group(0) for vs in images.values() for c in vs.values() for m in c["summary"][:1] for k in KEY_RX.finditer(m.get("body") or "")})
    jira = {}
    for i in range(0, len(keys), 50):
        try:
            got = B.run_json(["python3", JIRA, *env, "jql", f"key in ({','.join(keys[i:i + 50])})", "--limit", "100", "--json"], timeout=300)
            jira.update({x["key"]: x for x in got.get("issues") or []})
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
            gaps.append(f"jira: {str(e)[:120]}")
    lanes = read_lanes(env, gaps)
    pins = constraints(env, gaps)
    cands = sorted((judge(img, vs, lanes, jira, pins) for img, vs in images.items()), key=lambda c: (c["rank"], c["image"]))
    return {"at": now().isoformat(timespec="seconds"), "days": a.days, "candidates": cands,
            "lanes": [{k: v for k, v in l.items() if k != "images"} for l in lanes], "gaps": gaps}


# ── page ────────────────────────────────────────────────────────────────────────────────────────────
VERDICT_WORD = {"ready": "✅ ready", "ready-with-questions": "🟡 ready, questions first", "not-ready": "⛔ not ready",
                "read-the-report": "❔ read the report", "under-test": "· under test"}


def link(key):
    return f"[{key}]({JIRA_BROWSE}{key})"


def keys_linked(text):
    return KEY_RX.sub(lambda m: link(m.group(0)), text or "")


def lane_text(l):
    if l["state"] == "unread":
        return f"{l['lane']} ?"
    if l["state"] == "absent":
        return f"{l['lane']} —"
    return f"{l['lane']} {'/'.join(l.get('have') or [])}" + {"at": " =", "ahead": " ▲", "behind": " ▼", "mixed": " ≠"}.get(l["state"], "")


def lanes_short(c):
    seen, parts = set(), []
    for l in c["lanes"]:
        if l["lane"] not in seen:
            seen.add(l["lane"]); parts.append(lane_text(l))
    return " · ".join(parts)


def promotable(res):
    return [c for c in res["candidates"] if c["verdict"].startswith("ready") and c["behind"]]


def lane_bundles(res):
    """[(lane, command)]: per daily lane, one bundle carrying every `ready` image behind on it (questions keep an image
    out until answered), so a lane moves once rather than once per image."""
    by = {}
    for c in res["candidates"]:
        if c["verdict"] != "ready":
            continue
        for l in c["lanes"]:
            if l["role"] == "daily" and l["state"] == "behind" and l.get("bundle"):
                b = by.setdefault(l["lane"], {"from": l["bundle"], "sets": [], "names": []})
                b["sets"] += [f'--set "{g}={c["version"]}"' for g in l["gm"]]
                b["names"].append(f"{c['image']} {c['version']}")
    return [(lane, f"ela release create --from {b['from']} {' '.join(b['sets'])} --note \"docker services QA reported ready: {', '.join(b['names'])}\"")
            for lane, b in sorted(by.items())]


def render(res, page=False):
    at, ready = res["at"], promotable(res)
    L = ["# Docker candidates", "",
         f"*{at[:10]} {at[11:16]} · QA's docker test reports of the last {res['days']} days against the lanes' GM bundles · "
         f"{len(ready)} promotable now*", ""]
    for lane, cmd in lane_bundles(res):
        L.append(f"**{lane}, one bundle for every ✅ ready image** (a dry run until `--apply`): `{cmd}`")
        L.append("")
    L += ["## Promotable now" + ("" if ready else " — none"), ""]
    for c in ready:
        r = c["report"]
        L += [f"### {c['image']} {c['version']} — {VERDICT_WORD[c['verdict']]}",
              f"- **QA** ({r.get('by') or ''}, {r['at'][:10]}): «{keys_linked(r['conclusion']) or '—'}»",
              f"- **Lanes**: {lanes_short(c)}"]
        tk = [t for t in c["tickets"] if t.get("status")]
        if tk:
            L.append("- **Tickets in the report**: " + "; ".join(
                f"{link(t['key'])} {t.get('priority') or ''} · {t.get('status') or ''}"
                + (f" · blocking: {'是' if t['blocking'] == 'yes' else '否'}" if t["blocking"] else "") for t in tk))
        L += [f"- **Question**: {keys_linked(q)}" for q in c["questions"]]
        L += [f"- **Risk**: {keys_linked(x)}" for x in c["risks"]]
        L += [f"- **Do** ({cmd['lane']}, a dry run until `--apply`): `{cmd['command']}`" for cmd in c["commands"]]
        L += [f"- **Ask**: {x}" for x in c["asks"]]
        L.append("")
    L += ["## Every image", "", "| image | version | verdict | QA said | lanes |", "|---|---|---|---|---|"]
    for c in res["candidates"]:
        r = c["report"] or {}
        said = (f"«{(r.get('conclusion') or '')[:90]}» ({r['at'][5:10]})" if r.get("conclusion") else
                f"daily report {r['at'][5:10]}, no summary yet" if r.get("signal") == "in-progress" else
                f"summary {r['at'][5:10]}, no conclusion found" if r else
                f"released {((c['release'] or {}).get('at') or '')[5:10]}, no report")
        L.append(f"| {c['image']} | {c['version']} | {VERDICT_WORD[c['verdict']]} | {said.replace('|', '/')} | {lanes_short(c) or '—'} |")
    L += ["", "*▼ the lane is behind this version · ▲ ahead · = carries it · ≠ the image's services differ · a word without a "
          "mark is a GM named tag, not comparable · — not in the lane's bundle · ? the lane could not be read. The verdict is ela's reading of QA's own words and the report's blocking "
          "column; the quote is the evidence. Prod moves with its line's promotion, not from here.*"]
    if res["gaps"]:
        L += ["", "*Not read: " + "; ".join(g[:160] for g in res["gaps"]) + ".*"]
    if page:
        L += ["", "*[[lanes|The lanes]]. Generated by `ela docker --page`.*"]
    return "\n".join(L) + "\n"


def morning_lines(res):
    """The morning page's lines: one per promotable candidate; the page holds the rest."""
    return [f"- **{c['image']} {c['version']}** {VERDICT_WORD[c['verdict']]} — behind on {', '.join(c['behind'])}"
            + (f"; {len(c['questions'])} question{'s' if len(c['questions']) != 1 else ''}" if c["questions"] else "")
            + " → [[lanes/docker|Docker candidates]]" for c in promotable(res)]


def main():
    ap = argparse.ArgumentParser(description="docker service candidates: QA's report per image against the lanes' bundles")
    ap.add_argument("--env-file", help="ela's env file")
    ap.add_argument("--days", type=int, default=21, help="how far back to read the mails (default 21)")
    ap.add_argument("--image", help="one image only (tvu_live_transmit)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="keep the result as <reports>/docker/candidates.json")
    ap.add_argument("--page", action="store_true", help="also write <reports>/lanes/docker.md (implies --write)")
    ap.add_argument("--morning", action="store_true", help="the morning page's lines from the written result; no reads")
    a = ap.parse_args()
    if a.image and (a.write or a.page):
        ap.exit(EX_USAGE, "docker.py: --write and --page keep every image; drop --image\n")
    with open(B.SITE, encoding="utf-8") as f:
        s = json.load(f)
    reports = s.get("reports") or os.path.join(s.get("projects", ""), "reports")
    path = os.path.join(reports, "docker", "candidates.json")
    if a.morning:                                           # the morning page tolerates no result yet: no lines
        try:
            with open(path, encoding="utf-8") as f:
                print("\n".join(morning_lines(json.load(f))))
        except (OSError, ValueError):
            pass
        return
    res = collect(a, ["--env-file", a.env_file] if a.env_file else [])
    if a.write or a.page:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    if a.page:
        os.makedirs(os.path.join(reports, "lanes"), exist_ok=True)
        with open(os.path.join(reports, "lanes", "docker.md"), "w", encoding="utf-8") as f:
            f.write(render(res, page=True))
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))


if __name__ == "__main__":
    main()
