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
  outward(text, env)   what a text must not carry to anyone but the owner: the host of a service address in the env
                       file (compared on hostname, or on a bare IP; named by its variable), except the sites the
                       colleagues use anyway (ALLOWED: Jira, Slack, the KB, Confluence, Figma, Google), and a local
                       address (localhost, loopback, a private-range IP), named by its line

Imported by the scripts that take a file from their caller or send text out; it has no verb of its own.
"""
import ipaddress, json, os, re, sys, urllib.parse

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


# ── addresses: fine for the owner, not for a channel ─────────────────────────────────────────────────────────
ALLOWED = ("JIRA_", "SLACK_", "OUTLINE_", "CONFLUENCE_", "FIGMA_", "GOOGLE_")   # by variable, so no address is written here
_IP = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w]|\.\d)")
_BARE = re.compile(r"([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?::\d+)?(?:/.*)?")


def service_hosts(env_file=None):
    """{hostname or IP: variable} for the env file's service addresses: a URL's host, a bare IP, and a bare host name
    under a variable that says it is one (…HOST…, …URL…). A host an ALLOWED variable also names is left out."""
    found, allowed = {}, set()
    try:
        with open(site_paths(env_file)[1], encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = (x.strip() for x in line.split("=", 1))
                v = v.strip("'\"")
                host = None
                if re.match(r"https?://", v):
                    host = urllib.parse.urlparse(v).hostname
                else:
                    m = _BARE.fullmatch(v)
                    if m and (_IP.fullmatch(m.group(1)) or re.search(r"HOST|URL", k)):
                        host = m.group(1)
                if host:
                    (allowed if k.startswith(ALLOWED) else found.setdefault(host.lower(), k) and set()).add(host.lower())
    except OSError:
        pass
    return {h: k for h, k in found.items() if h not in allowed}


def local_lines(text):
    """The 1-based lines that carry localhost, a loopback or a private-range address."""
    out = []
    for n, line in enumerate((text or "").split("\n"), 1):
        hit = bool(re.search(r"(?<![\w.-])localhost(?![\w-])", line, re.I))
        for m in _IP.finditer(line):
            try:
                ip = ipaddress.ip_address(m.group(1))
            except ValueError:
                continue
            hit = hit or ip.is_loopback or ip.is_private or ip.is_link_local
        if hit:
            out.append(n)
    return out


def outward(text, env_file=None):
    """[reason, …] why this text goes to the owner alone; empty when it may go to others."""
    low = (text or "").lower()
    names = sorted({k for h, k in service_hosts(env_file).items() if re.search(r"(?<![\w.-])" + re.escape(h) + r"(?![\w-])", low)})
    lines = local_lines(text)
    return ([f"the host of {', '.join(names)} from the site's env file"] if names else []) + \
           ([f"a local address (localhost, loopback or a private range) on line {', '.join(map(str, lines))}"] if lines else [])
