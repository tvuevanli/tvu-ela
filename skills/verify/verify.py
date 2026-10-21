#!/usr/bin/env python3
"""The verification report, rendered from a run directory — deterministic; the verdicts in it are the skill's.
L1: stdlib only.

  report --key MH-2570 --run <dir> [--out <reports>/verify/<KEY>-<date>/index.html] [--single F] [--json]
        --single F  also write one self-contained HTML (screenshots embedded) for the ticket's attachment

The run directory is what /ela:verify leaves behind:
  ticket.json   {key, summary, type, status, parent, asked, added: [..], commits: [{sha, subject}], later: [{key, what}]}
  plan.json     [{id, kind: black|provenance|precondition, goal, source, expected, superseded_by}]
  env.json      `ela browser env --json` (panel, lane, compare, verdict)
  cases.json    `ela browser run --json` (result: [{id, action, observed, result, shot}], page_errors)
  ancestry.json {lane, build, sha, descends, commits: [..]}            (optional)
  technique.json {stack: [..], procedure: [..], notes: [..]}           (optional)
  shots/*.png   screenshots the case script took; copied beside the page as img/

The page under `<reports>` is the owner's reading copy; the `--single` file is the QA record attached to the ticket
(`jira attach`), written for colleagues: facts only — lane, versions, goals, cases, screenshots — no narrative of how
the run went. Nothing here links to claude.ai. Exit codes: 0 ok · 2 usage.
"""
import argparse, base64, datetime, html, json, os, shutil, subprocess, sys

EX_USAGE, EX_FAIL = 2, 5
HERE = os.path.dirname(os.path.realpath(__file__))
RESULT_CLASS = {"pass": "pass", "fail": "fail", "changed": "warn", "n/a": "na", "na": "na", "unproven": "fail", "match": "pass", "differs": "fail"}


def site():
    try:
        return json.load(open(os.path.expanduser("~/.claude/ela/site.json")))
    except (OSError, ValueError):
        return {}


def load(run, name, default):
    p = os.path.join(run, name)
    if not os.path.isfile(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except ValueError:
        print(f"{name}: not json", file=sys.stderr); sys.exit(EX_USAGE)


def esc(x):
    return html.escape(str(x if x is not None else ""))


def pill(result):
    r = str(result or "").lower()
    return f'<span class="pill {RESULT_CLASS.get(r, "na")}">{esc(result or "—").upper()}</span>'


def clock_line(env):
    """The browser's clock and, when the gate ran with a ticket, the lanes whose build carries its fix."""
    clock = env.get("clock") or {}
    if not clock and not env.get("key"):
        return ""
    parts = []
    if clock:
        parts.append(f"Browser clock: {clock.get('tz') or '?'} at {clock.get('now') or '?'}.")
    if env.get("key"):
        parts.append(f"Lanes whose build carries the fix ({env.get('key')}): {', '.join(env.get('fix_lanes') or []) or 'none shown'}.")
    if env.get("fix_verdict"):
        parts.append(str(env["fix_verdict"]))
    return "<p>" + esc(" ".join(parts)) + "</p>"


def overall(cases, env):
    if not env or not str(env.get("verdict", "")).startswith("proven"):
        return "unproven"
    rs = [str(c.get("result", "")).lower() for c in cases]
    if any(r == "fail" for r in rs):
        return "fail"
    if rs and all(r in ("pass", "n/a", "na") for r in rs):
        return "pass" if any(r == "pass" for r in rs) else "unproven"
    return "unproven"


def details(title, body, print_mode):
    """A technical section: collapsed on screen, open and page-broken in print, so the readable part is what a reader
    sees first and the technical record is there for whoever needs it."""
    return f'<details class="tech"{" open" if print_mode else ""}><summary><h2>{esc(title)}</h2></summary><section>{body}</section></details>'


def service_row(c):
    return (f"<tr><td>{esc(c.get('slug'))}</td><td class=num>{esc(c.get('panel'))}</td><td class=num>{esc(c.get('map') or '—')}</td>"
            f"<td>{pill(c.get('verdict'))}</td></tr>")


def render(key, run, out_dir, embed=False, print_mode=False):
    t, plan, env, cases_out = load(run, "ticket.json", {}), load(run, "plan.json", []), load(run, "env.json", {}), load(run, "cases.json", {})
    anc, tech = load(run, "ancestry.json", {}), load(run, "technique.json", {})
    cases = (cases_out or {}).get("result") or []
    if isinstance(cases, dict):
        cases = cases.get("cases") or []
    today = datetime.date.today().isoformat()
    verdict = overall(cases, env)
    fe = next((c for c in env.get("compare") or [] if c.get("slug") == "mediahub-frontend"), {})
    be = next((c for c in env.get("compare") or [] if c.get("slug") == "mediahub-backend"), {})
    lane_env = next((s.get("env") for s in env.get("sections") or [] if s.get("lane") == env.get("lane")), env.get("lane"))
    # screenshots: copied beside the page
    img_dir = os.path.join(out_dir, "img"); os.makedirs(img_dir, exist_ok=True)
    shots = os.path.join(run, "shots")
    copied = {}
    if os.path.isdir(shots):
        for root, _, files in os.walk(shots):
            for f in sorted(files):
                if f.lower().endswith(".png"):
                    shutil.copy2(os.path.join(root, f), os.path.join(img_dir, f)); copied[f] = "img/" + f
    def shot_of(c):
        s = c.get("shot") or ""
        name = os.path.basename(s)
        rel = copied.get(name) or (copied.get(f"{c.get('id','').lower()}.png"))
        if rel and embed:
            data = base64.b64encode(open(os.path.join(out_dir, rel), "rb").read()).decode()
            return f"data:image/png;base64,{data}"
        return rel
    verdict_word = {"pass": "requirement met", "fail": "requirement not met", "unproven": "environment not proven — results discarded"}[verdict]
    H = []
    H.append(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(key)} Browser Test</title>
<style>
:root{{--bg:#f6f7f5;--surface:#fff;--fg:#1d2420;--muted:#5d6862;--line:#dde2de;--accent:#23874a;--pass:#1f7a43;--pass-bg:#e3f3e8;--warn:#8a5a00;--warn-bg:#fbefd6;--na:#4f5a62;--na-bg:#e8ecef;--fail:#a3261c;--fail-bg:#f8e1de;--code:#eef1ee;color-scheme:light}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#121614;--surface:#1a201d;--fg:#e4e9e5;--muted:#9aa59f;--line:#2c3430;--accent:#4cc27a;--pass:#6fd497;--pass-bg:#18362a;--warn:#f0c060;--warn-bg:#3a2f14;--na:#b3bec6;--na-bg:#262e33;--fail:#f08a80;--fail-bg:#3d1f1c;--code:#222a26;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#121614;--surface:#1a201d;--fg:#e4e9e5;--muted:#9aa59f;--line:#2c3430;--accent:#4cc27a;--pass:#6fd497;--pass-bg:#18362a;--warn:#f0c060;--warn-bg:#3a2f14;--na:#b3bec6;--na-bg:#262e33;--fail:#f08a80;--fail-bg:#3d1f1c;--code:#222a26;color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 "IBM Plex Sans","Segoe UI",system-ui,sans-serif}}
.wrap{{max-width:920px;margin:0 auto;padding:40px 16px 72px;display:flex;flex-direction:column;gap:40px}}
h1,h2{{margin:0;line-height:1.2}}h1{{font-size:2rem}}h2{{font-size:1.25rem}}p{{margin:0;max-width:70ch}}section{{display:flex;flex-direction:column;gap:12px;min-width:0}}
.eyebrow{{font:500 .75rem/1 ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}
code,.num,.panel{{font-family:ui-monospace,"IBM Plex Mono",Menlo,monospace;font-size:.88em}}code{{background:var(--code);padding:1px 5px;border-radius:3px}}
.verdict{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:6px;overflow:hidden}}
.verdict>div{{background:var(--surface);padding:12px 14px;display:flex;flex-direction:column;gap:4px;min-width:0}}.verdict .k{{font:500 .72rem/1 ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}}.verdict .v{{font-weight:600;overflow-wrap:anywhere}}
.pill{{display:inline-block;font:600 .72rem/1 ui-monospace,monospace;letter-spacing:.05em;padding:4px 7px;border-radius:3px;white-space:nowrap}}.pass{{color:var(--pass);background:var(--pass-bg)}}.warn{{color:var(--warn);background:var(--warn-bg)}}.na{{color:var(--na);background:var(--na-bg)}}.fail{{color:var(--fail);background:var(--fail-bg)}}
.scroll{{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--surface)}}table{{border-collapse:collapse;width:100%;min-width:560px;font-size:.92rem}}th,td{{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--line)}}th{{font:500 .72rem/1.3 ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}}tr:last-child td{{border-bottom:0}}td.num{{white-space:nowrap}}
.panel{{background:var(--code);border-radius:6px;padding:14px 16px;overflow-x:auto;white-space:pre;margin:0;line-height:1.55}}
figure{{margin:0;display:flex;flex-direction:column;gap:8px}}figure img{{width:100%;height:auto;border:1px solid var(--line);border-radius:6px;display:block}}figcaption{{font-size:.85rem;color:var(--muted)}}
.shots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px}}@media (max-width:420px){{.shots{{grid-template-columns:1fr}}}}
details.tech{{border:1px solid var(--line);border-radius:6px;background:var(--surface);padding:10px 14px}}details.tech summary{{cursor:pointer;list-style:none}}details.tech summary h2{{display:inline;font-size:1.05rem}}details.tech summary::before{{content:"▸ ";color:var(--muted)}}details.tech[open] summary::before{{content:"▾ "}}details.tech>section{{margin-top:12px}}
.appendix{{page-break-before:always;break-before:page}}@media print{{body{{background:#fff;color:#000}}details.tech{{border:none;padding:0}}details.tech summary::before{{content:""}}.shots{{grid-template-columns:1fr 1fr}}}}
.note{{border-left:3px solid var(--warn);background:var(--warn-bg);padding:10px 14px;border-radius:0 6px 6px 0;max-width:72ch}}ul,ol{{margin:0;padding-left:1.3em;display:flex;flex-direction:column;gap:6px;max-width:72ch}}
</style></head><body><div class="wrap">
<header style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">QA record · MediaHub · {today}</span><h1>{esc(key)} Browser Test</h1>
<p>{esc(t.get('asked') or t.get('summary') or '')} The test ran in a real browser against the product, on the lane named in the version panel below, as the owner's own login. Nothing was saved.</p>
<div class="verdict"><div><span class="k">Verdict</span><span class="v">{pill(verdict)} {esc(verdict_word)}</span></div><div><span class="k">Environment</span><span class="v num">{esc(lane_env or '—')}</span></div><div><span class="k">Frontend</span><span class="v num">{esc(fe.get('panel') or '—')}</span></div><div><span class="k">Backend</span><span class="v num">{esc(be.get('panel') or '—')}</span></div></div></header>""")
    env_words = (f"The test ran on {env.get('lane') or 'an unnamed lane'}, frontend {fe.get('panel') or '?'} and backend {be.get('panel') or '?'}, "
                 + ("which match the release map for that lane." if env.get("verdict") == "proven" else f"and the environment gate said: {env.get('verdict') or 'not run'}."))
    H.append(f'<section><h2>What was tested</h2><p>{esc(env_words)}</p>')
    crows_front = "".join(f"<tr><td class=num>{esc(c.get('id'))}</td><td>{esc(c.get('action'))}</td><td>{esc(c.get('observed'))}</td><td>{pill(c.get('result'))}</td></tr>" for c in cases)
    H.append(f'<div class="scroll"><table><tr><th>Step</th><th>What was done</th><th>What was seen</th><th>Result</th></tr>{crows_front}</table></div></section>')
    H.append(f'<section class="appendix"><h2>Appendix: technical record</h2><p>Selectors, builds, the version panel, commit ancestry and the method: for whoever needs to repeat or audit the run.</p></section>')
    # ticket
    rows = [f"<tr><th>Key</th><td><a href=\"https://tvunetworks.atlassian.net/browse/{esc(key)}\">{esc(key)}</a> · {esc(t.get('type') or '')} · {esc(t.get('status') or '')}" + (f" · parent {esc(t['parent'])}" if t.get("parent") else "") + "</td></tr>"]
    if t.get("asked"): rows.append(f"<tr><th>Asked</th><td>{esc(t['asked'])}</td></tr>")
    for a in t.get("added") or []: rows.append(f"<tr><th>Added in comments</th><td>{esc(a)}</td></tr>")
    if t.get("commits"): rows.append("<tr><th>Commits</th><td>" + " · ".join(f"<code>{esc(c.get('sha','')[:8])}</code> {esc(c.get('subject',''))}" for c in t["commits"]) + "</td></tr>")
    for l in t.get("later") or []: rows.append(f"<tr><th>Later change</th><td>{esc(l.get('key'))}: {esc(l.get('what'))}</td></tr>")
    H.append(details('Target ticket', '<div class="scroll"><table>' + "".join(rows) + "</table></div>", print_mode))
    # goals
    if plan:
        by_id = {str(c.get("id")): c for c in cases}
        grows = "".join(f"<tr><td class=num>{esc(g.get('id'))}</td><td>{esc(g.get('kind') or 'black')}</td><td>{esc(g.get('goal'))}</td><td>{esc(g.get('source'))}" + (f" · superseded by {esc(g['superseded_by'])}" if g.get("superseded_by") else "") + f"</td><td>{pill((by_id.get(str(g.get('id'))) or {}).get('result') or g.get('result'))}</td></tr>" for g in plan)
        H.append(details('Goals', f'''<p>Expectations come from the requirement, never from the code. Black-box cases observe the product as a user sees it; provenance and precondition checks prove the build under test carries the fix and the lane holds what it depends on. The default plan is the tech lead\'s acceptance of the ticket\'s claim, not QA\'s matrix.</p><div class="scroll"><table><tr><th>#</th><th>Kind</th><th>Goal</th><th>Source</th><th>Result</th></tr>{grows}</table></div>''', print_mode))
    # environment proof
    srows = "".join(service_row(c) for c in env.get("compare") or [])
    anc_row = f"<tr><td>Build {esc(anc.get('build'))} sha descends from the fix commits</td><td class=num>{esc((anc.get('sha') or '')[:8])}</td><td>{pill('pass' if anc.get('descends') else 'fail')}</td></tr>" if anc else ""
    panel_img = next((v for k, v in copied.items() if "panel" in k.lower() or "env" in k.lower()), None)
    if panel_img and embed:
        panel_img = "data:image/png;base64," + base64.b64encode(open(os.path.join(out_dir, panel_img), "rb").read()).decode()
    H.append(details('Environment proof', f'<p>A result counts only when the version panel (hover the MediaHub logo) names the lane and the versions in the same browser run; every service the panel lists is recorded and compared with the release map for <code>{esc(env.get("lane") or "?")}</code>. Verdict of the gate: <b>{esc(env.get("verdict") or "not run")}</b>.</p>'
             f'<pre class="panel">{esc(env.get("panel") or "(no panel)")}</pre>'
             + clock_line(env) +
             f'<div class="scroll"><table><tr><th>Service</th><th>Panel</th><th>Release map</th><th></th></tr>{srows}{anc_row}</table></div>'
             + (f'<figure><img src="{panel_img}" alt="The version panel captured in the same browser run"><figcaption>Version panel, same run as the cases.</figcaption></figure>' if panel_img else "") + "", print_mode))
    # results
    crows = "".join(f"<tr><td class=num>{esc(c.get('id'))}</td><td>{esc(c.get('action'))}</td><td>{esc(c.get('observed'))}</td><td>{pill(c.get('result'))}</td></tr>" for c in cases)
    figs = "".join(f'<figure><img src="{shot_of(c)}" alt="{esc(c.get("id"))}: {esc(c.get("action"))}"><figcaption>{esc(c.get("id"))} · {esc(c.get("observed"))}</figcaption></figure>' for c in cases if shot_of(c))
    notes = "".join(f"<div class=note><p><b>For the ticket owner.</b> {esc(n)}</p></div>" for n in (tech.get("notes") or []))
    errs = (cases_out or {}).get("page_errors") or []
    H.append(details('Screenshots and notes', notes + (f'<p class="eyebrow">page errors: {esc("; ".join(errs))}</p>' if errs else "") + f'<div class="shots">{figs}</div>', print_mode))
    # technique
    if tech.get("stack") or tech.get("procedure"):
        H.append(details('Test technique', ("<h3>Stack</h3><ul>" + "".join(f"<li>{esc(x)}</li>" for x in tech.get("stack") or []) + "</ul>" if tech.get("stack") else "")
                 + ("<h3>Procedure</h3><ol>" + "".join(f"<li>{esc(x)}</li>" for x in tech.get("procedure") or []) + "</ol>" if tech.get("procedure") else ""), print_mode))
    H.append(f'<footer style="color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:14px">QA record generated on {today} from a read-only browser run against the lane named above; the cases and screenshots are from one run.</footer></div></body></html>')
    return "\n".join(H), verdict


def cmd_report(a):
    run = os.path.realpath(a.run)
    if not os.path.isdir(run):
        print(f"no run directory {run}", file=sys.stderr); sys.exit(EX_USAGE)
    key = a.key.upper()
    out = a.out or os.path.join(site().get("projects") or os.getcwd(), "reports", "verify", f"{key}-{datetime.date.today().isoformat()}", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    page, verdict = render(key, run, os.path.dirname(out))
    open(out, "w", encoding="utf-8").write(page)
    res = {"key": key, "out": out, "verdict": verdict, "bytes": len(page.encode())}
    if a.single:
        single, _ = render(key, run, os.path.dirname(out), embed=True)
        open(a.single, "w", encoding="utf-8").write(single)
        res["single"] = a.single; res["single_bytes"] = len(single.encode())
    if a.pdf:
        printable = os.path.join(os.path.dirname(out), f"{key}-print.html")
        open(printable, "w", encoding="utf-8").write(render(key, run, os.path.dirname(out), embed=True, print_mode=True)[0])
        r = subprocess.run(["python3", os.path.join(os.path.dirname(HERE), "browser", "browser.py"), "pdf", printable, "--out", a.pdf], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"pdf failed: {(r.stderr or r.stdout).strip()[-300:]}", file=sys.stderr); sys.exit(EX_FAIL)
        res["pdf"] = a.pdf; res["pdf_bytes"] = os.path.getsize(a.pdf)
    if a.json:
        print(json.dumps(res))
    else:
        print(f"{key}: {verdict} — report written to {out} ({res['bytes']} bytes)" + (f"; self-contained copy: {a.single} ({res['single_bytes']} bytes)" if a.single else "")
              + (f"; pdf for the ticket: {a.pdf} ({res['pdf_bytes']} bytes)" if a.pdf else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="accepted for the adapter's sake; this script reads no credential")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report", help="render the report page from a run directory"); p.add_argument("--key", required=True); p.add_argument("--run", required=True); p.add_argument("--out"); p.add_argument("--pdf", help="also print the self-contained page to this PDF through the browser sense: the readable part first, the technical record as an appendix"); p.add_argument("--single", help="also write one self-contained HTML for the ticket's attachment"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
