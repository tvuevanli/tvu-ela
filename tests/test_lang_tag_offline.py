#!/usr/bin/env python3
"""lang-tag: a standalone `#zh` tag adds Chinese-for-the-session context; anything else passes silently, never blocks."""
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


for p in ["#zh what is on prod-3", "#zh: explain MH-3555", "explain MH-3555 (#zh)", "#ZH why did it fail",
          "why did it fail? #Zh", "#zh 这个 graph 跑在哪", "what changed? #zh.", "#ZH\nfirst line is the tag"]:
    check(p, True)
for p in ["explain MH-3555", "zhn what is on prod-3", "zh: explain MH-3555", "chn what is on prod-3", "CN why did it fail",
          "中文 这个 graph 跑在哪", "the zhang branch", "#zhn is not a tag", "##zh is not a tag", "issue#zh is not a tag",
          "open https://example.cn/#zh", "run `ela brief --tag #zh`", "see docs/#zh/manual.md",
          "```\nlocale = #zh\n```\nwhat does this do", "the #zh-CN locale string", "mail.#zh is a host", ""]:
    check(p, False)

for raw in ["not json", "{}", json.dumps({"prompt": None})]:
    rc, out = run(raw)
    ok = rc == 0 and not out.strip()
    print(("ok   " if ok else "FAIL ") + f"malformed input passes: {raw!r}")
    fail |= not ok

raise SystemExit(fail)
