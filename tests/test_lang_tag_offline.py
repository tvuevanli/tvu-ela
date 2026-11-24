#!/usr/bin/env python3
"""lang-tag: a standalone `zhn` tag adds Chinese-for-the-session context; anything else passes silently, never blocks."""
import json, os, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "lang-tag.sh")
fail = 0


def run(raw):
    p = subprocess.run(["bash", HOOK], input=raw, capture_output=True, text=True)
    return p.returncode, p.stdout


def check(prompt, want):
    global fail
    rc, out = run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}))
    got = bool(out.strip())
    ok = rc == 0 and got == want
    if got:
        try:
            ctx = json.loads(out)["hookSpecificOutput"]
            ok = ok and ctx["hookEventName"] == "UserPromptSubmit" and "Chinese" in ctx["additionalContext"] and "end of the conversation" in ctx["additionalContext"]
        except Exception:
            ok = False
    print(("ok   " if ok else "FAIL ") + f"{'tag' if want else 'none'}: {prompt!r}")
    fail |= not ok


for p in ["zhn what is on prod-3", "zhn: explain MH-3555", "explain MH-3555 (zhn)", "ZHN why did it fail",
          "why did it fail? Zhn", "zhn 这个 graph 跑在哪", "what changed? zhn.", "ZHN\nfirst line is the tag"]:
    check(p, True)
for p in ["explain MH-3555", "chn what is on prod-3", "zh: explain MH-3555", "CN why did it fail",
          "中文 这个 graph 跑在哪", "is cnn reporting it", "the zhang branch", "zhnx is not a tag",
          "open https://example.cn/zhn/page", "run `ela brief --lang zhn`", "see docs/zhn/manual.md",
          "```\nlocale = zhn\n```\nwhat does this do", "the zhn-CN locale string", "mail.zhn is a host", ""]:
    check(p, False)

for raw in ["not json", "{}", json.dumps({"prompt": None})]:
    rc, out = run(raw)
    ok = rc == 0 and not out.strip()
    print(("ok   " if ok else "FAIL ") + f"malformed input passes: {raw!r}")
    fail |= not ok

raise SystemExit(fail)
