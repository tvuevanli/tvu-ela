#!/usr/bin/env python3
"""The verification report, rendered from a run directory — deterministic; the verdicts in it are the skill's.
L1: stdlib only.

  report --key MH-2570 --run <dir> [--out <reports>/verify/<KEY>-<date>/index.html] [--single F] [--json]
        --single F  also write one self-contained HTML (screenshots embedded) for the ticket's attachment
  plan --key MH-2570 --plan plan.json --lane qa-cn3 --version "2.2.121 build 176" [--minutes N] [--json]
        the plan gate as a note: <reports>/verify/plans/<date>-<KEY>.md (the vault's to-read verify-plan note) and
        the plan beside it as .json, which the owner's `run` starts; nothing opens a browser here

The run directory is what /ela:verify leaves behind:
  ticket.json   {key, summary, type, status, parent, asked, added: [..], commits: [{sha, subject}], later: [{key, what}]}
  plan.json     [{id, kind: black|guard|timed|provenance|precondition, goal, source, expected, superseded_by}]
  env.json      `ela browser env --json` (panel, lane, compare, verdict)
  cases.json    `ela browser run --json` (result: [{id, action, observed, result, shot}], page_errors)
  ancestry.json {lane, build, sha, descends, commits: [..]}            (optional)
  technique.json {stack: [..], procedure: [..], notes: [..]}           (optional)
  shots/*.png   screenshots the case script took; copied beside the page as img/

The page under `<reports>` is the owner's reading copy; the `--single` file is the QA record attached to the ticket
(`jira attach`), written for colleagues: facts only — lane, versions, goals, cases, screenshots — no narrative of how
the run went. Nothing here links to claude.ai. Exit codes: 0 ok · 2 usage.
"""
import argparse, base64, datetime, html, json, os, re, shutil, subprocess, sys

EX_USAGE, EX_FAIL = 2, 5
HERE = os.path.dirname(os.path.realpath(__file__))
RESULT_CLASS = {"pass": "pass", "fail": "fail", "changed": "warn", "blocked": "warn", "n/a": "na", "na": "na", "unproven": "fail", "match": "pass", "differs": "fail"}


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


def tidy_version(v):
    """A panel line like v3.0.36build1912026-10-20 09:45:35 has no spaces; put them back for a reader."""
    v = str(v or "")
    v = re.sub(r"(?<=\d)(build\d+)", r" \1", v)
    v = re.sub(r"(build\d+)(\d{4}-\d{2}-\d{2})", r"\1 \2", v)
    return v


def plain_seen(c, limit=150):
    """What a reader sees in the front table: the case's own `seen` sentence when the script wrote one, else the
    observed text cut before its first machine part (a json object, a request path, a list). The full observed text
    stays in the appendix run log."""
    if c.get("seen"):
        return str(c["seen"])
    o = str(c.get("observed") or "")
    cut = re.split(r"\s*(?:\{|\bPOST\b|\bGET\b|\[\"|;\s*calls:|\(cards\b)", o, maxsplit=1)[0].strip(" ;:,")
    if len(cut) > limit:
        cut = cut[:limit].rsplit(" ", 1)[0] + "…"
    return cut or "(see run log)"


def is_fixture(c, plan_by_id):
    """Setup and cleanup steps (C1, T0, kinds setup/cleanup/fixture) are not checks of the requirement."""
    cid = str(c.get("id") or "")
    kind = str((plan_by_id.get(cid) or {}).get("kind") or "")
    return kind in ("setup", "cleanup", "fixture") or re.match(r"^(C\d+|T0)$", cid) is not None


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


def overall(cases, env, plan=None):
    """The ticket's verdict. A `guard` goal (a behaviour the ticket says is unchanged, kept as a regression check) that
    could not be observed is reported in its row but does not decide the verdict: the asked behaviour was observed or
    it was not, and a guard blocked by the fixture (an HLS source with no receiving-side PID table, MH-3365,
    2026-10-22) must not turn a verified ticket into "not observable"."""
    if not env or not str(env.get("verdict", "")).startswith("proven"):
        return "unproven"
    kinds = {str(g.get("id")): str(g.get("kind") or "") for g in (plan or [])}
    rs = [(str(c.get("result", "")).lower(), kinds.get(str(c.get("id")), str(c.get("kind") or ""))) for c in cases]
    if any(r == "fail" for r, _ in rs):
        return "fail"
    if any(r == "blocked" and k != "guard" for r, k in rs):
        return "blocked"                         # the lane is proven, a precondition the account lacks stopped a case
    decisive = [r for r, k in rs if not (r == "blocked" and k == "guard")]
    if decisive and all(r in ("pass", "n/a", "na") for r in decisive):
        return "pass" if any(r == "pass" for r in decisive) else "unproven"
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
    verdict = overall(cases, env, plan)
    # The services named up front are the ticket's (its Fixed In slug, e.g. unified-media-frontend) and that service's
    # backend; mediahub-frontend/backend only when the ticket names none the panel lists. A record that quotes the
    # product's frontend for a ticket fixed in another service proves the wrong build (MH-3722, 2026-10-22).
    compare = env.get("compare") or []
    fixed_slug = str((t.get("fixed_in") or "")).split("@")[0].strip()
    fe_slug = fixed_slug if any(c.get("slug") == fixed_slug for c in compare) else "mediahub-frontend"
    be_slug = fe_slug.replace("frontend", "backend") if any(c.get("slug") == fe_slug.replace("frontend", "backend") for c in compare) else "mediahub-backend"
    fe = next((c for c in compare if c.get("slug") == fe_slug), {})
    be = next((c for c in compare if c.get("slug") == be_slug), {})
    fe_name = f"{fe_slug} {tidy_version(fe.get('panel'))}" if fe.get("panel") else "?"
    be_name = f"{be_slug} {tidy_version(be.get('panel'))}" if be.get("panel") else "?"
    # Who was logged in and whether the run wrote: the QA deployment is read with ela's own test account, and a plan
    # with cleanup goals created its own objects — the boilerplate must not claim the owner's login or a read-only run.
    login_words = "as the QA test account" if env.get("host") == "qa" else "as the owner's own login"
    wrote = any(str(g.get("kind")) in ("cleanup", "write") for g in plan) or any(str(c.get("id", "")).startswith("C") for c in cases)
    # technique.json may state exactly what the run saved (a cleanup step can be a restored setting, not a created object)
    saved_words = str(tech.get("saved") or ("The run created its own test objects and deleted them afterwards; nothing else was saved." if wrote else "Nothing was saved."))
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
    verdict_word = {"pass": "requirement met", "fail": "requirement not met", "blocked": "not observable on this account — environment proven, a precondition missing",
                    "unproven": "environment not proven — results discarded"}[verdict]
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
<p>{esc(t.get('asked') or t.get('summary') or '')} The test ran in a real browser against the product, on the lane named in the version panel below, {login_words}. {saved_words}</p>
<div class="verdict"><div><span class="k">Verdict</span><span class="v">{pill(verdict)} {esc(verdict_word)}</span></div><div><span class="k">Environment</span><span class="v num">{esc(lane_env or '—')}</span></div><div><span class="k">Frontend</span><span class="v num">{esc(tidy_version(fe.get('panel')) or '—')}</span></div><div><span class="k">Backend</span><span class="v num">{esc(tidy_version(be.get('panel')) or '—')}</span></div></div></header>""")
    env_words = (f"The test ran on {env.get('lane') or 'an unnamed lane'}, frontend {fe_name} and backend {be_name}, "
                 + ("which match the release map for that lane." if env.get("verdict") == "proven" else f"and the environment gate said: {env.get('verdict') or 'not run'}."))
    H.append(f'<section><h2>What was tested</h2><p>{esc(env_words)}</p>')
    plan_by_id = {str(g.get("id")): g for g in plan}
    checks = [c for c in cases if not is_fixture(c, plan_by_id)]
    fixtures = [c for c in cases if is_fixture(c, plan_by_id)]
    def check_words(c):
        g = plan_by_id.get(str(c.get("id")) or "") or {}
        return g.get("goal") or c.get("action") or ""
    crows_front = "".join(f"<tr><td class=num>{esc(c.get('id'))}</td><td>{esc(check_words(c))}</td><td>{esc(plain_seen(c))}</td><td>{pill(c.get('result'))}</td></tr>" for c in checks)
    H.append(f'<div class="scroll"><table><tr><th>Check</th><th>What the ticket asks</th><th>What was seen</th><th>Result</th></tr>{crows_front}</table></div>'
             + (f'<p class="eyebrow">{len(fixtures)} setup and cleanup steps ran around these checks; they are in the run log below.</p>' if fixtures else "") + '</section>')
    if not embed and not print_mode:
        write_markdown(out_dir, key, t, verdict, verdict_word, lane_env, fe, be, env_words, login_words, saved_words,
                       checks, fixtures, check_words, shot_of)
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
    # the gate's own screenshot (ela browser env --shots: version-panel.png), never a case shot whose name happens to say "panel"
    panel_img = (next((v for k, v in copied.items() if k.lower() in ("version-panel.png", "panel.png", "env.png")), None)
                 or next((v for k, v in copied.items() if k.lower().startswith(("version-panel", "env-", "panel-"))), None))
    if panel_img and embed:
        panel_img = "data:image/png;base64," + base64.b64encode(open(os.path.join(out_dir, panel_img), "rb").read()).decode()
    H.append(details('Environment proof', f'<p>A result counts only when the version panel (hover the MediaHub logo) names the lane and the versions in the same browser run; every service the panel lists is recorded and compared with the release map for <code>{esc(env.get("lane") or "?")}</code>. Verdict of the gate: <b>{esc(env.get("verdict") or "not run")}</b>.</p>'
             f'<pre class="panel">{esc(env.get("panel") or "(no panel)")}</pre>'
             + clock_line(env) +
             f'<div class="scroll"><table><tr><th>Service</th><th>Panel</th><th>Release map</th><th></th></tr>{srows}{anc_row}</table></div>'
             + (f'<figure><img src="{panel_img}" alt="The version panel captured in the same browser run"><figcaption>Version panel, same run as the cases.</figcaption></figure>' if panel_img else "") + "", print_mode))
    # results: the run log holds every step as the script reported it, machine text included
    crows = "".join(f"<tr><td class=num>{esc(c.get('id'))}</td><td>{esc(c.get('action'))}</td><td>{esc(c.get('observed'))}</td><td>{pill(c.get('result'))}</td></tr>" for c in cases)
    H.append(details('Run log', '<div class="scroll"><table><tr><th>Step</th><th>What was done</th><th>What was seen, as recorded</th><th>Result</th></tr>' + crows + '</table></div>', print_mode))
    figs = "".join(f'<figure><img src="{shot_of(c)}" alt="{esc(c.get("id"))}: {esc(c.get("action"))}"><figcaption>{esc(c.get("id"))} · {esc(c.get("observed"))}</figcaption></figure>' for c in cases if shot_of(c))
    notes = "".join(f"<div class=note><p><b>For the ticket owner.</b> {esc(n)}</p></div>" for n in (tech.get("notes") or []))
    errs = (cases_out or {}).get("page_errors") or []
    H.append(details('Screenshots and notes', notes + (f'<p class="eyebrow">page errors: {esc("; ".join(errs))}</p>' if errs else "") + f'<div class="shots">{figs}</div>', print_mode))
    # technique
    if tech.get("stack") or tech.get("procedure"):
        H.append(details('Test technique', ("<h3>Stack</h3><ul>" + "".join(f"<li>{esc(x)}</li>" for x in tech.get("stack") or []) + "</ul>" if tech.get("stack") else "")
                 + ("<h3>Procedure</h3><ol>" + "".join(f"<li>{esc(x)}</li>" for x in tech.get("procedure") or []) + "</ol>" if tech.get("procedure") else ""), print_mode))
    H.append(f'<footer style="color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:14px">QA record generated on {today} from one browser run against the lane named above, {login_words}; {saved_words[0].lower() + saved_words[1:]} The cases and screenshots are from that run.</footer></div></body></html>')
    return "\n".join(H), verdict


CALLOUT = {"pass": "success", "fail": "failure", "blocked": "warning", "unproven": "info"}


def md_cell(x):
    return str(x if x is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def write_markdown(out_dir, key, t, verdict, verdict_word, lane_env, fe, be, env_words, login_words, saved_words,
                   checks, fixtures, check_words, shot_of):
    """report.md beside index.html: the same record for the owner's vault, rendered from the same run data, so it
    costs no model call. The title carries the verdict and the ticket's summary; then what was asked, one line of
    environment, the checks with the result first, and the screenshots: a failed or blocked check's open, the rest
    folded. The HTML stays the full record (appendix, ancestry, run log) and the PDF its printable copy."""
    dated = re.search(r"\d{4}-\d{2}-\d{2}", os.path.basename(os.path.normpath(out_dir)))
    day = dated.group(0) if dated else datetime.date.today().isoformat()      # the run's day, not the render's
    summary = md_cell(t.get("summary") or "")
    lane = re.search(r"^The test ran on ([^,]+),", env_words)
    L = [f"# {key} · {verdict.upper()}" + (f" on {lane.group(1)}" if lane else "") + (f" · {summary}" if summary else ""), "",
         f"> [!{CALLOUT.get(verdict, 'info')}] {verdict.upper()}: {verdict_word}", ""]
    if t.get("asked"):
        L += [md_cell(t["asked"]), ""]
    gate = "builds match the release map" if "match the release map" in env_words else env_words.rsplit(" and ", 1)[-1].rstrip(".")
    env = " · ".join(x for x in ((lane.group(1) if lane else "") + (f" ({md_cell(lane_env)})" if lane_env else ""),
                                  f"frontend {md_cell(tidy_version(fe.get('panel')))}" if fe.get("panel") else "",
                                  f"backend {md_cell(tidy_version(be.get('panel')))}" if be.get("panel") else "", gate, f"run {day}") if x.strip())
    L += [f"*{env}*", "", f"The browser ran {login_words}. {saved_words}", "",
          "Technical record (version panel, build ancestry, run log): `index.html` beside this file.", "",
          "## Checks", "", "| result | check | what the ticket asks | what was seen |", "|---|---|---|---|"]
    def mark(c):
        r = str(c.get("result") or "—").upper()
        return f"**{r}**" if r in ("FAIL", "BLOCKED") else r
    L += [f"| {mark(c)} | {md_cell(c.get('id'))} | {md_cell(check_words(c))} | {md_cell(plain_seen(c))} |" for c in checks]
    if fixtures:
        L += ["", f"{len(fixtures)} setup and cleanup steps ran around these checks; they are in the full record."]
    shots = [(c, shot_of(c)) for c in checks if shot_of(c)]
    first = [x for x in shots if str(x[0].get("result") or "").lower() in ("fail", "blocked")]
    rest = [x for x in shots if x not in first]
    if first:
        L += ["", "## What failed, seen", ""]
        for c, rel in first:
            L += [f"**{md_cell(c.get('id'))}** · {md_cell(plain_seen(c, limit=600))}", "", f"![[{rel}]]", ""]
    if rest:
        L += ["", f"> [!example]- The other {len(rest)} screenshots"]
        for c, rel in rest:
            L += [">", f"> **{md_cell(c.get('id'))}** · {md_cell(plain_seen(c, limit=300))}", ">", f"> ![[{rel}]]"]
        L.append("")
    open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")


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


def cmd_plan(a):
    """Write the plan the owner confirms before a browser opens (SKILL §2) as a page the vault carries into to-read:
    the goals table, the lane and version it would run on, and how long. Unattended runs stop here instead of at a
    terminal prompt; his `run` on the note is the confirm."""
    try:
        plan = json.load(open(a.plan, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"plan: {e}", file=sys.stderr); sys.exit(EX_USAGE)
    if not isinstance(plan, list) or not plan:
        print("plan: an empty plan has nothing to run", file=sys.stderr); sys.exit(EX_USAGE)
    s = site()
    reports = s.get("reports") or os.path.join(s.get("projects", ""), "reports")
    date = datetime.date.today().isoformat()
    d = os.path.join(reports, "verify", "plans")
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, f"{date}-{a.key}")
    cell = lambda v: str(v or "").replace("|", "\\|").replace("\n", " ")  # noqa: E731
    minutes = a.minutes or max(5, 3 * len(plan))
    L = ["---", 'type: "verify-plan"', f'key: "{a.key}"', f'lane: "{a.lane}"', f'version: "{a.version}"', f"minutes: {minutes}",
         f'plan: "verify/plans/{date}-{a.key}.json"', "---", f"# {a.key} · verify plan", "",
         f"*{len(plan)} goal{'s' if len(plan) != 1 else ''} · on {a.lane} at {a.version} · about {minutes} minutes*", "",
         "| # | goal | kind | source | expected |", "|---|---|---|---|---|"]
    L += [f"| {cell(g.get('id'))} | {cell(g.get('goal'))} | {cell(g.get('kind') or 'black')} | {cell(g.get('source'))}"
          + (f" · superseded by {cell(g['superseded_by'])}" if g.get("superseded_by") else "") + f" | {cell(g.get('expected'))} |" for g in plan]
    L += ["", "Expectations come from the requirement, never from the code. To change a goal, write an `ela:` line under "
          "this table before choosing run.", "", f"*Plan file: `verify/plans/{date}-{a.key}.json` under the reports root.*", ""]
    if os.path.realpath(a.plan) != os.path.realpath(stem + ".json"):
        shutil.copyfile(a.plan, stem + ".json")
    open(stem + ".md", "w", encoding="utf-8").write("\n".join(L))
    out = {"note": stem + ".md", "plan": stem + ".json", "goals": len(plan), "minutes": minutes}
    print(json.dumps(out) if a.json else f"written: {out['note']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="accepted for the adapter's sake; this script reads no credential")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report", help="render the report page from a run directory"); p.add_argument("--key", required=True); p.add_argument("--run", required=True); p.add_argument("--out"); p.add_argument("--pdf", help="also print the self-contained page to this PDF through the browser sense: the readable part first, the technical record as an appendix"); p.add_argument("--single", help="also write one self-contained HTML for the ticket's attachment"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("plan", help="write the plan as a note for the owner's word (the unattended gate)")
    p.add_argument("--key", required=True); p.add_argument("--plan", required=True, help="plan.json: [{id, kind, goal, source, expected}]")
    p.add_argument("--lane", required=True); p.add_argument("--version", required=True)
    p.add_argument("--minutes", type=int, help="how long the run would take (default three a goal, at least five)")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"report": cmd_report, "plan": cmd_plan}[a.cmd](a)


if __name__ == "__main__":
    main()
