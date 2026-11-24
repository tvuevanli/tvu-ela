#!/usr/bin/env python3
"""lang-tag: a standalone zh/chn/cn/中文 tag adds Chinese-reply context; anything else passes silently, never blocks."""
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
            ok = ok and ctx["hookEventName"] == "UserPromptSubmit" and "Chinese" in ctx["additionalContext"]
        except Exception:
            ok = False
    print(("ok   " if ok else "FAIL ") + f"{'tag' if want else 'none'}: {prompt!r}")
    fail |= not ok


for p in ["chn what is on prod-3", "zh: explain MH-3555", "explain MH-3555 (zh)", "CN why did it fail",
          "why did it fail? Chn", "中文 这个 graph 跑在哪", "explain this graph, 中文", "what changed? zh.",
          "ZH\nfirst line is the tag"]:
    check(p, True)
for p in ["explain MH-3555", "is cnn reporting it", "the zhang branch", "open https://example.cn/zh/page",
          "run `ela brief --lang zh`", "see docs/zh/manual.md", "```\nlocale = cn\n```\nwhat does this do",
          "the zh-CN locale string", "translate to 中文版 later", "mail.cn is a host", ""]:
    check(p, False)

for raw in ["not json", "{}", json.dumps({"prompt": None})]:
    rc, out = run(raw)
    ok = rc == 0 and not out.strip()
    print(("ok   " if ok else "FAIL ") + f"malformed input passes: {raw!r}")
    fail |= not ok

raise SystemExit(fail)
