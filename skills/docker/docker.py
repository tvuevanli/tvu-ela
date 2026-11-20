#!/usr/bin/env python3
"""Media docker services: which image versions can move to the followed lines' lanes, and what each version changed.

    docker.py [--env-file F] [--days 21]              the page as Markdown
    docker.py … --json                                 the result
    docker.py … --image tvu_live_transmit              one image only
    docker.py … --write                                keep it as <reports>/docker/candidates.json
    docker.py … --page                                 also write <reports>/lanes/media-docker-services.md (the vault places it)
    docker.py --morning                                the morning page's lines, from the written result; no reads

A docker service is released by its developer in a mail whose subject names the image
(`docker.tvunetworks.com/<group>/<image>:<version>`, its body the change log) and reported on by QA in a
"Summary/Daily Test Report" mail naming the same image. A lane takes a docker version through a GM bundle, so a lane's
version is the tag its newest bundle carries. The lines followed are one setting, `docker_lines` in the release map
(<elak>/map/release.yaml, read through the published map); without it, the newest followed line. Only the daily and
prod lanes are read: QA's environments can no longer be read, and a QA report is evidence on a version, not a lane.

For each image, every version from the oldest version a lane runs to the newest released is a row: its changes (the
release mail's change log, else the QA report's scope line, else tvu-kb's record of the image, else `changes not
read`), QA's verdict read from its own words (`ready` · `not ready` · `read the report` · `under test` · `no QA
report`), and its mails, each a Gmail link with a clean label. An image can move when its newest ready version is
ahead of a lane; a ready verdict older than READY_STALE days that no lane took is flagged. Daily lanes get one dry-run
bundle command per lane; prod moves through its line's promotion, never from here.
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
ROLES = ("daily", "prod")                                    # QA's environments can no longer be read (2026-11-20)
WINDOW_NOTE = "mail window"
READY_STALE = 14                                            # a ready verdict no lane took after this many days is flagged
GMAIL = "https://mail.google.com/mail/u/0/#all/"
NO_CHANGES = ("\u76ee\u5f55\u91cc\u6ca1\u6709",)                                 # tvu-kb's "no job pushed this image": no record, not a change


def docker_lines():
    """The release lines the page tracks: the release map's `docker_lines` (a list), else the newest followed line."""
    want = R.rmap("docker_lines")
    if isinstance(want, (list, tuple)) and want:
        return [str(x) for x in want]
    if isinstance(want, str) and want.strip():
        return [x.strip() for x in want.split(",") if x.strip()]
    return B.followed_lines()[:1]


def lane_name(lane):
    """A lane by its MediaHub name: Wednesday, Prod 3, Stage."""
    try:
        sys.path.insert(0, os.path.join(SKILLS, "release"))
        import line as LP                                    # noqa: E402
        return LP.mh_name(lane)
    except Exception:                                        # noqa: BLE001
        return lane


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


def read_lanes(env, gaps, lines=None):
    """[{line, role, lane, name, bundle, images|None, error}] for each tracked line's daily and prod lanes."""
    cfgs, cache, out = R.rmap("lines") or {}, {}, []
    for line in lines or docker_lines():
        cfg = cfgs.get(line) or {}
        if not cfg.get("bundle_line") or not cfg.get("lanes"):
            gaps.append(f"line {line}: no lanes or bundle line in the release map")
            continue
        for role in ROLES:
            lane = cfg["lanes"].get(role)
            if not lane:
                continue
            row = {"line": line, "role": role, "lane": lane, "name": lane_name(lane), "bundle": None, "images": None, "error": None}
            try:
                got = B.lane_bundles(env, line, role, "prod", cfg)
                if got:
                    row["bundle"] = {"name": got[0].get("bundleName"), "id": str(got[0].get("bundleId")), "at": R.when(got[0].get("createTime"))}
                    row["images"] = bundle_images(env, got[0], "prod", cache)
                else:
                    row["error"] = "no bundle for this lane"
            except (B.LaneError, subprocess.TimeoutExpired, ValueError, KeyError) as e:
                row["error"] = f"not readable: {str(e).split('{')[0].strip()[:120] or type(e).__name__}"
            if row["error"]:
                gaps.append(f"{row['name']} ({line} {role}): {row['error']}")
            out.append(row)
    return out


def constraints(env, gaps):
    try:
        return B.run_json(["python3", PROMOTE, *env, "constraints", "--json"], timeout=120).get("active") or []
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
        gaps.append(f"standing constraints: {str(e)[:120]}")
        return []


# ── one version: its changes, QA's verdict, its mails ──────────────────────────────────────────────────
CHANGELOG_RX = re.compile(r"(?:change\s*logs?|changelog|\u66f4\u65b0\u5185\u5bb9|\u4fee\u6539\u5185\u5bb9|\u53d8\u66f4\u5185\u5bb9)\**[^\n]{0,40}\n(.+?)"
                          r"(?=\n\s*\n(?!\s*(?:[-*•]|\d+[.、)]))|\n\s*\*?(?:note|cmd|then|for more|you can)\b|\bdocker (?:run|cmd)\b|\bmediabox cmd\b|\Z)",
                          re.I | re.S)
CHANGES_MAX = 240                                           # a table cell: the change log's head, the mail holds the rest
SCOPE_RX = re.compile(r"(?:\u672c\u8f6e\u8303\u56f4|\u6d4b\u8bd5\u8303\u56f4|Scope)\s*[:\uff1a]\s*(.+)")


def change_log(body):
    """The release mail's change log as one line: its items joined, the line breaks of the mail undone."""
    m = CHANGELOG_RX.search(clean(body))
    if not m:
        return None
    items = re.split(r"\n\s*(?=\d+[.、)]|[-*•]\s)", "\n" + m.group(1).strip())
    out = [re.sub(r"^\s*(?:\d+[.、)]|[-*•])\s*", "", " ".join(i.split())) for i in items if i.strip()]
    text = re.sub(r"\*+", "", "; ".join(x for x in out if x)).strip(" ;")   # the mail's bold: on the page only names and targets are bold
    return (text if len(text) <= CHANGES_MAX else text[:CHANGES_MAX].rsplit(" ", 1)[0] + " …") or None


def qa_scope(body):
    m = SCOPE_RX.search(clean(body))
    return " ".join(m.group(1).split())[:200] if m else None


def tvukb_changes(env, image, ver):
    """tvu-kb's record of the image's build, its first line; None when it has none."""
    try:
        got = B.run_json(["python3", os.path.join(SKILLS, "tvukb", "tvukb.py"), "image", f"{image}:{ver}", "--json"], timeout=60)
    except (B.LaneError, subprocess.TimeoutExpired, ValueError):
        return None
    text = (got.get("output") or "").strip()
    if got.get("exit") or not text or any(text.startswith(x) for x in NO_CHANGES):
        return None
    return "tvu-kb: " + " ".join(text.splitlines()[0].split())[:200]


def verdict_of(cell):
    """QA's verdict on one version, read from its summary report's own words: (verdict, words, report mail)."""
    if cell["summary"]:
        m = cell["summary"][0]
        body = m.get("body") or ""
        if not body:
            return "read the report", None, m
        quote = re.sub(r"\s*<[^>\s]+@[^>\s]+>|\*", "", conclusion(body)).strip()
        sig, word = signal(body, quote)
        return {"positive": "ready", "negative": "not ready"}.get(sig, "read the report"), word, m
    if cell["daily"]:
        return "under test", None, cell["daily"][0]
    return "no QA report", None, None


def mail_label(kind, image, ver, m):
    """`QA summary · tvu_live_transmit 1.0.28 · Soffee Shu · 11-18` · `Release mail · mixer 1.0.36 · 11-19`."""
    by = who(m.get("from")) if kind != "Release mail" else None
    return " · ".join(x for x in (kind, f"{image} {ver}", by, (m.get("at") or "")[5:10]) if x)


def mail_link(kind, image, ver, m):
    if not m:
        return None
    return f"[{mail_label(kind, image, ver, m)}]({GMAIL}{m.get('thread') or m.get('id')})"


# ── one image ───────────────────────────────────────────────────────────────────────────────────────
def lane_cell(lane, image):
    """A lane's tags of one image. Its version is the lowest comparable tag (a GM named tag such as `Production2` beside
    it is another service of the image); only named tags: not comparable."""
    if lane["images"] is None:
        return {"state": "unread", "why": lane["error"]}
    tags = lane["images"].get(image)
    if not tags:
        return {"state": "absent"}
    have = sorted({t for _, t in tags}, key=vtuple)
    vers = [t for t in have if B.is_version(t)]
    cell = {"gm": [g for g, t in tags if B.is_version(t)] or [g for g, _ in tags], "have": have, "versions": vers}
    cell["state"] = "named" if not vers else "mixed" if len({vtuple(t) for t in vers}) > 1 else "at"
    return cell


def image_record(image, versions, lanes, jira, pins, today, changes=None):
    """One image: its lanes, one row per version from the oldest lane version to the newest, the version that can move."""
    lane_rows = []
    for lane in lanes:
        lc = lane_cell(lane, image)
        lane_rows.append(dict(lc, line=lane["line"], role=lane["role"], lane=lane["lane"], name=lane["name"],
                              bundle=(lane["bundle"] or {}).get("name")))
    comparable = [l for l in lane_rows if l["state"] in ("at", "mixed")]
    for l in comparable:
        l["version"] = l["versions"][0]                        # the lowest: a move must bring every service of it up
    floor = min((vtuple(l["version"]) for l in comparable), default=None)
    every = {**{l["version"]: None for l in comparable}, **{v: v for v in versions}}
    keyed = {}
    for v in every:                                            # v1.0.19 and 1.0.19 are one version
        keyed.setdefault(vtuple(v), v if v in versions else keyed.get(vtuple(v), v))
    order = sorted(keyed.values(), key=vtuple, reverse=True)
    rows = []
    for v in order:
        if floor is not None and vtuple(v) < floor:
            continue
        cell = versions.get(v) or {"release": None, "summary": [], "daily": []}
        verdict, word, rep = verdict_of(cell)
        rel = cell["release"]
        ch = (changes or {}).get(v)
        if ch is None:
            ch = (change_log((rel or {}).get("body") or "") or qa_scope((cell["summary"][0] if cell["summary"] else {}).get("body") or ""))
        on = [l["name"] for l in comparable if vtuple(l["version"]) == vtuple(v)]
        mailed = bool(cell["release"] or cell["summary"] or cell["daily"])
        if not mailed:                                         # a lane's version older than the window: nothing to read here
            verdict = f"before the {WINDOW_NOTE}"
        rows.append({"version": v, "released": (rel or {}).get("at"), "changes": ch, "verdict": verdict, "word": word,
                     "qa_at": (rep or {}).get("at") if verdict not in ("no QA report",) else None,
                     "qa_by": who((rep or {}).get("from")) if rep else None,
                     "mails": [x for x in (mail_link("QA summary" if cell["summary"] else "QA daily", image, v, rep) if rep else None,
                                           mail_link("Release mail", image, v, rel) if rel else None) if x],
                     "lanes": on, "body": None})
    newest = rows[0]["version"] if rows else None
    target = next((r for r in rows if r["verdict"] == "ready"), None)
    behind = [l for l in comparable if target and vtuple(l["version"]) < vtuple(target["version"])]
    c = {"image": image, "lanes": lane_rows, "rows": rows, "newest": newest, "version": (target or (rows[0] if rows else {})).get("version"),
         "target": target["version"] if target else None, "behind": [l["lane"] for l in behind if l["role"] != "prod"],
         "prod_behind": [l["lane"] for l in behind if l["role"] == "prod"], "commands": [], "questions": [], "risks": []}
    rep = (versions.get(c["version"]) or {}).get("summary") or []
    if rep:
        body = rep[0].get("body") or ""
        c["report"] = {"id": rep[0]["id"], "at": rep[0]["at"], "by": who(rep[0].get("from")), "subject": rep[0].get("subject")}
        blocking = []
        for t in ticket_rows(body):
            j = jira.get(t["key"]) or {}
            if t["blocking"] == "yes" and (j.get("status") or "").lower() not in ("done", "closed", "resolved"):
                blocking.append(t["key"])
        if blocking:
            c["risks"].append("QA marks as blocking: " + ", ".join(blocking))
        b = breaking(body)
        if b:
            c["questions"].append(f"a breaking change another layer must absorb: {b}")
    else:
        c["report"] = None
    for p in pins:
        if image.lower() in json.dumps(p, ensure_ascii=False).lower():
            c["questions"].append(f"a standing constraint names this image: {p.get('what') or p.get('id')}")
    if target:
        age = (today - datetime.date.fromisoformat(target["qa_at"][:10])).days if target.get("qa_at") else 0
        c["stale"] = target["qa_at"][5:10] if behind and age > READY_STALE else None
        for l in behind:
            if l["role"] == "daily" and l["bundle"]:
                sets = " ".join(f'--set "{g}={target["version"]}"' for g in l["gm"])
                c["commands"].append({"lane": l["lane"], "name": l["name"], "line": l["line"],
                                      "command": f"ela release create --from {l['bundle']} {sets} --note \"{image} {target['version']}: QA summary {target['qa_at'][:10]}\""})
    c["verdict"] = "ready" if target and behind else (rows[0]["verdict"] if rows else "no QA report")
    c["can_move"] = bool(target and behind)
    c["waiting"] = waiting_reason(c) if not c["can_move"] else None
    c["gm"] = sorted({g for l in lane_rows for g in l.get("gm") or []})
    return c


def waiting_reason(c):
    """Why an image whose newest version no lane runs cannot move, one clause; None when every lane is current."""
    if not c["rows"]:
        return None
    top = c["rows"][0]
    lanes = [l for l in c["lanes"] if l["state"] in ("at", "mixed")]
    if top["lanes"] and len(top["lanes"]) == len(lanes):
        return None                                            # every lane runs the newest
    if not lanes:
        named = sorted({t for l in c["lanes"] if l["state"] == "named" for t in l["have"]})
        if named:
            return f"the lanes carry the GM tag {', '.join(named)}, not a version; {top['version']}: {top['verdict']}"
        return None if all(l["state"] == "absent" for l in c["lanes"]) else "no lane could be read"
    if top["verdict"] == "under test":
        return f"{top['version']} under test (QA daily report {(top['qa_at'] or '')[5:10]})"
    if top["verdict"] == "no QA report":
        return f"{top['version']} released {(top['released'] or '')[5:10]}, no QA report yet"
    if top["verdict"] == "not ready":
        return f"{top['version']}: QA says not ready ({top['word'] or 'its report'})" + (f"; {c['risks'][0]}" if c["risks"] else "")
    if top["verdict"] == "read the report":
        return f"{top['version']}: QA's report states no verdict ela can read"
    return None


def collect(a, env):
    gaps = []
    try:
        images = collect_mails(env, a.days)
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
        print(f"mails not read: {str(e)[:200]}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    if a.image:
        images = {k: v for k, v in images.items() if B.norm(k) == B.norm(a.image)}
    lanes = read_lanes(env, gaps)
    for image, vs in images.items():
        for cell in vs.values():
            for part in ("summary", "daily"):
                cell[part].sort(key=lambda m: m["at"], reverse=True)
            for m in [cell["release"]] + cell["summary"][:1]:  # the change log and QA's words are read in full
                if not m:
                    continue
                try:
                    m["body"] = B.run_json(["python3", MAIL, *env, "read", m["id"], "--json"], timeout=120).get("body") or ""
                except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
                    gaps.append(f"mail {m['id']}: {str(e)[:100]}")
    keys = sorted({k.group(0) for vs in images.values() for c in vs.values() for m in c["summary"][:1] for k in KEY_RX.finditer(m.get("body") or "")})
    jira = {}
    for i in range(0, len(keys), 50):
        try:
            got = B.run_json(["python3", JIRA, *env, "jql", f"key in ({','.join(keys[i:i + 50])})", "--limit", "100", "--json"], timeout=300)
            jira.update({x["key"]: x for x in got.get("issues") or []})
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as e:
            gaps.append(f"jira: {str(e)[:120]}")
    pins = constraints(env, gaps)
    today = now().date()
    cands = []
    for img, vs in images.items():
        c = image_record(img, vs, lanes, jira, pins, today)
        for r in c["rows"]:                                    # no change log or scope line: tvu-kb, else said plainly
            if not r["changes"]:
                r["changes"] = tvukb_changes(env, img, r["version"]) or "changes not read"
        cands.append(c)
    cands.sort(key=lambda c: (not c["can_move"], c["waiting"] is None, c["image"]))
    return {"at": now().isoformat(timespec="seconds"), "days": a.days, "lines": docker_lines(), "candidates": cands,
            "lanes": [{k: v for k, v in l.items() if k != "images"} for l in lanes], "gaps": gaps}


# ── page ────────────────────────────────────────────────────────────────────────────────────────────
ALIASES = ("mds", "docker", "Docker candidates")             # the old page's names: links and the switcher keep working


def link(key):
    return f"[{key}]({JIRA_BROWSE}{key})"


def keys_linked(text):
    return KEY_RX.sub(lambda m: link(m.group(0)), text or "")


def cell(text):
    return (text or "").replace("|", "/").replace("\n", " ")


def lanes_from(c):
    """`Wednesday 1.0.27 / Prod 3 1.0.27`: each lane behind the target, by its MediaHub name."""
    return " / ".join(f"{l['name']} {l['version']}" for l in c["lanes"] if l["lane"] in c["behind"] + c["prod_behind"])


def can_move_line(c):
    t = next(r for r in c["rows"] if r["version"] == c["target"])
    qa = f"QA ready {t['qa_at'][5:10]}" + (f" · ready since {c['stale']}, not moved" if c.get("stale") else "")
    return " · ".join(x for x in (f"**{c['image']}**", f"{lanes_from(c)} → **{c['target']}**", qa, t["mails"][0] if t["mails"] else None) if x)


def fold_title(c):
    lanes = " · ".join(f"{l['name']} {'/'.join(l['have'])}" if l.get("have") else f"{l['name']} —" for l in c["lanes"]
                       if l["state"] != "unread")
    return f"{c['image']} · {lanes} · newest {c['newest']}"


def render(res, page=False):
    at = res["at"]
    lines = ", ".join(res.get("lines") or [])
    moving = [c for c in res["candidates"] if c.get("can_move")]
    waiting = [c for c in res["candidates"] if not c.get("can_move") and c.get("waiting")]
    reads = "; ".join(f"{l['name']} bundle {(l.get('bundle') or {}).get('name') or '—'} {((l.get('bundle') or {}).get('at') or '')[5:16]}"
                      for l in res["lanes"] if l.get("bundle"))
    L = []
    if page:
        L += ["---", 'aliases: [' + ", ".join(f'"{a}"' for a in ALIASES) + "]", "---", ""]
    L += [f"# Media docker services · {lines}", "",
          f"*{at[:10]} {at[11:16]} · mails of the last {res['days']} days · lanes: {reads or 'none read'}*", ""]
    L += ["## Can move", ""] + ([f"- {can_move_line(c)}" for c in moving] or ["Nothing can move: every lane runs the newest ready version."])
    L += ["", "## Waiting", ""] + ([f"- **{c['image']}** · {c['waiting']}" for c in waiting] or ["Nothing waits."])
    L += ["", "## Images", ""]
    for c in res["candidates"]:
        if not c["rows"]:
            continue
        L += [f"> [!note]- {fold_title(c)}", "> | version | date | changes | QA | mail |", "> |---|---|---|---|---|"]
        for r in c["rows"]:
            v = f"**{r['version']}**" if r["version"] == c.get("target") else r["version"]
            v += f" ← {', '.join(r['lanes'])}" if r["lanes"] else ""
            qa = r["verdict"] + (f" {r['qa_at'][5:10]}" if r.get("qa_at") else "")
            L.append(f"> | {v} | {(r['released'] or '')[5:10] or '—'} | {cell(keys_linked(r['changes']))} | {qa} | {cell(' · '.join(r['mails'])) or '—'} |")
        for q in c["questions"] + c["risks"]:
            L.append(f"> ")
            L.append(f"> {keys_linked(q)}")
        L.append("")
    cmds = lane_bundles(res)
    L += ["## Commands", "", f"> [!note]- {len(cmds)} bundle command{'s' if len(cmds) != 1 else ''} (each a dry run until `--apply`; prod moves with its line's promotion)"]
    L += [f"> **{name}** ({line}): `{cmd}`" + "\n>" for name, line, cmd in cmds] or ["> None: no daily lane is behind a ready version."]
    if res["gaps"]:
        L += ["", "*Not read: " + "; ".join(g[:160] for g in res["gaps"]) + ".*"]
    if page:
        L += ["", "*[[lanes|The lanes]]. Generated by `ela docker --page`.*"]
    return "\n".join(L) + "\n"


def lane_bundles(res):
    """[(lane name, line, command)]: per daily lane, one bundle carrying every image that can move there, so a lane
    moves once rather than once per image."""
    by = {}
    for c in res["candidates"]:
        for cmd in c.get("commands") or []:
            b = by.setdefault(cmd["lane"], {"name": cmd["name"], "line": cmd["line"], "from": None, "sets": [], "names": []})
            b["from"] = b["from"] or re.search(r"--from (\S+)", cmd["command"]).group(1)
            b["sets"] += re.findall(r'--set "[^"]+"', cmd["command"])
            b["names"].append(f"{c['image']} {c['target']}")
    return [(b["name"], b["line"], f"ela release create --from {b['from']} {' '.join(b['sets'])} --note \"docker services QA reported ready: {', '.join(b['names'])}\"")
            for _, b in sorted(by.items())]


def morning_lines(res):
    """The morning page's lines: one per image that can move; the page holds the rest."""
    return [f"- **{c['image']}** → **{c['target']}** on {', '.join(lane_name(l) for l in c['behind'] + c['prod_behind'])}"
            + (f" · ready since {c['stale']}, not moved" if c.get("stale") else "")
            + f" → [[{PAGE[:-3]}|Media docker services]]" for c in res.get("candidates") or [] if c.get("can_move")]


PAGE = "releases/media-docker-services.md"
SOURCE = ("lanes", "media-docker-services.md")


def main():
    ap = argparse.ArgumentParser(description="media docker services: which image versions can move, and what each changed")
    ap.add_argument("--env-file", help="ela's env file")
    ap.add_argument("--days", type=int, default=21, help="how far back to read the mails (default 21)")
    ap.add_argument("--image", help="one image only (tvu_live_transmit)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="keep the result as <reports>/docker/candidates.json")
    ap.add_argument("--page", action="store_true", help="also write <reports>/lanes/media-docker-services.md (implies --write)")
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
            json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    if a.page:
        os.makedirs(os.path.join(reports, SOURCE[0]), exist_ok=True)
        with open(os.path.join(reports, *SOURCE), "w", encoding="utf-8") as f:
            f.write(render(res, page=True))
        old = os.path.join(reports, "lanes", "docker.md")
        if os.path.exists(old):                             # the old source: kept beside, never read again
            os.replace(old, old + ".retired")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str) if a.json else render(res))


if __name__ == "__main__":
    main()
