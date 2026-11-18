#!/usr/bin/env python3
"""The env file's precedence, offline: --env-file, then the per-capability and ELA_ENV_FILE variables, then the
site.json `env` path (with ~ expanded), so a session or an unattended run calls a script with no flag at all.
HOME points at a temporary site directory; nothing is called."""
import importlib, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []
def check(name, cond, got=None):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if got is not None:
            print("     ", got)

home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.makedirs(os.path.join(home, ".claude", "ela"))
def envfile(name, value):
    p = os.path.join(home, name)
    with open(p, "w") as f:
        f.write(f"SLACK_BOT_TOKEN={value}\nSENTRY_URL={value}\n")
    return p
site, var, ela, flag = envfile("site.env", "site"), envfile("var.env", "var"), envfile("ela.env", "ela"), envfile("flag.env", "flag")
SITE_JSON = os.path.join(home, ".claude", "ela", "site.json")
with open(SITE_JSON, "w") as f:
    json.dump({"env": "~/site.env"}, f)
for k in ("SLACK_BOT_TOKEN", "SENTRY_URL", "SLACK_ENV_FILE", "SENTRY_ENV_FILE", "ELA_ENV_FILE"):
    os.environ.pop(k, None)

for cap, key, var_name in (("slack", "SLACK_BOT_TOKEN", "SLACK_ENV_FILE"), ("sentry", "SENTRY_URL", "SENTRY_ENV_FILE"),
                           ("graph", "SLACK_BOT_TOKEN", None), ("release", "SLACK_BOT_TOKEN", None)):
    sys.path.insert(0, os.path.join(ROOT, "skills", cap))
    m = importlib.import_module(cap)
    check(f"{cap}: no flag, no variable: site.json env", m.env_value(key) == "site", m.env_value(key))
    os.environ["ELA_ENV_FILE"] = ela
    check(f"{cap}: ELA_ENV_FILE outranks site.json", m.env_value(key) == "ela", m.env_value(key))
    if var_name:
        os.environ[var_name] = var
        check(f"{cap}: {var_name} outranks ELA_ENV_FILE", m.env_value(key) == "var", m.env_value(key))
    check(f"{cap}: --env-file outranks every variable", m.env_value(key, flag) == "flag", m.env_value(key, flag))
    for k in ("ELA_ENV_FILE", var_name):
        if k:
            os.environ.pop(k, None)

empty = os.path.join(home, "empty.env")
open(empty, "w").close()

import slack as S  # noqa: E402
check("a named file without the key: site.json is not read behind it", S.env_value("SLACK_BOT_TOKEN", empty) is None)

sys.path.insert(0, os.path.join(ROOT, "skills", "jira"))
import jira as J  # noqa: E402
with open(site, "w") as f:
    f.write("".join(f"{k}=v-{k}\n" for k in J.ENV_KEYS))
for k in list(J.ENV_KEYS) + ["JIRA_ENV_FILE"]:
    os.environ.pop(k, None)
got = J.load_env(None)
check("jira: load_env reads the site.json env with no flag", all(got.get(k, "").startswith("v-") for k in J.ENV_KEYS), got)

os.remove(SITE_JSON)

check("no site.json: no env file and no error", S.site_env() is None and S.env_value("SLACK_BOT_TOKEN") is None)

print("env fallback:", "FAILED" if failures else "passed")
sys.exit(1 if failures else 0)
