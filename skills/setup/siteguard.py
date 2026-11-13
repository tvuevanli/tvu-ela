#!/usr/bin/env python3
"""siteguard — what no verb reads for a session and no write carries out: the site directory, its env file, a credential.

A session may be steered by text other people wrote (a Slack thread, a ticket). Two things keep that text from
reaching a credential through ela's own verbs:

  refused(path)        why a file a caller named is not read, or None: the site directory (~/.claude/ela) and the
                       site's env file, wherever site.json puts it; links and `..` are resolved first
  guard(path)          the same, exiting 2 with the reason; `-` (stdin) and an empty value pass
  credentials(env)     {value: variable name} for the env file's credentials: values of 8 characters or more that are
                       not an address (a URL, an email, a file path), since a ticket link carries the Jira base URL
                       and a reply may carry the owner's own email
  carried(text, env)   the names of the variables whose credential appears in the text, never a value

Imported by the scripts that take a file from their caller or send text out; it has no verb of its own.
"""
import json, os, re, sys

SITE_DIR = os.path.join("~", ".claude", "ela")
MIN = 8


def site_paths(env_file=None):
    """(the site directory, the env file), both resolved; the env file may live outside the directory."""
    d = os.path.realpath(os.path.expanduser(SITE_DIR))
    env = env_file or os.environ.get("ELA_ENV_FILE") or ""
    if not env:
        try:
            with open(os.path.join(d, "site.json")) as fh:
                env = json.load(fh).get("env") or ""
        except Exception:
            pass
    return d, os.path.realpath(os.path.expanduser(env or os.path.join(d, ".env")))


def refused(path, env_file=None):
    real = os.path.realpath(os.path.expanduser(path))
    d, env = site_paths(env_file)
    if real == env or real == site_paths()[1]:
        return "the site's env file is not read"
    if real == d or real.startswith(d + os.sep):
        return "a file in the site directory is not read"
    return None


def guard(path, env_file=None):
    if not path or path == "-":
        return path
    why = refused(path, env_file)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        sys.exit(2)
    return path


def _address(v):
    return bool(re.match(r"https?://", v) or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) or v.startswith(("/", "~")))


def credentials(env_file=None):
    out = {}
    try:
        with open(site_paths(env_file)[1], encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip("'\"")
                if len(v) >= MIN and not _address(v):
                    out.setdefault(v, k.strip())
    except OSError:
        pass
    return out


def carried(text, env_file=None):
    return sorted({k for v, k in credentials(env_file).items() if v in (text or "")})
