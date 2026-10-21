#!/usr/bin/env python3
"""The browser sense: MediaHub opened in headless Chromium as the owner's own session, read-only.
L1: subcommands, --json, stdlib; the driver is browser.js (Playwright, node) beside this file.

  setup [--url U]      install playwright into <runtime>/browser (no root; the system libraries are the owner's
                       `playwright install-deps`), record the product URL in site.json `mediahub_url`
  env [--lane L] [--key K] [--shots D]
                       open the product, read the version panel (every service's ENV and build) and compare it
                       with the release map for the lane: the environment proof a browser result needs. Services the
                       panel does not list but the session reaches through the gateway (the scheduler,
                       tvu-aioc-service, GET /base/version) are read on the same session and recorded beside it —
                       the account's lane by construction, no map entry to match. --shots D keeps version-panel.png,
                       the panel as read. Exit 4 when the
                       panel carries no ENV (the session cookies are stale or missing: `ela login tvu --force`), exit 3
                       when a service of the lane disagrees with the map. --key: the lanes carrying the ticket's fix
                       (`ela fixed-in`, ancestry) are read first; exit 6 when the panel's lane is not one of them —
                       the owner's account sits on a daily or prod lane, and a fix that only reached a QA lane is not
                       testable there
  shot <path> --out F  a screenshot of one product path
  pdf <html> --out F   print a local html page to PDF (the verify report for a ticket attachment)
  run <case.js> [--shots D] [--phase P --state F] [--timeout S]
                       run one case script (exports async ({p, ctx, b, panel, url, shots, phase, state, fakeTime}) =>
                       result) and print its result; a case reads, and never saves unless the owner confirmed that
                       run. A scheduled behaviour is two runs over one state file: create, then observe after the
                       scheduled time; fakeTime(iso) fakes the browser clock for a form or display case

Why a sense at all: a ticket verified in the product is evidence only when the lane and the versions were read in
the same browser run; the gateway routes each service by per-user tag cookies, so a session with the SID alone
lands on the default lane and the panel shows no ENV (MH-2570, 2026-10-21). Exit codes: 0 ok · 2 usage · 3 mismatch ·
4 unproven (no ENV / no cookies) · 5 browser or network failure · 6 the fix is not on the panel's lane.
"""
import argparse, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "release"))
import release as R  # noqa: E402 — the release map, parse_version, vlabel, envs

EX_USAGE, EX_MISMATCH, EX_UNPROVEN, EX_FAIL, EX_ABSENT = 2, 3, 4, 5, 6
SITE = os.path.expanduser("~/.claude/ela/site.json")
PLAYWRIGHT = "playwright@1.64.1"

# What the panel's section titles and lines mean in the release map's slugs (tvu-common-ui top-header).
SECTIONS = {
    "tvu mediahub": {"frontend": "mediahub-frontend", "backend": "mediahub-backend"},
    "unified media": {"frontend": "unified-media-frontend", "backend": "unified-media-backend"},
    "unified resources caller": {"backend": "unified-streaming"},
    "unified resources portal": {"portal": "ur-portal"},
    "unified resources license": {"volumelicense": "volume-license"},
}
def section_key(title):
    """'Unified Resources Portal Service' and 'Unified Resources Portal' are one section."""
    return re.sub(r"\s+service$", "", title.strip().lower())


SECTION_RX = re.compile(r"^(.*?)\s*\(ENV:\s*([^)]*)\)\s*(.*)$")
LINE_RX = re.compile(r"^(frontend|backend)\s*:\s*(\{.*\}|v?\S+(?:\s*build\s*\d+)?)", re.I)
INLINE_RX = re.compile(r"\b(portal|volumelicense)\s+(\S+)")


def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def runtime_dir():
    s = site()
    return s.get("runtime") or os.path.join(s.get("projects") or os.getcwd(), ".ela")


def timezone():
    """The wall clock the page should keep: site.json `timezone`, else the box's /etc/timezone, else the browser's own."""
    tz = site().get("timezone")
    if tz:
        return tz
    try:
        return open("/etc/timezone").read().strip() or None
    except OSError:
        return None


def fix_lanes(env_file, key):
    """(lanes, gaps): the lanes whose build carries the key's fix, by ancestry (ela fixed-in), and the gaps fixed-in
    named — a lane whose build fell outside the fetched Jenkins window, or a host read without a session. A lane in
    the gaps was not judged; it is never read as 'does not carry the fix' (2026-10-21: one read in three answered
    'QA lanes only' for a fix prod-3 had carried since September)."""
    try:
        r = subprocess.run(["python3", os.path.join(os.path.dirname(HERE), "fixedin", "fixedin.py"), "--env-file", env_file or "",
                            "draft", key, "--json"], capture_output=True, text=True, timeout=300)
        recs = json.loads(r.stdout).get("keys") or []
    except (subprocess.TimeoutExpired, ValueError):
        return [], ["fixed-in unread"]
    if not recs:
        return [], ["fixed-in: no record"]
    rec = recs[0]
    lanes = sorted({x["lane"] for x in rec.get("lanes") or [] if x.get("lane")})
    return lanes, list(rec.get("gaps") or [])


def fix_verdict(lane, lanes, gaps=()):
    """The panel's lane against the lanes carrying the fix: None when it is one of them; 'fix lanes unread' when the
    lane sits in fixed-in's gaps (not judged: rerun, exit unproven); else the sentence to stop on (exit absent)."""
    if lane and lane in lanes:
        return None
    unread = [g for g in gaps if (lane and lane in g) or "unread" in g or "no record" in g]
    if unread:
        return f"fix lanes unread for {lane}: {'; '.join(unread)} — the lane's build was not judged; rerun ela browser env, or ela fixed-in draft, before testing"
    if not lanes:
        return "fix lanes unknown: no lane's build was shown to carry the fix (see ela fixed-in)"
    qa_only = all(l.startswith("qa") for l in lanes)
    where = ", ".join(lanes)
    return (f"fix absent: the fix is on QA lanes only ({where}); the panel shows {lane}, a lane whose build does not carry it"
            if qa_only else f"fix absent: the fix is on {where}; the panel shows {lane} — switch the account's bundle and run ela login tvu --force")


def node_path():
    """Where the playwright module lives: the runtime install first, then any npx cache that bundles the same
    chromium build — never a global install, which needs root."""
    cands = [os.path.join(runtime_dir(), "browser", "node_modules")]
    npx = os.path.expanduser("~/.npm/_npx")
    if os.path.isdir(npx):
        for d in sorted(os.listdir(npx)):
            cands.append(os.path.join(npx, d, "node_modules"))
    for c in cands:
        if os.path.isfile(os.path.join(c, "playwright", "package.json")):
            return c
    return None


def lane_suffixes():
    """ENV suffix → lane, read from the release map's own table (tag_suffix_to_lane) rather than retyped."""
    try:
        text = open(os.path.join(site().get("map", ""), "release.yaml"), encoding="utf-8").read()
        m = re.search(r"tag_suffix_to_lane:\s*(\{.*\})", text)
        return json.loads(m.group(1)) if m else {}
    except (OSError, ValueError):
        return {}


def parse_panel(text):
    """Panel text → {sections: [{title, env, lane, services: [{slug, version, parsed}]}], lanes: {lane: count}}."""
    suffixes = lane_suffixes()
    def lane_of(env):
        for suf, lane in sorted(suffixes.items(), key=lambda kv: -len(kv[0])):
            if env.lower().endswith(suf.lower()):
                return lane
        return None
    sections, cur = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for part in re.split(r"\s+·\s+", line):          # "Home (ENV: Production3) · Billing (ENV: billingp1)"
            m = SECTION_RX.match(part)
            if m:
                title, env, tail = m.group(1).strip(), m.group(2).strip(), m.group(3)
                cur = {"title": title, "env": env, "lane": lane_of(env), "services": []}
                sections.append(cur)
                slugs = SECTIONS.get(section_key(title), {})
                for im in INLINE_RX.finditer(tail):
                    slug = slugs.get(im.group(1).lower())
                    if slug:
                        pv = R.parse_version(im.group(2))
                        cur["services"].append({"slug": slug, "version": im.group(2), "parsed": pv})
                continue
            lm = LINE_RX.match(part)
            if lm and cur is not None:
                slugs = SECTIONS.get(section_key(cur["title"]), {})
                if lm.group(2).startswith("{"):            # Backend: { "portal": "1.9.0+89" } — a json object of named parts
                    try:
                        for k, v in json.loads(part.split(":", 1)[1].strip()).items():
                            if slugs.get(k.lower()):
                                cur["services"].append({"slug": slugs[k.lower()], "version": str(v), "parsed": R.parse_version(str(v))})
                    except ValueError:
                        pass
                    continue
                slug = slugs.get(lm.group(1).lower())
                if slug:
                    ver = lm.group(2).strip()
                    cur["services"].append({"slug": slug, "version": ver, "parsed": R.parse_version(ver)})
    lanes = {}
    for s in sections:
        if s["lane"]:
            lanes[s["lane"]] = lanes.get(s["lane"], 0) + 1
    return {"sections": sections, "lanes": lanes, "proven": any(s["env"] for s in sections)}


def compare(parsed, lane, env_file):
    """Each panel service against `release envs --host prod` for the lane: match · differs · unread."""
    out = []
    for s in parsed["sections"]:
        for svc in s["services"]:
            rc, body, err = R_envs(env_file, svc["slug"])
            row = {"slug": svc["slug"], "panel": svc["version"], "panel_lane": s["lane"], "lane": lane, "map": None, "verdict": "unread"}
            if rc == 0:
                hit = next((r for r in body if r.get("lane") == lane), None)
                if hit:
                    row["map"] = hit.get("version")
                    a, b = svc["parsed"], R.parse_version(hit.get("version") or "")
                    row["verdict"] = "match" if (a and b and a[:5] == b[:5]) else "differs"
            elif rc == 4:
                row["verdict"] = "unread: no session (ela login tvu)"
            out.append(row)
    return out


def R_envs(env_file, slug):
    try:
        r = subprocess.run(["python3", os.path.join(os.path.dirname(HERE), "release", "release.py"), "--env-file", env_file or "",
                            "envs", slug, "--host", "prod", "--json"], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return 5, [], "timeout"
    if r.returncode == 0:
        try:
            return 0, [x for x in json.loads(r.stdout).get("rows") or [] if x.get("service") == slug], ""
        except ValueError:
            return 5, [], "not json"
    return r.returncode, [], (r.stderr or r.stdout).strip()[:120]


def node(cmd, *args, timeout=240):
    np = node_path()
    if not np:
        print("playwright is not installed for ela — run: ela browser setup", file=sys.stderr); sys.exit(EX_UNPROVEN)
    url = site().get("mediahub_url")
    if not url:
        print("site.json has no `mediahub_url` — run: ela browser setup --url <product url>", file=sys.stderr); sys.exit(EX_USAGE)
    env = dict(os.environ, NODE_PATH=np)
    tz = timezone()
    if tz:
        env["ELA_TZ"] = tz
    r = subprocess.run(["node", os.path.join(HERE, "browser.js"), cmd, "--url", url, *args], capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        print(f"browser: {(r.stderr or r.stdout).strip()[-300:]}", file=sys.stderr); sys.exit(EX_FAIL)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print("browser: driver printed no json", file=sys.stderr); sys.exit(EX_FAIL)


def cmd_setup(a):
    d = os.path.join(runtime_dir(), "browser"); os.makedirs(d, exist_ok=True)
    if a.url:
        s = site(); s["mediahub_url"] = a.url
        json.dump(s, open(SITE, "w"), indent=2, ensure_ascii=False); print(f"site.json mediahub_url set")
    if node_path() and os.path.isfile(os.path.join(d, "node_modules", "playwright", "package.json")):
        print(f"playwright present at {d}")
    else:
        print(f"installing {PLAYWRIGHT} into {d} (no root)")
        r = subprocess.run(["npm", "install", "--prefix", d, "--no-audit", "--no-fund", PLAYWRIGHT], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print((r.stderr or r.stdout).strip()[-400:], file=sys.stderr); sys.exit(EX_FAIL)
        print("installed")
    r = subprocess.run(["npx", "--prefix", d, "playwright", "install", "chromium"], capture_output=True, text=True, timeout=900)
    print("chromium: " + ("present" if r.returncode == 0 else "install failed: " + (r.stderr or r.stdout).strip()[-200:]))
    chrome = subprocess.run(["bash", "-lc", "ldd $(ls ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | tail -1) | grep -c 'not found' || true"],
                            capture_output=True, text=True).stdout.strip()
    print(f"system libraries missing for chromium: {chrome or '?'}" + ("" if chrome == "0" else " — the owner runs: sudo npx playwright install-deps chromium"))
    if not site().get("mediahub_url"):
        print("mediahub_url not set — pass --url once", file=sys.stderr)


def cmd_env(a):
    lanes, gaps = fix_lanes(a.env_file, a.key) if a.key else ([], [])
    shot = os.path.join(os.path.realpath(a.shots), "version-panel.png") if a.shots else None
    if shot:
        os.makedirs(os.path.dirname(shot), exist_ok=True)
    d = node("env", *(["--shot", shot] if shot else []))
    parsed = parse_panel(d.get("panel") or "")
    res = {"url": d.get("url"), "panel": d.get("panel"), "sections": parsed["sections"], "lanes": parsed["lanes"], "proven": parsed["proven"],
           "lane": a.lane, "compare": [], "verdict": None, "clock": d.get("clock"), "key": a.key, "fix_lanes": lanes, "fix_gaps": gaps,
           "fix_verdict": None, "shot": d.get("shot"), "services": d.get("services") or {}}
    if a.key and not lanes and gaps:
        res["fix_verdict"] = "; ".join(gaps)
    if not parsed["proven"]:
        res["verdict"] = "unproven: the panel names no ENV — the session cookies are stale or missing (ela login tvu --force)"
    else:
        lane = a.lane or (max(parsed["lanes"], key=parsed["lanes"].get) if parsed["lanes"] else None)
        res["lane"] = lane
        if lane:
            res["compare"] = compare(parsed, lane, a.env_file)
            bad = [c for c in res["compare"] if c["verdict"] == "differs" or (c["panel_lane"] and c["panel_lane"] != lane)]
            res["verdict"] = "proven" if not bad else "mismatch: " + ", ".join(f"{c['slug']} panel {c['panel']} ({c['panel_lane']}) vs map {c['map']} ({lane})" for c in bad)
            # services the panel does not list, read through the gateway on the same session: the account's lane by
            # construction, nothing in the map to match, so recorded (or unreachable), never a mismatch
            for slug, v in res["services"].items():
                res["compare"].append({"slug": slug, "panel": v.get("version"), "panel_lane": None, "lane": lane, "map": None,
                                       "verdict": "recorded" if v.get("version") else "unreachable", "via": f"gateway {v.get('path') or ''}".strip()})
            if a.key and res["verdict"] == "proven":
                res["fix_verdict"] = fix_verdict(lane, lanes, gaps)
                if res["fix_verdict"]:
                    res["verdict"] = res["fix_verdict"]
        else:
            res["verdict"] = "proven lane unknown: ENV names map to no lane in release.yaml"
    for s in res["sections"]:
        for svc in s["services"]:
            svc.pop("parsed", None)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"# {res['url']}")
        print(res["panel"] or "(empty panel)")
        print()
        for c in res["compare"]:
            print(f"  {c['slug']:<26} panel {c['panel']:<24} map[{c['lane']}] {str(c['map']):<28} {c['verdict']}")
        if res["clock"]:
            print(f"clock: {res['clock'].get('tz')} {res['clock'].get('now')}")
        if a.key:
            print(f"fix lanes ({a.key}): {', '.join(res['fix_lanes']) or '(none)'}")
        print(f"verdict: {res['verdict']}")
    if res["verdict"].startswith("unproven") or res["verdict"].startswith("fix lanes unread"):
        sys.exit(EX_UNPROVEN)
    if res["verdict"].startswith("mismatch"):
        sys.exit(EX_MISMATCH)
    if res["verdict"].startswith("fix "):
        sys.exit(EX_ABSENT)


def cmd_shot(a):
    d = node("shot", "--out", a.out, *(["--full", "1"] if a.full else []))
    # the product path is appended to the product url by the driver's caller: here the driver takes the full url
    print(json.dumps(d) if a.json else f"screenshot: {d.get('out')}")


def cmd_pdf(a):
    src = os.path.realpath(a.html)
    if not os.path.isfile(src):
        print(f"no such file: {src}", file=sys.stderr); sys.exit(EX_USAGE)
    d = node("pdf", "--in", src, "--out", os.path.realpath(a.out))
    print(json.dumps(d) if a.json else f"pdf: {d.get('out')}")


def cmd_run(a):
    script = os.path.realpath(a.script)
    if not os.path.isfile(script):
        print(f"no such script: {script}", file=sys.stderr); sys.exit(EX_USAGE)
    shots = a.shots or os.path.join(runtime_dir(), "browser", "shots", os.path.splitext(os.path.basename(script))[0])
    extra = []
    if a.phase:
        extra += ["--phase", a.phase]
    if a.state:
        extra += ["--state", os.path.realpath(a.state)]
    d = node("run", "--script", script, "--shots", shots, *extra, timeout=a.timeout)
    if a.json:
        print(json.dumps(d, ensure_ascii=False))
    else:
        print(json.dumps(d.get("result"), ensure_ascii=False, indent=1))
        if d.get("error"):
            print(f"! error: {d['error']}")
        if d.get("page_errors"):
            print(f"! page errors: {'; '.join(d['page_errors'])}")
    if d.get("error"):
        sys.exit(EX_FAIL)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup", help="install playwright into the runtime directory (no root) and record the product url"); p.add_argument("--url")
    p = sub.add_parser("env", help="the version panel, compared with the release map: the environment proof"); p.add_argument("--lane", help="prod-3, prod-8 … (default: the lane the panel names)"); p.add_argument("--key", help="a ticket: its fix must be on the panel's lane (ela fixed-in), else exit 6"); p.add_argument("--shots", help="directory for version-panel.png, the panel as read"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("shot", help="screenshot the product"); p.add_argument("--out", required=True); p.add_argument("--full", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("pdf", help="print a local html page to PDF"); p.add_argument("html"); p.add_argument("--out", required=True); p.add_argument("--json", action="store_true")
    p = sub.add_parser("run", help="run one case script and print its result"); p.add_argument("script"); p.add_argument("--shots"); p.add_argument("--phase", help="create | observe: one script, two runs over --state"); p.add_argument("--state", help="json file the phases share"); p.add_argument("--timeout", type=int, default=240, help="seconds the run may take (default 240)"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"setup": cmd_setup, "env": cmd_env, "shot": cmd_shot, "pdf": cmd_pdf, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
