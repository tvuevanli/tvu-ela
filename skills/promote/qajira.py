#!/usr/bin/env python3
"""QA's verdict from Jira: the latest QA comment per ticket, its counts, its environment, the tickets it split into.

  qajira.py read <KEY>... [--fresh] [--json]       the verdict per key, as promote shows it
  qajira.py parse <file|->  [--json]               one comment's text: verdict, counts, environment

Why: on 2026-11-09 promote read QA from report mails only. Seven verdicts QA had written in Jira on build 85 were
missed, partial passes (a ⚠️ headline with 3 Pass + 1 Fail) were shown as passes or as fails, and a FAIL that
QA had split into other tickets was shown without them. Jira is the first source; mail stays the second.

A comment counts when its author is a QA person in the roster (team.records, area qa) and it reads as a result:
  pass      ✅ / 已修复 / 已实现 / 验证通过, no Fail count and no open point
  partial   ⚠️ / 遗漏 / 部分 / both Pass and Fail counts / a pass with open points (a 待确认 count, a 说明 or 存在的问题
            line naming what is still open or tracked elsewhere) / unmarked words with a fixed and a broken half
            — shown ⚠ with the counts and the open points, never as a pass
  fail      ❌ / 未修复 / only Fail counts / 依然复现
  accepted  保持现状 / 按 PM 口径 / as designed — QA accepts the current behaviour; the described change does not ship
  n-a       N/A / 无需 QA / 不在 MH 端验证
The environment block (验证环境, a pasted version panel) is proven with envproof.panel: the lane and the versions
the verdict was observed on. Splits: the keys a QA comment names after split / 拆 / 转 / 单独提 / 新建, and the
ticket's Jira links of type Cloners or a split type; each split is read once and its own verdict and status shown.
"""
import argparse, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}-\d{2,6}\b")

PASS_W = re.compile(r"(?i)" + "|".join([r"已修复", r"已实现", r"验证通过", r"测试通过", r"全部通过", r"\bverified\b", r"\ball pass"]))
PARTIAL_W = re.compile("|".join([r"⚠", r"遗漏", r"部分通过", r"部分修复", r"主功能通过但", r"partial"]))
FAIL_W = re.compile("|".join([r"❌", r"未修复", r"依然复现", r"仍然复现", r"still reproduces", r"验证失败", r"不通过"]))
ACCEPT_W = re.compile("|".join([r"保持现状", r"按\s*PM\s*口径", r"as designed", r"按设计", r"不做修改"]))
NA_W = re.compile(r"(?i)" + "|".join([r"\bN/?A\b", r"无需\s*QA", r"不在\s*MH\s*端验证", r"无需验证", r"not applicable"]))
RESULT_HINT = re.compile(r"(?i)" + "|".join([r"验证结果", r"测试结果", r"QA\s*result", r"\d+\s*Pass", r"\d+\s*Fail", r"✅", r"⚠", r"❌", r"N/?A"]))
SPLIT_CTX = re.compile(r"(?i)" + "|".join([r"split", r"拆", r"转到", r"转为", r"单独提", r"新建", r"另提", r"提了", r"clone", r"跟进单", r"新单"]))
COUNT = {"pass": re.compile(r"(?i)(\d+)\s*(?:个\s*)?Pass"), "fail": re.compile(r"(?i)(\d+)\s*(?:个\s*)?Fail"),
         "pending": re.compile(r"(\d+)\s*(?:个\s*)?(?:待确认|Pending|Blocked|待定)")}
OPEN_LINE = re.compile(r"(?i)^\W*(" + "|".join([r"说明", r"存在的问题", r"遗留问题?", r"待确认问题", r"问题", r"open (?:question|point)s?", r"note"]) + r")\s*[:：]")
OPEN_CTX = re.compile(r"(?i)" + "|".join([r"另开", r"跟踪", r"未覆盖", r"未实现", r"仍", r"依然", r"still", r"not covered", r"pending", r"待\s*PM", r"需\s*PM", r"遗漏"]))
POS_W = re.compile("|".join([r"未看到", r"没有再", r"不再出现", r"已正常", r"恢复正常", r"已解决"]))
NEG_W = re.compile("|".join([r"但是", r"还是", r"仍然", r"依然", r"问题", r"不同步", r"很慢", r"卡顿", r"\b卡\b", r"失败"]))
DATE = re.compile(r"(?:" + "|".join(["验证日期", "测试日期", "实测"]) + r")[^0-9]{0,8}(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})")


def headline(text):
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()[:200]
    return ""


def parse(text, key=None):
    """One comment → {verdict, counts, flags, head, env, splits, tested_on} or None when it is no result."""
    t = text or ""
    head = headline(t)
    if not RESULT_HINT.search(t):
        # QA's words with no result marker (MH-3772, 2026-10-23: ordering fixed, still slow): a verdict only when the words carry
        # both a fixed and a still-broken half (partial) or only the broken half with a failure word (fail)
        body = "\n".join(l for l in t.splitlines() if "ENV:" not in l)[:600]
        if POS_W.search(body) and NEG_W.search(body):
            v = "partial"
        elif FAIL_W.search(body):
            v = "fail"
        else:
            return None
        env = None
        if "ENV:" in t:
            import envproof as E  # noqa: E402
            env = E.panel(t)
        return {"verdict": v, "counts": {"pass": 0, "fail": 0, "pending": 0}, "flags": ["QA's words, no result marker"],
                "open_points": [head], "head": head, "env": env, "splits": [], "tested_on": None}
    top = "\n".join(t.splitlines()[:3])
    counts = {k: sum(int(x) for x in rx.findall(top) or rx.findall(t)[:1]) for k, rx in COUNT.items()}
    flags = []
    if NA_W.search(top) and not counts["pass"] and not counts["fail"]:
        v = "n-a"
    elif ACCEPT_W.search(top):
        v = "accepted"
    elif FAIL_W.search(top) and not PASS_W.search(top):
        v = "fail"
    elif PARTIAL_W.search(top) or (counts["pass"] and counts["fail"]):
        v = "partial"
    elif counts["fail"] and not counts["pass"]:
        v = "fail"
    elif PASS_W.search(top) or "✅" in top or (counts["pass"] and not counts["fail"]):
        v = "pass"
    elif FAIL_W.search(t):
        v = "fail"
    else:
        return {"verdict": "unclear", "counts": counts, "flags": ["a result comment no rule reads"], "head": head,
                "env": None, "splits": [], "tested_on": None}
    if counts["pending"]:
        flags.append(f"{counts['pending']} 待确认")
    open_points = [l.strip()[:200] for l in t.splitlines() if OPEN_LINE.match(l.strip()) and OPEN_CTX.search(l)]
    if counts["pending"]:
        open_points.insert(0, f"{counts['pending']} case(s) 待确认")
    if v == "pass" and open_points:
        v = "partial"                                     # ⚠ is "pass with open points": the open points are QA's own words
    m = DATE.search(t)
    tested_on = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
    splits = []
    for ln in t.splitlines():
        if SPLIT_CTX.search(ln):
            splits += [k for k in KEY_RE.findall(ln) if k != key]
    env = None
    if re.search(r"ENV:", t):
        import envproof as E  # noqa: E402
        env = E.panel(t)
    return {"verdict": v, "counts": counts, "flags": flags, "open_points": open_points, "head": head, "env": env,
            "splits": list(dict.fromkeys(splits)), "tested_on": tested_on}


def adf_text(node):
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "hardBreak":
        return "\n"
    inner = adf_text(node.get("content") or [])
    return inner + ("\n" if t in ("paragraph", "heading", "listItem", "tableRow", "codeBlock", "blockquote") else
                    " " if t in ("tableCell", "tableHeader") else "")


def qa_names():
    sys.path.insert(0, os.path.join(SKILLS, "team"))
    try:
        import team as T  # noqa: E402
        roster = T.read_roster(T.records())[1]
    except (SystemExit, Exception):  # noqa: BLE001 — no roster: no QA person, every comment is a non-QA comment
        return set()
    out = set()
    for p in roster:
        if (p.get("area") or "") == "qa":
            for n in (p.get("name"), p.get("jira_name")):
                if n:
                    out.add(str(n).strip().lower())
    return out


def jira(key, env_file=None, fresh=False):
    argv = ["python3", os.path.join(SKILLS, "jira", "jira.py")] + (["--env-file", env_file] if env_file else []) + \
           ["read", key, "--json"] + (["--fresh"] if fresh else [])
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=90)
        return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None
    except (subprocess.TimeoutExpired, ValueError):
        return None


SPLIT_LINK = re.compile(r"(?i)clone|split|拆")


def verdict_of(issue, qa=None, key=None):
    """The latest QA-person comment that reads as a result, with every earlier one kept as history."""
    qa = qa if qa is not None else qa_names()
    key = key or issue.get("key")
    results = []
    for c in issue.get("comments") or []:
        a = c.get("author")
        who = a if isinstance(a, str) else (a or {}).get("displayName") or ""
        if who.strip().lower() not in qa:
            continue
        text = adf_text(c.get("body")) if not isinstance(c.get("body"), str) else c["body"]
        mentioned = set(KEY_RE.findall(text))
        if key and mentioned and key not in mentioned and len(mentioned) > 0 and re.match(r"^\W*" + KEY_RE.pattern, text.strip()):
            continue                                           # a copy of another ticket's report, headed by its key
        p = parse(text, key)
        if p:
            results.append({**p, "who": who, "when": (c.get("created") or "")[:16], "id": c.get("id")})
    f = issue.get("fields") or {}
    links = []
    for l in f.get("issuelinks") or []:
        other = l.get("outwardIssue") or l.get("inwardIssue") or {}
        name = (l.get("type") or {}).get("name") or ""
        if other.get("key"):
            links.append({"type": name, "key": other["key"], "direction": "out" if l.get("outwardIssue") else "in",
                          "status": ((other.get("fields") or {}).get("status") or {}).get("name"),
                          "split": bool(SPLIT_LINK.search(name))})
    latest = results[-1] if results else None
    return {"key": key, "status": (f.get("status") or {}).get("name"), "summary": f.get("summary"),
            "verdict": latest["verdict"] if latest else "none", "latest": latest, "history": results[:-1],
            "links": links}


def read(keys, env_file=None, fresh=False, follow=True):
    qa = qa_names()
    out, seen = {}, set()
    for k in keys:
        iss = jira(k, env_file, fresh)
        if not iss:
            out[k] = {"key": k, "verdict": "unreadable"}
            continue
        v = verdict_of(iss, qa, k)
        if follow:
            split_keys = list(dict.fromkeys(((v.get("latest") or {}).get("splits") or []) +
                                            [s for h in v.get("history") or [] for s in h.get("splits") or []] +
                                            [l["key"] for l in v["links"] if l["split"]]))
            v["splits"] = []
            for sk in split_keys:
                if sk in seen or sk == k:
                    continue
                seen.add(sk)
                si = jira(sk, env_file, fresh)
                sv = verdict_of(si, qa, sk) if si else {"key": sk, "verdict": "unreadable"}
                v["splits"].append({"key": sk, "status": sv.get("status"), "verdict": sv.get("verdict"),
                                    "who": (sv.get("latest") or {}).get("who"), "when": (sv.get("latest") or {}).get("when"),
                                    "summary": sv.get("summary")})
        out[k] = v
    return out


MARK = {"pass": "✅", "accepted": "✅", "partial": "⚠", "fail": "❌", "n-a": "N/A", "none": "⏳", "unclear": "?", "unreadable": "!"}


def line(v):
    """One line as the page shows it: marker, counts, who and when, environment, splits."""
    lt = v.get("latest") or {}
    c = lt.get("counts") or {}
    counts = " + ".join(f"{n} {w}" for w, n in (("Pass", c.get("pass")), ("Fail", c.get("fail")), ("待确认", c.get("pending"))) if n)
    env = lt.get("env") or {}
    where = ""
    if env.get("lane"):
        us = (env.get("versions") or {}).get("unified-streaming")
        where = f" on {env['lane']}" + (f" (UR Caller {us.split()[0]})" if us else "")
    s = f"{MARK.get(v.get('verdict'), '?')} {v.get('verdict')}"
    if lt:
        s += f" — {lt.get('who')} {str(lt.get('when'))[:10]}" + (f": {counts}" if counts else "") + where
    if lt.get("open_points"):
        s += " — open: " + " · ".join(lt["open_points"][:2])
    if v.get("verdict") == "accepted":
        s += " — accepted as-is; the described change does not ship"
    for sp in v.get("splits") or []:
        s += f"; split {sp['key']} {MARK.get(sp['verdict'], '?')} {sp.get('status') or ''}".rstrip()
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read", help="the QA verdict per key, from Jira, with splits followed")
    p.add_argument("keys", nargs="+"); p.add_argument("--fresh", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("parse", help="one comment's text"); p.add_argument("file"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not a.env_file:
        try:
            a.env_file = os.environ.get("ELA_ENV_FILE") or json.load(open(os.path.expanduser("~/.claude/ela/site.json"))).get("env")
        except (OSError, ValueError):
            pass
    if a.cmd == "parse":
        text = sys.stdin.read() if a.file == "-" else open(a.file).read()
        r = parse(text)
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else (r or {}).get("verdict", "no result"))
        return
    out = read(a.keys, a.env_file, a.fresh)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for k, v in out.items():
            print(f"{k:<9} {v.get('status') or '':<12} {line(v)}")


if __name__ == "__main__":
    main()
