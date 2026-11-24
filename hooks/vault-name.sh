#!/usr/bin/env bash
# ela UserPromptSubmit hook — a vault note named in the owner's message is located for the session.
# Reads the prompt (JSON: prompt) on stdin. The owner copies a note's name from Obsidian: its title, an alias or its
# file name stem. Each one found in the message, matched against the name index the vault sync writes
# (<runtime>/vault-index.json, site.json `runtime`; ELA_SITE overrides the site file), adds one context line
# `vault note: <vault-relative path>`, at most five. A name counts when it is a dated stem (yyyy-mm-dd-…) or has at
# least two words and eight characters, so a one-word alias (today, home) never matches ordinary prose; a name
# inside a longer one already matched is not counted again. No index, no match: no output.
# Always exit 0: this hook never blocks a prompt.
INPUT="$(cat)"
python3 - "$INPUT" <<'PY' 2>/dev/null
import json, os, re, sys
try:
    prompt = json.loads(sys.argv[1]).get("prompt") or ""
    site = json.load(open(os.environ.get("ELA_SITE") or os.path.expanduser("~/.claude/ela/site.json")))
    names = json.load(open(os.path.join(site["runtime"], "vault-index.json")))["names"]
except Exception:
    sys.exit(0)
if not prompt.strip() or not isinstance(names, dict):
    sys.exit(0)
CAP = 5
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}-\S")
EDGE = "A-Za-z0-9_\\-"                                        # a name touching these is part of a longer token


def counts(n):
    return bool(DATED.match(n)) or (len(n) >= 8 and len([w for w in re.split(r"[\s\-_·]+", n) if w]) >= 2)


low = prompt.lower()
spans, found = [], []                                          # (start, end) taken; (start, path)
for n in sorted((n for n in names if isinstance(n, str) and counts(n)), key=len, reverse=True):
    paths = names[n] if isinstance(names[n], list) else [names[n]]
    rx = re.compile(rf"(?<![{EDGE}]){re.escape(n.lower())}(?![{EDGE}])")
    for m in rx.finditer(low):
        if any(s <= m.start() and m.end() <= e for s, e in spans):
            continue
        spans.append((m.start(), m.end()))
        found += [(m.start(), p) for p in paths if isinstance(p, str)]
        break
seen, out = set(), []
for _, p in sorted(found):
    if p not in seen:
        seen.add(p)
        out.append(f"vault note: {p}")
if not out:
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                         "additionalContext": "\n".join(out[:CAP])}}, ensure_ascii=False))
PY
exit 0
