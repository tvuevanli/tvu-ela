#!/usr/bin/env python3
"""`mr create` builds the merge request from the remote path and the stack's lane, and never writes.

Offline: the survey cache, the site config and every git call are replaced by fakes, so nothing is read
from the network or from a real checkout; the only files touched live in a temporary directory."""
import contextlib, io, json, os, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "mr"))
import mr  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


tmp = tempfile.mkdtemp(prefix="ela-mr-test-")
code, work = os.path.join(tmp, "code"), os.path.join(tmp, "work")
HOSTS = {"gitlab-web": {"url": "https://gitweb.example", "matches": ["gitweb", "gitweb.example"], "api": "https://gitweb/api/v4", "token_env": "GITLAB_WEB_TOKEN"}}
REPOS = {
    "media-hub-front": ("webteam/media-hub-front", "team-stack"),
    "mediahub-admin-front": ("webteam/mediahub-admin-frontend", "team-stack"),
    "plain-service": ("webteam/plain-service", "repo-local"),
}
for d in REPOS:
    os.makedirs(os.path.join(code, "web", d))
os.makedirs(os.path.join(code, "web", "mediahub-agent"))
json.dump({"services": [], "frontends": [
    {"dir": "media-hub-front", "repo": "webteam/media-hub-front", "mainBranch": "release2.1"},
    {"dir": "mediahub-admin-front", "repo": "webteam/mediahub-admin-frontend", "mainBranch": "master"}]},
    open(os.path.join(code, "web", "mediahub-agent", "workspace.json"), "w"))

mr.load_site = lambda: {"projects": tmp, "code": code, "work": work, "hosts": json.loads(json.dumps(HOSTS))}
mr.survey_repos = lambda: [{"name": d, "path": os.path.join(code, "web", d), "governance": g, "in_place": True}
                           for d, (_, g) in REPOS.items()]
mr.remote_url = lambda path: f"https://gitweb.example/{REPOS[os.path.basename(path)][0]}.git"


def fake_git(path, *args):
    if args[:1] == ("symbolic-ref",):
        return 0, "origin/develop"
    if args[:1] == ("rev-parse",):
        return 0, ""               # the branch exists
    return 1, ""


mr.git = fake_git


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    rc = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            mr.main(list(argv))
        except SystemExit as e:
            rc = e.code or 0
    return rc, out.getvalue(), err.getvalue()


def plan(*argv):
    rc, out, _ = run("create", *argv, "--json")
    return json.loads(out) if rc == 0 else {"rc": rc}


host, path = mr.ela_map.parse_remote("https://gitweb.example/webteam/media-hub-front.git", HOSTS)
check((host, path) == ("gitlab-web", "webteam/media-hub-front"), "parse_remote on an ssh url → host key and remote path")
check(mr.project_id(path) == "webteam%2Fmedia-hub-front", "project id is the url-quoted remote path")

p = plan("MH-1234", "mediahub-admin-front")
check(p.get("project_id") == "webteam%2Fmediahub-admin-frontend", "project id comes from the remote path, not the directory")
check(p.get("lane") == "master" and "workspace.json" in p.get("lane_rule", ""), "team-stack lane from workspace.json mainBranch")

p = plan("MH-1234", "media-hub-front", "--lane", "hotfix")
check(p.get("lane") == "hotfix" and p.get("lane_rule") == "--lane", "--lane overrides the stack")

p = plan("MH-1234", "plain-service")
check(p.get("lane") == "develop" and p.get("lane_rule") == "origin/HEAD", "a repo outside a stack falls back to origin/HEAD")

rc, out, _ = run("create", "MH-1234", "media-hub-front")
check(rc == 0 and '"source_branch": "evan/mh-1234"' in out, "the printed request names source_branch evan/mh-1234")
check("gitweb" not in out, "no host address is printed")

rc, _, err = run("create", "MH-1234", "media-hub-front", "--apply")
check(rc == 2 and "not enabled" in err, "--apply exits 2")

rc, _, _ = run("create", "MH-1234", "no-such-repo")
check(rc == 3, "an unknown repo exits 3")

shutil.rmtree(tmp)

if failures:
    print(f"mr dry run: {len(failures)} failed"); sys.exit(1)
print("mr dry run: all cases pass")
