#!/usr/bin/env python3
"""ela's site credentials, entered locally. Stdlib only.

L1: `secret NAME` asks for the value without echo and writes NAME=value into the site's env file (mode 600),
replacing an existing line. The value never passes through a chat or a transcript, never prints, and is never
logged; only the key name and the outcome are reported. A token pasted into a conversation should be rotated and
then entered here (the 2026-10-22 learning draft, E8).

Usage:
    setup.py secret NAME      in a terminal; the prompt does not echo

Exit codes: 0 written · 2 usage (no terminal, a bad name, an empty value).
"""
import argparse, getpass, json, os, re, sys

SITE = os.path.expanduser("~/.claude/ela/site.json")


def env_path():
    try:
        return json.load(open(SITE)).get("env") or os.path.expanduser("~/.claude/ela/.env")
    except (OSError, ValueError):
        return os.path.expanduser("~/.claude/ela/.env")


def cmd_secret(a):
    name = a.name.strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", name):
        print("a key name is upper case letters, digits and underscores, e.g. SLACK_BOT_TOKEN", file=sys.stderr); sys.exit(2)
    if not sys.stdin.isatty():
        print("run this in a terminal: the value is typed at a prompt that does not echo, never passed as an argument", file=sys.stderr); sys.exit(2)
    value = getpass.getpass(f"{name} (not shown): ").strip()
    if not value:
        print("nothing entered; the file is unchanged", file=sys.stderr); sys.exit(2)
    path = env_path()
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.isfile(path) else []
    replaced = False
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == name:
            lines[i] = f"{name}={value}"; replaced = True
    if not replaced:
        lines.append(f"{name}={value}")
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path); os.chmod(path, 0o600)
    print(f"{name} {'replaced' if replaced else 'added'} in the site env file (mode 600); the value was not shown or logged")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("secret", help="enter a credential at a prompt that does not echo; written to the site env file")
    p.add_argument("name")
    p.set_defaults(func=cmd_secret)
    a = ap.parse_args(); a.func(a)


if __name__ == "__main__":
    main()
