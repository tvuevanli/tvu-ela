#!/usr/bin/env python3
"""The information tier of each kind of notice (skills/slack/tiers.py): every kind a notifier uses is placed, an
incident is always I1, an unplaced kind is an error, and only I1 becomes a direct message."""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "slack"))
import tiers as T  # noqa: E402

failures = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


used = set()
for rel in ("skills/mention/mention.py", "skills/watch/watch.py"):
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    used |= set(re.findall(r'TI\.(?:tier|messages_now)\("([a-z]+)", "([a-z-]+)"\)', src))
check("the notifiers ask the table", len(used) >= 4)
check("every kind a notifier asks about is placed", all(k in T.TIERS for k in used))
check("every tier in the table is one of the four, with its rule", all(t in T.WHERE and why for t, why in T.TIERS.values()))
check("an incident is I1, and the floor holds", T.tier("mention", "incident") == T.I1 and T.FLOOR[("mention", "incident")] == T.I1)
try:
    T.tier("mention", "no-such-kind"); unknown = False
except KeyError:
    unknown = True
check("an unplaced kind is an error, never a guess", unknown)
check("only I1 is a message now: a watch topic and a held ask are not; a notice is a record",
      not T.messages_now("watch", "topic") and not T.messages_now("mention", "ask-held") and T.tier("mention", "notice") == T.I4)

print("tiers: all offline checks passed" if not failures else f"tiers: {len(failures)} failed")
sys.exit(1 if failures else 0)
