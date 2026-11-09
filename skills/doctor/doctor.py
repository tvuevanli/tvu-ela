#!/usr/bin/env python3
"""ela doctor — does everything of ela work on this machine? One read-only pass, one line per check.

    doctor.py [--env-file F]                       every section
    doctor.py … --only site,units,timers,senses,facts
    doctor.py … --timeout 60                       seconds per sense probe (they run in parallel)
    doctor.py … --json

Sections, in order:
  site     site.json roots resolve, the env file is mode 600, the plugin tree's uncommitted paths
  units    the long-running user services (the Slack runner, Helm) are active; Helm answers HTTP
  timers   every ela-* user timer is enabled with a next run, and its service's last result did not fail
  senses   the /ela:setup §3 probes: each source read once, live (never the fact store)
  facts    `ela facts status` per source: stale, or a gap recorded by the last pass
Each line is ✓ (ok), ! (warn: a state, not a fault) or ✗ (fail), the failures with the next action.
Read-only: every probe is a read; nothing is written, retried or refreshed. A credential value is never
printed: any env-file value that appears in a probe's output is masked.
Exit codes: 0 no ✗ · 1 at least one ✗ · 2 usage.
"""
import argparse, concurrent.futures as cf, json, os, signal, ssl, stat, subprocess, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
ROOT = os.path.dirname(SKILLS)
SITE = os.path.expanduser("~/.claude/ela/site.json")
SECTIONS = ("site", "units", "timers", "senses", "facts")
OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✓", WARN: "!", FAIL: "✗"}
EX_USAGE = 2

ROOTS = ("projects", "code", "work", "runtime", "lab", "elak", "map", "map_source", "published", "reports", "vault")
UNITS = ("ela-runner-slack.service", "helm-ops.service")
HELM_URL = "https://127.0.0.1:7654"

# name → (script, argv, {exit code: (status, detail, action)}, the keys an auth failure points at)
SENSES = {
    "jira":       ("jira", ["jql", "project = MH ORDER BY updated DESC", "--limit", "1", "--fresh"], {}, "JIRA_TOKEN"),
    "slack":      ("slack", ["whoami"], {}, "SLACK_BOT_TOKEN"),
    "mail":       ("mail", ["search", "newer_than:2d", "--limit", "1", "--fresh"], {}, "GOOGLE_TOKEN_FILE"),
    "kb":         ("kb", ["search", "MediaHub", "--limit", "1"], {}, "OUTLINE_TOKEN"),
    "confluence": ("confluence", ["spaces"], {}, "CONFLUENCE_TOKEN"),
    "gdoc":       ("gdoc", ["list", "--limit", "1"], {}, "GOOGLE_TOKEN_FILE"),
    "figma":      ("figma", ["me"], {}, "FIGMA_TOKEN"),
    "ur":         ("graph", ["graphs", "--pages", "1", "--limit", "1"],
                   {3: (OK, "answers (no graphs of mine)", "")}, "UR_ACCESS_KEY"),
    "jenkins":    ("release", ["builds", "mediahub-backend", "--limit", "1", "--fresh"], {}, ""),
    "lanes":      ("release", ["envs", "--fresh"], {}, "TVUTEST_ACCOUNT"),   # QA lanes: the tvutest login
    "sentry":     ("sentry", ["projects"],
                   {4: (WARN, "no token yet (a state, not a fault)", "ela secret SENTRY_TOKEN")}, "SENTRY_TOKEN"),
    "browser":    ("browser", ["env"],
                   {4: (FAIL, "cookies missing", "ela login tvu --force")}, ""),
}


def check(section, name, status, detail="", action=""):
    return {"section": section, "name": name, "status": status, "detail": detail, "action": action}


# ── secrets: read the env file only to mask its values ──────────────────────────────────────────────

def env_values(path):
    vals = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                v = line.split("=", 1)[1].strip().strip("'\"")
                if len(v) >= 8:
                    vals.append(v)
    except OSError:
        pass
    return sorted(set(vals), key=len, reverse=True)


def mask(text, secrets):
    for v in secrets:
        text = text.replace(v, "***")
    return text


def last_line(text, width=160):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    s = lines[-1] if lines else ""
    return s if len(s) <= width else s[:width - 1] + "…"


# ── classification (pure; tests/test_doctor_offline.py) ─────────────────────────────────────────────

def classify(name, rc, out, err, secrets=(), timeout=None):
    """A sense probe's result as (status, detail, action). rc None = timed out."""
    _, _, special, key = SENSES[name]
    tail = mask(last_line(err) or last_line(out), secrets)
    if rc is None:
        return FAIL, f"no answer within {timeout:g}s", "is the network/VPN up? run the probe alone to see where it hangs"
    if rc in special:
        st, detail, action = special[rc]
        return st, detail, action
    if rc == 0:
        return OK, "answers", ""
    if rc == 4:
        act = f"ela secret {key} (or /ela:setup §2)" if key else "/ela:setup §2"
        if name == "lanes":
            act = "the QA userservice refuses the tvutest account: ask QA to check it, or ela secret TVUTEST_ACCOUNT for another"
        return FAIL, f"auth refused — {tail}" if tail else "auth refused", act
    if rc == 5:
        return FAIL, f"remote error — {tail}" if tail else "remote error", "the source is down or unreachable; retry later"
    if rc == 3:
        return FAIL, f"not found — {tail}" if tail else "not found", "run the probe alone"
    return FAIL, f"exit {rc} — {tail}" if tail else f"exit {rc}", "run the probe alone"


def classify_fact(src, rec):
    """One `facts status` source as a check."""
    if not rec.get("at"):
        return check("facts", src, WARN, "never read", f"ela facts refresh --source {src}")
    gap = rec.get("gap")
    if gap:
        why = gap.get("why") or "a gap"
        part = " (partial)" if gap.get("partial") else ""
        return check("facts", src, WARN, f"gap{part}: {why} — pass at {rec['at'][:16]}",
                     f"see the probe of that source; then ela facts refresh --source {src}")
    if not rec.get("fresh"):
        return check("facts", src, WARN, f"stale — last pass {rec['at'][:16]}", f"ela facts refresh --source {src}")
    return check("facts", src, OK, f"fresh — {rec['at'][:16]}")


def classify_timer(name, props, svc):
    """A timer's `systemctl show` properties and its service's, as a check."""
    if props.get("UnitFileState") not in ("enabled", "static", "linked"):
        return check("timers", name, FAIL, f"not enabled ({props.get('UnitFileState') or '?'})",
                     f"systemctl --user enable --now {name}")
    if props.get("ActiveState") != "active":
        return check("timers", name, FAIL, f"enabled but {props.get('ActiveState')}", f"systemctl --user start {name}")
    nxt = props.get("NextElapseUSecRealtime") or ""
    mono = props.get("NextElapseUSecMonotonic") or ""
    if not nxt and mono not in ("", "0", "infinity"):              # OnUnitActiveSec timers: a monotonic next run
        nxt = "in " + mono.split(".")[0] + ("s" if "." in mono else "")
    if not nxt or nxt in ("n/a", "0"):
        return check("timers", name, FAIL, "no next run", f"systemctl --user restart {name}")
    service = props.get("Unit") or name.replace(".timer", ".service")
    result = svc.get("Result") or "success"
    if result != "success":
        return check("timers", name, FAIL, f"next {nxt}; last {service} result: {result}",
                     f"journalctl --user -u {service} -n 50")
    return check("timers", name, OK, f"next {nxt}")


# ── sections ────────────────────────────────────────────────────────────────────────────────────────

def sh(argv, timeout=15):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "", str(e)


def section_site(s, env_file):
    out = []
    for k in ROOTS:
        p = s.get(k)
        if not p:
            continue
        p = os.path.expanduser(p)
        if os.path.exists(p):
            out.append(check("site", k, OK, p))
        else:
            hint = "is the drive mounted?" if p.startswith("/mnt/") else "fix the path in site.json (/ela:setup §1)"
            out.append(check("site", k, FAIL, f"{p} does not resolve", hint))
    try:
        mode = stat.S_IMODE(os.stat(env_file).st_mode)
        out.append(check("site", "env file", OK, "mode 600") if mode == 0o600 else
                   check("site", "env file", FAIL, f"mode {mode:o}", f"chmod 600 {env_file}"))
    except OSError:
        out.append(check("site", "env file", FAIL, f"{env_file} missing", "/ela:setup §2"))
    rc, so, _ = sh(["git", "-C", ROOT, "status", "--porcelain"])
    if rc != 0:
        out.append(check("site", "plugin tree", WARN, "not a git checkout"))
    else:
        paths = [l[3:] for l in so.splitlines() if l.strip()]
        out.append(check("site", "plugin tree", OK, "clean") if not paths else
                   check("site", "plugin tree", WARN, f"{len(paths)} uncommitted: " + ", ".join(paths[:4])
                         + (" …" if len(paths) > 4 else ""), "commit or drop them (another session may own them)"))
    return out


def section_units(s):
    out = []
    for u in UNITS:
        rc, so, _ = sh(["systemctl", "--user", "is-active", u])
        state = (so or "").strip() or "unknown"
        out.append(check("units", u, OK, "active") if state == "active" else
                   check("units", u, FAIL, state, f"systemctl --user restart {u}; journalctl --user -u {u} -n 50"))
    url = s.get("helm_local_url") or HELM_URL
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE        # loopback, Helm's own certificate
    try:
        with urllib.request.urlopen(url, timeout=5, context=ctx) as r:
            out.append(check("units", "helm http", OK, f"{url} → {r.status}"))
    except urllib.error.HTTPError as e:                                 # an HTTP answer is an answer
        out.append(check("units", "helm http", OK, f"{url} → {e.code}"))
    except Exception as e:
        out.append(check("units", "helm http", FAIL, f"{url}: {e.__class__.__name__}",
                         "systemctl --user status helm-ops.service"))
    return out


def show(unit, props):
    rc, so, _ = sh(["systemctl", "--user", "show", unit, "-p", ",".join(props)])
    return dict(l.split("=", 1) for l in so.splitlines() if "=" in l) if rc == 0 else {}


def section_timers():
    rc, so, _ = sh(["systemctl", "--user", "list-unit-files", "ela-*.timer", "--no-legend", "--no-pager"])
    timers = sorted({l.split()[0] for l in so.splitlines() if l.strip()}) if rc == 0 else []
    if not timers:
        return [check("timers", "ela-*.timer", FAIL, "none installed", "/ela:setup §3b; the runner's install")]
    out = []
    for t in timers:
        props = show(t, ("UnitFileState", "ActiveState", "NextElapseUSecRealtime", "NextElapseUSecMonotonic", "Unit"))
        svc = show(props.get("Unit") or t.replace(".timer", ".service"), ("Result",))
        out.append(classify_timer(t, props, svc))
    return out


def probe(name, env_file, timeout, secrets):
    script, argv, _, _ = SENSES[name]
    cmd = [sys.executable, os.path.join(SKILLS, script, f"{script}.py"), "--env-file", env_file, *argv]
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                             text=True, start_new_session=True)
    except OSError as e:
        return check("senses", name, FAIL, str(e), "")
    try:
        so, se = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)                           # the browser's Chromium goes with it
        except OSError:
            pass
        p.communicate()
        so, se, rc = "", "", None
    st, detail, action = classify(name, rc, so, se, secrets, timeout)
    c = check("senses", name, st, detail, action)
    c["seconds"] = round(time.time() - t0, 1)
    return c


def section_senses(env_file, timeout, secrets):
    with cf.ThreadPoolExecutor(max_workers=len(SENSES)) as ex:
        futs = {n: ex.submit(probe, n, env_file, timeout, secrets) for n in SENSES}
        return [futs[n].result() for n in SENSES]


def section_facts(env_file, secrets):
    rc, so, se = sh([sys.executable, os.path.join(SKILLS, "facts", "facts.py"), "--env-file", env_file,
                     "status", "--json"], timeout=30)
    try:
        data = json.loads(so)
    except (ValueError, TypeError):
        return [check("facts", "status", FAIL, mask(last_line(se) or f"exit {rc}", secrets), "ela facts status")]
    return [classify_fact(src, rec) for src, rec in (data.get("sources") or {}).items()]


# ── output ──────────────────────────────────────────────────────────────────────────────────────────

def summary(checks):
    n = {k: sum(1 for c in checks if c["status"] == k) for k in (OK, WARN, FAIL)}
    bad = [f"{c['section']} {c['name']}" for c in checks if c["status"] == FAIL]
    line = f"ela doctor: {n[OK]} ok · {n[WARN]} warn · {n[FAIL]} fail"
    return n, line + (" — " + ", ".join(bad) if bad else "")


def render(checks):
    width = max((len(c["name"]) for c in checks), default=8)
    sec = None
    for c in checks:
        if c["section"] != sec:
            sec = c["section"]
            print(("\n" if sec != checks[0]["section"] else "") + sec)
        line = f"  {MARK[c['status']]} {c['name']:<{width}}  {c['detail']}"
        if c["status"] != OK and c.get("action"):
            line += f"  → {c['action']}"
        print(line)
    print("\n" + summary(checks)[1])


def main():
    ap = argparse.ArgumentParser(description="ela's self-check: site, units, timers, senses, facts. Read-only.")
    ap.add_argument("--env-file")
    ap.add_argument("--only", help="comma list of " + ",".join(SECTIONS))
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds per sense probe (default 60)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    only = [x.strip() for x in (a.only or ",".join(SECTIONS)).split(",") if x.strip()]
    unknown = [x for x in only if x not in SECTIONS]
    if unknown:
        print(f"doctor: unknown section(s) {', '.join(unknown)}; choose from {','.join(SECTIONS)}", file=sys.stderr)
        sys.exit(EX_USAGE)
    try:
        s = json.load(open(SITE))
    except (OSError, ValueError):
        s = {}
    env_file = os.path.expanduser(a.env_file or s.get("env") or "~/.claude/ela/.env")
    secrets = env_values(env_file)

    checks = []
    if not s:
        checks.append(check("site", "site.json", FAIL, f"{SITE} missing or unreadable", "/ela:setup §1"))
    with cf.ThreadPoolExecutor(max_workers=2) as ex:                  # the slow section starts first
        senses = ex.submit(section_senses, env_file, a.timeout, secrets) if "senses" in only else None
        if "site" in only and s:
            checks += section_site(s, env_file)
        if "units" in only:
            checks += section_units(s)
        if "timers" in only:
            checks += section_timers()
        if senses:
            checks += senses.result()
    if "facts" in only:
        checks += section_facts(env_file, secrets)

    n, line = summary(checks)
    if a.json:
        print(json.dumps({"checks": checks, "counts": n, "summary": line}, ensure_ascii=False, indent=1))
    else:
        render(checks)
    sys.exit(1 if n[FAIL] else 0)


if __name__ == "__main__":
    main()
