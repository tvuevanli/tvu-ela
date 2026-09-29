#!/usr/bin/env python3
"""Merge-request capability. L1: subcommands, --json, meaningful exit codes, stdlib only. Preflight and
dry run only: this version prints exactly what would be pushed and posted, and never pushes or posts.

  preflight [--host gitlab-web|gitlab-media]   the token's scopes and expiry per GitLab host (default: both)
  create <KEY> <repo> [--lane <branch>]        the push command and the merge-request request that would
                                               deliver branch evan/<key> from <work>/<KEY>/<repo>

`skills/task/SKILL.md` §6 delivers an `mr-gated` task as a pushed branch plus a merge request naming the
owner; this is that last step, stopped before either write. The push and the MR are two confirms the owner
makes at the shell, so `--apply` is refused here.

Site facts come from ~/.claude/ela/site.json: `hosts` (each host: url, api, matches, token_env), `code`,
`work`, and the survey cache ~/.claude/ela/map/host.json. The GitLab project id is built from the remote
path, never from the directory name (a checkout may be named differently from its remote). No host address
or token is printed: a host appears by its key, its api as `<api:KEY>`.

Credentials: the host's `token_env` from the environment → --env-file → $ELA_ENV_FILE.

Exit codes: 0 ok · 2 usage · 3 not found · 4 auth or no credential · 5 remote error.
"""
import argparse, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "map"))
import map as ela_map  # noqa: E402 — parse_remote and Layout: one reading of remotes and roots

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
CACHE = os.path.expanduser("~/.claude/ela/map/host.json")
GITLAB_HOSTS = ("gitlab-web", "gitlab-media")
DESCRIPTION = """<type>(<scope>): <what changed>

<why>

Jira: {key}

## 验证
<verification command and result>
"""


def fail(msg, code):
    print(msg, file=sys.stderr); sys.exit(code)


def load_site():
    try:
        return json.load(open(SITE))
    except Exception:
        fail("no ~/.claude/ela/site.json — run /ela:setup", EX_USAGE)


def survey_repos():
    try:
        return json.load(open(CACHE))["repos"]
    except Exception:
        fail("no survey cache (~/.claude/ela/map/host.json) — run `ela survey`", EX_NOTFOUND)


def git(path, *args):
    try:
        r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def remote_url(path):
    code, out = git(path, "remote", "get-url", "origin")
    return out if code == 0 else None


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in filter(None, [env_file, os.environ.get("ELA_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def project_id(remote_path):
    return urllib.parse.quote(remote_path, safe="")


# ── preflight ────────────────────────────────────────────────────────────────

def check_token(key, host, env_file):
    """→ (exit code, line). The line names the host key and the env var, never the url or the token."""
    var = host.get("token_env")
    if not host.get("api") or not var:
        return EX_USAGE, f"{key}: no `api` or `token_env` in site.json hosts — run /ela:setup"
    tok = env_value(var, env_file)
    if not tok:
        return EX_AUTH, f"{key}: {var} is empty — put a token with scope `api` in ela's env file"
    req = urllib.request.Request(host["api"].rstrip("/") + "/personal_access_tokens/self", headers={"PRIVATE-TOKEN": tok})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return EX_AUTH, f"{key}: {var} is rejected (HTTP {e.code})"
        return EX_REMOTE, f"{key}: HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return EX_REMOTE, f"{key}: network error {type(e).__name__}"
    try:
        info = json.loads(body)
    except ValueError:
        return EX_AUTH, f"{key}: {var} — the answer is not JSON (a login page means the token is not accepted)"
    scopes = info.get("scopes") or []
    if "api" not in scopes:
        return EX_AUTH, f"{key}: {var} lacks scope `api` (scopes {', '.join(scopes) or 'none'})"
    return 0, f"{key}: ok  scopes {', '.join(scopes)}  expires {info.get('expires_at') or 'never'}"


def cmd_preflight(a):
    hosts = load_site().get("hosts", {})
    keys = [a.host] if a.host else list(GITLAB_HOSTS)
    worst = 0
    for key in keys:
        if key not in hosts:
            code, line = EX_USAGE, f"{key}: not in site.json hosts — run /ela:setup"
        else:
            code, line = check_token(key, hosts[key], a.env_file)
        print(line, file=sys.stderr if code else sys.stdout)
        worst = worst or code
    sys.exit(worst)


# ── create (dry run) ─────────────────────────────────────────────────────────

def find_repo(name):
    hits = [r for r in survey_repos() if r.get("name") == name or os.path.basename(r.get("path", "")) == name]
    if not hits:
        fail(f"{name}: not in the survey cache — run `ela survey`, or `ela find {name}`", EX_NOTFOUND)
    return next((r for r in hits if r.get("in_place")), hits[0])


def choose_lane(lay, repo, remote_path, override):
    """→ (lane, the rule that chose it)."""
    if override:
        return override, "--lane"
    if repo.get("governance") == "team-stack":
        ws = os.path.join(lay.code, "web", "mediahub-agent", "workspace.json")
        try:
            w = json.load(open(ws))
        except (OSError, ValueError):
            w = {}
        base = os.path.basename(repo["path"])
        for e in (w.get("services") or []) + (w.get("frontends") or []):
            if (e.get("dir") == base or e.get("repo") == remote_path) and e.get("mainBranch"):
                return e["mainBranch"], "mediahub-agent workspace.json mainBranch"
    code, out = git(repo["path"], "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out:
        return out[len("origin/"):] if out.startswith("origin/") else out, "origin/HEAD"
    fail(f"{repo['name']}: no lane — origin/HEAD is not set and no stack names one; pass --lane", EX_USAGE)


def title_for(lay, key):
    try:
        for line in open(os.path.join(lay.work, key, "ticket.md"), encoding="utf-8"):
            if line.startswith("#"):
                summary = line.lstrip("#").strip()
                if summary.upper().startswith(key):
                    summary = summary[len(key):].lstrip(" :—-")
                return f"{key} {summary}".strip()
    except OSError:
        pass
    return key


def plan(a):
    s = load_site()
    lay = ela_map.Layout(s)
    key = a.key.upper()
    repo = find_repo(a.repo)
    url = remote_url(repo["path"])
    if not url:
        fail(f"{repo['name']}: no `origin` remote in {repo['path']}", EX_NOTFOUND)
    host, remote_path = ela_map.parse_remote(url, lay.hosts)
    if not host:
        fail(f"{repo['name']}: the origin remote is not a url ela reads", EX_USAGE)
    if host == "github":
        fail("GitHub merge requests are not supported (no token configured)", EX_USAGE)
    if not lay.hosts.get(host, {}).get("api"):
        fail(f"{repo['name']}: host {host} has no `api` in site.json hosts — run /ela:setup", EX_USAGE)
    lane, rule = choose_lane(lay, repo, remote_path, a.lane)
    branch = f"evan/{key.lower()}"
    wt = os.path.join(lay.work, key, os.path.basename(repo["path"]))
    where = next((d for d in (wt, repo["path"]) if os.path.isdir(d) and git(d, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0), None)
    if not where:
        fail(f"{branch}: no such branch in {wt} or {repo['path']} — `map.py worktree {repo['name']} {key}` creates it", EX_NOTFOUND)
    pid = project_id(remote_path)
    body = {"source_branch": branch, "target_branch": lane, "title": title_for(lay, key),
            "description": DESCRIPTION.format(key=key), "remove_source_branch": False}
    return {"key": key, "repo": repo["name"], "path": repo["path"], "governance": repo.get("governance"),
            "host": host, "remote_path": remote_path, "project_id": pid, "lane": lane, "lane_rule": rule,
            "push": {"cwd": where, "command": f"git push -u origin {branch}"},
            "request": {"method": "POST", "url": f"<api:{host}>/projects/{pid}/merge_requests", "body": body},
            "dry_run": True}


def cmd_create(a):
    if a.apply:
        fail("apply is not enabled in this version: push and MR are two confirms the owner makes at the shell", EX_USAGE)
    p = plan(a)
    if a.json:
        print(json.dumps(p, ensure_ascii=False)); return
    r = p["request"]
    print(f"repo     {p['repo']}  [{p['governance']}]  {p['path']}")
    print(f"remote   {p['host']}  {p['remote_path']}  (project id {p['project_id']})")
    print(f"lane     {p['lane']}  (chosen by {p['lane_rule']})")
    print(f"title    {r['body']['title']}")
    print(f"\nwould run, in {p['push']['cwd']}:\n  {p['push']['command']}")
    print(f"\nwould send:\n  {r['method']} {r['url']}")
    print("  " + json.dumps(r["body"], ensure_ascii=False, indent=2).replace("\n", "\n  "))
    print("\ndry run: nothing pushed, nothing posted. Fill the description's placeholders; never invent evidence.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Merge requests: preflight and dry run; never pushes or posts.")
    ap.add_argument("--env-file", help="ela's env file, holding each host's token_env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight", help="the token's scopes and expiry per GitLab host")
    p.add_argument("--host", choices=GITLAB_HOSTS)
    p = sub.add_parser("create", help="the push and the MR request that would deliver evan/<key>")
    p.add_argument("key"); p.add_argument("repo")
    p.add_argument("--lane", help="target branch; overrides the stack's mainBranch and origin/HEAD")
    p.add_argument("--json", action="store_true")
    p.add_argument("--apply", action="store_true", help="refused in this version")
    a = ap.parse_args(argv)
    {"preflight": cmd_preflight, "create": cmd_create}[a.cmd](a)


if __name__ == "__main__":
    main()
